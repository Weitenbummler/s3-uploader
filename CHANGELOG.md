# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach
[Semantic Versioning](https://semver.org/lang/de/).

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
