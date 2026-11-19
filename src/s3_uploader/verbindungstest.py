"""Verbindungstest mit Ursachen-Diagnose.

Ein S3-Speicher antwortet auf viele Probleme nur mit „403 Forbidden“. Der Test grenzt die
Ursache ein, indem er die Reihenfolge nutzt, in der S3 eine Anfrage prüft:

1. Verbindung und TLS-Zertifikat – kommt überhaupt eine Antwort?
2. Uhrzeit – weicht die eigene Uhr zu stark ab, verwirft S3 jede Signatur.
3. Zugangsdaten – ist der Access Key bekannt (``InvalidAccessKeyId``), passt das Passwort
   (``SignatureDoesNotMatch``), stimmt die Region (``AuthorizationHeaderMalformed``)?
4. Rechte – erst wenn die Signatur stimmt, prüft S3 die Berechtigung (``AccessDenied``).
   Ein ``AccessDenied`` beweist also, dass Access Key und Passwort richtig sind.

Wichtig: ``HeadBucket`` liefert bei 403 keinen Fehlercode (eine HEAD-Antwort hat keinen
Inhalt). Der Test fragt deshalb zuerst mit ``ListObjectsV2`` (GET), dessen Fehlerantwort den
genauen Code enthält.

Fehlende Leserechte sind nur ein Hinweis, kein Fehler: Viele Datenablagen erlauben einem
Upload-Konto bewusst nur das Schreiben in ein Präfix. Ob das klappt, zeigt ``--schreibtest``.
"""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, SSLError

from s3_uploader.client import S3Client

#: Ab dieser Abweichung der Uhr (Sekunden) wird gewarnt; S3 lehnt ab etwa 15 Minuten ab.
UHR_WARNUNG = 120
UHR_GRENZE = 15 * 60


class Stufe(enum.Enum):
    """Bewertung eines Prüfschritts."""

    OK = "OK  "
    HINWEIS = "HINW"
    FEHLER = "FEHL"


@dataclass(frozen=True, slots=True)
class Pruefung:
    """Ergebnis eines einzelnen Prüfschritts.

    Attributes:
        name: Bezeichnung des Schritts.
        stufe: Bewertung; nur :attr:`Stufe.FEHLER` verhindert das Hochladen.
        hinweis: Erläuterung bzw. Ursache und Abhilfe für den Benutzer.
    """

    name: str
    stufe: Stufe
    hinweis: str

    @property
    def ok(self) -> bool:
        """``True``, solange der Schritt kein Fehler ist (Hinweise zählen als bestanden)."""
        return self.stufe is not Stufe.FEHLER


def _code(err: ClientError) -> str:
    return str(err.response.get("Error", {}).get("Code", ""))


def _meldung(err: ClientError) -> str:
    return str(err.response.get("Error", {}).get("Message", "")).strip()


def _serverzeit(antwort: dict[str, Any]) -> datetime | None:
    """Liest den HTTP-Kopf ``Date`` aus einer Antwort oder Fehlerantwort."""
    kopf = antwort.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get("date")
    if not kopf:
        return None
    try:
        return parsedate_to_datetime(str(kopf))
    except (TypeError, ValueError):
        return None


def beschreibe_tls_fehler(text: str) -> str:
    """Übersetzt eine TLS-Fehlermeldung in Ursache und Abhilfe.

    Args:
        text: Text der Ausnahme.

    Returns:
        Verständlicher Hinweis.
    """
    if re.search(r"self[- ]signed|unable to get local issuer", text):
        return (
            "Zertifikat des Endpunkts ist selbst signiert oder von einer eigenen "
            "Zertifizierungsstelle – deren Zertifikat mit --ca-zertifikat DATEI.pem angeben "
            "(siehe README). Nur zum Testen: --ohne-tls-pruefung."
        )
    if "PEM lib" in text or "NO_CERTIFICATE_OR_CRL_FOUND" in text:
        return (
            "Die Zertifikatsdatei (--ca-zertifikat, S3_CA_ZERTIFIKAT oder AWS_CA_BUNDLE) "
            "ist nicht lesbar – Format prüfen (siehe README, Abschnitt Zertifikat)."
        )
    if "expired" in text:
        return "Zertifikat des Endpunkts ist abgelaufen – Betreiber des Speichers informieren."
    if "hostname" in text.lower() or "match" in text.lower():
        return (
            "Zertifikat passt nicht zum Namen des Endpunkts – genau den Namen aus dem "
            "Zertifikat in --endpunkt verwenden (nicht die IP-Adresse oder einen Alias)."
        )
    return f"TLS-Fehler: {text} – Zertifikat prüfen, ggf. --ca-zertifikat angeben."


# Zuordnung der S3-Fehlercodes zu (Prüfschritt, Ursache und Abhilfe). Alle hier
# aufgeführten Codes entstehen, bevor S3 die Rechte prüft.
_ANMELDEFEHLER: dict[str, tuple[str, str]] = {
    "InvalidAccessKeyId": (
        "Access Key",
        "Der Access Key ist dem Speicher unbekannt – Schreibweise prüfen (Groß/Klein, keine "
        "Leerzeichen) und ob der Schlüssel gelöscht oder deaktiviert wurde.",
    ),
    "SignatureDoesNotMatch": (
        "Passwort (Secret Key)",
        "Der Access Key ist bekannt, aber das Passwort passt nicht – Secret Key prüfen "
        "(vollständig kopiert? Leerzeichen am Ende?). Seltener: ein Proxy verändert die "
        "Anfrage.",
    ),
    "RequestTimeTooSkewed": (
        "Uhrzeit",
        "Die Uhr dieses Rechners weicht zu stark von der des Speichers ab – Uhrzeit und "
        "Zeitzone des Rechners korrigieren (automatische Zeitsynchronisation einschalten).",
    ),
    "AuthorizationHeaderMalformed": (
        "Region",
        "Die Region passt nicht zum Speicher – Wert aus der Meldung mit --region angeben.",
    ),
    "InvalidToken": ("Zugangsdaten", "Das Sitzungstoken ist ungültig oder abgelaufen."),
    "ExpiredToken": ("Zugangsdaten", "Das Sitzungstoken ist abgelaufen."),
    "AccountProblem": ("Konto", "Das Konto beim Speicher ist gesperrt oder eingeschränkt."),
    "AllAccessDisabled": ("Konto", "Der Zugriff auf diesen Bucket ist gesperrt."),
}


def teste_verbindung(
    client: S3Client, bucket: str, prefix: str, schreibtest: bool = False
) -> list[Pruefung]:
    """Prüft Verbindung, Uhrzeit, Zugangsdaten und Rechte und benennt die Ursache.

    Bei Verbindungs- und Anmeldefehlern endet der Test sofort, denn alle weiteren Schritte
    würden aus demselben Grund scheitern. Fehlende Rechte werden einzeln gemeldet.

    Args:
        client: S3-Client.
        bucket: Bucket-Name.
        prefix: Normalisiertes Präfix.
        schreibtest: Ob Schreib- und Löschrecht mit einem Testobjekt geprüft werden.

    Returns:
        Ergebnisse der ausgeführten Schritte.
    """
    ergebnisse: list[Pruefung] = []

    def melde(name: str, stufe: Stufe, hinweis: str) -> None:
        ergebnisse.append(Pruefung(name, stufe, hinweis))

    # --- Schritt 1: eine Anfrage mit auswertbarer Fehlerantwort ---------------------------
    antwort: dict[str, Any]
    fehler: ClientError | None = None
    try:
        antwort = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    except SSLError as err:
        melde("Verbindung und Zertifikat", Stufe.FEHLER, beschreibe_tls_fehler(str(err)))
        return ergebnisse
    except EndpointConnectionError:
        melde(
            "Verbindung und Zertifikat",
            Stufe.FEHLER,
            "Endpunkt nicht erreichbar – URL, Port, Netzwerk, Proxy oder Firewall prüfen.",
        )
        return ergebnisse
    except BotoCoreError as err:
        melde("Verbindung und Zertifikat", Stufe.FEHLER, f"{type(err).__name__}: {err}")
        return ergebnisse
    except ClientError as err:
        fehler = err
        antwort = err.response
    melde("Verbindung und Zertifikat", Stufe.OK, "Speicher antwortet, Zertifikat gültig")

    # --- Schritt 2: Uhrzeit ----------------------------------------------------------------
    serverzeit = _serverzeit(antwort)
    if serverzeit is not None:
        abweichung = (datetime.now(UTC) - serverzeit).total_seconds()
        text = f"Abweichung zur Uhr des Speichers: {abweichung:+.0f} s"
        if abs(abweichung) >= UHR_GRENZE:
            melde("Uhrzeit", Stufe.FEHLER, text + " – Uhr dieses Rechners korrigieren.")
            return ergebnisse
        stufe = Stufe.HINWEIS if abs(abweichung) >= UHR_WARNUNG else Stufe.OK
        melde("Uhrzeit", stufe, text)

    # --- Schritt 3: Zugangsdaten -------------------------------------------------------------
    code = _code(fehler) if fehler is not None else ""
    if code in _ANMELDEFEHLER:
        name, ursache = _ANMELDEFEHLER[code]
        zusatz = _meldung(fehler) if fehler is not None else ""
        if code == "AuthorizationHeaderMalformed" and zusatz:
            ursache += f" Meldung des Speichers: {zusatz}"
        melde(name, Stufe.FEHLER, f"{ursache} (Code {code})")
        return ergebnisse
    if code in {"NoSuchBucket"}:
        melde("Zugangsdaten", Stufe.OK, "Access Key und Passwort werden akzeptiert")
        melde("Bucket", Stufe.FEHLER, f"Bucket {bucket!r} existiert nicht – Namen prüfen.")
        return ergebnisse
    if code in {"PermanentRedirect", "301"}:
        melde(
            "Bucket",
            Stufe.FEHLER,
            "Bucket liegt in einer anderen Region oder braucht eine andere Adressierung – "
            "--region bzw. --adressierung prüfen.",
        )
        return ergebnisse
    if code and code not in {"AccessDenied", "403"}:
        melde(
            "Zugangsdaten", Stufe.FEHLER, f"S3-Fehler {code}: {_meldung(fehler) if fehler else ''}"
        )
        return ergebnisse
    if code == "403":
        # Nur ein Status ohne Code (manche Speicher): Ursache nicht eindeutig.
        melde(
            "Zugangsdaten",
            Stufe.FEHLER,
            "Speicher verweigert den Zugriff ohne genaue Begründung – Access Key, Passwort und "
            "Rechte für den Bucket beim Betreiber prüfen lassen.",
        )
        return ergebnisse
    melde("Zugangsdaten", Stufe.OK, "Access Key und Passwort werden akzeptiert")

    # --- Schritt 4: Rechte -------------------------------------------------------------------
    if code == "AccessDenied":
        melde(
            "Leserecht im Präfix",
            Stufe.HINWEIS,
            f"Auflisten von {bucket!r}/{prefix or '(gesamter Bucket)'} nicht erlaubt (fehlt "
            "s3:ListBucket). Hochladen kann trotzdem funktionieren – mit --schreibtest prüfen. "
            "Ohne Leserecht gehen --pruefe-ziel und Fortsetzen nicht zuverlässig.",
        )
    else:
        inhalt = "enthält bereits Objekte" if antwort.get("KeyCount", 0) else "ist leer"
        melde("Bucket und Leserecht", Stufe.OK, f"Bucket {bucket!r} vorhanden, Präfix {inhalt}")

    if not schreibtest:
        return ergebnisse

    testschluessel = f"{prefix}.s3-uploader-verbindungstest-{uuid.uuid4().hex}"
    try:
        client.put_object(Bucket=bucket, Key=testschluessel, Body=b"s3-uploader")
    except ClientError as err:
        if _code(err) in {"AccessDenied", "403"}:
            melde(
                "Schreibrecht",
                Stufe.FEHLER,
                f"Schreiben unter {prefix or '(Bucket-Wurzel)'} nicht erlaubt (fehlt "
                "s3:PutObject) – Präfix prüfen oder Recht beim Betreiber anfordern.",
            )
        else:
            melde("Schreibrecht", Stufe.FEHLER, f"S3-Fehler {_code(err)}: {_meldung(err)}")
        return ergebnisse
    melde("Schreibrecht", Stufe.OK, f"Testobjekt {testschluessel!r} angelegt")

    try:
        client.delete_object(Bucket=bucket, Key=testschluessel)
    except ClientError as err:
        melde(
            "Löschrecht",
            Stufe.HINWEIS,
            f"Testobjekt konnte nicht gelöscht werden ({_code(err)}) und bleibt liegen: "
            f"{testschluessel!r}. Für das Hochladen nicht nötig.",
        )
    else:
        melde("Löschrecht", Stufe.OK, "Testobjekt wieder entfernt")
    return ergebnisse


def zusammenfassung(ergebnisse: list[Pruefung]) -> str:
    """Fasst die Prüfschritte in einem Satz zusammen.

    Args:
        ergebnisse: Ergebnisse aus :func:`teste_verbindung`.

    Returns:
        Abschlusssatz für die Ausgabe.
    """
    fehler = next((p for p in ergebnisse if p.stufe is Stufe.FEHLER), None)
    if fehler is not None:
        return f"Verbindungstest fehlgeschlagen. Ursache: {fehler.name}."
    if any(p.stufe is Stufe.HINWEIS for p in ergebnisse):
        return "Verbindungstest bestanden, mit Hinweisen (siehe HINW)."
    return "Verbindungstest erfolgreich."
