"""Tests des Verbindungstests: echte Abläufe mit moto, Fehlerbilder mit einer Attrappe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, SSLError

from s3_uploader.verbindungstest import Stufe, teste_verbindung, zusammenfassung

from conftest import BUCKET


def test_erfolgreicher_test_mit_schreibtest(s3: Any) -> None:
    ergebnisse = teste_verbindung(s3, BUCKET, "p/", schreibtest=True)
    namen = [p.name for p in ergebnisse]
    assert namen[0] == "Verbindung und Zertifikat"
    assert "Zugangsdaten" in namen and "Schreibrecht" in namen and "Löschrecht" in namen
    assert all(p.stufe is Stufe.OK for p in ergebnisse)
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0
    assert zusammenfassung(ergebnisse) == "Verbindungstest erfolgreich."


def test_fehlender_bucket_wird_benannt(s3: Any) -> None:
    ergebnisse = teste_verbindung(s3, "gibtsnicht", "", schreibtest=True)
    assert ergebnisse[-1].name == "Bucket"
    assert ergebnisse[-1].stufe is Stufe.FEHLER
    assert "existiert nicht" in ergebnisse[-1].hinweis


# --- Fehlerbilder mit einer Attrappe ------------------------------------------------------


def _fehler(
    code: str, meldung: str = "", status: int = 403, uhr: datetime | None = None
) -> ClientError:
    kopf = {"date": format_datetime(uhr or datetime.now(UTC), usegmt=True)}
    return ClientError(
        {
            "Error": {"Code": code, "Message": meldung},
            "ResponseMetadata": {"HTTPStatusCode": status, "HTTPHeaders": kopf},
        },
        "ListObjectsV2",
    )


class Attrappe:
    """S3-Client, dessen Antworten je Methode vorgegeben werden."""

    def __init__(self, **antworten: Any) -> None:
        self.antworten = antworten
        self.aufrufe: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def methode(**_kwargs: Any) -> Any:
            self.aufrufe.append(name)
            antwort = self.antworten.get(name, {})
            if isinstance(antwort, Exception):
                raise antwort
            return antwort

        return methode


def _ergebnis(client: Attrappe, schreibtest: bool = False) -> dict[str, Any]:
    ergebnisse = teste_verbindung(client, "b", "p/", schreibtest)
    return {p.name: p for p in ergebnisse} | {"_liste": ergebnisse}


@pytest.mark.parametrize(
    ("code", "schritt", "stichwort"),
    [
        ("InvalidAccessKeyId", "Access Key", "unbekannt"),
        ("SignatureDoesNotMatch", "Passwort (Secret Key)", "Passwort passt nicht"),
        ("RequestTimeTooSkewed", "Uhrzeit", "Uhr"),
        ("AuthorizationHeaderMalformed", "Region", "--region"),
    ],
)
def test_anmeldefehler_werden_eindeutig_benannt(code: str, schritt: str, stichwort: str) -> None:
    client = Attrappe(list_objects_v2=_fehler(code, "the region 'eu-1' is wrong"))
    ergebnis = _ergebnis(client, schreibtest=True)
    assert ergebnis[schritt].stufe is Stufe.FEHLER
    assert stichwort in ergebnis[schritt].hinweis
    assert "put_object" not in client.aufrufe  # nach Anmeldefehler keine weiteren Versuche
    assert zusammenfassung(ergebnis["_liste"]).endswith(f"Ursache: {schritt}.")


def test_region_meldung_des_speichers_wird_weitergegeben() -> None:
    client = Attrappe(
        list_objects_v2=_fehler("AuthorizationHeaderMalformed", "expecting 'eu-central-1'")
    )
    assert "eu-central-1" in _ergebnis(client)["Region"].hinweis


def test_access_denied_beweist_gueltige_zugangsdaten_und_ist_nur_hinweis() -> None:
    client = Attrappe(list_objects_v2=_fehler("AccessDenied"))
    ergebnis = _ergebnis(client)
    assert ergebnis["Zugangsdaten"].stufe is Stufe.OK
    assert ergebnis["Leserecht im Präfix"].stufe is Stufe.HINWEIS
    assert "--schreibtest" in ergebnis["Leserecht im Präfix"].hinweis
    assert all(p.ok for p in ergebnis["_liste"])


def test_nur_schreibrecht_reicht_zum_hochladen() -> None:
    client = Attrappe(
        list_objects_v2=_fehler("AccessDenied"), delete_object=_fehler("AccessDenied")
    )
    ergebnis = _ergebnis(client, schreibtest=True)
    assert ergebnis["Schreibrecht"].stufe is Stufe.OK
    assert ergebnis["Löschrecht"].stufe is Stufe.HINWEIS
    assert zusammenfassung(ergebnis["_liste"]).startswith(
        "Verbindungstest bestanden, mit Hinweisen"
    )


def test_fehlendes_schreibrecht_ist_fehler() -> None:
    client = Attrappe(list_objects_v2={"KeyCount": 0}, put_object=_fehler("AccessDenied"))
    ergebnis = _ergebnis(client, schreibtest=True)
    assert ergebnis["Schreibrecht"].stufe is Stufe.FEHLER
    assert "s3:PutObject" in ergebnis["Schreibrecht"].hinweis


def test_starke_zeitabweichung_wird_erkannt() -> None:
    falsche_uhr = datetime.now(UTC) - timedelta(minutes=20)
    client = Attrappe(list_objects_v2=_fehler("AccessDenied", uhr=falsche_uhr))
    ergebnis = _ergebnis(client)
    assert ergebnis["Uhrzeit"].stufe is Stufe.FEHLER


def test_leichte_zeitabweichung_ist_hinweis() -> None:
    uhr = datetime.now(UTC) - timedelta(minutes=5)
    kopf = {"date": format_datetime(uhr, usegmt=True)}
    client = Attrappe(list_objects_v2={"KeyCount": 0, "ResponseMetadata": {"HTTPHeaders": kopf}})
    assert _ergebnis(client)["Uhrzeit"].stufe is Stufe.HINWEIS


def test_403_ohne_code_wird_ehrlich_als_unklar_gemeldet() -> None:
    client = Attrappe(list_objects_v2=_fehler("403"))
    assert "ohne genaue Begründung" in _ergebnis(client)["Zugangsdaten"].hinweis


def test_selbst_signiertes_zertifikat_bekommt_klaren_hinweis() -> None:
    fehler = SSLError(
        endpoint_url="https://s3.intern",
        error="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "self-signed certificate in certificate chain",
    )
    ergebnis = _ergebnis(Attrappe(list_objects_v2=fehler))
    assert "--ca-zertifikat" in ergebnis["Verbindung und Zertifikat"].hinweis


def test_nicht_erreichbarer_endpunkt() -> None:
    fehler = EndpointConnectionError(endpoint_url="https://s3.intern")
    ergebnis = _ergebnis(Attrappe(list_objects_v2=fehler))
    assert "nicht erreichbar" in ergebnis["Verbindung und Zertifikat"].hinweis
