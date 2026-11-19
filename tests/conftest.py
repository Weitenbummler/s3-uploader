"""Gemeinsame Testhilfen: S3-Attrappe (moto) und Beispieldateien."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from moto import mock_aws

from s3_uploader.client import erzeuge_client
from s3_uploader.konfiguration import Verbindung

BUCKET = "testbucket"
MIB = 1024**2


@pytest.fixture
def verbindung() -> Verbindung:
    # Fantasie-Zugangsdaten für die Attrappe – nie echte Daten in Tests (PY-X1).
    return Verbindung(
        endpunkt="https://s3.amazonaws.com",
        bucket=BUCKET,
        access_key="testkey",
        secret_key="testsecret",
    )


@pytest.fixture
def s3(verbindung: Verbindung) -> Iterator[Any]:
    """Startet die S3-Attrappe und legt den Test-Bucket an."""
    os.environ.pop("AWS_PROFILE", None)
    with mock_aws():
        client = erzeuge_client(verbindung)
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def quelle(tmp_path: Path) -> Path:
    """Quellverzeichnis mit kleinen Dateien, Unterordnern und einer großen Datei."""
    wurzel = tmp_path / "quelle"
    (wurzel / "unter" / "tief").mkdir(parents=True)
    (wurzel / "a.txt").write_text("Hallo")
    (wurzel / "unter" / "b.txt").write_text("Welt")
    (wurzel / "unter" / "tief" / "c.bin").write_bytes(bytes(range(256)) * 4)
    (wurzel / "gross.bin").write_bytes(os.urandom(12 * MIB))
    return wurzel


def lies_objekt(client: Any, schluessel: str) -> bytes:
    return bytes(client.get_object(Bucket=BUCKET, Key=schluessel)["Body"].read())
