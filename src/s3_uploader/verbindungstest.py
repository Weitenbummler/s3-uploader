"""Verbindungstest: prüft Endpunkt, Anmeldung, Bucket, Leserecht und optional Schreibrecht."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, SSLError

from s3_uploader.client import S3Client


@dataclass(frozen=True, slots=True)
class Pruefung:
    """Ergebnis eines einzelnen Prüfschritts.

    Attributes:
        name: Bezeichnung des Schritts.
        ok: Ob der Schritt erfolgreich war.
        hinweis: Erläuterung bzw. Fehlerursache für den Benutzer.
    """

    name: str
    ok: bool
    hinweis: str


def _beschreibe_fehler(err: Exception) -> str:
    """Übersetzt typische Fehler in verständliche Hinweise."""
    if isinstance(err, SSLError):
        text = str(err)
        if re.search(r"self[- ]signed|unable to get local issuer", text):
            return (
                "Zertifikat des Endpunkts ist selbst signiert oder von einer eigenen "
                "Zertifizierungsstelle – deren Zertifikat mit --ca-zertifikat DATEI.pem angeben "
                "(siehe README). Nur zum Testen: --ohne-tls-pruefung."
            )
        if "expired" in text:
            return "Zertifikat des Endpunkts ist abgelaufen – Betreiber des Speichers informieren."
        if "hostname" in text.lower() or "match" in text.lower():
            return (
                "Zertifikat passt nicht zum Namen des Endpunkts – genau den Namen aus dem "
                "Zertifikat in --endpunkt verwenden (nicht die IP-Adresse oder einen Alias)."
            )
        return f"TLS-Fehler: {text} – Zertifikat prüfen, ggf. --ca-zertifikat angeben."
    if isinstance(err, EndpointConnectionError):
        return "Endpunkt nicht erreichbar – URL, Port, Netzwerk oder Firewall prüfen."
    if isinstance(err, ClientError):
        code = str(err.response.get("Error", {}).get("Code", ""))
        status = err.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            return f"Zugriff verweigert ({code}) – Access Key, Passwort und Rechte prüfen."
        if code in {"404", "NoSuchBucket"}:
            return "Bucket existiert nicht – Namen prüfen."
        if code in {"301", "PermanentRedirect"}:
            return "Falsche Region oder Adressierung – --region oder --adressierung prüfen."
        return f"S3-Fehler {code or status}: {err}"
    return f"{type(err).__name__}: {err}"


def teste_verbindung(
    client: S3Client, bucket: str, prefix: str, schreibtest: bool = False
) -> list[Pruefung]:
    """Führt die Prüfschritte nacheinander aus und bricht beim ersten Fehler ab.

    Schritte:

    1. ``HeadBucket`` – Endpunkt erreichbar, Anmeldung gültig, Bucket vorhanden.
    2. ``ListObjectsV2`` mit Präfix – Leserecht.
    3. Optional ``PutObject`` und ``DeleteObject`` einer kleinen Testdatei unter dem Präfix –
       Schreibrecht. Ohne Löschrecht bleibt die Testdatei liegen; das wird gemeldet.

    Args:
        client: S3-Client.
        bucket: Bucket-Name.
        prefix: Normalisiertes Präfix.
        schreibtest: Ob das Schreibrecht geprüft werden soll.

    Returns:
        Ergebnisse der ausgeführten Schritte.
    """
    ergebnisse: list[Pruefung] = []

    def schritt(name: str, aktion: Callable[[], str]) -> bool:
        """Führt einen Schritt aus, merkt sich das Ergebnis und meldet den Erfolg."""
        try:
            hinweis = aktion()
        except (ClientError, BotoCoreError) as err:
            ergebnisse.append(Pruefung(name, False, _beschreibe_fehler(err)))
            return False
        ergebnisse.append(Pruefung(name, True, hinweis))
        return True

    def anmelden() -> str:
        client.head_bucket(Bucket=bucket)
        return f"Bucket {bucket!r} erreichbar"

    def lesen() -> str:
        antwort = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
        return "Präfix enthält bereits Objekte" if antwort.get("KeyCount", 0) else "Präfix ist leer"

    testschluessel = f"{prefix}.s3-uploader-verbindungstest-{uuid.uuid4().hex}"

    def schreiben() -> str:
        client.put_object(Bucket=bucket, Key=testschluessel, Body=b"s3-uploader")
        return f"Testobjekt {testschluessel!r} angelegt"

    def loeschen() -> str:
        client.delete_object(Bucket=bucket, Key=testschluessel)
        return "Testobjekt wieder entfernt"

    # Kurzschlussauswertung: Jeder Schritt läuft nur, wenn der vorige erfolgreich war.
    if (
        schritt("Anmeldung und Bucket", anmelden)
        and schritt("Leserecht", lesen)
        and schreibtest
        and schritt("Schreibrecht", schreiben)
    ):
        schritt("Löschrecht", loeschen)
    return ergebnisse
