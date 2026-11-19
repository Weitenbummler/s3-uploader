from pathlib import Path

import pytest

from s3_uploader.dateisuche import finde_dateien
from s3_uploader.fehler import KonfigurationsFehler


def test_findet_alle_dateien_mit_praefix(quelle: Path) -> None:
    schluessel = sorted(d.schluessel for d in finde_dateien(quelle, "p/"))
    assert schluessel == ["p/a.txt", "p/gross.bin", "p/unter/b.txt", "p/unter/tief/c.bin"]


def test_ausschluesse_greifen(quelle: Path) -> None:
    schluessel = {d.schluessel for d in finde_dateien(quelle, "", ["*.bin"])}
    assert schluessel == {"a.txt", "unter/b.txt"}


def test_symlinks_werden_nicht_verfolgt(quelle: Path) -> None:
    (quelle / "verweis").symlink_to(quelle / "unter")
    schluessel = {d.schluessel for d in finde_dateien(quelle, "")}
    assert not any(s.startswith("verweis") for s in schluessel)


def test_fehlende_quelle(tmp_path: Path) -> None:
    with pytest.raises(KonfigurationsFehler):
        list(finde_dateien(tmp_path / "gibtsnicht", ""))
