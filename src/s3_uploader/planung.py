"""Aufteilung großer Dateien in Teile für den S3-Multipart-Upload.

Grenzwerte laut AWS-Dokumentation „Amazon S3 multipart upload limits“
(https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html):

- Teile: 5 MiB bis 5 GiB, nur der letzte Teil darf kleiner sein.
- Höchstens 10 000 Teile je Upload.
- Objekte höchstens 5 TiB, ein einfacher PUT höchstens 5 GiB.
"""

from __future__ import annotations

from dataclasses import dataclass

from s3_uploader.fehler import KonfigurationsFehler, UploadFehler

MIB = 1024**2
MIN_TEILGROESSE = 5 * MIB
MAX_TEILGROESSE = 5 * 1024**3
MAX_TEILE = 10_000
MAX_OBJEKTGROESSE = 5 * 1024**4
MAX_EINFACHER_PUT = 5 * 1024**3


@dataclass(frozen=True, slots=True)
class Teil:
    """Ein Abschnitt einer Datei für den Multipart-Upload.

    Attributes:
        nummer: Teilnummer ab 1 (S3-Vorgabe).
        start: Byte-Position in der Datei.
        laenge: Anzahl Bytes.
    """

    nummer: int
    start: int
    laenge: int


def pruefe_schwelle(schwelle: int) -> None:
    """Stellt sicher, dass Dateien bis zur Schwelle per einfachem PUT hochladbar sind.

    Args:
        schwelle: Multipart-Schwelle in Bytes.

    Raises:
        KonfigurationsFehler: Wenn die Schwelle über 5 GiB liegt oder kleiner als 5 MiB ist.
    """
    if not MIN_TEILGROESSE <= schwelle <= MAX_EINFACHER_PUT:
        raise KonfigurationsFehler("Die Multipart-Schwelle muss zwischen 5 MiB und 5 GiB liegen.")


def braucht_multipart(dateigroesse: int, schwelle: int) -> bool:
    """Entscheidet, ob eine Datei in Teilen hochgeladen wird.

    Args:
        dateigroesse: Größe der Datei in Bytes.
        schwelle: Multipart-Schwelle in Bytes.

    Returns:
        ``True``, wenn die Datei größer als die Schwelle ist.
    """
    return dateigroesse > schwelle


def berechne_teilgroesse(dateigroesse: int, wunsch: int) -> int:
    """Bestimmt die Teilgröße so, dass die S3-Grenzen eingehalten werden.

    Ist die gewünschte Teilgröße zu klein, um die Datei in höchstens 10 000 Teilen
    unterzubringen, wird sie auf das nächste volle MiB oberhalb des Mindestwerts erhöht.

    Args:
        dateigroesse: Größe der Datei in Bytes.
        wunsch: Gewünschte Teilgröße in Bytes.

    Returns:
        Zulässige Teilgröße in Bytes.

    Raises:
        UploadFehler: Wenn die Datei größer als 5 TiB ist.
    """
    if dateigroesse > MAX_OBJEKTGROESSE:
        raise UploadFehler("Die Datei ist größer als 5 TiB und kann nicht in S3 abgelegt werden.")
    teilgroesse = min(max(wunsch, MIN_TEILGROESSE), MAX_TEILGROESSE)
    mindestens = -(-dateigroesse // MAX_TEILE)  # Aufrunden ohne Gleitkomma
    if teilgroesse < mindestens:
        teilgroesse = -(-mindestens // MIB) * MIB
    return teilgroesse


def zerlege(dateigroesse: int, teilgroesse: int) -> list[Teil]:
    """Zerlegt eine Datei in aufeinanderfolgende Teile.

    Args:
        dateigroesse: Größe der Datei in Bytes.
        teilgroesse: Teilgröße in Bytes (aus :func:`berechne_teilgroesse`).

    Returns:
        Liste der Teile, nummeriert ab 1. Der letzte Teil ist ggf. kürzer.
    """
    return [
        Teil(nummer=index + 1, start=start, laenge=min(teilgroesse, dateigroesse - start))
        for index, start in enumerate(range(0, dateigroesse, teilgroesse))
    ]
