"""Durchsuchen des Quellverzeichnisses nach hochzuladenden Dateien."""

from __future__ import annotations

import fnmatch
import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from s3_uploader.fehler import KonfigurationsFehler

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Datei:
    """Eine lokale Datei mit ihrem Zielschlüssel.

    Attributes:
        pfad: Absoluter lokaler Pfad.
        schluessel: Objektschlüssel im Bucket (Präfix + relativer Pfad mit ``/``).
        groesse: Größe in Bytes zum Zeitpunkt der Suche.
        mtime_ns: Änderungszeit in Nanosekunden; zusammen mit der Größe erkennt das
            Wiederaufsetzen, ob sich eine Datei seit dem letzten Lauf verändert hat.
    """

    pfad: Path
    schluessel: str
    groesse: int
    mtime_ns: int


def finde_dateien(quelle: Path, prefix: str, ausschluesse: Sequence[str] = ()) -> Iterator[Datei]:
    """Liefert alle regulären Dateien unterhalb von ``quelle`` in stabiler Reihenfolge.

    Die Suche arbeitet mit einem eigenen Stapel statt Rekursion, damit auch sehr tiefe
    Verzeichnisbäume kein Rekursionslimit erreichen. Symbolische Links werden nicht verfolgt
    und protokolliert: Sie könnten Schleifen bilden oder Dateien außerhalb der Quelle
    einschließen.

    Args:
        quelle: Quellverzeichnis.
        prefix: Normalisiertes Schlüsselpräfix.
        ausschluesse: Glob-Muster für relative Pfade (``*.tmp``, ``cache/*``).

    Yields:
        Gefundene Dateien.

    Raises:
        KonfigurationsFehler: Wenn ``quelle`` kein Verzeichnis ist.
    """
    if not quelle.is_dir():
        raise KonfigurationsFehler(f"Quellverzeichnis nicht gefunden: {quelle}")
    wurzel = quelle.resolve()
    stapel = [wurzel]
    while stapel:
        verzeichnis = stapel.pop()
        try:
            eintraege = sorted(os.scandir(verzeichnis), key=lambda e: e.name)
        except OSError as err:
            log.warning("Verzeichnis nicht lesbar, wird übersprungen: %s (%s)", verzeichnis, err)
            continue
        unterverzeichnisse: list[Path] = []
        for eintrag in eintraege:
            relativ = Path(eintrag.path).relative_to(wurzel).as_posix()
            if any(fnmatch.fnmatch(relativ, muster) for muster in ausschluesse):
                log.info("Ausgeschlossen: %s", relativ)
                continue
            if eintrag.is_symlink():
                log.warning("Symbolischer Link wird nicht verfolgt: %s", relativ)
            elif eintrag.is_dir(follow_symlinks=False):
                unterverzeichnisse.append(Path(eintrag.path))
            elif eintrag.is_file(follow_symlinks=False):
                info = eintrag.stat(follow_symlinks=False)
                yield Datei(
                    pfad=Path(eintrag.path),
                    schluessel=prefix + relativ,
                    groesse=info.st_size,
                    mtime_ns=info.st_mtime_ns,
                )
        # Umgekehrt auf den Stapel, damit alphabetisch zuerst Bearbeitetes oben liegt.
        stapel.extend(reversed(unterverzeichnisse))
