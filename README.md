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

## Einrichtung und Start – Betriebssystem wählen

Die Abschnitte sind jeweils vollständig. Lies nur den für dein System:

| Betriebssystem | Kommandozeile | Abschnitt |
|---|---|---|
| Windows 10/11 | PowerShell | [Windows](#windows) |
| macOS | Terminal (zsh) | [macOS](#macos) |
| Linux (Debian, Ubuntu, Fedora, RHEL …) | Terminal (bash) | [Linux](#linux) |

Alles danach ([Parameter](#parameter-und-umgebungsvariablen), [Optionen](#optionen-von-hochladen),
[Exit-Codes](#exit-codes) …) gilt für alle Systeme gleich.

Gemeinsame Voraussetzung: **Python 3.11 oder neuer** und Netzwerkzugang zum S3-Endpunkt.

---

## Windows

Alle Befehle in **PowerShell** (Startmenü → „PowerShell“). Befehle, die mit `.\` beginnen,
genau so eingeben – ohne `.\` findet PowerShell Programme im aktuellen Ordner nicht.

### W1. Python installieren

1. Installer von <https://www.python.org/downloads/windows/> herunterladen und ausführen.
2. Im ersten Fenster **„Add python.exe to PATH“** anhaken, dann „Install Now“.
3. Neues PowerShell-Fenster öffnen und prüfen:

```powershell
py --version
```

Unter Windows heißt der Python-Starter `py`. Die Befehle `python3` und anfangs oft auch
`python` sind nur Verknüpfungen zum Microsoft Store und melden „Python wurde nicht
gefunden“ – deshalb in den nächsten Schritten immer `py` verwenden, bis die virtuelle
Umgebung aktiv ist.

### W2. Quellcode holen

Mit git (falls installiert):

```powershell
git clone https://github.com/Weitenbummler/s3-uploader.git
```

```powershell
cd s3-uploader
```

Ohne git: auf <https://github.com/Weitenbummler/s3-uploader> „Code → Download ZIP“, ZIP
entpacken (z. B. nach `D:\Entwicklung\s3-uploader`) und in PowerShell dorthin wechseln:
`cd D:\Entwicklung\s3-uploader`.

### W3. Virtuelle Umgebung anlegen und aktivieren

```powershell
py -m venv .venv
```

Windows sperrt in PowerShell standardmäßig das Ausführen von Skripten, auch das
Aktivierungsskript der Umgebung („… kann nicht geladen werden, da die Ausführung von
Skripts auf diesem System deaktiviert ist“). Deshalb zuerst Skripte **nur für dieses
Fenster** erlauben – das ändert keine Systemeinstellung und gilt bis zum Schließen des
Fensters:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

Dann die Umgebung aktivieren:

```powershell
.\.venv\Scripts\Activate.ps1
```

Danach steht `(.venv)` vor der Eingabeaufforderung. Ab jetzt gelten `python` und `pip`
für die virtuelle Umgebung.

Darf `Set-ExecutionPolicy` nicht verwendet werden (z. B. durch eine Firmenrichtlinie),
geht es ohne Aktivierung: In allen folgenden Schritten `python` durch
`.\.venv\Scripts\python.exe`, `pip` durch `.\.venv\Scripts\pip.exe` und `s3-uploader`
durch `.\.venv\Scripts\s3-uploader.exe` ersetzen. (In der alten Eingabeaufforderung
`cmd.exe` lautet die Aktivierung `.venv\Scripts\activate.bat`; dort gibt es die Sperre nicht.)

### W4. s3-uploader installieren

```powershell
python -m pip install --upgrade pip
```

```powershell
pip install -r requirements.txt
```

```powershell
pip install .
```

Alle drei Befehle sind nötig. `requirements.txt` installiert nur die Zusatzmodule; erst
`pip install .` installiert s3-uploader selbst und legt den Befehl `s3-uploader` an.

### W5. Installation prüfen

```powershell
s3-uploader --version
```

Meldet PowerShell „Der Begriff „s3-uploader“ wird nicht … erkannt“: Ist `(.venv)` nicht
zu sehen, Schritt W3 (Freigabe und Aktivierung) wiederholen; sonst fehlt `pip install .`
aus W4.

### W6. Starten

Passwort: Am sichersten gar nicht angeben – dann fragt s3-uploader beim Start verdeckt
danach. Für mehrere Aufrufe hintereinander kann es für dieses Fenster gesetzt werden (die
Zeile landet allerdings im PowerShell-Verlauf):

```powershell
$env:S3_SECRET_KEY = 'DEIN-SECRET-KEY'
```

Verbindung testen – lange Befehle mit `` ` `` (Backtick) am Zeilenende umbrechen:

```powershell
s3-uploader test --endpunkt https://s3.example.org --bucket archiv `
  --access-key MEINKEY --prefix backup/2026 --schreibtest
```

Hochladen:

```powershell
s3-uploader hochladen --endpunkt https://s3.example.org --bucket archiv `
  --access-key MEINKEY --prefix backup/2026 --quelle D:\Daten\Export
```

Nach einem Abbruch denselben Befehl noch einmal ausführen – der Lauf wird fortgesetzt.

### W7. In einem neuen PowerShell-Fenster

Freigabe, Aktivierung und `$env:S3_SECRET_KEY` gelten nur im jeweiligen Fenster. Später also:

```powershell
cd D:\Entwicklung\s3-uploader
```

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

```powershell
.\.venv\Scripts\Activate.ps1
```

Ohne Aktivierung geht es auch direkt: `.\.venv\Scripts\s3-uploader.exe hochladen …`
(aus dem Projektordner heraus).

### W8. Aktualisieren und Deinstallieren

Aktualisieren (im Projektordner, Umgebung aktiv):

```powershell
git pull
```

```powershell
pip install -r requirements.txt
```

```powershell
pip install .
```

Wurde der Quellcode als ZIP geholt: neues ZIP über den alten Ordner entpacken (`.venv`
bleibt erhalten), dann die beiden `pip`-Befehle.

Deinstallieren: den Projektordner löschen (er enthält auch `.venv`) und die Zustandsdateien
unter `%USERPROFILE%\.s3-uploader\` (z. B. `C:\Users\Name\.s3-uploader\`).

### W9. Ohne Internet installieren

Auf einem Rechner mit Internet, gleiche Windows- und Python-Version, im Projektordner:

```powershell
pip download -r requirements.txt -d pakete
```

Projektordner samt `pakete` auf den Zielrechner kopieren, dort nach W3:

```powershell
pip install --no-index --find-links pakete -r requirements.txt
```

```powershell
pip install --no-index --find-links pakete .
```

### W10. Entwickeln und Testen

```powershell
pip install -r requirements-dev.txt
```

```powershell
pip install -e .
```

```powershell
pytest --cov=s3_uploader
```

```powershell
ruff check .
```

```powershell
mypy src
```

Mit **Python 3.15** scheitert `requirements-dev.txt` derzeit: Das Testwerkzeug `moto`
braucht PyYAML, für das es unter Windows noch kein fertiges Paket für 3.15 gibt, und pip
verlangt dann die „Microsoft C++ Build Tools“. Zum Entwickeln deshalb Python 3.13 oder
3.14 zusätzlich installieren und die Umgebung damit anlegen: `py -3.14 -m venv .venv`.
Für den reinen Betrieb (W4) ist 3.15 kein Problem.

### W11. Hinweise für Windows

- Getestet unter Windows 11 mit Python 3.15 und PowerShell 5.1: alle Tests,
  Verbindungstest, Hochladen, Fortsetzen, Abbruch per Strg+C, `--ohne-teilung`, Pfade mit
  Leerzeichen und Umlauten.
- Pfade in Anführungszeichen nicht mit `\` beenden: `--quelle "D:\Daten\"` wird als
  `D:\Daten"` gelesen. Richtig: `--quelle "D:\Daten"` oder `--quelle D:\Daten`.
- Groß-/Kleinschreibung und `/` oder `\` im Quellpfad spielen keine Rolle: `D:\Daten` und
  `d:/daten` finden dieselbe Zustandsdatei.
- Für die Fortschrittszeile in der klassischen Konsole schaltet s3-uploader die
  Verarbeitung von Steuerzeichen selbst ein; gelingt das nicht, überschreibt es die Zeile
  mit Leerzeichen. Windows Terminal versteht die Steuerzeichen ohnehin.
- Von einem anderen Programm gesperrte Dateien (z. B. in Excel geöffnet) schlagen einzeln
  fehl und werden beim nächsten Aufruf erneut versucht.
- Pfade über 260 Zeichen brauchen die Windows-Einstellung „Lange Pfade aktivieren“
  (`LongPathsEnabled`).

---

## macOS

Alle Befehle im **Terminal** (Programme → Dienstprogramme → Terminal).

### M1. Python installieren

Prüfen, ob ein ausreichend neues Python vorhanden ist (3.11 oder neuer):

```bash
python3 --version
```

Das von Apple mitgelieferte Python ist oft 3.9 und damit zu alt. Neueres Python mit
[Homebrew](https://brew.sh):

```bash
brew install python@3.13
```

Danach heißt der Befehl `python3.13`. Wo unten `python3` steht, dann `python3.13`
verwenden. Alternativ den Installer von <https://www.python.org/downloads/macos/>.

### M2. Quellcode holen

```bash
git clone https://github.com/Weitenbummler/s3-uploader.git
```

```bash
cd s3-uploader
```

Fehlt git, bietet macOS beim ersten Aufruf die „Command Line Tools“ an. Ohne git: auf
GitHub „Code → Download ZIP“, entpacken und mit `cd` in den Ordner wechseln.

### M3. Virtuelle Umgebung anlegen und aktivieren

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

Danach steht `(.venv)` vor der Eingabeaufforderung. Ab jetzt gelten `python` und `pip`
für die virtuelle Umgebung.

### M4. s3-uploader installieren

```bash
python -m pip install --upgrade pip
```

```bash
pip install -r requirements.txt
```

```bash
pip install .
```

Alle drei Befehle sind nötig. `requirements.txt` installiert nur die Zusatzmodule; erst
`pip install .` installiert s3-uploader selbst und legt den Befehl `s3-uploader` an.

### M5. Installation prüfen

```bash
s3-uploader --version
```

Meldet das Terminal `command not found`: Ist `(.venv)` nicht zu sehen, Schritt M3
wiederholen; sonst fehlt `pip install .` aus M4.

### M6. Starten

Passwort: Am sichersten gar nicht angeben – dann fragt s3-uploader beim Start verdeckt
danach. Für mehrere Aufrufe hintereinander kann es für dieses Fenster gesetzt werden (die
Zeile landet allerdings im Shell-Verlauf):

```bash
export S3_SECRET_KEY='DEIN-SECRET-KEY'
```

Verbindung testen – lange Befehle mit `\` am Zeilenende umbrechen:

```bash
s3-uploader test --endpunkt https://s3.example.org --bucket archiv \
  --access-key MEINKEY --prefix backup/2026 --schreibtest
```

Hochladen:

```bash
s3-uploader hochladen --endpunkt https://s3.example.org --bucket archiv \
  --access-key MEINKEY --prefix backup/2026 --quelle ~/Daten/Export
```

Nach einem Abbruch denselben Befehl noch einmal ausführen – der Lauf wird fortgesetzt.

### M7. In einem neuen Terminalfenster

```bash
cd ~/Pfad/zu/s3-uploader
```

```bash
source .venv/bin/activate
```

Ohne Aktivierung geht es auch direkt: `.venv/bin/s3-uploader hochladen …`.

### M8. Aktualisieren und Deinstallieren

```bash
git pull && pip install -r requirements.txt && pip install .
```

Deinstallieren: Projektordner löschen (enthält `.venv`) und die Zustandsdateien entfernen:
`rm -r ~/.s3-uploader`.

### M9. Ohne Internet installieren

Auf einem Mac mit Internet (gleiche macOS- und Python-Version), im Projektordner:

```bash
pip download -r requirements.txt -d pakete
```

Projektordner samt `pakete` kopieren, auf dem Zielrechner nach M3:

```bash
pip install --no-index --find-links pakete -r requirements.txt && pip install --no-index --find-links pakete .
```

### M10. Entwickeln und Testen

```bash
pip install -r requirements-dev.txt && pip install -e .
```

```bash
ruff format --check . && ruff check . && mypy src && pytest --cov=s3_uploader
```

### M11. Hinweise für macOS

- Ein laufender Upload hält den Mac nicht wach. Für lange Läufe den Befehl mit
  `caffeinate -i` davor starten: `caffeinate -i s3-uploader hochladen …`.
- Quellordner in „Dokumente“, „Schreibtisch“ oder auf externen Laufwerken brauchen ggf. die
  Freigabe für das Terminal (Systemeinstellungen → Datenschutz & Sicherheit →
  Festplattenvollzugriff).
- Finder-Hilfsdateien wie `.DS_Store` lassen sich mit `--ausschliessen '*.DS_Store'`
  auslassen.

---

## Linux

Alle Befehle im **Terminal** (bash).

### L1. Python installieren

Prüfen (3.11 oder neuer nötig):

```bash
python3 --version
```

Fehlt Python oder `venv`:

- **Debian 12 / Ubuntu 24.04 und neuer:** `sudo apt install python3 python3-venv python3-pip git`
- **Fedora:** `sudo dnf install python3 python3-pip git`
- **RHEL / Rocky / Alma 9:** Das Standard-Python ist 3.9. Stattdessen
  `sudo dnf install python3.11 python3.11-pip git` und unten `python3.11` statt `python3`.
- **Ubuntu 22.04:** Das Standard-Python ist 3.10. Stattdessen
  `sudo apt install python3.11 python3.11-venv` und unten `python3.11` statt `python3`.

### L2. Quellcode holen

```bash
git clone https://github.com/Weitenbummler/s3-uploader.git
```

```bash
cd s3-uploader
```

### L3. Virtuelle Umgebung anlegen und aktivieren

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

Danach steht `(.venv)` vor der Eingabeaufforderung. Meldet `venv` „ensurepip is not
available“, fehlt das Paket `python3-venv` (siehe L1).

### L4. s3-uploader installieren

```bash
python -m pip install --upgrade pip
```

```bash
pip install -r requirements.txt
```

```bash
pip install .
```

Alle drei Befehle sind nötig. `requirements.txt` installiert nur die Zusatzmodule; erst
`pip install .` installiert s3-uploader selbst und legt den Befehl `s3-uploader` an.

### L5. Installation prüfen

```bash
s3-uploader --version
```

Bei `command not found`: Ist `(.venv)` nicht zu sehen, L3 wiederholen; sonst fehlt
`pip install .` aus L4.

### L6. Starten

Passwort: Am sichersten gar nicht angeben – dann fragt s3-uploader beim Start verdeckt
danach. Für mehrere Aufrufe hintereinander kann es gesetzt werden (die Zeile landet
allerdings im Shell-Verlauf; mit einem Leerzeichen am Zeilenanfang meist nicht):

```bash
export S3_SECRET_KEY='DEIN-SECRET-KEY'
```

Verbindung testen – lange Befehle mit `\` am Zeilenende umbrechen:

```bash
s3-uploader test --endpunkt https://s3.example.org --bucket archiv \
  --access-key MEINKEY --prefix backup/2026 --schreibtest
```

Hochladen:

```bash
s3-uploader hochladen --endpunkt https://s3.example.org --bucket archiv \
  --access-key MEINKEY --prefix backup/2026 --quelle /daten/export
```

Nach einem Abbruch denselben Befehl noch einmal ausführen – der Lauf wird fortgesetzt.

### L7. In einem neuen Terminal

```bash
cd /pfad/zu/s3-uploader && source .venv/bin/activate
```

Ohne Aktivierung, z. B. in Cron-Jobs oder systemd-Units, das Programm mit vollem Pfad
aufrufen: `/pfad/zu/s3-uploader/.venv/bin/s3-uploader hochladen …`.

### L8. Aktualisieren und Deinstallieren

```bash
git pull && pip install -r requirements.txt && pip install .
```

Deinstallieren: Projektordner löschen und `rm -r ~/.s3-uploader`.

### L9. Ohne Internet installieren

Auf einem Rechner mit Internet (gleiche Distribution und Python-Version), im Projektordner:

```bash
pip download -r requirements.txt -d pakete
```

Projektordner samt `pakete` kopieren, auf dem Zielrechner nach L3:

```bash
pip install --no-index --find-links pakete -r requirements.txt && pip install --no-index --find-links pakete .
```

### L10. Entwickeln und Testen

```bash
pip install -r requirements-dev.txt && pip install -e .
```

```bash
ruff format --check . && ruff check . && mypy src && pytest --cov=s3_uploader
```

### L11. Hinweise für Linux

- Lange Läufe auf Servern in `tmux` oder `screen` starten, damit sie das Abmelden
  überstehen; oder mit `nohup … > upload.log 2>&1 &`. In eine Datei umgeleitet schreibt die
  Fortschrittsanzeige alle 30 Sekunden eine eigene Zeile.
- Für Cron/systemd das Passwort nicht in die Unit oder Crontab schreiben, sondern aus einer
  nur für den Benutzer lesbaren Datei laden (`chmod 600`), z. B.
  `EnvironmentFile=/etc/s3-uploader/zugang.env` mit `S3_SECRET_KEY=…`.

---

## Parameter und Umgebungsvariablen

Für alle Systeme gleich. Alle Angaben gehen als Parameter **oder** als Umgebungsvariable:

| Parameter | Umgebungsvariable | Bedeutung |
|---|---|---|
| `--endpunkt` | `S3_ENDPUNKT` | URL, z. B. `https://s3.example.org` |
| `--bucket` | `S3_BUCKET` | Ziel-Bucket |
| `--prefix` | `S3_PREFIX` | Präfix im Bucket, z. B. `backup/2026` |
| `--access-key` | `S3_ACCESS_KEY` | Access Key |
| `--passwort` / `--secret-key` | `S3_SECRET_KEY` | Secret Key; fehlt er, wird verdeckt gefragt |
| `--region` | `S3_REGION` | Region für die Signatur (Standard `us-east-1`) |

Umgebungsvariable setzen: Windows `$env:NAME = 'wert'`, macOS/Linux `export NAME='wert'`.

> **Sicherheitshinweis:** Parameter auf der Kommandozeile sind für andere Benutzer im
> Prozesslisting und im Shell-Verlauf sichtbar. Das Passwort besser per Umgebungsvariable
> oder verdeckter Eingabe übergeben. Zugangsdaten werden nie in die Zustandsdatei oder ins
> Protokoll geschrieben.

## Was die Befehle ausgeben

Verbindungstest:

```text
Teste https://s3.example.org – Bucket 'archiv', Präfix 'backup/2026/'
  [OK  ] Anmeldung und Bucket: Bucket 'archiv' erreichbar
  [OK  ] Leserecht: Präfix ist leer
  [OK  ] Schreibrecht: Testobjekt 'backup/2026/.s3-uploader-verbindungstest-…' angelegt
  [OK  ] Löschrecht: Testobjekt wieder entfernt
Verbindungstest erfolgreich.
```

Hochladen (aus `<quelle>/projekt/a.pdf` wird das Objekt `backup/2026/projekt/a.pdf`):

```text
Durchsuche …
18342 Dateien (1,2 TiB), davon 0 bereits erledigt; offen: 18110 einfach, 232 in Teilen (1,2 TiB).
Zustandsdatei: …/.s3-uploader/zustand-3f9c0a1b2d4e5f60.sqlite
[ 42,3 %] 7712/18342 Dateien | 519,4 GiB / 1,2 TiB | 98,6 MiB/s | Rest 2:05:11
```

## Abgebrochenen Lauf fortsetzen

Denselben Befehl einfach noch einmal aufrufen. Die Zustandsdatei (im Benutzerordner unter
`.s3-uploader`) wird über Endpunkt, Bucket, Präfix und Quelle automatisch wiedergefunden.
Strg+C beendet einen Lauf geordnet: laufende Teile werden noch fertig übertragen.

Wurde die Zustandsdatei gelöscht, übernimmt `--pruefe-ziel` bereits vorhandene Objekte
gleicher Größe, statt sie erneut zu übertragen.

## Teilung großer Dateien ein- oder ausschalten

Standardmäßig werden Dateien über der Schwelle (`--schwelle`, Standard 64 MiB) in Teile
zerlegt. Mit `--ohne-teilung` geht jede Datei als ein einziger Upload (`PutObject`):
`s3-uploader hochladen … --ohne-teilung`.

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

## Optionen von `hochladen`

| Option | Standard | Bedeutung |
|---|---|---|
| `--quelle PFAD` | – | Quellverzeichnis (Pflicht) |
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

Alle Optionen mit Erklärung: `s3-uploader hochladen --help`.

**Speicherbedarf:** höchstens etwa `parallel-dateien × parallel-teile × teilgroesse`
(Standard 256 MiB). Einzelne Uploads werden gestreamt und brauchen kaum Speicher.

## Exit-Codes

| Code | Bedeutung |
|---|---|
| 0 | Alles erfolgreich |
| 1 | Mindestens eine Datei fehlgeschlagen oder Verbindungstest negativ |
| 2 | Bedienfehler (fehlende/ungültige Angabe, falsche Zustandsdatei) |
| 130 | Abbruch mit Strg+C – erneuter Aufruf setzt fort |

## Zusatzmodule

| Datei | Inhalt | Wofür |
|---|---|---|
| [`requirements.txt`](requirements.txt) | `boto3` (AWS SDK, Apache-2.0) | Betrieb – immer nötig |
| [`requirements-dev.txt`](requirements-dev.txt) | zusätzlich `pytest`, `pytest-cov`, `moto`, `ruff`, `mypy` | Entwicklung und Tests |

`pyproject.toml` liest die Laufzeit-Abhängigkeiten direkt aus `requirements.txt`; sie
stehen also nur an einer Stelle. Paket bauen (Wheel unter `dist/`):
`pip install build` und danach `python -m build`.

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
