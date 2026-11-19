"""Erzeugung des S3-Clients mit Zeitlimits, Wiederholungen und Kompatibilitätseinstellungen."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config

from s3_uploader.konfiguration import Verbindung

#: boto3 erzeugt Clients dynamisch und liefert ohne das Zusatzpaket boto3-stubs keine
#: Typen. ``Any`` macht diese Lücke an genau einer Stelle sichtbar.
S3Client = Any


def tls_pruefung(verbindung: Verbindung) -> bool | str | None:
    """Bestimmt den Wert für boto3s Parameter ``verify``.

    - ``False``: keine Prüfung (``--ohne-tls-pruefung``).
    - Pfad als Text: nur Zertifizierungsstellen aus dieser PEM-Datei gelten
      (``--ca-zertifikat``).
    - ``None``: boto3 entscheidet selbst – öffentliche Zertifizierungsstellen oder, falls
      gesetzt, die Datei aus der Umgebungsvariablen ``AWS_CA_BUNDLE``. Ein festes ``True``
      wäre hier falsch, denn damit übergeht boto3 ``AWS_CA_BUNDLE``.

    Args:
        verbindung: Verbindungsangaben.

    Returns:
        Wert für ``verify``.
    """
    if not verbindung.tls_pruefen:
        return False
    if verbindung.ca_zertifikat is not None:
        return str(verbindung.ca_zertifikat)
    return None


def erzeuge_client(
    verbindung: Verbindung, max_verbindungen: int = 10, max_versuche: int = 10
) -> S3Client:
    """Erzeugt einen S3-Client für einen beliebigen S3-kompatiblen Endpunkt.

    Wichtige Einstellungen:

    - Zeitlimits für Aufbau und Lesen sowie bis zu 10 Versuche mit adaptivem Backoff
      (PY-E6). Damit übersteht der Lauf kurze Netzstörungen und Drosselung (HTTP 503).
    - ``request_checksum_calculation="when_required"``: Neuere boto3-Versionen senden
      sonst standardmäßig CRC-Prüfsummen, die viele S3-kompatible Speicher ablehnen. Die
      Integrität sichert s3-uploader stattdessen selbst über ``Content-MD5``.
    - Der Verbindungspool wird an die Parallelität angepasst, sonst warten Threads auf
      freie Verbindungen.
    - Zertifikatsprüfung siehe :func:`tls_pruefung`.

    Args:
        verbindung: Endpunkt und Zugangsdaten.
        max_verbindungen: Größe des HTTP-Verbindungspools.
        max_versuche: Versuche je Anfrage. Für Prüfungen klein halten: Auch dauerhafte
            Fehler wie ein unbekanntes Zertifikat wiederholt boto3 sonst mehrfach mit
            wachsender Wartezeit, und die Meldung käme erst nach rund einer halben Minute.

    Returns:
        boto3-S3-Client.
    """
    konfig = Config(
        region_name=verbindung.region,
        connect_timeout=15,
        read_timeout=120,
        retries={"max_attempts": max_versuche, "mode": "adaptive"},
        max_pool_connections=max_verbindungen,
        s3={"addressing_style": verbindung.adressierung},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client(
        "s3",
        endpoint_url=verbindung.endpunkt,
        aws_access_key_id=verbindung.access_key,
        aws_secret_access_key=verbindung.secret_key,
        verify=tls_pruefung(verbindung),
        config=konfig,
    )
