# Architektur von s3-uploader

Die Diagramme sind in Mermaid geschrieben und werden von Gitea direkt dargestellt.

## Module im Überblick

| Modul | Aufgabe |
|---|---|
| `cli.py` | Argumente und Umgebungsvariablen lesen, Objekte bauen, Ausgabe, Exit-Codes |
| `konfiguration.py` | Datenklassen `Verbindung`, `UploadEinstellungen`; Präfix, Größenangaben, Zustandsdatei-Ort |
| `client.py` | boto3-Client mit Zeitlimits, Wiederholungen, Kompatibilitätseinstellungen |
| `verbindungstest.py` | Prüfschritte des Verbindungstests |
| `dateisuche.py` | Quellverzeichnis durchlaufen, `Datei`-Objekte mit Zielschlüssel |
| `planung.py` | Multipart-Entscheidung, Teilgröße, Zerlegung in `Teil`e |
| `uploader.py` | Kern: einfacher Upload, Multipart, Fortsetzen, Parallelität |
| `zustand.py` | SQLite-Zustandsdatei für das Wiederaufsetzen |
| `fortschritt.py` | Threadsichere Zählung, Fortschrittszeile, logging-Handler |
| `terminal.py` | Betriebssystemunabhängige Terminal-Ausgabe (Windows-Konsole, Kodierung, Zeilenbreite) |
| `fehler.py` | Ausnahmehierarchie |

## Paketabhängigkeiten

```mermaid
flowchart TD
    cli --> konfiguration
    cli --> client
    cli --> verbindungstest
    cli --> dateisuche
    cli --> uploader
    cli --> zustand
    cli --> fortschritt
    fortschritt --> terminal
    cli --> terminal
    uploader --> planung
    uploader --> zustand
    uploader --> fortschritt
    uploader --> dateisuche
    zustand --> dateisuche
    verbindungstest --> client
    client --> konfiguration
    client -.-> boto3[(boto3)]
    zustand -.-> sqlite3[(sqlite3)]
```

## Klassendiagramm

```mermaid
classDiagram
    direction LR

    class Verbindung {
        <<dataclass, frozen>>
        +str endpunkt
        +str bucket
        +str access_key
        -str secret_key
        +str region
        +str adressierung
        +bool tls_pruefen
    }

    class UploadEinstellungen {
        <<dataclass, frozen>>
        +Path quelle
        +str prefix
        +Path zustandsdatei
        +int schwelle
        +int teilgroesse
        +int parallel_dateien
        +int parallel_teile
        +bool teilung
        +bool pruefe_ziel
        +tuple ausschluesse
    }

    class Datei {
        <<dataclass, frozen>>
        +Path pfad
        +str schluessel
        +int groesse
        +int mtime_ns
    }

    class Teil {
        <<dataclass, frozen>>
        +int nummer
        +int start
        +int laenge
    }

    class Uploader {
        -S3Client client
        -str bucket
        -Event abbruch
        +plane(dateien) Plan
        +lade_hoch(dateien) Ergebnis
        -_verarbeite(datei) bool
        -_einfach(datei)
        -_multipart(datei)
        -_setze_fort_oder_beginne(datei)
        -_teile_auf_server(datei, upload_id, teilgroesse)
        -_lade_teil(datei, upload_id, teil) tuple
    }

    class Zustand {
        -Connection db
        -Lock sperre
        +pruefe_kontext(kontext)
        +ist_erledigt(datei) bool
        +multipart_stand(datei) MultipartStand
        +veralteter_upload(datei) str
        +offener_upload(schluessel) str
        +starte_multipart(datei, upload_id, teilgroesse)
        +teil_erledigt(schluessel, nummer, etag)
        +markiere_erledigt(datei, etag)
        +verwerfe(schluessel)
    }

    class MultipartStand {
        <<dataclass, frozen>>
        +str upload_id
        +int teilgroesse
        +dict teile
    }

    class Fortschritt {
        -Lock sperre
        +beginne(dateien, bytes_gesamt)
        +bytes_uebertragen(anzahl)
        +bytes_vorhanden(anzahl)
        +datei_hochgeladen()
        +datei_uebersprungen(groesse)
        +datei_fehlgeschlagen(groesse, bereits)
        +momentaufnahme() Momentaufnahme
    }

    class Momentaufnahme {
        <<dataclass, frozen>>
        +prozent float
        +rate float
        +restzeit float
        +als_zeile() str
    }

    class Anzeige {
        -Thread thread
        +__enter__()
        +__exit__()
    }

    class Ergebnis {
        <<dataclass>>
        +int hochgeladen
        +int uebersprungen
        +list fehler
    }

    class Plan {
        <<dataclass, frozen>>
        +int dateien
        +int erledigt
        +int einfach
        +int multipart
        +int zu_gross
    }

    class S3UploaderFehler
    class KonfigurationsFehler
    class UploadFehler
    class Abgebrochen

    Exception <|-- S3UploaderFehler
    S3UploaderFehler <|-- KonfigurationsFehler
    S3UploaderFehler <|-- UploadFehler
    S3UploaderFehler <|-- Abgebrochen

    Uploader --> UploadEinstellungen : nutzt
    Uploader --> Zustand : schreibt
    Uploader --> Fortschritt : meldet
    Uploader ..> Datei : verarbeitet
    Uploader ..> Teil : zerlegt in
    Uploader ..> Ergebnis : liefert
    Uploader ..> Plan : liefert
    Zustand ..> MultipartStand : liefert
    Fortschritt ..> Momentaufnahme : liefert
    Anzeige --> Fortschritt : liest
```

## Ablauf eines Uploads (Sequenzdiagramm)

```mermaid
sequenceDiagram
    actor Benutzer
    participant CLI as cli
    participant Suche as dateisuche
    participant U as Uploader
    participant Z as Zustand (SQLite)
    participant S3 as S3-Endpunkt

    Benutzer->>CLI: s3-uploader hochladen …
    CLI->>Suche: finde_dateien(quelle, prefix)
    Suche-->>CLI: Liste von Datei
    CLI->>Z: pruefe_kontext()
    CLI->>U: plane() / lade_hoch()

    loop je Datei (parallel_dateien Threads)
        U->>Z: ist_erledigt(datei)?
        alt erledigt und unverändert
            U-->>U: überspringen
        else klein (≤ Schwelle) oder --ohne-teilung (≤ 5 GiB)
            U->>Z: offener_upload(schluessel)?
            opt alter Multipart vorhanden
                U->>S3: AbortMultipartUpload
            end
            U->>S3: PutObject gestreamt (Content-MD5)
            U->>Z: markiere_erledigt
        else groß und Teilung an
            U->>Z: multipart_stand(datei)
            alt Stand vorhanden
                U->>S3: ListParts(UploadId)
                S3-->>U: fertige Teile
            else neu
                U->>S3: CreateMultipartUpload
                U->>Z: starte_multipart
            end
            par fehlende Teile (parallel_teile Threads)
                U->>S3: UploadPart (Content-MD5)
                U->>Z: teil_erledigt
            end
            U->>S3: CompleteMultipartUpload
            U->>Z: markiere_erledigt
        end
    end
    U-->>CLI: Ergebnis
    CLI-->>Benutzer: Zusammenfassung, Exit-Code
```

## Zustände einer Datei

```mermaid
stateDiagram-v2
    [*] --> unbekannt
    unbekannt --> erledigt : PutObject erfolgreich
    unbekannt --> laufend : CreateMultipartUpload
    laufend --> laufend : Teil hochgeladen
    laufend --> erledigt : CompleteMultipartUpload
    laufend --> unbekannt : Datei verändert → AbortMultipartUpload
    laufend --> unbekannt : Upload serverseitig verschwunden
    erledigt --> unbekannt : Datei verändert (neue Größe/Zeit)
    erledigt --> [*]
```

`unbekannt` bedeutet: kein Eintrag in der Zustandsdatei. `laufend` und `erledigt` sind die
Werte der Spalte `status` in der Tabelle `dateien`.

## Datenmodell der Zustandsdatei

```mermaid
erDiagram
    meta {
        TEXT schluessel PK
        TEXT wert
    }
    dateien {
        TEXT schluessel PK
        INTEGER groesse
        INTEGER mtime_ns
        TEXT status
        TEXT upload_id
        INTEGER teilgroesse
        TEXT etag
        REAL aktualisiert
    }
    teile {
        TEXT schluessel PK
        INTEGER nummer PK
        TEXT etag
    }
    dateien ||--o{ teile : "hat (nur während Multipart)"
```

## Entwurfsentscheidungen

| Entscheidung | Begründung |
|---|---|
| boto3 statt eigener S3-Signatur | Bewährte Signatur (SigV4), Wiederholungen, Paginierung; S3-kompatible Speicher unterstützt |
| Multipart selbst steuern statt `upload_file` | `upload_file` kann nicht über Programmläufe hinweg fortsetzen; eigener Ablauf merkt sich Upload-ID und Teile |
| SQLite als Zustand | In der Standardbibliothek, atomare Schreibvorgänge, schnell auch bei Millionen Einträgen |
| Server (`ListParts`) entscheidet beim Fortsetzen | Ein Teil kann übertragen, aber vor dem Speichern im Zustand abgebrochen worden sein |
| Erkennung von Änderungen über Größe + `mtime_ns` | Prüfsummen über Terabytes vorab zu berechnen wäre zu langsam |
| `Content-MD5` statt boto3-Standardprüfsummen | Wird von praktisch allen S3-kompatiblen Speichern verstanden |
| Teilung abschaltbar (`--ohne-teilung`) | Manche S3-kompatible Speicher unterstützen Multipart nur eingeschränkt; einzelne Uploads liefern einen MD5-ETag |
| Einzelne Uploads gestreamt | Ohne Teilung sind Dateien bis 5 GiB möglich; sie sollen nicht vollständig im Speicher liegen |
| Warten mit Zeitgrenze statt `as_completed` | Unter Windows unterbricht Strg+C ein Warten ohne Zeitgrenze nicht; mit 0,5 s Zeitgrenze reagiert der Abbruch sofort |
| Quellpfad mit `os.path.normcase` vereinheitlicht | Unter Windows sind `D:\Daten` und `d:/daten` derselbe Ordner und müssen dieselbe Zustandsdatei finden |
| Threads statt asyncio | Ein-/Ausgabe-lastig, boto3 ist synchron; Threads sind hier einfach und ausreichend |
