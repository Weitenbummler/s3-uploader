"""s3-uploader – wiederaufsetzbares Hochladen vieler und großer Dateien in einen S3-Bucket.

Autor: Oliver Tesch. Lizenz: MIT (siehe LICENSE).
"""

from importlib.metadata import PackageNotFoundError, version

__author__ = "Oliver Tesch"

try:
    # Die Version steht nur in pyproject.toml (PY-V1) und wird hier zur Laufzeit gelesen.
    __version__ = version("s3-uploader")
except PackageNotFoundError:  # pragma: no cover - nur bei Aufruf ohne Installation
    __version__ = "0.0.0"
