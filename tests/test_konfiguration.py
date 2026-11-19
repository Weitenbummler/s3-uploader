from pathlib import Path

import pytest

from s3_uploader.fehler import KonfigurationsFehler
from s3_uploader.konfiguration import (
    Verbindung,
    normalisiere_prefix,
    parse_groesse,
    standard_zustandsdatei,
)


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [
        ("", ""),
        ("/", ""),
        ("backup", "backup/"),
        ("/backup//2026/", "backup/2026/"),
        ("a\\b", "a/b/"),
    ],
)
def test_prefix_wird_normalisiert(eingabe: str, erwartet: str) -> None:
    assert normalisiere_prefix(eingabe) == erwartet


@pytest.mark.parametrize(
    ("eingabe", "erwartet"),
    [("100", 100), ("16MiB", 16 * 1024**2), ("1,5 GiB", int(1.5 * 1024**3)), ("10mb", 10**7)],
)
def test_groessenangaben(eingabe: str, erwartet: int) -> None:
    assert parse_groesse(eingabe) == erwartet


def test_unverstaendliche_groesse() -> None:
    with pytest.raises(KonfigurationsFehler):
        parse_groesse("viel")


def test_passwort_erscheint_nicht_in_repr() -> None:
    v = Verbindung("https://x", "b", "schluessel", "geheim123")
    assert "geheim123" not in repr(v)


def test_zustandsdatei_haengt_vom_ziel_ab_nicht_vom_passwort(tmp_path: Path) -> None:
    a = standard_zustandsdatei(Verbindung("https://x", "b", "k", "p1"), tmp_path, "")
    b = standard_zustandsdatei(Verbindung("https://x", "b", "k", "p2"), tmp_path, "")
    c = standard_zustandsdatei(Verbindung("https://x", "anderer", "k", "p1"), tmp_path, "")
    assert a == b != c
    assert "p1" not in a.name
