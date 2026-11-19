r"""Betriebssystemunabhängige Terminal-Ausgabe (Windows, macOS, Linux).

Unter Windows gibt es zwei Besonderheiten, die hier an einer Stelle behandelt werden:

- Die klassische Konsole (``conhost``, z. B. PowerShell 5 außerhalb von Windows Terminal)
  versteht ANSI-Steuerzeichen wie ``\033[K`` erst, wenn das Programm den
  „Virtual Terminal“-Modus einschaltet. Gelingt das nicht, wird die Zeile stattdessen mit
  Leerzeichen überschrieben.
- Je nach Python-Version und Umleitung ist die Kodierung der Ausgabe nicht UTF-8. Zeichen
  wie „–“ dürfen dann nicht zum Absturz führen.
"""

from __future__ import annotations

import shutil
import sys
from typing import TextIO

_ANSI_LOESCHEN = "\r\033[K"


def _schalte_vt_modus_ein(ausgabe: TextIO) -> bool:
    """Schaltet unter Windows die Verarbeitung von ANSI-Steuerzeichen für die Konsole ein.

    Args:
        ausgabe: ``sys.stdout`` oder ``sys.stderr``.

    Returns:
        ``True``, wenn ANSI-Steuerzeichen verwendet werden können.
    """
    # sys.platform statt os.name: mypy wertet diese Prüfung aus und prüft den Windows-Teil
    # nur für Windows, wo es ctypes.windll und msvcrt gibt.
    if sys.platform != "win32":
        return True
    try:
        import ctypes  # nur unter Windows benötigt
        import msvcrt

        kernel32 = ctypes.windll.kernel32
        griff = msvcrt.get_osfhandle(ausgabe.fileno())
        modus = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(griff, ctypes.byref(modus)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004 (Windows 10 ab 1511)
        return bool(kernel32.SetConsoleMode(griff, modus.value | 0x0004))
    except (AttributeError, OSError, ValueError):
        return False


class Terminal:
    """Schreibt überschreibbare Zeilen in ein Terminal, mit oder ohne ANSI-Unterstützung.

    Args:
        ausgabe: Zielstrom, üblicherweise ``sys.stderr``.
    """

    def __init__(self, ausgabe: TextIO) -> None:
        self.ausgabe = ausgabe
        self.ist_terminal = ausgabe.isatty()
        self._ansi = self.ist_terminal and _schalte_vt_modus_ein(ausgabe)

    def breite(self) -> int:
        """Liefert die aktuelle Spaltenzahl des Terminals (Standard 80)."""
        return max(shutil.get_terminal_size((80, 24)).columns, 20)

    def loesch_text(self) -> str:
        """Liefert die Zeichenfolge, die die aktuelle Zeile leert und an ihren Anfang springt."""
        if self._ansi:
            return _ANSI_LOESCHEN
        return "\r" + " " * (self.breite() - 1) + "\r"

    def ueberschreibe(self, zeile: str, abschluss: bool = False) -> None:
        r"""Ersetzt die aktuelle Zeile durch ``zeile``.

        Die Zeile wird auf die Terminalbreite gekürzt: Eine umbrochene Zeile ließe sich mit
        ``\r`` nicht mehr vollständig überschreiben.

        Args:
            zeile: Neuer Inhalt.
            abschluss: Danach einen Zeilenumbruch ausgeben.
        """
        zeile = zeile[: self.breite() - 1]
        self.ausgabe.write(self.loesch_text() + zeile + ("\n" if abschluss else ""))
        self.ausgabe.flush()


def bereite_konsole_vor() -> None:
    """Verhindert Abstürze durch nicht darstellbare Zeichen in stdout und stderr.

    Nicht darstellbare Zeichen werden durch ``?`` ersetzt statt einen
    ``UnicodeEncodeError`` auszulösen (z. B. bei umgeleiteter Ausgabe unter Windows).
    """
    for strom in (sys.stdout, sys.stderr):
        neu_konfigurieren = getattr(strom, "reconfigure", None)
        if neu_konfigurieren is not None:
            neu_konfigurieren(errors="replace")
