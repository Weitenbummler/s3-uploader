# s3-uploader

Kommandozeilenwerkzeug, das sehr viele und auch sehr große Dateien aus einem
Verzeichnis in einen S3-Bucket hochlädt – mit Verbindungstest, Fortschrittsanzeige
und Wiederaufsetzen nach Abbrüchen. Funktioniert mit AWS S3 und S3-kompatiblen
Speichern (MinIO, Ceph, NetApp StorageGRID, Wasabi, Hetzner, IONOS …).

Lizenz: [MIT](LICENSE). Entwickelt nach den (intern gepflegten) python-richtlinien 1.1.0.

> Das führende Repository liegt in einer privaten Gitea-Instanz; [github.com/Weitenbummler/s3-uploader](https://github.com/Weitenbummler/s3-uploader) ist ein automatisch gespiegelter, schreibgeschützter Stand. Änderungen direkt auf GitHub werden beim nächsten Abgleich überschrieben – Hinweise und Fehler bitte als Issue melden.

## Funktionen

- **Verbindungstest** (`s3-uploader test`): Endpunkt, Anmeldung, Bucket, Leserecht,
  optional Schreib- und Löschrecht – mit verständlichen Fehlerhinweisen.
- **Multipart für große Dateien**: Dateien oberhalb der Schwelle (Standard 64 MiB) werden in
  Teile zerlegt. Die Teilgröße wird automatisch so vergrößert, dass die S3-Grenze von
  10 000 Teilen eingehalten wird (Dateien bis 5 TiB). Die Teilung ist optional und lässt sich
  mit `--ohne-teilung` abschalten.
- **Parallel**: mehrere Dateien und mehrere Teile je Datei gleichzeitig.
- **Fortschritt**: laufende Zeile mit Prozent, Dateien, Bytes, Rate und Restzeit.
- **Wiederaufsetzen**: Der Stand wird je Datei und je Teil in einer SQLite-Zustandsdatei
  gespeichert. Ein erneuter Aufruf mit denselben Parametern überspringt Erledigtes und setzt
  angefangene Multipart-Uploads beim ersten fehlenden Teil fort.
- **Integrität**: Jeder Upload sendet `Content-MD5`; der Server weist verfälschte Daten ab.
  Dateien, die sich während des Uploads ändern, werden erkannt und nicht halb übernommen.

## Voraussetzungen

| Was | Version | Prüfen mit |
|---|---|---|
| Python | 3.11 oder neuer | `python3 --version` |
| pip und venv | mit Python geliefert | `python3 -m pip --version` |
| git | beliebig | `git --version` |
| Netzwerkzugang zum S3-Endpunkt | – | `s3-uploader test …` |

Python installieren, falls nötig:

- **macOS** (Homebrew): `brew install python@3.12`
- **Debian/Ubuntu**: `sudo apt install python3 python3-venv python3-pip`
- **RHEL/Fedora**: `sudo dnf install python3 python3-pip`
- **Windows**: Installer von <https://www.python.org/downloads/> (bzw. „Python Install
  Manager“). Danach steht der Starter `py` zur Verfügung. `python3` und oft auch `python`
  sind unter Windows nur Verknüpfungen zum Microsoft Store und melden „Python wurde nicht
  gefunden“ – für Windows gelten deshalb die eigenen PowerShell-Befehle unten.

## Installation

### 1. Quellcode holen

```bash
git clone https://github.com/Weitenbummler/s3-uploader.git
cd s3-uploader
```

### 2. Virtuelle Umgebung anlegen und aktivieren

Eine virtuelle Umgebung hält die Zusatzmodule vom System-Python getrennt.

**macOS und Linux** (Terminal):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

**Windows** (PowerShell):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Wichtig in PowerShell: Pfade zu Programmen im aktuellen Verzeichnis beginnen mit `.\`.
Ohne diesen Vorsatz liest PowerShell `.venv\…` als „Modul .venv, Befehl …“ und meldet
„Das Modul „.venv“ konnte nicht geladen werden“.

Nach der Aktivierung steht `(.venv)` vor der Eingabeaufforderung; ab dann gilt `python`
bzw. `pip` für die virtuelle Umgebung, auf allen Systemen gleich.

Meldet PowerShell beim Aktivieren „Die Ausführung von Skripts ist auf diesem System
deaktiviert“, gibt es zwei Wege:

- ohne Aktivierung arbeiten und die Programme der Umgebung direkt aufrufen:
  `.\.venv\Scripts\python.exe -m pip …` und `.\.venv\Scripts\s3-uploader.exe …`, oder
- Skripte nur für das aktuelle Fenster erlauben:
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`
  (gilt nur bis zum Schließen des Fensters; dauerhafte Änderungen nur in Absprache mit der IT).

In der Windows-Eingabeaufforderung (cmd.exe) statt PowerShell lautet die Aktivierung
`.\.venv\Scripts\activate.bat`.

Die Aktivierung gilt nur für das aktuelle Terminal. In jedem neuen Terminal erneut
aktivieren oder das Programm direkt aufrufen: `.venv/bin/s3-uploader` (macOS/Linux) bzw.
`.\.venv\Scripts\s3-uploader.exe` (Windows).

### 3. Zusatzmodule installieren

Die Zusatzmodule stehen in zwei requirements-Dateien:

| Datei | Inhalt | Wofür |
|---|---|---|
| [`requirements.txt`](requirements.txt) | `boto3` (AWS SDK, Apache-2.0) | Betrieb – immer nötig |
| [`requirements-dev.txt`](requirements-dev.txt) | zusätzlich `pytest`, `pytest-cov`, `moto`, `ruff`, `mypy` | Entwicklung und Tests |

**Nur benutzen:**

```bash
pip install -r requirements.txt
pip install .
```

**Entwickeln** (Programm editierbar installieren, Änderungen am Code wirken sofort):

```bash
pip install -r requirements-dev.txt
pip install -e .
```

`pyproject.toml` liest die Laufzeit-Abhängigkeiten direkt aus `requirements.txt`; sie
stehen also nur an einer Stelle.

### 4. Installation prüfen

```bash
s3-uploader --version
s3-uploader --help
```

Alternativ ohne Einstiegspunkt: `python -m s3_uploader --help`.

### Ohne Netz installieren (Offline-Rechner)

Auf einem Rechner mit Internet die Pakete herunterladen, Verzeichnis kopieren, dann
offline installieren:

```bash
pip download -r requirements.txt -d pakete/
```

```bash
pip install --no-index --find-links pakete/ -r requirements.txt
pip install --no-index --find-links pakete/ .
```

### Aktualisieren und Deinstallieren

```bash
git pull && pip install -r requirements.txt && pip install .
```

```bash
pip uninstall s3-uploader
```

Zum vollständigen Entfernen zusätzlich das Verzeichnis `.venv/` und die Zustandsdateien
unter `~/.s3-uploader/` löschen.

## Bedienung

### Zugangsdaten übergeben

Alle Angaben gehen als Parameter **oder** als Umgebungsvariable:

| Parameter | Umgebungsvariable | Bedeutung |
|---|---|---|
| `--endpunkt` | `S3_ENDPUNKT` | URL, z. B. `https://s3.example.org` |
| `--bucket` | `S3_BUCKET` | Ziel-Bucket |
| `--prefix` | `S3_PREFIX` | Präfix im Bucket, z. B. `backup/2026` |
| `--access-key` | `S3_ACCESS_KEY` | Access Key |
| `--passwort` / `--secret-key` | `S3_SECRET_KEY` | Secret Key; fehlt er, wird verdeckt gefragt |
| `--region` | `S3_REGION` | Region für die Signatur (Standard `us-east-1`) |

> **Sicherheitshinweis:** Parameter auf der Kommandozeile sind für andere Benutzer im
> Prozesslisting (`ps`) und im Shell-Verlauf sichtbar. Das Passwort besser per
> Umgebungsvariable oder verdeckter Eingabe übergeben. Zugangsdaten werden nie in die
> Zustandsdatei oder ins Protokoll geschrieben.

Die Beispiele unten sind für macOS/Linux geschrieben. In der Windows-PowerShell:

| macOS/Linux | Windows-PowerShell |
|---|---|
| `export S3_SECRET_KEY='…'` | `$env:S3_SECRET_KEY = '…'` |
| Zeilenfortsetzung mit `\` am Zeilenende | Zeilenfortsetzung mit `` ` `` (Backtick) am Zeilenende |
| `--quelle /daten/export` | `--quelle D:\daten\export` |
| Zustandsdateien unter `~/.s3-uploader/` | unter `%USERPROFILE%\.s3-uploader\` |

### Verbindungstest

```bash
export S3_SECRET_KEY='…'
s3-uploader test --endpunkt https://s3.example.org --bucket archiv \
  --access-key MEINKEY --prefix backup/2026 --schreibtest
```

Ausgabe:

```text
Teste https://s3.example.org – Bucket 'archiv', Präfix 'backup/2026/'
  [OK  ] Anmeldung und Bucket: Bucket 'archiv' erreichbar
  [OK  ] Leserecht: Präfix ist leer
  [OK  ] Schreibrecht: Testobjekt 'backup/2026/.s3-uploader-verbindungstest-…' angelegt
  [OK  ] Löschrecht: Testobjekt wieder entfernt
Verbindungstest erfolgreich.
```

### Hochladen

```bash
s3-uploader hochladen --endpunkt https://s3.example.org --bucket archiv \
  --access-key MEINKEY --prefix backup/2026 --quelle /daten/export
```

Aus `/daten/export/projekt/a.pdf` wird das Objekt `backup/2026/projekt/a.pdf`.

```text
Durchsuche /daten/export …
18342 Dateien (1,2 TiB), davon 0 bereits erledigt; offen: 18110 einfach, 232 in Teilen (1,2 TiB).
Zustandsdatei: /home/nutzer/.s3-uploader/zustand-3f9c0a1b2d4e5f60.sqlite
[ 42,3 %] 7712/18342 Dateien | 519,4 GiB / 1,2 TiB | 98,6 MiB/s | Rest 2:05:11
```

### Abgebrochenen Lauf fortsetzen

Denselben Befehl einfach noch einmal aufrufen. Die Zustandsdatei wird über Endpunkt,
Bucket, Präfix und Quelle automatisch wiedergefunden. Strg+C beendet einen Lauf geordnet:
laufende Teile werden noch fertig übertragen.

Wurde die Zustandsdatei gelöscht, übernimmt `--pruefe-ziel` bereits vorhandene Objekte
gleicher Größe, statt sie erneut zu übertragen.

### Teilung großer Dateien ein- oder ausschalten

Standardmäßig werden Dateien über der Schwelle (`--schwelle`, Standard 64 MiB) in Teile
zerlegt. Mit `--ohne-teilung` geht jede Datei als ein einziger Upload (`PutObject`):

```bash
s3-uploader hochladen … --quelle /daten/export --ohne-teilung
```

| | mit Teilung (Standard) | `--ohne-teilung` |
|---|---|---|
| Größte Datei | 5 TiB | 5 GiB (S3-Grenze für einen einzelnen Upload) |
| Abbruch mitten in einer großen Datei | Fortsetzen ab dem ersten fehlenden Teil | Diese Datei beginnt von vorn |
| Parallelität innerhalb einer Datei | `--parallel-teile` | keine |
| Objekt im Bucket | identischer Inhalt; ETag hat die Form `…-<Teilanzahl>` | ETag ist in der Regel der MD5-Wert der Datei |
| Wann sinnvoll | Normalfall, große Dateien, unsichere Leitungen | Speicher ohne (vollständige) Multipart-Unterstützung, gewünschter MD5-ETag |

Ohne Teilung liest das Programm jede Datei zweimal: einmal für die Prüfsumme, einmal für
die Übertragung. Der Inhalt wird gestreamt, liegt also nicht vollständig im Speicher, und
die Fortschrittsanzeige bewegt sich auch während einer einzelnen großen Datei. Dateien über
5 GiB meldet schon die Übersicht vor dem Start als Warnung; sie schlagen ohne Teilung fehl.

Wird ein mit Teilung begonnener Lauf mit `--ohne-teilung` fortgesetzt, bricht das Programm
angefangene Multipart-Uploads im Bucket ab und lädt die betroffenen Dateien neu hoch.

### Weitere Optionen von `hochladen`

| Option | Standard | Bedeutung |
|---|---|---|
| `--ohne-teilung` | – | Keine Teilung: jede Datei als ein Upload (max. 5 GiB) |
| `--schwelle` | `64MiB` | Ab dieser Größe Multipart (5 MiB – 5 GiB) |
| `--teilgroesse` | `16MiB` | Gewünschte Teilgröße (min. 5 MiB, wächst bei Bedarf) |
| `--parallel-dateien` | `4` | Gleichzeitig bearbeitete Dateien |
| `--parallel-teile` | `4` | Gleichzeitige Teile je großer Datei |
| `--zustand` | automatisch | Eigene Zustandsdatei |
| `--neu` | – | Zustand verwerfen, alles neu |
| `--pruefe-ziel` | – | Vorhandene Objekte gleicher Größe überspringen |
| `--ausschliessen MUSTER` | – | Glob-Muster auslassen, mehrfach möglich (`'*.tmp'`) |
| `--probelauf` | – | Nur Übersicht, nichts übertragen |
| `--still` | – | Keine Fortschrittsanzeige |
| `--adressierung` | `path` | `virtual` für AWS-Buckets mit DNS-Namen |
| `--ohne-tls-pruefung` | – | Zertifikat nicht prüfen (nur Testsysteme) |
| `-v`, `-vv` | – | Mehr Meldungen |

**Speicherbedarf:** höchstens etwa `parallel-dateien × parallel-teile × teilgroesse`
(Standard 256 MiB). Einzelne Uploads werden gestreamt und brauchen kaum Speicher.

### Exit-Codes

| Code | Bedeutung |
|---|---|
| 0 | Alles erfolgreich |
| 1 | Mindestens eine Datei fehlgeschlagen oder Verbindungstest negativ |
| 2 | Bedienfehler (fehlende/ungültige Angabe, falsche Zustandsdatei) |
| 130 | Abbruch mit Strg+C – erneuter Aufruf setzt fort |

## Entwicklung: Build und Test

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .
ruff format --check .     # Formatierung
ruff check .              # Linting
mypy src                  # Typprüfung (strict)
pytest --cov=s3_uploader  # Tests mit Abdeckung, ohne Netzwerk (S3-Attrappe moto)
```

Paket bauen (Wheel unter `dist/`): `pip install build && python -m build`.

## Dokumentation

- [docs/architektur.md](docs/architektur.md) – Aufbau mit UML-Diagrammen (Klassen, Ablauf, Zustände)
- [docs/lernen.md](docs/lernen.md) – Lern-Dokumentation: der Code Schritt für Schritt erklärt
- [CHANGELOG.md](CHANGELOG.md)

## Lizenzen der Abhängigkeiten

| Paket | Lizenz | Verwendung |
|---|---|---|
| boto3 / botocore | Apache-2.0 | Laufzeit |
| pytest, pytest-cov | MIT | Entwicklung |
| moto | Apache-2.0 | Entwicklung |
| ruff, mypy | MIT | Entwicklung |

s3-uploader selbst steht unter der [MIT-Lizenz](LICENSE).
