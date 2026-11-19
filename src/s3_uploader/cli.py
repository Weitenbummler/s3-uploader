"""Kommandozeile von s3-uploader.

Diese Schicht liest Argumente und Umgebungsvariablen, baut daraus die
Konfigurationsobjekte und ruft die Fachmodule auf. Sie enthält keine Fachlogik (PY-P5).

Exit-Codes (PY-E5): 0 Erfolg, 1 fachlicher Fehler, 2 Bedienfehler, 130 Abbruch (Strg+C).
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from s3_uploader import __version__
from s3_uploader.client import erzeuge_client
from s3_uploader.dateisuche import finde_dateien
from s3_uploader.fehler import KonfigurationsFehler, S3UploaderFehler
from s3_uploader.fortschritt import (
    Anzeige,
    Fortschritt,
    ZeilenfesterHandler,
    formatiere_bytes,
    formatiere_dauer,
)
from s3_uploader.konfiguration import (
    UploadEinstellungen,
    Verbindung,
    normalisiere_prefix,
    parse_groesse,
    quellkennung,
    standard_zustandsdatei,
)
from s3_uploader.planung import pruefe_schwelle
from s3_uploader.terminal import bereite_konsole_vor
from s3_uploader.uploader import Uploader
from s3_uploader.verbindungstest import teste_verbindung
from s3_uploader.zustand import Zustand

EXIT_OK = 0
EXIT_FEHLER = 1
EXIT_BEDIENUNG = 2
EXIT_ABBRUCH = 130

log = logging.getLogger("s3_uploader")


def _umgebung(name: str) -> str | None:
    """Liest eine Umgebungsvariable; leere Werte gelten als nicht gesetzt."""
    return os.environ.get(name) or None


def erzeuge_parser() -> argparse.ArgumentParser:
    """Baut den Argument-Parser mit den Befehlen ``test`` und ``hochladen``.

    Returns:
        Fertig konfigurierter Parser.
    """
    gemeinsam = argparse.ArgumentParser(add_help=False)
    ziel = gemeinsam.add_argument_group("Ziel und Zugang")
    ziel.add_argument(
        "--endpunkt",
        default=_umgebung("S3_ENDPUNKT"),
        help="URL des S3-Endpunkts, z. B. https://s3.example.org (S3_ENDPUNKT)",
    )
    ziel.add_argument("--bucket", default=_umgebung("S3_BUCKET"), help="Ziel-Bucket (S3_BUCKET)")
    ziel.add_argument(
        "--prefix",
        default=_umgebung("S3_PREFIX") or "",
        help="Schlüsselpräfix im Bucket, z. B. backup/2026 (S3_PREFIX)",
    )
    ziel.add_argument(
        "--access-key", default=_umgebung("S3_ACCESS_KEY"), help="Access Key (S3_ACCESS_KEY)"
    )
    ziel.add_argument(
        "--passwort",
        "--secret-key",
        dest="passwort",
        default=_umgebung("S3_SECRET_KEY"),
        help="Secret Key/Passwort (S3_SECRET_KEY). Fehlt es, wird verdeckt gefragt.",
    )
    ziel.add_argument(
        "--region",
        default=_umgebung("S3_REGION") or "us-east-1",
        help="Region für die Signatur (Standard: us-east-1)",
    )
    ziel.add_argument(
        "--adressierung",
        choices=["path", "virtual", "auto"],
        default="path",
        help="Adressierungsart (Standard: path, passend für MinIO, Ceph u. a.)",
    )
    ziel.add_argument(
        "--ohne-tls-pruefung",
        action="store_true",
        help="TLS-Zertifikat nicht prüfen (nur für Testsysteme!)",
    )
    gemeinsam.add_argument(
        "-v",
        "--ausfuehrlich",
        action="count",
        default=0,
        help="Mehr Meldungen (-v Info, -vv Diagnose)",
    )

    parser = argparse.ArgumentParser(
        prog="s3-uploader",
        description="Lädt viele und große Dateien wiederaufsetzbar in einen S3-Bucket.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    befehle = parser.add_subparsers(dest="befehl", required=True, metavar="BEFEHL")

    test = befehle.add_parser(
        "test",
        parents=[gemeinsam],
        help="Verbindung prüfen",
        description="Prüft Endpunkt, Anmeldung, Bucket und Rechte.",
    )
    test.add_argument(
        "--schreibtest",
        action="store_true",
        help="Zusätzlich ein Testobjekt anlegen und wieder löschen",
    )

    hoch = befehle.add_parser(
        "hochladen",
        parents=[gemeinsam],
        help="Dateien hochladen",
        description="Lädt ein Verzeichnis hoch; ein erneuter Aufruf "
        "setzt einen abgebrochenen Lauf fort.",
    )
    hoch.add_argument("--quelle", type=Path, required=True, help="Quellverzeichnis")
    hoch.add_argument(
        "--ohne-teilung",
        action="store_true",
        help="Große Dateien nicht in Teile zerlegen: jede Datei als ein PUT (höchstens 5 GiB "
        "je Datei, Abbruch einer Datei bedeutet Neubeginn dieser Datei)",
    )
    hoch.add_argument(
        "--schwelle",
        type=parse_groesse,
        default="64MiB",
        help="Ab dieser Größe Multipart verwenden (Standard: 64MiB)",
    )
    hoch.add_argument(
        "--teilgroesse",
        type=parse_groesse,
        default="16MiB",
        help="Gewünschte Teilgröße, wird bei Bedarf vergrößert (Standard: 16MiB)",
    )
    hoch.add_argument(
        "--parallel-dateien",
        type=int,
        default=4,
        help="Gleichzeitig bearbeitete Dateien (Standard: 4)",
    )
    hoch.add_argument(
        "--parallel-teile",
        type=int,
        default=4,
        help="Gleichzeitige Teile je großer Datei (Standard: 4)",
    )
    hoch.add_argument(
        "--zustand",
        type=Path,
        help="Zustandsdatei (Standard: ~/.s3-uploader/zustand-<kennung>.sqlite)",
    )
    hoch.add_argument(
        "--neu", action="store_true", help="Gespeicherten Zustand verwerfen und von vorn beginnen"
    )
    hoch.add_argument(
        "--pruefe-ziel",
        action="store_true",
        help="Objekte gleicher Größe im Ziel als erledigt werten",
    )
    hoch.add_argument(
        "--ausschliessen",
        action="append",
        default=[],
        metavar="MUSTER",
        help="Glob-Muster relativer Pfade auslassen (mehrfach möglich)",
    )
    hoch.add_argument(
        "--probelauf", action="store_true", help="Nur anzeigen, was hochgeladen würde"
    )
    hoch.add_argument("--still", action="store_true", help="Keine Fortschrittsanzeige")
    return parser


def _richte_logging_ein(stufe: int) -> logging.Handler:
    """Leitet Meldungen des Pakets nach stderr; liefert den Handler zum späteren Entfernen."""
    handler = ZeilenfesterHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel([logging.WARNING, logging.INFO, logging.DEBUG][min(stufe, 2)])
    return handler


def _lies_verbindung(args: argparse.Namespace) -> Verbindung:
    """Baut die Verbindung und fragt ein fehlendes Passwort verdeckt ab (PY-X2)."""
    fehlend = [
        name
        for name, wert in (
            ("--endpunkt", args.endpunkt),
            ("--bucket", args.bucket),
            ("--access-key", args.access_key),
        )
        if not wert
    ]
    if fehlend:
        raise KonfigurationsFehler("Fehlende Angabe: " + ", ".join(fehlend))
    passwort = args.passwort
    if not passwort:
        if not sys.stdin.isatty():
            raise KonfigurationsFehler("Passwort fehlt: --passwort oder S3_SECRET_KEY angeben.")
        passwort = getpass.getpass("Secret Key/Passwort: ")
    return Verbindung(
        endpunkt=args.endpunkt,
        bucket=args.bucket,
        access_key=args.access_key,
        secret_key=passwort,
        region=args.region,
        adressierung=args.adressierung,
        tls_pruefen=not args.ohne_tls_pruefung,
    )


def befehl_test(args: argparse.Namespace) -> int:
    """Führt den Verbindungstest aus und gibt die Ergebnisse aus.

    Args:
        args: Ausgewertete Argumente.

    Returns:
        Exit-Code.
    """
    verbindung = _lies_verbindung(args)
    prefix = normalisiere_prefix(args.prefix)
    print(f"Teste {verbindung.endpunkt} – Bucket {verbindung.bucket!r}, Präfix {prefix!r}")
    ergebnisse = teste_verbindung(
        erzeuge_client(verbindung), verbindung.bucket, prefix, args.schreibtest
    )
    for pruefung in ergebnisse:
        print(f"  [{'OK  ' if pruefung.ok else 'FEHL'}] {pruefung.name}: {pruefung.hinweis}")
    erfolgreich = all(p.ok for p in ergebnisse)
    print("Verbindungstest erfolgreich." if erfolgreich else "Verbindungstest fehlgeschlagen.")
    return EXIT_OK if erfolgreich else EXIT_FEHLER


def befehl_hochladen(args: argparse.Namespace) -> int:
    """Lädt das Quellverzeichnis hoch bzw. setzt einen Lauf fort.

    Args:
        args: Ausgewertete Argumente.

    Returns:
        Exit-Code.
    """
    pruefe_schwelle(args.schwelle)
    if args.parallel_dateien < 1 or args.parallel_teile < 1:
        raise KonfigurationsFehler("Parallelität muss mindestens 1 sein.")
    verbindung = _lies_verbindung(args)
    prefix = normalisiere_prefix(args.prefix)
    quelle: Path = args.quelle.expanduser()
    zustandsdatei = args.zustand or standard_zustandsdatei(verbindung, quelle, prefix)
    einstellungen = UploadEinstellungen(
        quelle=quelle,
        prefix=prefix,
        zustandsdatei=zustandsdatei,
        schwelle=args.schwelle,
        teilgroesse=args.teilgroesse,
        parallel_dateien=args.parallel_dateien,
        parallel_teile=args.parallel_teile,
        teilung=not args.ohne_teilung,
        pruefe_ziel=args.pruefe_ziel,
        ausschluesse=tuple(args.ausschliessen),
    )

    if args.neu:
        for endung in ("", "-wal", "-shm"):
            Path(f"{zustandsdatei}{endung}").unlink(missing_ok=True)

    print(f"Durchsuche {quelle} …", file=sys.stderr)
    dateien = list(finde_dateien(quelle, prefix, einstellungen.ausschluesse))
    kontext = f"{verbindung.endpunkt}|{verbindung.bucket}|{prefix}|{quellkennung(quelle)}"
    with Zustand(zustandsdatei) as zustand:
        zustand.pruefe_kontext(kontext)
        client = erzeuge_client(
            verbindung, max_verbindungen=args.parallel_dateien * (args.parallel_teile + 1)
        )
        fortschritt = Fortschritt()
        uploader = Uploader(client, verbindung.bucket, einstellungen, zustand, fortschritt)
        plan = uploader.plane(dateien)
        print(
            f"{plan.dateien} Dateien ({formatiere_bytes(plan.bytes_gesamt)}), davon "
            f"{plan.erledigt} bereits erledigt; offen: {plan.einfach} einfach, "
            f"{plan.multipart} in Teilen ({formatiere_bytes(plan.bytes_offen)}).",
            file=sys.stderr,
        )
        if not einstellungen.teilung:
            print("Teilung abgeschaltet: jede Datei wird als ein PUT übertragen.", file=sys.stderr)
        if plan.zu_gross:
            print(
                f"Warnung: {plan.zu_gross} Dateien sind größer als 5 GiB und werden ohne "
                "Teilung fehlschlagen.",
                file=sys.stderr,
            )
        print(f"Zustandsdatei: {zustandsdatei}", file=sys.stderr)
        if args.probelauf:
            return EXIT_OK

        beginn = time.monotonic()
        if args.still:
            ergebnis = uploader.lade_hoch(dateien)
        else:
            with Anzeige(fortschritt, sys.stderr):
                ergebnis = uploader.lade_hoch(dateien)

    print(
        f"Fertig nach {formatiere_dauer(time.monotonic() - beginn)}: "
        f"{ergebnis.hochgeladen} hochgeladen, {ergebnis.uebersprungen} übersprungen, "
        f"{len(ergebnis.fehler)} fehlgeschlagen."
    )
    for schluessel, ursache in ergebnis.fehler:
        print(f"  FEHL {schluessel}: {ursache}")
    if ergebnis.fehler:
        print(
            "Erneuter Aufruf mit denselben Parametern versucht die fehlgeschlagenen Dateien erneut."
        )
        return EXIT_FEHLER
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Einstiegspunkt der Kommandozeile.

    Args:
        argv: Argumente ohne Programmnamen; ``None`` nimmt ``sys.argv[1:]``.

    Returns:
        Exit-Code.
    """
    bereite_konsole_vor()
    parser = erzeuge_parser()
    try:
        args = parser.parse_args(argv)
    except KonfigurationsFehler as err:  # aus parse_groesse
        parser.error(str(err))
    handler = _richte_logging_ein(args.ausfuehrlich)
    try:
        if args.befehl == "test":
            return befehl_test(args)
        return befehl_hochladen(args)
    except KonfigurationsFehler as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return EXIT_BEDIENUNG
    except S3UploaderFehler as err:
        print(f"Fehler: {err}", file=sys.stderr)
        return EXIT_FEHLER
    except KeyboardInterrupt:
        print(
            "\nAbgebrochen. Erneuter Aufruf mit denselben Parametern setzt den Lauf fort.",
            file=sys.stderr,
        )
        return EXIT_ABBRUCH
    finally:
        # Wichtig bei mehrfachem Aufruf von main() im selben Prozess (z. B. in Tests).
        log.removeHandler(handler)
