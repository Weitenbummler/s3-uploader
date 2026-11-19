"""Fortschrittszählung und -anzeige.

:class:`Fortschritt` zählt threadsicher, :class:`Anzeige` gibt den Stand regelmäßig aus.
Die Trennung hält die Fachlogik frei von Ausgabedetails (PY-E4): Der Uploader meldet nur
Ereignisse, wie sie dargestellt werden, entscheidet die Anzeige.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from types import TracebackType
from typing import TextIO

from s3_uploader.terminal import Terminal

_EINHEITEN = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


def formatiere_bytes(anzahl: float) -> str:
    """Formatiert eine Byte-Anzahl lesbar mit deutschem Dezimalkomma.

    Args:
        anzahl: Anzahl Bytes.

    Returns:
        Text wie ``1,5 GiB``.
    """
    wert = float(anzahl)
    for einheit in _EINHEITEN:
        if wert < 1024 or einheit == _EINHEITEN[-1]:
            text = f"{wert:.0f}" if einheit == "B" else f"{wert:.1f}"
            return f"{text.replace('.', ',')} {einheit}"
        wert /= 1024
    raise AssertionError("nicht erreichbar")  # pragma: no cover


def formatiere_dauer(sekunden: float | None) -> str:
    """Formatiert eine Dauer als ``h:mm:ss``.

    Args:
        sekunden: Dauer in Sekunden oder ``None``, wenn unbekannt.

    Returns:
        Text wie ``1:02:03`` oder ``–:––:––``.
    """
    if sekunden is None:
        return "–:––:––"
    gesamt = int(sekunden)
    return f"{gesamt // 3600}:{gesamt % 3600 // 60:02d}:{gesamt % 60:02d}"


@dataclass(frozen=True, slots=True)
class Momentaufnahme:
    """Unveränderlicher Stand des Fortschritts zu einem Zeitpunkt.

    Attributes:
        dateien_gesamt: Anzahl aller Dateien des Laufs.
        dateien_hochgeladen: In diesem Lauf vollständig hochgeladene Dateien.
        dateien_uebersprungen: Bereits vorher erledigte Dateien.
        dateien_fehler: Fehlgeschlagene Dateien.
        bytes_gesamt: Gesamtgröße aller Dateien.
        bytes_fertig: Bereits vorhandene oder in diesem Lauf übertragene Bytes.
        bytes_uebertragen: In diesem Lauf tatsächlich übertragene Bytes.
        dauer: Laufzeit in Sekunden.
    """

    dateien_gesamt: int
    dateien_hochgeladen: int
    dateien_uebersprungen: int
    dateien_fehler: int
    bytes_gesamt: int
    bytes_fertig: int
    bytes_uebertragen: int
    dauer: float

    @property
    def dateien_bearbeitet(self) -> int:
        """Anzahl abgeschlossener Dateien (hochgeladen, übersprungen oder fehlgeschlagen)."""
        return self.dateien_hochgeladen + self.dateien_uebersprungen + self.dateien_fehler

    @property
    def prozent(self) -> float:
        """Anteil der fertigen Bytes in Prozent (100, wenn nichts zu tun ist)."""
        return 100.0 if self.bytes_gesamt == 0 else 100.0 * self.bytes_fertig / self.bytes_gesamt

    @property
    def rate(self) -> float:
        """Durchschnittliche Übertragungsrate in Bytes je Sekunde in diesem Lauf."""
        return self.bytes_uebertragen / self.dauer if self.dauer > 0 else 0.0

    @property
    def restzeit(self) -> float | None:
        """Geschätzte Restzeit in Sekunden oder ``None``, solange keine Rate bekannt ist."""
        rest = self.bytes_gesamt - self.bytes_fertig
        if rest <= 0:
            return 0.0
        return rest / self.rate if self.rate > 0 else None

    def als_zeile(self) -> str:
        """Erzeugt die einzeilige Fortschrittsdarstellung.

        Returns:
            Text wie ``[ 42,3 %] 12/345 Dateien | 1,2 GiB / 2,8 GiB | 45,1 MiB/s | Rest 0:00:35``.
        """
        prozent = f"{self.prozent:5.1f}".replace(".", ",")
        zeile = (
            f"[{prozent} %] {self.dateien_bearbeitet}/{self.dateien_gesamt} Dateien | "
            f"{formatiere_bytes(self.bytes_fertig)} / {formatiere_bytes(self.bytes_gesamt)} | "
            f"{formatiere_bytes(self.rate)}/s | Rest {formatiere_dauer(self.restzeit)}"
        )
        if self.dateien_fehler:
            zeile += f" | Fehler {self.dateien_fehler}"
        return zeile


class Fortschritt:
    """Threadsicherer Zähler für Dateien und Bytes eines Laufs."""

    def __init__(self) -> None:
        self._sperre = threading.Lock()
        self._start = time.monotonic()
        self._dateien_gesamt = 0
        self._bytes_gesamt = 0
        self._hochgeladen = 0
        self._uebersprungen = 0
        self._fehler = 0
        self._bytes_fertig = 0
        self._bytes_uebertragen = 0

    def beginne(self, dateien: int, bytes_gesamt: int) -> None:
        """Setzt den Umfang des Laufs und startet die Zeitmessung.

        Args:
            dateien: Anzahl Dateien.
            bytes_gesamt: Gesamtgröße in Bytes.
        """
        with self._sperre:
            self._dateien_gesamt = dateien
            self._bytes_gesamt = bytes_gesamt
            self._start = time.monotonic()

    def bytes_uebertragen(self, anzahl: int) -> None:
        """Meldet in diesem Lauf übertragene Bytes.

        Args:
            anzahl: Anzahl Bytes.
        """
        with self._sperre:
            self._bytes_fertig += anzahl
            self._bytes_uebertragen += anzahl

    def bytes_vorhanden(self, anzahl: int) -> None:
        """Meldet Bytes, die schon vorher im Ziel lagen (zählen nicht zur Rate).

        Args:
            anzahl: Anzahl Bytes.
        """
        with self._sperre:
            self._bytes_fertig += anzahl

    def datei_hochgeladen(self) -> None:
        """Meldet eine vollständig hochgeladene Datei."""
        with self._sperre:
            self._hochgeladen += 1

    def datei_uebersprungen(self, groesse: int) -> None:
        """Meldet eine bereits erledigte Datei.

        Args:
            groesse: Größe der Datei in Bytes.
        """
        with self._sperre:
            self._uebersprungen += 1
            self._bytes_fertig += groesse

    def datei_fehlgeschlagen(self, groesse: int, bereits_gezaehlt: int) -> None:
        """Meldet eine fehlgeschlagene Datei.

        Die noch offenen Bytes der Datei werden als „fertig“ verbucht, damit Prozentangabe
        und Restzeit nicht auf eine Datei warten, die in diesem Lauf nicht mehr kommt.

        Args:
            groesse: Größe der Datei in Bytes.
            bereits_gezaehlt: Bytes dieser Datei, die schon gemeldet wurden.
        """
        with self._sperre:
            self._fehler += 1
            self._bytes_fertig += max(groesse - bereits_gezaehlt, 0)

    def momentaufnahme(self) -> Momentaufnahme:
        """Liefert den aktuellen Stand.

        Returns:
            Unveränderliche Momentaufnahme.
        """
        with self._sperre:
            return Momentaufnahme(
                dateien_gesamt=self._dateien_gesamt,
                dateien_hochgeladen=self._hochgeladen,
                dateien_uebersprungen=self._uebersprungen,
                dateien_fehler=self._fehler,
                bytes_gesamt=self._bytes_gesamt,
                bytes_fertig=self._bytes_fertig,
                bytes_uebertragen=self._bytes_uebertragen,
                dauer=time.monotonic() - self._start,
            )


class Anzeige:
    """Gibt den Fortschritt in einem Hintergrund-Thread regelmäßig aus.

    Im Terminal wird eine Zeile laufend überschrieben. Wird die Ausgabe umgeleitet (Datei,
    Cron, CI), erscheint stattdessen in größerem Abstand je eine neue Zeile, damit das
    Protokoll lesbar bleibt.

    Args:
        fortschritt: Zu beobachtender Zähler.
        ausgabe: Zielstrom, üblicherweise ``sys.stderr``.
        intervall: Sekunden zwischen zwei Ausgaben im Terminal.
        intervall_protokoll: Sekunden zwischen zwei Ausgaben ohne Terminal.
    """

    def __init__(
        self,
        fortschritt: Fortschritt,
        ausgabe: TextIO,
        intervall: float = 0.5,
        intervall_protokoll: float = 30.0,
    ) -> None:
        self._fortschritt = fortschritt
        self._terminal = Terminal(ausgabe)
        self._intervall = intervall if self._terminal.ist_terminal else intervall_protokoll
        self._stopp = threading.Event()
        self._thread = threading.Thread(target=self._schleife, name="anzeige", daemon=True)

    def __enter__(self) -> Anzeige:
        self._thread.start()
        return self

    def __exit__(
        self,
        typ: type[BaseException] | None,
        wert: BaseException | None,
        verlauf: TracebackType | None,
    ) -> None:
        self._stopp.set()
        self._thread.join()
        self._zeichne(abschluss=True)

    def _schleife(self) -> None:
        while not self._stopp.wait(self._intervall):
            self._zeichne()

    def _zeichne(self, abschluss: bool = False) -> None:
        zeile = self._fortschritt.momentaufnahme().als_zeile()
        if self._terminal.ist_terminal:
            self._terminal.ueberschreibe(zeile, abschluss)
        else:
            self._terminal.ausgabe.write(zeile + "\n")
            self._terminal.ausgabe.flush()


class ZeilenfesterHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Logging-Handler, der vor jeder Meldung die laufende Fortschrittszeile löscht.

    Ohne ihn würde eine Warnung mitten in die überschriebene Fortschrittszeile geschrieben.

    Args:
        ausgabe: Zielstrom, üblicherweise ``sys.stderr``.
    """

    def __init__(self, ausgabe: TextIO) -> None:
        super().__init__(ausgabe)
        self._terminal = Terminal(ausgabe)

    def emit(self, record: logging.LogRecord) -> None:
        """Gibt eine Meldung aus und löscht im Terminal vorher die aktuelle Zeile.

        Args:
            record: Zu protokollierende Meldung.
        """
        if self._terminal.ist_terminal:
            self.stream.write(self._terminal.loesch_text())
        super().emit(record)
