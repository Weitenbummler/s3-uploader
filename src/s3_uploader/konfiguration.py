"""Konfigurationsobjekte und Hilfsfunktionen zum Einlesen von Parametern.

Die Kommandozeile übersetzt ihre Argumente in die hier definierten, unveränderlichen
Datenklassen. Alle übrigen Module arbeiten nur mit diesen Objekten (PY-P5, PY-T4).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import ssl
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
        ca_zertifikat: PEM-Datei mit dem Zertifikat (oder mehreren) der Zertifizierungsstelle,
            die das Serverzertifikat ausgestellt hat – nötig bei selbst signierten oder
            firmeneigenen Zertifikaten. ``None`` nimmt die üblichen öffentlichen
            Zertifizierungsstellen bzw. die Umgebungsvariable ``AWS_CA_BUNDLE``.
    """

    endpunkt: str
    bucket: str
    access_key: str
    secret_key: str = field(repr=False)
    region: str = "us-east-1"
    adressierung: Adressierung = "path"
    tls_pruefen: bool = True
    ca_zertifikat: Path | None = None


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


_PEM_ANFANG = b"-----BEGIN CERTIFICATE-----"
#: Größte geprüfte CA-Datei; Zertifikatsspeicher von Linux-Systemen sind rund 200 KB groß.
_MAX_CA_GROESSE = 10 * 1024**2


def pruefe_ca_datei(pfad: Path) -> None:
    """Stellt sicher, dass eine CA-Datei im PEM-Format vorliegt, bevor die Verbindung startet.

    Ohne diese Prüfung fiele ein falsches Format erst beim Verbindungsaufbau auf – mit einer
    schwer verständlichen TLS-Meldung. Erkannt werden die drei häufigsten Fälle:

    - binäres Format (DER), oft mit Endung ``.crt`` oder ``.cer``: beginnt mit dem Byte
      ``0x30`` (ASN.1-Sequenz);
    - Text in UTF-16, wie ihn Windows PowerShell 5.1 bei Umleitung mit ``>`` schreibt;
    - Dateien ganz ohne Zertifikat (z. B. nur ein privater Schlüssel);
    - doppelt kodierte Dateien: eine schon als Text vorliegende ``.crt`` wurde zusätzlich
      mit ``certutil -encode`` umgewandelt (OpenSSL meldet dann ``[X509] PEM lib``);
    - sonst beschädigte Inhalte – zum Schluss lädt die Prüfung die Datei probeweise mit dem
      ``ssl``-Modul, genau wie später die Verbindung.

    Args:
        pfad: Pfad der angegebenen CA-Datei.

    Raises:
        KonfigurationsFehler: Wenn die Datei fehlt, zu groß ist oder kein PEM-Zertifikat enthält.
    """
    if not pfad.is_file():
        raise KonfigurationsFehler(f"CA-Zertifikat nicht gefunden: {pfad}")
    if pfad.stat().st_size > _MAX_CA_GROESSE:
        raise KonfigurationsFehler(f"CA-Zertifikat ist unplausibel groß: {pfad}")
    inhalt = pfad.read_bytes()
    ziel = pfad.with_name(pfad.stem + "-ca.pem")
    if _PEM_ANFANG in inhalt:
        _pruefe_pem_inhalt(pfad, inhalt)
        return
    if inhalt.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise KonfigurationsFehler(
            f"CA-Zertifikat {pfad} ist als UTF-16 gespeichert (typisch für '>' in Windows "
            "PowerShell 5.1). Neu speichern mit: Get-Content "
            f'"{pfad}" | Set-Content "{ziel}" -Encoding ascii'
        )
    if inhalt[:1] == b"\x30":
        raise KonfigurationsFehler(
            f"CA-Zertifikat {pfad} ist im binären Format (DER) und muss einmal in das "
            "Textformat PEM umgewandelt werden. "
            f'Windows: certutil -encode "{pfad}" "{ziel}" – '
            f'macOS/Linux: openssl x509 -inform der -in "{pfad}" -out "{ziel}". '
            "Danach die neue Datei angeben."
        )
    raise KonfigurationsFehler(
        f"{pfad} enthält kein Zertifikat (keine Zeile '-----BEGIN CERTIFICATE-----'). "
        "Benötigt wird das Zertifikat der Zertifizierungsstelle, kein privater Schlüssel."
    )


def _pruefe_pem_inhalt(pfad: Path, inhalt: bytes) -> None:
    """Prüft die Zertifikatsblöcke einer PEM-Datei und lädt sie probeweise.

    Args:
        pfad: Pfad der Datei (für Meldungen).
        inhalt: Dateiinhalt.

    Raises:
        KonfigurationsFehler: Wenn ein Block doppelt kodiert oder beschädigt ist.
    """
    bloecke = re.findall(
        rb"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----", inhalt, flags=re.S
    )
    for block in bloecke:
        try:
            roh = base64.b64decode(b"".join(block.split()), validate=True)
        except (binascii.Error, ValueError):
            roh = b""
        if roh.startswith(b"-----BEGIN"):
            raise KonfigurationsFehler(
                f"CA-Zertifikat {pfad} ist doppelt kodiert: Die Ausgangsdatei war bereits im "
                "Textformat PEM und wurde zusätzlich umgewandelt (z. B. mit certutil -encode). "
                "Stattdessen die ursprüngliche .crt-Datei direkt mit --ca-zertifikat angeben."
            )
        if roh[:1] != b"\x30":
            raise KonfigurationsFehler(
                f"CA-Zertifikat {pfad} ist beschädigt (Inhalt zwischen BEGIN und END ist kein "
                "gültiges Zertifikat). Datei neu vom Betreiber besorgen oder neu exportieren."
            )
    try:
        ssl.create_default_context(cafile=str(pfad))
    except ssl.SSLError as err:
        raise KonfigurationsFehler(
            f"CA-Zertifikat {pfad} kann nicht geladen werden ({err}). Datei neu vom Betreiber "
            "besorgen oder neu exportieren."
        ) from err


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


def quellkennung(quelle: Path) -> str:
    r"""Liefert eine eindeutige Schreibweise des Quellverzeichnisses.

    Unter Windows sind Pfade unabhängig von Groß-/Kleinschreibung und ``/`` ist gleich ``\``.
    ``D:\Daten`` und ``d:/daten`` müssen deshalb dieselbe Zustandsdatei finden, sonst würde
    ein Fortsetzen von vorn beginnen. ``os.path.normcase`` gleicht das an; unter macOS und
    Linux lässt es den Pfad unverändert.

    Args:
        quelle: Quellverzeichnis.

    Returns:
        Absoluter, vereinheitlichter Pfad als Text.
    """
    return os.path.normcase(str(quelle.resolve()))


def standard_zustandsdatei(verbindung: Verbindung, quelle: Path, prefix: str) -> Path:
    r"""Ermittelt den Standardort der Zustandsdatei für eine Kombination aus Quelle und Ziel.

    Der Dateiname enthält einen Hash aus Endpunkt, Bucket, Präfix und Quellpfad. Derselbe
    Aufruf findet dadurch beim Wiederaufsetzen automatisch seine Zustandsdatei wieder,
    ohne dass Zugangsdaten im Namen auftauchen (PY-X4). Die Datei liegt bewusst nicht im
    Quellverzeichnis, damit sie nicht selbst hochgeladen wird.

    Args:
        verbindung: Zielverbindung.
        quelle: Quellverzeichnis.
        prefix: Normalisiertes Präfix.

    Returns:
        Pfad unter ``~/.s3-uploader/`` (Windows: ``%USERPROFILE%\.s3-uploader\``).
    """
    kennung = f"{verbindung.endpunkt}|{verbindung.bucket}|{prefix}|{quellkennung(quelle)}"
    kurz = hashlib.sha256(kennung.encode()).hexdigest()[:16]
    return Path.home() / ".s3-uploader" / f"zustand-{kurz}.sqlite"
