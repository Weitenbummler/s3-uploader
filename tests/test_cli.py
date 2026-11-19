from pathlib import Path
from typing import Any

import pytest

from s3_uploader.cli import EXIT_BEDIENUNG, EXIT_OK, main

from conftest import BUCKET, lies_objekt


def _basis(tmp_path: Path) -> list[str]:
    return [
        "--endpunkt",
        "https://s3.amazonaws.com",
        "--bucket",
        BUCKET,
        "--access-key",
        "testkey",
        "--prefix",
        "/cli/",
    ]


@pytest.fixture(autouse=True)
def _passwort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_SECRET_KEY", "testsecret")


def test_verbindungstest(s3: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["test", *_basis(tmp_path), "--schreibtest"]) == EXIT_OK
    assert "Verbindungstest erfolgreich." in capsys.readouterr().out


def test_hochladen_und_fortsetzen(
    s3: Any, quelle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argumente = [
        "hochladen",
        *_basis(tmp_path),
        "--quelle",
        str(quelle),
        "--zustand",
        str(tmp_path / "z.sqlite"),
        "--still",
    ]
    assert main(argumente) == EXIT_OK
    assert lies_objekt(s3, "cli/a.txt") == b"Hallo"
    assert main(argumente) == EXIT_OK
    assert "0 hochgeladen, 4 übersprungen" in capsys.readouterr().out


def test_probelauf_laedt_nichts(s3: Any, quelle: Path, tmp_path: Path) -> None:
    assert (
        main(
            [
                "hochladen",
                *_basis(tmp_path),
                "--quelle",
                str(quelle),
                "--zustand",
                str(tmp_path / "z.sqlite"),
                "--probelauf",
            ]
        )
        == EXIT_OK
    )
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


def test_fehlende_angaben_sind_bedienfehler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("S3_ENDPUNKT", "S3_BUCKET", "S3_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert main(["test"]) == EXIT_BEDIENUNG
    assert "--endpunkt" in capsys.readouterr().err


def test_ungueltige_groesse(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as fehler:
        main(["hochladen", "--quelle", ".", "--schwelle", "riesig"])
    assert fehler.value.code == EXIT_BEDIENUNG


def test_ohne_teilung_per_parameter(
    s3: Any, quelle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "hochladen",
                *_basis(tmp_path),
                "--quelle",
                str(quelle),
                "--ohne-teilung",
                "--zustand",
                str(tmp_path / "z.sqlite"),
                "--schwelle",
                "5MiB",
                "--still",
            ]
        )
        == EXIT_OK
    )
    fehler = capsys.readouterr().err
    assert "0 in Teilen" in fehler and "Teilung abgeschaltet" in fehler
    assert lies_objekt(s3, "cli/gross.bin") == (quelle / "gross.bin").read_bytes()


def test_hochladen_bricht_vor_dem_upload_ab_wenn_bucket_fehlt(
    s3: Any, quelle: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from s3_uploader.cli import EXIT_FEHLER

    argumente = [
        "hochladen",
        "--endpunkt",
        "https://s3.amazonaws.com",
        "--bucket",
        "gibtsnicht",
        "--access-key",
        "testkey",
        "--quelle",
        str(quelle),
        "--zustand",
        str(tmp_path / "z.sqlite"),
        "--still",
    ]
    assert main(argumente) == EXIT_FEHLER
    ausgabe = capsys.readouterr().out
    assert "Abbruch vor dem Upload" in ausgabe and "Bucket existiert nicht" in ausgabe
