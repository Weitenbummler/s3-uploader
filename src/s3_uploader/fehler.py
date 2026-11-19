"""Ausnahmen des Pakets s3-uploader.

Alle fachlichen Fehler leiten von :class:`S3UploaderFehler` ab (PY-E1). So kann die
Kommandozeile sie gezielt abfangen, ohne fremde Programmierfehler zu verschlucken.
"""


class S3UploaderFehler(Exception):
    """Basisklasse aller fachlichen Fehler von s3-uploader."""


class KonfigurationsFehler(S3UploaderFehler):
    """Ungültige oder widersprüchliche Parameter."""


class UploadFehler(S3UploaderFehler):
    """Eine einzelne Datei konnte nicht hochgeladen werden."""


class Abgebrochen(S3UploaderFehler):
    """Der Lauf wurde vom Benutzer abgebrochen (z. B. mit Strg+C)."""
