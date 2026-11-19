from typing import Any

from s3_uploader.verbindungstest import teste_verbindung

from conftest import BUCKET


def test_erfolgreicher_test_mit_schreibtest(s3: Any) -> None:
    ergebnisse = teste_verbindung(s3, BUCKET, "p/", schreibtest=True)
    assert [p.name for p in ergebnisse] == [
        "Anmeldung und Bucket",
        "Leserecht",
        "Schreibrecht",
        "Löschrecht",
    ]
    assert all(p.ok for p in ergebnisse)
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


def test_fehlender_bucket_bricht_frueh_ab(s3: Any) -> None:
    ergebnisse = teste_verbindung(s3, "gibtsnicht", "", schreibtest=True)
    assert len(ergebnisse) == 1
    assert not ergebnisse[0].ok
    assert "Bucket existiert nicht" in ergebnisse[0].hinweis


def test_ohne_schreibtest_nur_lesen(s3: Any) -> None:
    assert len(teste_verbindung(s3, BUCKET, "")) == 2


def test_selbst_signiertes_zertifikat_bekommt_klaren_hinweis() -> None:
    from botocore.exceptions import SSLError

    from s3_uploader.verbindungstest import _beschreibe_fehler

    fehler = SSLError(
        endpoint_url="https://s3.intern",
        error="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "self-signed certificate in certificate chain",
    )
    assert "--ca-zertifikat" in _beschreibe_fehler(fehler)
