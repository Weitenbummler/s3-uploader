from pathlib import Path

import pytest

from s3_uploader.cli import EXIT_BEDIENUNG, main
from s3_uploader.client import erzeuge_client, tls_pruefung
from s3_uploader.konfiguration import Verbindung


def _verbindung(**extra: object) -> Verbindung:
    return Verbindung("https://s3.intern", "b", "k", "geheim", **extra)  # type: ignore[arg-type]


def test_standard_ueberlaesst_boto3_die_wahl_damit_aws_ca_bundle_wirkt() -> None:
    assert tls_pruefung(_verbindung()) is None


def test_ohne_pruefung() -> None:
    assert tls_pruefung(_verbindung(tls_pruefen=False)) is False


def test_eigene_ca_wird_an_boto3_uebergeben(tmp_path: Path) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    client = erzeuge_client(_verbindung(ca_zertifikat=ca))
    assert client._endpoint.http_session._verify == str(ca)


def test_aws_ca_bundle_wird_beachtet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ca = tmp_path / "bundle.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv("AWS_CA_BUNDLE", str(ca))
    client = erzeuge_client(_verbindung())
    assert client._endpoint.http_session._verify == str(ca)


def test_fehlende_ca_datei_ist_bedienfehler(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "test",
            "--endpunkt",
            "https://s3.intern",
            "--bucket",
            "b",
            "--access-key",
            "k",
            "--passwort",
            "p",
            "--ca-zertifikat",
            str(tmp_path / "fehlt.pem"),
        ]
    )
    assert code == EXIT_BEDIENUNG
    assert "CA-Zertifikat nicht gefunden" in capsys.readouterr().err


def test_ca_und_ohne_pruefung_schliessen_sich_aus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    code = main(
        [
            "test",
            "--endpunkt",
            "https://s3.intern",
            "--bucket",
            "b",
            "--access-key",
            "k",
            "--passwort",
            "p",
            "--ca-zertifikat",
            str(ca),
            "--ohne-tls-pruefung",
        ]
    )
    assert code == EXIT_BEDIENUNG
    assert "schließen sich aus" in capsys.readouterr().err
