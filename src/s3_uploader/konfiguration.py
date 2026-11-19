"""Konfigurationsobjekte und Hilfsfunktionen zum Einlesen von Parametern.

Die Kommandozeile übersetzt ihre Argumente in die hier definierten, unveränderlichen
Datenklassen. Alle übrigen Module arbeiten nur mit diesen Objekten (PY-P5, PY-T4).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from s3_uploader.fehler import KonfigurationsFehler

#: Erlaubte Adressierungsarten von S3. ``path`` (https://endpunkt/bucket/schluessel) ist bei
#: S3-kompatiblen Speichern (MinIO, Ceph, NetApp, Wasabi …) am verbreitetsten.
Adressierung = Literal["path", "virtual", "auto"]

_EINHEITEN = {
    "": 1,
    "B": 1,
    "K": 1000,
    "KB": 1000,
    "KIB": 1024,
    "M": 1000**2,
    "MB": 1000**2,
    "MIB": 1024**2,
    "G": 1000**3,
    "GB": 1000**3,
    "GIB": 1024**3,
}


@dataclass(frozen=True, slots=True)
class Verbindung:
    """Zugangsdaten und Adresse des S3-Speichers.

    Attributes:
        endpunkt: URL des S3-Endpunkts, z. B. ``https://s3.example.org``.
        bucket: Name des Ziel-Buckets.
        access_key: Access Key (Benutzerkennung).
        secret_key: Secret Key (Passwort). Wird in ``repr`` nicht angezeigt (PY-X3).
        region: Region für die Signatur; S3-kompatible Speicher akzeptieren meist jede.
        adressierung: Adressierungsart, siehe :data:`Adressierung`.
        tls_pruefen: Ob das TLS-Zertifikat des Endpunkts geprüft wird.
    """

    endpunkt: str
    bucket: str
    access_key: str
    secret_key: str = field(repr=False)
    region: str = "us-east-1"
    adressierung: Adressierung = "path"
    tls_pruefen: bool = True


@dataclass(frozen=True, slots=True)
class UploadEinstellungen:
    """Steuerung eines Upload-Laufs.

    Attributes:
        quelle: Quellverzeichnis, dessen Inhalt rekursiv hochgeladen wird.
        prefix: Schlüsselpräfix im Bucket (normalisiert, endet auf ``/`` oder ist leer).
        zustandsdatei: SQLite-Datei, in der der Fortschritt für das Wiederaufsetzen steht.
        schwelle: Ab dieser Dateigröße (Bytes, exklusiv) wird Multipart verwendet.
        teilgroesse: Gewünschte Teilgröße für Multipart in Bytes (wird bei Bedarf vergrößert).
        parallel_dateien: Anzahl gleichzeitig bearbeiteter Dateien.
        parallel_teile: Anzahl gleichzeitig hochgeladener Teile je Multipart-Datei.
        teilung: Ob große Dateien in Teilen (Multipart) hochgeladen werden. Ohne Teilung
            geht jede Datei als ein ``PutObject``; dann gilt die S3-Grenze von 5 GiB je Datei
            und ein abgebrochener Upload einer Datei beginnt beim Fortsetzen von vorn.
        pruefe_ziel: Vor dem Upload prüfen, ob das Objekt mit gleicher Größe schon existiert.
        ausschluesse: Glob-Muster relativer Pfade, die nicht hochgeladen werden.
    """

    quelle: Path
    prefix: str
    zustandsdatei: Path
    schwelle: int = 64 * 1024**2
    teilgroesse: int = 16 * 1024**2
    parallel_dateien: int = 4
    parallel_teile: int = 4
    teilung: bool = True
    pruefe_ziel: bool = False
    ausschluesse: tuple[str, ...] = ()


def normalisiere_prefix(prefix: str) -> str:
    """Bringt ein Schlüsselpräfix in eine einheitliche Form.

    Führende Schrägstriche werden entfernt, mehrfache zusammengefasst und ein nicht leeres
    Präfix endet immer auf ``/``. So entstehen keine Schlüssel wie ``//daten/x``.

    Args:
        prefix: Präfix in beliebiger Schreibweise, z. B. ``/backup//2026``.

    Returns:
        Normalisiertes Präfix, z. B. ``backup/2026/``, oder ``""``.
    """
    teile = [teil for teil in prefix.replace("\\", "/").split("/") if teil]
    return "/".join(teile) + "/" if teile else ""


def parse_groesse(text: str) -> int:
    """Wandelt eine Größenangabe wie ``16MiB`` oder ``100M`` in Bytes um.

    Args:
        text: Zahl mit optionaler Einheit (B, K, KB, KiB, M, MB, MiB, G, GB, GiB).

    Returns:
        Anzahl Bytes.

    Raises:
        KonfigurationsFehler: Wenn die Angabe nicht verstanden wird.
    """
    treffer = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([A-Za-z]*)\s*", text)
    if not treffer or treffer.group(2).upper() not in _EINHEITEN:
        raise KonfigurationsFehler(f"Unverständliche Größenangabe: {text!r} (Beispiel: 16MiB)")
    zahl = float(treffer.group(1).replace(",", "."))
    return int(zahl * _EINHEITEN[treffer.group(2).upper()])


def standard_zustandsdatei(verbindung: Verbindung, quelle: Path, prefix: str) -> Path:
    """Ermittelt den Standardort der Zustandsdatei für eine Kombination aus Quelle und Ziel.

    Der Dateiname enthält einen Hash aus Endpunkt, Bucket, Präfix und Quellpfad. Derselbe
    Aufruf findet dadurch beim Wiederaufsetzen automatisch seine Zustandsdatei wieder,
    ohne dass Zugangsdaten im Namen auftauchen (PY-X4). Die Datei liegt bewusst nicht im
    Quellverzeichnis, damit sie nicht selbst hochgeladen wird.

    Args:
        verbindung: Zielverbindung.
        quelle: Quellverzeichnis.
        prefix: Normalisiertes Präfix.

    Returns:
        Pfad unter ``~/.s3-uploader/``.
    """
    kennung = f"{verbindung.endpunkt}|{verbindung.bucket}|{prefix}|{quelle.resolve()}"
    kurz = hashlib.sha256(kennung.encode()).hexdigest()[:16]
    return Path.home() / ".s3-uploader" / f"zustand-{kurz}.sqlite"
