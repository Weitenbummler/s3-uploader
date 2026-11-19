"""Ende-zu-Ende-Tests des Uploaders gegen die S3-Attrappe."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from s3_uploader.dateisuche import Datei, finde_dateien
from s3_uploader.fortschritt import Fortschritt
from s3_uploader.konfiguration import UploadEinstellungen
from s3_uploader.uploader import Uploader
from s3_uploader.zustand import Zustand

from conftest import BUCKET, MIB, lies_objekt


class StoerClient:
    """Reicht alles an den echten Client durch, lässt aber ausgewählte Teile scheitern."""

    def __init__(self, client: Any, fehlerhafte_teile: set[int]) -> None:
        self._client = client
        self.fehlerhafte_teile = fehlerhafte_teile
        self.hochgeladene_teile: list[int] = []

    def upload_part(self, **kwargs: Any) -> Any:
        if kwargs["PartNumber"] in self.fehlerhafte_teile:
            raise ClientError({"Error": {"Code": "InternalError"}}, "UploadPart")
        self.hochgeladene_teile.append(kwargs["PartNumber"])
        return self._client.upload_part(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _einstellungen(quelle: Path, tmp_path: Path, **extra: Any) -> UploadEinstellungen:
    return UploadEinstellungen(
        quelle=quelle,
        prefix="ziel/",
        zustandsdatei=tmp_path / "zustand.sqlite",
        schwelle=5 * MIB,
        teilgroesse=5 * MIB,
        parallel_dateien=2,
        parallel_teile=2,
        **extra,
    )


def _lauf(client: Any, quelle: Path, tmp_path: Path, **extra: Any) -> tuple[Any, Fortschritt]:
    einstellungen = _einstellungen(quelle, tmp_path, **extra)
    dateien = list(finde_dateien(quelle, einstellungen.prefix))
    fortschritt = Fortschritt()
    with Zustand(einstellungen.zustandsdatei) as zustand:
        ergebnis = Uploader(client, BUCKET, einstellungen, zustand, fortschritt).lade_hoch(dateien)
    return ergebnis, fortschritt


def test_alle_dateien_kommen_unverfaelscht_an(s3: Any, quelle: Path, tmp_path: Path) -> None:
    ergebnis, fortschritt = _lauf(s3, quelle, tmp_path)
    assert (ergebnis.hochgeladen, ergebnis.uebersprungen, ergebnis.fehler) == (4, 0, [])
    for datei in quelle.rglob("*"):
        if datei.is_file():
            schluessel = "ziel/" + datei.relative_to(quelle).as_posix()
            assert lies_objekt(s3, schluessel) == datei.read_bytes()
    assert fortschritt.momentaufnahme().prozent == 100.0


def test_zweiter_lauf_ueberspringt_alles(s3: Any, quelle: Path, tmp_path: Path) -> None:
    _lauf(s3, quelle, tmp_path)
    ergebnis, _ = _lauf(s3, quelle, tmp_path)
    assert (ergebnis.hochgeladen, ergebnis.uebersprungen) == (0, 4)


def test_abgebrochener_multipart_wird_fortgesetzt(s3: Any, quelle: Path, tmp_path: Path) -> None:
    stoerer = StoerClient(s3, fehlerhafte_teile={2})
    ergebnis, _ = _lauf(stoerer, quelle, tmp_path)
    assert [s for s, _ in ergebnis.fehler] == ["ziel/gross.bin"]
    assert ergebnis.hochgeladen == 3
    teile_erster_lauf = set(stoerer.hochgeladene_teile)
    assert 2 not in teile_erster_lauf

    stoerer.fehlerhafte_teile.clear()
    stoerer.hochgeladene_teile.clear()
    ergebnis, fortschritt = _lauf(stoerer, quelle, tmp_path)
    assert (ergebnis.hochgeladen, ergebnis.uebersprungen, ergebnis.fehler) == (1, 3, [])
    # Nur die fehlenden Teile wurden erneut übertragen.
    assert set(stoerer.hochgeladene_teile) == {1, 2, 3} - teile_erster_lauf
    assert lies_objekt(s3, "ziel/gross.bin") == (quelle / "gross.bin").read_bytes()
    stand = fortschritt.momentaufnahme()
    assert stand.bytes_uebertragen < stand.bytes_gesamt


def test_veraenderte_datei_beginnt_neu(s3: Any, quelle: Path, tmp_path: Path) -> None:
    _lauf(StoerClient(s3, fehlerhafte_teile={3}), quelle, tmp_path)
    assert s3.list_multipart_uploads(Bucket=BUCKET).get("Uploads")
    neu = os.urandom(11 * MIB)
    (quelle / "gross.bin").write_bytes(neu)
    ergebnis, _ = _lauf(s3, quelle, tmp_path)
    assert ergebnis.fehler == []
    assert lies_objekt(s3, "ziel/gross.bin") == neu
    assert not s3.list_multipart_uploads(Bucket=BUCKET).get("Uploads")


def test_verlorener_upload_auf_server_beginnt_neu(s3: Any, quelle: Path, tmp_path: Path) -> None:
    _lauf(StoerClient(s3, fehlerhafte_teile={2}), quelle, tmp_path)
    for upload in s3.list_multipart_uploads(Bucket=BUCKET)["Uploads"]:
        s3.abort_multipart_upload(Bucket=BUCKET, Key=upload["Key"], UploadId=upload["UploadId"])
    ergebnis, _ = _lauf(s3, quelle, tmp_path)
    assert ergebnis.fehler == []
    assert lies_objekt(s3, "ziel/gross.bin") == (quelle / "gross.bin").read_bytes()


def test_pruefe_ziel_uebernimmt_vorhandene_objekte(s3: Any, quelle: Path, tmp_path: Path) -> None:
    _lauf(s3, quelle, tmp_path)
    (tmp_path / "zustand.sqlite").unlink()
    ergebnis, _ = _lauf(s3, quelle, tmp_path, pruefe_ziel=True)
    assert (ergebnis.hochgeladen, ergebnis.uebersprungen) == (0, 4)


def test_plan_zeigt_offene_arbeit(s3: Any, quelle: Path, tmp_path: Path) -> None:
    einstellungen = _einstellungen(quelle, tmp_path)
    dateien = list(finde_dateien(quelle, "ziel/"))
    with Zustand(einstellungen.zustandsdatei) as zustand:
        plan = Uploader(s3, BUCKET, einstellungen, zustand, Fortschritt()).plane(dateien)
    assert (plan.dateien, plan.erledigt, plan.einfach, plan.multipart) == (4, 0, 3, 1)


def test_waehrend_upload_veraenderte_datei_scheitert(
    s3: Any, quelle: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from s3_uploader import uploader as modul

    original = modul._lies_abschnitt

    def lies_und_veraendere(pfad: Path, start: int, laenge: int) -> bytes:
        daten = original(pfad, start, laenge)
        os.utime(pfad, ns=(1, 1))
        return daten

    monkeypatch.setattr(modul, "_lies_abschnitt", lies_und_veraendere)
    ergebnis, _ = _lauf(s3, quelle, tmp_path)
    assert [s for s, _ in ergebnis.fehler] == ["ziel/gross.bin"]


def test_einzelne_datei_als_datenklasse(tmp_path: Path) -> None:
    pfad = tmp_path / "x"
    pfad.write_text("1")
    assert Datei(pfad, "x", 1, 0).groesse == 1


def test_leere_datei_wird_hochgeladen(s3: Any, tmp_path: Path) -> None:
    quelle = tmp_path / "leer"
    quelle.mkdir()
    (quelle / "nichts.txt").write_bytes(b"")
    ergebnis, _ = _lauf(s3, quelle, tmp_path)
    assert ergebnis.hochgeladen == 1
    assert lies_objekt(s3, "ziel/nichts.txt") == b""
