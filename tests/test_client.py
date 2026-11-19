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


# --- Formatprüfung der CA-Datei ----------------------------------------------------------

# Echtes, selbst signiertes Test-Zertifikat ohne zugehörigen Schlüssel (nur zum Laden).
PEM = (Path(__file__).parent / "daten" / "test-ca.pem").read_bytes()


@pytest.mark.parametrize(
    "inhalt",
    [PEM, b"# Zertifikatsspeicher\nIssuer: Firma\n" + PEM + PEM],
    ids=["einzeln", "buendel_mit_kopfzeilen"],
)
def test_pem_dateien_werden_angenommen(tmp_path: Path, inhalt: bytes) -> None:
    from s3_uploader.konfiguration import pruefe_ca_datei

    datei = tmp_path / "firma.crt"
    datei.write_bytes(inhalt)
    pruefe_ca_datei(datei)


@pytest.mark.parametrize(
    ("inhalt", "erwartet"),
    [
        (b"\x30\x82\x05\x99\x30\x82", "certutil -encode"),
        ("-----BEGIN CERTIFICATE-----\n".encode("utf-16"), "UTF-16"),
        (b"-----BEGIN PRIVATE KEY-----\nMIIE\n", "kein Zertifikat"),
    ],
    ids=["binaer_der", "utf16", "nur_schluessel"],
)
def test_falsche_formate_werden_mit_abhilfe_gemeldet(
    tmp_path: Path, inhalt: bytes, erwartet: str
) -> None:
    from s3_uploader.fehler import KonfigurationsFehler
    from s3_uploader.konfiguration import pruefe_ca_datei

    datei = tmp_path / "firma.crt"
    datei.write_bytes(inhalt)
    with pytest.raises(KonfigurationsFehler, match=erwartet):
        pruefe_ca_datei(datei)


def test_binaere_crt_ist_bedienfehler_mit_umwandlungsbefehl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    datei = tmp_path / "firma.crt"
    datei.write_bytes(b"\x30\x82\x05\x99")
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
            str(datei),
        ]
    )
    assert code == EXIT_BEDIENUNG
    fehler = capsys.readouterr().err
    assert "certutil -encode" in fehler and "openssl x509 -inform der" in fehler
    assert "firma-ca.pem" in fehler


def test_doppelt_kodierte_datei_wird_erkannt(tmp_path: Path) -> None:
    import base64

    from s3_uploader.fehler import KonfigurationsFehler
    from s3_uploader.konfiguration import pruefe_ca_datei

    # So sieht eine .crt aus, die schon PEM war und mit certutil -encode erneut kodiert wurde.
    innen = base64.encodebytes(PEM).decode()
    datei = tmp_path / "firma-ca.pem"
    datei.write_text(f"-----BEGIN CERTIFICATE-----\n{innen}-----END CERTIFICATE-----\n")
    with pytest.raises(KonfigurationsFehler, match="doppelt kodiert"):
        pruefe_ca_datei(datei)


def test_beschaedigter_inhalt_wird_erkannt(tmp_path: Path) -> None:
    from s3_uploader.fehler import KonfigurationsFehler
    from s3_uploader.konfiguration import pruefe_ca_datei

    datei = tmp_path / "kaputt.pem"
    datei.write_text("-----BEGIN CERTIFICATE-----\nMIIBkaputt\n-----END CERTIFICATE-----\n")
    with pytest.raises(KonfigurationsFehler, match=r"beschädigt|nicht geladen"):
        pruefe_ca_datei(datei)
