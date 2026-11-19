"""Tests für die betriebssystemunabhängige Terminal-Ausgabe und Windows-Pfade."""

import io
import ntpath
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from s3_uploader import konfiguration
from s3_uploader.terminal import Terminal, bereite_konsole_vor
from s3_uploader.uploader import _fertige_auftraege


class FalschesTerminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_ohne_ansi_wird_mit_leerzeichen_ueberschrieben(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("s3_uploader.terminal._schalte_vt_modus_ein", lambda _a: False)
    terminal = Terminal(FalschesTerminal())
    text = terminal.loesch_text()
    assert "\033" not in text
    assert text.startswith("\r") and text.endswith("\r") and text.strip() == ""


def test_lange_zeilen_werden_auf_terminalbreite_gekuerzt(monkeypatch: pytest.MonkeyPatch) -> None:
    ausgabe = FalschesTerminal()
    terminal = Terminal(ausgabe)
    monkeypatch.setattr(terminal, "breite", lambda: 30)
    terminal.ueberschreibe("x" * 100)
    assert ausgabe.getvalue().count("x") == 29


def test_konsole_vorbereiten_verhindert_kodierungsfehler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roh = io.BytesIO()
    strom = io.TextIOWrapper(roh, encoding="ascii", newline="\n")
    monkeypatch.setattr("sys.stdout", strom)
    bereite_konsole_vor()
    print("Präfix – fertig", file=strom)
    strom.flush()
    assert roh.getvalue() == b"Pr?fix ? fertig\n"


def test_quellkennung_ignoriert_schreibweise_unter_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Windows-Verhalten von os.path.normcase nachbilden (Kleinschreibung, \ statt /).
    monkeypatch.setattr(konfiguration.os.path, "normcase", ntpath.normcase)
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    assert konfiguration.quellkennung(Path("D:/Daten/Export")) == konfiguration.quellkennung(
        Path("d:/daten/export")
    )


def test_fertige_auftraege_liefert_alle_ergebnisse() -> None:
    with ThreadPoolExecutor(2) as pool:
        auftraege = {pool.submit(lambda n=n: time.sleep(0.01 * n) or True) for n in range(4)}
        assert len(list(_fertige_auftraege(auftraege))) == 4
