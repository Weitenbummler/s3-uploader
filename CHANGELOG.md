# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach
[Semantic Versioning](https://semver.org/lang/de/).

## [0.4.0] – 2026-11-19

### Geändert
- Verbindungstest grenzt die Ursache ein: Verbindung und Zertifikat, Uhrzeit (Abweichung zur
  Uhr des Speichers), Access Key unbekannt, Passwort falsch, Region, Bucket, Lese-, Schreib-
  und Löschrecht – jeweils mit Abhilfe. Ergebnis je Schritt `OK`, `HINW` oder `FEHL`.
- Fehlendes Leserecht ist nur noch ein Hinweis; Vorabprüfung von `hochladen` lässt den Upload
  dann weiterlaufen (Konten mit reinem Schreibrecht werden unterstützt).

### Hinzugefügt
- README: Tabelle „Verbindungstest: Ursachen eingrenzen“ und „Benötigte Rechte“.
- Tests mit echter Signatur- und Rechteprüfung (moto IAM).

## [0.3.1] – 2026-11-19

### Hinzugefügt
- `--ca-zertifikat` prüft die Datei beim Start und nennt die Abhilfe für binäre (DER),
  doppelt kodierte (`[X509] PEM lib`), als UTF-16 gespeicherte, beschädigte Dateien und
  Dateien ohne Zertifikat.
- README W12, M12, L12: Form der Datei prüfen und nur binäre Dateien umwandeln.

### Geändert
- Verbindungstest: verständlicher Hinweis bei unlesbarer Zertifikatsdatei.

## [0.3.0] – 2026-11-19

### Hinzugefügt
- Option `--ca-zertifikat DATEI` (Umgebungsvariable `S3_CA_ZERTIFIKAT`) für selbst signierte
  oder firmeneigene Zertifikate; README-Abschnitte W12, M12, L12 zum Besorgen und Exportieren
  der Datei je Betriebssystem.
- Verständliche Hinweise bei Zertifikatsfehlern (selbst signiert, abgelaufen, falscher Name).
- `hochladen` prüft die Verbindung vorab und bricht bei dauerhaften Fehlern sofort ab.

### Behoben
- Die Standard-Umgebungsvariable `AWS_CA_BUNDLE` wurde übergangen.
- Verbindungstest meldete Zertifikats- und Verbindungsfehler erst nach rund 30 s
  (10 Wiederholungen); jetzt nach Sekunden.


### Geändert
- README: Einrichtung und Start vollständig nach Betriebssystem getrennt (Windows/PowerShell,
  macOS, Linux), je mit Python-Installation, Umgebung, Installation, Prüfung, Start, neuem
  Fenster, Aktualisieren/Deinstallieren, Offline-Installation, Entwicklung und Hinweisen.
- README: Tabelle „Getestet unter“; Linux ist noch nicht geprüft.
- Folgt python-richtlinien 1.2.0.
- README Windows: Freigabe per `Set-ExecutionPolicy -Scope Process` ist regulärer Schritt,
  weil Windows die Aktivierung standardmäßig sperrt.

## [0.2.1] – 2026-11-19

### Behoben
- Windows: Strg+C bricht einen Lauf sofort ab, statt bis zum Ende der aktuellen Datei zu warten.
- Windows: Fortschrittszeile in der klassischen Konsole (Steuerzeichen werden eingeschaltet,
  sonst wird mit Leerzeichen überschrieben); Zeile wird auf die Fensterbreite gekürzt.
- Windows: Quellpfade in anderer Schreibweise (`d:/daten` statt `D:\Daten`) finden dieselbe
  Zustandsdatei.
- Nicht darstellbare Zeichen in der Ausgabe führen nicht mehr zum Absturz.
- Test für symbolische Links wird übersprungen, wenn das System keine Links erlaubt.

### Geändert
- README: Hinweise für Windows, Pflicht von `pip install .`, Python 3.15 und Entwicklungswerkzeuge.
- README: eigene Installationsbefehle für Windows-PowerShell (`py`, `Activate.ps1`,
  Ausführungsrichtlinie, Aufruf ohne Aktivierung) und PowerShell-Entsprechungen der Beispiele.
- README: Windows-Pfade mit `.\` davor, sonst deutet PowerShell `.venv\…` als Modulnamen.

## [0.2.0] – 2026-11-19

### Hinzugefügt
- Option `--ohne-teilung`: Teilung großer Dateien abschaltbar; jede Datei als ein
  `PutObject` (höchstens 5 GiB). Warnung in der Übersicht für zu große Dateien; begonnene
  Multipart-Uploads werden beim Wechsel aufgeräumt.
- MIT-Lizenz.
- Spiegelung nach GitHub (github.com/Weitenbummler/s3-uploader), Hinweis im README.

### Geändert
- Einzelne Uploads werden gestreamt statt vollständig in den Speicher geladen; die
  Fortschrittsanzeige bewegt sich auch während einer einzelnen großen Datei.
- Klon-Anleitung verweist auf das öffentliche GitHub-Repository statt auf die interne Gitea-Adresse.

## [0.1.0] – 2026-11-19

### Hinzugefügt
- Befehl `test`: Verbindungstest (Anmeldung, Bucket, Lese-, optional Schreib-/Löschrecht).
- Befehl `hochladen`: rekursiver Upload mit Präfix, Multipart oberhalb einer Schwelle,
  automatische Teilgröße (10 000-Teile-Grenze), parallele Dateien und Teile.
- Wiederaufsetzen über SQLite-Zustandsdatei; Abgleich fertiger Teile per `ListParts`.
- Fortschrittsanzeige mit Prozent, Rate und Restzeit; Protokollmodus ohne Terminal.
- `Content-MD5` für jeden Upload, Erkennung während des Uploads veränderter Dateien.
- Optionen `--pruefe-ziel`, `--ausschliessen`, `--probelauf`, `--neu`.
- Abhängigkeiten in `requirements.txt` und `requirements-dev.txt`.
- Dokumentation: README mit vollständiger Installation, Architektur mit UML (Mermaid),
  Lern-Dokumentation.
