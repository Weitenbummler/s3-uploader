"""Kern des Programms: lädt Dateien einfach oder in Teilen hoch und setzt Läufe fort.

Ablauf je Datei (siehe auch ``docs/architektur.md``):

1. Laut Zustandsdatei bereits erledigt und unverändert → überspringen.
2. Optional: Objekt gleicher Größe existiert im Ziel → als erledigt merken, überspringen.
3. Datei bis zur Schwelle oder Teilung abgeschaltet → ein einzelnes ``PutObject``
   (höchstens 5 GiB, der Inhalt wird gestreamt statt ganz in den Speicher geladen).
4. Größere Datei bei eingeschalteter Teilung → Multipart-Upload. Ein gespeicherter Upload
   wird fortgesetzt; welche Teile fertig sind, fragt das Programm beim Server ab
   (``ListParts``), denn nur dessen Auskunft ist verlässlich.

Parallelität: Ein Thread-Pool bearbeitet mehrere Dateien gleichzeitig, jede
Multipart-Datei nutzt zusätzlich einen eigenen kleinen Pool für ihre Teile. Höchstens
``parallel_dateien × parallel_teile`` Teile liegen gleichzeitig im Speicher.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
from collections.abc import Callable
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from botocore.exceptions import BotoCoreError, ClientError

from s3_uploader.client import S3Client
from s3_uploader.dateisuche import Datei
from s3_uploader.fehler import Abgebrochen, S3UploaderFehler, UploadFehler
from s3_uploader.fortschritt import Fortschritt
from s3_uploader.konfiguration import UploadEinstellungen
from s3_uploader.planung import (
    MAX_EINFACHER_PUT,
    Teil,
    berechne_teilgroesse,
    braucht_multipart,
    zerlege,
)
from s3_uploader.zustand import Zustand

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Ergebnis:
    """Zusammenfassung eines Laufs.

    Attributes:
        hochgeladen: Anzahl in diesem Lauf hochgeladener Dateien.
        uebersprungen: Anzahl bereits erledigter Dateien.
        fehler: Fehlgeschlagene Dateien als Paare (Schlüssel, Ursache).
    """

    hochgeladen: int = 0
    uebersprungen: int = 0
    fehler: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Plan:
    """Vorschau eines Laufs ohne Übertragung (Probelauf).

    Attributes:
        dateien: Anzahl aller gefundenen Dateien.
        bytes_gesamt: Gesamtgröße.
        erledigt: Bereits laut Zustandsdatei erledigte Dateien.
        einfach: Offene Dateien, die mit einem PUT übertragen werden.
        multipart: Offene Dateien, die in Teilen übertragen werden.
        bytes_offen: Größe der offenen Dateien.
        zu_gross: Offene Dateien über 5 GiB, die ohne Teilung nicht hochladbar sind.
    """

    dateien: int
    bytes_gesamt: int
    erledigt: int
    einfach: int
    multipart: int
    bytes_offen: int
    zu_gross: int = 0


class _Zaehler:
    """Threadsicherer Zähler für die bereits gemeldeten Bytes einer Datei.

    ``x += 1`` ist in Python nicht atomar; mehrere Teil-Threads brauchen daher eine Sperre.
    """

    def __init__(self) -> None:
        self._sperre = threading.Lock()
        self.wert = 0

    def plus(self, anzahl: int) -> None:
        with self._sperre:
            self.wert += anzahl


_LESEBLOCK = 8 * 1024**2


class _FortschrittsLeser:
    """Hülle um eine geöffnete Datei, die gelesene Bytes an die Fortschrittsanzeige meldet.

    So bewegt sich die Anzeige auch bei einem einzelnen großen ``PutObject``. botocore springt
    bei einer Wiederholung mit ``seek(0)`` an den Anfang zurück; gemeldet wird deshalb nur,
    was über die bisher weiteste Leseposition hinausgeht – nichts wird doppelt gezählt.

    Args:
        datei: Zum Lesen geöffnete Datei.
        melde: Wird mit der Anzahl neu gelesener Bytes aufgerufen.
    """

    def __init__(self, datei: IO[bytes], melde: Callable[[int], None]) -> None:
        self._datei = datei
        self._melde = melde
        self._weiteste = 0

    def read(self, anzahl: int = -1) -> bytes:
        """Liest wie ``IO.read`` und meldet neu erreichte Bytes."""
        daten = self._datei.read(anzahl)
        position = self._datei.tell()
        if position > self._weiteste:
            self._melde(position - self._weiteste)
            self._weiteste = position
        return daten

    def __getattr__(self, name: str) -> Any:
        # seek, tell, close … reicht die Hülle unverändert an die Datei durch.
        return getattr(self._datei, name)


def _md5_datei_base64(pfad: Path) -> str:
    """Berechnet ``Content-MD5`` blockweise, ohne die Datei ganz in den Speicher zu laden."""
    pruefsumme = hashlib.md5(usedforsecurity=False)
    with pfad.open("rb") as datei:
        while block := datei.read(_LESEBLOCK):
            pruefsumme.update(block)
    return base64.b64encode(pruefsumme.digest()).decode()


def _md5_base64(daten: bytes) -> str:
    """Berechnet den Wert für den HTTP-Kopf ``Content-MD5``.

    Der Server prüft damit, ob die Daten unverfälscht angekommen sind, und lehnt sonst ab.
    MD5 dient hier nur der Übertragungsprüfung, nicht der Sicherheit.
    """
    return base64.b64encode(hashlib.md5(daten, usedforsecurity=False).digest()).decode()


def _fehlercode(err: ClientError) -> str:
    return str(err.response.get("Error", {}).get("Code", ""))


class Uploader:
    """Lädt eine Liste von Dateien in einen Bucket und führt dabei den Zustand nach.

    Args:
        client: S3-Client.
        bucket: Ziel-Bucket.
        einstellungen: Steuerung des Laufs.
        zustand: Zustandsdatei.
        fortschritt: Zähler für die Fortschrittsanzeige.
        abbruch: Wird gesetzt, wenn der Lauf beendet werden soll; laufende Teile werden
            noch fertig übertragen, neue nicht mehr begonnen.
    """

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        einstellungen: UploadEinstellungen,
        zustand: Zustand,
        fortschritt: Fortschritt,
        abbruch: threading.Event | None = None,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._e = einstellungen
        self._zustand = zustand
        self._fortschritt = fortschritt
        self._abbruch = abbruch or threading.Event()

    # --- Öffentliche Schnittstelle ------------------------------------------------------

    def plane(self, dateien: list[Datei]) -> Plan:
        """Ermittelt, was ein Lauf tun würde, ohne etwas zu übertragen.

        Args:
            dateien: Gefundene Dateien.

        Returns:
            Vorschau des Laufs.
        """
        offen = [d for d in dateien if not self._zustand.ist_erledigt(d)]
        anzahl_multipart = sum(self._in_teilen(d) for d in offen)
        zu_gross = 0 if self._e.teilung else sum(d.groesse > MAX_EINFACHER_PUT for d in offen)
        return Plan(
            dateien=len(dateien),
            bytes_gesamt=sum(d.groesse for d in dateien),
            erledigt=len(dateien) - len(offen),
            einfach=len(offen) - anzahl_multipart,
            multipart=anzahl_multipart,
            bytes_offen=sum(d.groesse for d in offen),
            zu_gross=zu_gross,
        )

    def lade_hoch(self, dateien: list[Datei]) -> Ergebnis:
        """Lädt alle Dateien hoch; Fehler einzelner Dateien beenden den Lauf nicht.

        Args:
            dateien: Hochzuladende Dateien.

        Returns:
            Zusammenfassung des Laufs.

        Raises:
            KeyboardInterrupt: Bei Strg+C, nachdem laufende Teile abgeschlossen sind. Der
                Zustand ist dann gespeichert und der Lauf kann fortgesetzt werden.
        """
        ergebnis = Ergebnis()
        self._fortschritt.beginne(len(dateien), sum(d.groesse for d in dateien))
        pool = ThreadPoolExecutor(self._e.parallel_dateien, thread_name_prefix="datei")
        try:
            auftraege = {pool.submit(self._verarbeite, d): d for d in dateien}
            for auftrag in as_completed(auftraege):
                datei = auftraege[auftrag]
                try:
                    if auftrag.result():
                        ergebnis.hochgeladen += 1
                    else:
                        ergebnis.uebersprungen += 1
                except Abgebrochen:
                    continue
                except (S3UploaderFehler, ClientError, BotoCoreError, OSError) as err:
                    log.error("Fehlgeschlagen: %s – %s", datei.schluessel, err)
                    ergebnis.fehler.append((datei.schluessel, str(err)))
        except KeyboardInterrupt:
            log.warning("Abbruch angefordert – laufende Teile werden noch abgeschlossen …")
            self._abbruch.set()
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        return ergebnis

    # --- Je Datei -----------------------------------------------------------------------

    def _verarbeite(self, datei: Datei) -> bool:
        """Bearbeitet eine Datei.

        Returns:
            ``True``, wenn hochgeladen wurde, ``False``, wenn übersprungen.
        """
        if self._abbruch.is_set():
            raise Abgebrochen()
        if self._zustand.ist_erledigt(datei):
            self._fortschritt.datei_uebersprungen(datei.groesse)
            return False
        if self._e.pruefe_ziel and self._existiert_im_ziel(datei):
            self._zustand.markiere_erledigt(datei, etag=None)
            self._fortschritt.datei_uebersprungen(datei.groesse)
            return False

        gemeldet = _Zaehler()  # An die Anzeige gemeldete Bytes, für den Fehlerfall
        try:
            if self._in_teilen(datei):
                self._multipart(datei, gemeldet)
            else:
                self._einfach(datei, gemeldet)
        except Abgebrochen:
            raise
        except BaseException:
            self._fortschritt.datei_fehlgeschlagen(datei.groesse, gemeldet.wert)
            raise
        self._fortschritt.datei_hochgeladen()
        return True

    def _in_teilen(self, datei: Datei) -> bool:
        """Entscheidet, ob eine Datei per Multipart übertragen wird."""
        return self._e.teilung and braucht_multipart(datei.groesse, self._e.schwelle)

    def _existiert_im_ziel(self, datei: Datei) -> bool:
        """Prüft per ``HeadObject``, ob ein Objekt gleicher Größe im Ziel liegt."""
        try:
            kopf = self._client.head_object(Bucket=self._bucket, Key=datei.schluessel)
        except ClientError as err:
            if _fehlercode(err) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return int(kopf.get("ContentLength", -1)) == datei.groesse

    @staticmethod
    def _pruefe_unveraendert(datei: Datei) -> None:
        """Bricht ab, wenn sich die Datei während des Uploads verändert hat.

        Sonst entstünde im Ziel ein Objekt aus alten und neuen Teilen.
        """
        info = datei.pfad.stat()
        if (info.st_size, info.st_mtime_ns) != (datei.groesse, datei.mtime_ns):
            raise UploadFehler("Datei wurde während des Uploads verändert")

    def _einfach(self, datei: Datei, gemeldet: _Zaehler) -> None:
        """Lädt eine Datei mit einem einzigen ``PutObject`` hoch.

        Der Inhalt wird aus der Datei gestreamt, damit auch Dateien bis 5 GiB (bei
        abgeschalteter Teilung) nicht vollständig im Speicher liegen. Die Prüfsumme wird
        vorab in einem eigenen Lesedurchgang berechnet.

        Raises:
            UploadFehler: Wenn die Datei größer als 5 GiB ist oder sich verändert hat.
        """
        if datei.groesse > MAX_EINFACHER_PUT:
            raise UploadFehler(
                "Datei ist größer als 5 GiB – ohne Teilung nicht möglich (--ohne-teilung weglassen)"
            )
        # Ein mit Teilung begonnener Upload derselben Datei würde sonst als Rest im Bucket bleiben.
        offene_id = self._zustand.offener_upload(datei.schluessel)
        if offene_id is not None:
            self._breche_upload_ab(datei, offene_id, "Teilung abgeschaltet")

        content_md5 = _md5_datei_base64(datei.pfad)
        self._pruefe_unveraendert(datei)

        def melde(anzahl: int) -> None:
            self._fortschritt.bytes_uebertragen(anzahl)
            gemeldet.plus(anzahl)

        with datei.pfad.open("rb") as quelle:
            antwort = self._client.put_object(
                Bucket=self._bucket,
                Key=datei.schluessel,
                Body=_FortschrittsLeser(quelle, melde),
                ContentLength=datei.groesse,
                ContentMD5=content_md5,
            )
        self._pruefe_unveraendert(datei)
        self._zustand.markiere_erledigt(datei, antwort.get("ETag"))
        # Falls botocore weniger über read() gelesen hat als gemeldet (z. B. leere Datei).
        rest = datei.groesse - gemeldet.wert
        if rest > 0:
            melde(rest)

    # --- Multipart ----------------------------------------------------------------------

    def _multipart(self, datei: Datei, gemeldet: _Zaehler) -> None:
        """Lädt eine große Datei in Teilen hoch oder setzt einen begonnenen Upload fort."""
        self._verwerfe_veralteten_upload(datei)
        upload_id, teilgroesse, fertige = self._setze_fort_oder_beginne(datei)
        teile = zerlege(datei.groesse, teilgroesse)

        bereits = sum(t.laenge for t in teile if t.nummer in fertige)
        if bereits:
            log.info(
                "Setze fort: %s (%d von %d Teilen vorhanden)",
                datei.schluessel,
                len(fertige),
                len(teile),
            )
            self._fortschritt.bytes_vorhanden(bereits)
            gemeldet.plus(bereits)

        offen = [t for t in teile if t.nummer not in fertige]
        with ThreadPoolExecutor(self._e.parallel_teile, thread_name_prefix="teil") as pool:
            auftraege: list[Future[tuple[int, str]]] = [
                pool.submit(self._lade_teil, datei, upload_id, teil, gemeldet) for teil in offen
            ]
            erledigt, _ = wait(auftraege, return_when=FIRST_EXCEPTION)
            for auftrag in erledigt:
                if auftrag.exception() is not None:
                    # Restliche Teile nicht mehr beginnen; der Upload bleibt fortsetzbar.
                    for rest in auftraege:
                        rest.cancel()
                    auftrag.result()  # löst die Ausnahme erneut aus
            for auftrag in auftraege:
                nummer, etag = auftrag.result()
                fertige[nummer] = etag

        self._pruefe_unveraendert(datei)
        antwort = self._client.complete_multipart_upload(
            Bucket=self._bucket,
            Key=datei.schluessel,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [{"PartNumber": n, "ETag": fertige[n]} for n in sorted(fertige)]
            },
        )
        self._zustand.markiere_erledigt(datei, antwort.get("ETag"))

    def _verwerfe_veralteten_upload(self, datei: Datei) -> None:
        """Bricht einen begonnenen Upload ab, dessen Quelldatei sich inzwischen geändert hat.

        Unvollständige Multipart-Uploads belegen sonst dauerhaft Speicher im Bucket.
        """
        alte_id = self._zustand.veralteter_upload(datei)
        if alte_id is not None:
            self._breche_upload_ab(datei, alte_id, "Datei verändert")

    def _breche_upload_ab(self, datei: Datei, upload_id: str, grund: str) -> None:
        """Bricht einen Multipart-Upload ab und entfernt ihn aus der Zustandsdatei."""
        log.info("%s, verwerfe begonnenen Upload: %s", grund, datei.schluessel)
        try:
            self._client.abort_multipart_upload(
                Bucket=self._bucket, Key=datei.schluessel, UploadId=upload_id
            )
        except ClientError as err:
            if _fehlercode(err) != "NoSuchUpload":
                raise
        self._zustand.verwerfe(datei.schluessel)

    def _setze_fort_oder_beginne(self, datei: Datei) -> tuple[str, int, dict[int, str]]:
        """Liefert Upload-ID, Teilgröße und fertige Teile – fortgesetzt oder neu begonnen."""
        stand = self._zustand.multipart_stand(datei)
        if stand is not None:
            try:
                fertige = self._teile_auf_server(datei, stand.upload_id, stand.teilgroesse)
            except ClientError as err:
                if _fehlercode(err) != "NoSuchUpload":
                    raise
                log.info(
                    "Gespeicherter Upload existiert nicht mehr, beginne neu: %s", datei.schluessel
                )
            else:
                for nummer, etag in fertige.items():
                    self._zustand.teil_erledigt(datei.schluessel, nummer, etag)
                return stand.upload_id, stand.teilgroesse, fertige

        teilgroesse = berechne_teilgroesse(datei.groesse, self._e.teilgroesse)
        antwort = self._client.create_multipart_upload(Bucket=self._bucket, Key=datei.schluessel)
        upload_id = str(antwort["UploadId"])
        self._zustand.starte_multipart(datei, upload_id, teilgroesse)
        return upload_id, teilgroesse, {}

    def _teile_auf_server(self, datei: Datei, upload_id: str, teilgroesse: int) -> dict[int, str]:
        """Fragt per ``ListParts`` ab, welche Teile vollständig auf dem Server liegen.

        Nur Teile mit genau der erwarteten Länge zählen; ein abweichender Teil wird neu
        übertragen und dabei überschrieben.
        """
        erwartet = {t.nummer: t.laenge for t in zerlege(datei.groesse, teilgroesse)}
        fertige: dict[int, str] = {}
        seiten = self._client.get_paginator("list_parts").paginate(
            Bucket=self._bucket, Key=datei.schluessel, UploadId=upload_id
        )
        for seite in seiten:
            for teil in seite.get("Parts", []):
                nummer = int(teil["PartNumber"])
                if erwartet.get(nummer) == int(teil["Size"]):
                    fertige[nummer] = str(teil["ETag"])
        return fertige

    def _lade_teil(
        self, datei: Datei, upload_id: str, teil: Teil, gemeldet: _Zaehler
    ) -> tuple[int, str]:
        """Liest einen Teil aus der Datei und lädt ihn hoch.

        Returns:
            Teilnummer und ETag.
        """
        if self._abbruch.is_set():
            raise Abgebrochen()
        daten = _lies_abschnitt(datei.pfad, teil.start, teil.laenge)
        antwort = self._client.upload_part(
            Bucket=self._bucket,
            Key=datei.schluessel,
            UploadId=upload_id,
            PartNumber=teil.nummer,
            Body=daten,
            ContentMD5=_md5_base64(daten),
        )
        etag = str(antwort["ETag"])
        # Sofort speichern: Bricht der Lauf jetzt ab, ist dieser Teil trotzdem gesichert.
        self._zustand.teil_erledigt(datei.schluessel, teil.nummer, etag)
        self._fortschritt.bytes_uebertragen(teil.laenge)
        gemeldet.plus(teil.laenge)
        return teil.nummer, etag


def _lies_abschnitt(pfad: Path, start: int, laenge: int) -> bytes:
    """Liest ``laenge`` Bytes ab Position ``start``.

    Raises:
        UploadFehler: Wenn die Datei kürzer ist als erwartet (inzwischen verändert).
    """
    with pfad.open("rb") as datei:
        datei.seek(start)
        daten = datei.read(laenge)
    if len(daten) != laenge:
        raise UploadFehler("Datei ist kürzer als erwartet – wurde sie verändert?")
    return daten
