"""Dauerhafter Laufzustand für das Wiederaufsetzen abgebrochener Uploads.

Der Zustand liegt in einer SQLite-Datei (Standardbibliothek). SQLite schreibt jede
Änderung atomar (PY-X6): Bricht der Lauf an beliebiger Stelle ab, bleibt die Datei
konsistent. Gespeichert werden je Datei Größe, Änderungszeit, Status und bei Multipart
die Upload-ID sowie die bereits übertragenen Teile. Zugangsdaten werden nie gespeichert
(PY-X4).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from s3_uploader.dateisuche import Datei
from s3_uploader.fehler import KonfigurationsFehler

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    schluessel TEXT PRIMARY KEY,
    wert TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dateien (
    schluessel TEXT PRIMARY KEY,
    groesse INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('laufend', 'erledigt')),
    upload_id TEXT,
    teilgroesse INTEGER,
    etag TEXT,
    aktualisiert REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS teile (
    schluessel TEXT NOT NULL,
    nummer INTEGER NOT NULL,
    etag TEXT NOT NULL,
    PRIMARY KEY (schluessel, nummer)
);
"""


@dataclass(frozen=True, slots=True)
class MultipartStand:
    """Gespeicherter Stand eines begonnenen Multipart-Uploads.

    Attributes:
        upload_id: Von S3 vergebene Kennung des Multipart-Uploads.
        teilgroesse: Beim Start gewählte Teilgröße in Bytes.
        teile: Bereits bestätigte Teile als Zuordnung Teilnummer → ETag.
    """

    upload_id: str
    teilgroesse: int
    teile: dict[int, str]


class Zustand:
    """Zugriff auf die Zustandsdatei, sicher für mehrere Threads.

    Eine einzige Verbindung wird von allen Arbeits-Threads geteilt und mit einer Sperre
    geschützt. Das ist einfacher als eine Verbindung je Thread und schnell genug, weil die
    Schreibzugriffe im Vergleich zur Netzwerkübertragung winzig sind.

    Args:
        pfad: Pfad der SQLite-Datei; fehlende Verzeichnisse werden angelegt.
    """

    def __init__(self, pfad: Path) -> None:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        self.pfad = pfad
        self._sperre = threading.Lock()
        # isolation_level=None: Autocommit, jede Anweisung ist sofort dauerhaft gespeichert.
        self._db = sqlite3.connect(pfad, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    # --- Kontextmanager -----------------------------------------------------------------

    def __enter__(self) -> Zustand:
        return self

    def __exit__(
        self,
        typ: type[BaseException] | None,
        wert: BaseException | None,
        verlauf: TracebackType | None,
    ) -> None:
        self.schliessen()

    def schliessen(self) -> None:
        """Schließt die Datenbankverbindung."""
        with self._sperre:
            self._db.close()

    # --- Kontext ------------------------------------------------------------------------

    def pruefe_kontext(self, kontext: str) -> None:
        """Bindet die Zustandsdatei an genau ein Ziel und eine Quelle.

        Beim ersten Lauf wird der Kontext gespeichert, später verglichen. So wird verhindert,
        dass eine Zustandsdatei versehentlich für ein anderes Ziel verwendet wird und Dateien
        fälschlich als erledigt gelten.

        Args:
            kontext: Beschreibung von Endpunkt, Bucket, Präfix und Quelle.

        Raises:
            KonfigurationsFehler: Wenn die Datei zu einem anderen Kontext gehört.
        """
        with self._sperre:
            zeile = self._db.execute(
                "SELECT wert FROM meta WHERE schluessel = 'kontext'"
            ).fetchone()
            if zeile is None:
                self._db.execute("INSERT INTO meta VALUES ('kontext', ?)", (kontext,))
            elif zeile[0] != kontext:
                raise KonfigurationsFehler(
                    f"Die Zustandsdatei {self.pfad} gehört zu einem anderen Lauf "
                    f"({zeile[0]}). Andere Datei mit --zustand wählen oder --neu verwenden."
                )

    # --- Abfragen -----------------------------------------------------------------------

    def ist_erledigt(self, datei: Datei) -> bool:
        """Prüft, ob die Datei in unveränderter Form bereits hochgeladen wurde.

        Args:
            datei: Lokale Datei.

        Returns:
            ``True``, wenn Status ``erledigt`` und Größe sowie Änderungszeit übereinstimmen.
        """
        with self._sperre:
            zeile = self._db.execute(
                "SELECT groesse, mtime_ns, status FROM dateien WHERE schluessel = ?",
                (datei.schluessel,),
            ).fetchone()
        return bool(zeile == (datei.groesse, datei.mtime_ns, "erledigt"))

    def multipart_stand(self, datei: Datei) -> MultipartStand | None:
        """Liefert einen begonnenen Multipart-Upload für die unveränderte Datei.

        Args:
            datei: Lokale Datei.

        Returns:
            Gespeicherter Stand oder ``None``, wenn keiner existiert oder die Datei sich
            inzwischen verändert hat.
        """
        with self._sperre:
            zeile = self._db.execute(
                "SELECT upload_id, teilgroesse FROM dateien "
                "WHERE schluessel = ? AND groesse = ? AND mtime_ns = ? "
                "AND status = 'laufend' AND upload_id IS NOT NULL",
                (datei.schluessel, datei.groesse, datei.mtime_ns),
            ).fetchone()
            if zeile is None:
                return None
            teile = dict(
                self._db.execute(
                    "SELECT nummer, etag FROM teile WHERE schluessel = ?", (datei.schluessel,)
                ).fetchall()
            )
        return MultipartStand(upload_id=zeile[0], teilgroesse=zeile[1], teile=teile)

    def veralteter_upload(self, datei: Datei) -> str | None:
        """Findet einen begonnenen Multipart-Upload zu einer inzwischen veränderten Datei.

        Args:
            datei: Lokale Datei in ihrem aktuellen Zustand.

        Returns:
            Upload-ID des veralteten Uploads, der abgebrochen werden sollte, sonst ``None``.
        """
        with self._sperre:
            zeile = self._db.execute(
                "SELECT upload_id FROM dateien WHERE schluessel = ? AND upload_id IS NOT NULL "
                "AND (groesse != ? OR mtime_ns != ?)",
                (datei.schluessel, datei.groesse, datei.mtime_ns),
            ).fetchone()
        return None if zeile is None else str(zeile[0])

    def offener_upload(self, schluessel: str) -> str | None:
        """Liefert die Upload-ID eines begonnenen Multipart-Uploads, unabhängig vom Dateistand.

        Wird gebraucht, wenn ein Lauf mit Teilung begonnen und ohne Teilung fortgesetzt wird:
        Der alte Multipart-Upload muss dann abgebrochen werden.

        Args:
            schluessel: Objektschlüssel.

        Returns:
            Upload-ID oder ``None``.
        """
        with self._sperre:
            zeile = self._db.execute(
                "SELECT upload_id FROM dateien WHERE schluessel = ? AND upload_id IS NOT NULL",
                (schluessel,),
            ).fetchone()
        return None if zeile is None else str(zeile[0])

    def anzahl_erledigt(self) -> int:
        """Zählt die als erledigt gespeicherten Dateien.

        Returns:
            Anzahl der Dateien mit Status ``erledigt``.
        """
        with self._sperre:
            return int(
                self._db.execute(
                    "SELECT COUNT(*) FROM dateien WHERE status = 'erledigt'"
                ).fetchone()[0]
            )

    # --- Änderungen ---------------------------------------------------------------------

    def starte_multipart(self, datei: Datei, upload_id: str, teilgroesse: int) -> None:
        """Merkt sich einen neu begonnenen Multipart-Upload.

        Args:
            datei: Lokale Datei.
            upload_id: Von S3 vergebene Upload-ID.
            teilgroesse: Gewählte Teilgröße in Bytes.
        """
        with self._sperre:
            self._db.execute("DELETE FROM teile WHERE schluessel = ?", (datei.schluessel,))
            self._db.execute(
                "INSERT OR REPLACE INTO dateien VALUES (?, ?, ?, 'laufend', ?, ?, NULL, ?)",
                (
                    datei.schluessel,
                    datei.groesse,
                    datei.mtime_ns,
                    upload_id,
                    teilgroesse,
                    time.time(),
                ),
            )

    def teil_erledigt(self, schluessel: str, nummer: int, etag: str) -> None:
        """Speichert einen erfolgreich übertragenen Teil.

        Args:
            schluessel: Objektschlüssel.
            nummer: Teilnummer.
            etag: Von S3 gelieferter ETag des Teils.
        """
        with self._sperre:
            self._db.execute(
                "INSERT OR REPLACE INTO teile VALUES (?, ?, ?)", (schluessel, nummer, etag)
            )

    def markiere_erledigt(self, datei: Datei, etag: str | None) -> None:
        """Markiert eine Datei als vollständig hochgeladen und räumt Teildaten auf.

        Args:
            datei: Lokale Datei.
            etag: ETag des fertigen Objekts, falls bekannt.
        """
        with self._sperre:
            self._db.execute("DELETE FROM teile WHERE schluessel = ?", (datei.schluessel,))
            self._db.execute(
                "INSERT OR REPLACE INTO dateien VALUES (?, ?, ?, 'erledigt', NULL, NULL, ?, ?)",
                (datei.schluessel, datei.groesse, datei.mtime_ns, etag, time.time()),
            )

    def verwerfe(self, schluessel: str) -> None:
        """Entfernt alle Angaben zu einer Datei, z. B. nach einem abgebrochenen Multipart.

        Args:
            schluessel: Objektschlüssel.
        """
        with self._sperre:
            self._db.execute("DELETE FROM teile WHERE schluessel = ?", (schluessel,))
            self._db.execute("DELETE FROM dateien WHERE schluessel = ?", (schluessel,))
