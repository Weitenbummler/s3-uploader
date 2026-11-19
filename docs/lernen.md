# s3-uploader verstehen – eine Lern-Dokumentation

Autor: Oliver Tesch

Diese Anleitung erklärt Schritt für Schritt, wie s3-uploader funktioniert und warum er so
gebaut ist. Sie richtet sich an Leserinnen und Leser, die Python-Grundlagen kennen
(Funktionen, Klassen, Module) und S3 sowie die verwendeten Techniken kennenlernen wollen.
Jedes Kapitel endet mit einer kleinen Übung.

Empfohlene Lesereihenfolge des Codes: `planung.py` → `dateisuche.py` → `zustand.py` →
`uploader.py` → `fortschritt.py` → `cli.py`.

---

## 1. Was ist S3?

S3 (Simple Storage Service) ist ein **Objektspeicher**. Anders als ein Dateisystem kennt er
keine echten Verzeichnisse:

- Ein **Bucket** ist ein Behälter, vergleichbar mit einem Laufwerk.
- Ein **Objekt** ist eine Datei samt Metadaten, angesprochen über einen **Schlüssel**
  (Key), z. B. `backup/2026/projekt/a.pdf`.
- Das **Präfix** `backup/2026/` ist nur der Anfang des Schlüssels. Oberflächen zeigen es
  wie einen Ordner an, technisch ist es eine Zeichenkette.

Man spricht S3 über HTTP an: `PUT` legt ein Objekt ab, `GET` liest es, `HEAD` liefert nur
die Metadaten. Jede Anfrage wird mit **Access Key** und **Secret Key** signiert
(Verfahren „Signature Version 4“). Diese Arbeit übernimmt die Bibliothek **boto3**.

Viele Anbieter (MinIO, Ceph, Wasabi …) bieten dieselbe Schnittstelle an. Deshalb nimmt
s3-uploader einen frei wählbaren **Endpunkt** entgegen.

> **Übung 1:** Öffne `client.py`. Welche drei Werte aus `Verbindung` braucht
> `boto3.client(...)` mindestens, um eine Anfrage zu signieren?

---

## 2. Warum „Paketierung“? – Multipart-Upload

Ein einzelner `PUT` darf höchstens 5 GiB groß sein. Außerdem wäre es ärgerlich, bei einer
80-GiB-Datei nach 79 GiB wegen eines Netzaussetzers von vorn anzufangen. S3 bietet dafür den
**Multipart-Upload**:

1. `CreateMultipartUpload` → S3 vergibt eine **UploadId**.
2. `UploadPart` für jeden Teil (Nummer 1 … 10 000), in beliebiger Reihenfolge, auch
   parallel. Jeder Teil liefert einen **ETag** (eine Kennung des Inhalts).
3. `CompleteMultipartUpload` mit der Liste aller Teilnummern und ETags → S3 setzt das
   Objekt zusammen.
4. Oder `AbortMultipartUpload`, um alles zu verwerfen.

Grenzen: Teile mindestens 5 MiB (außer dem letzten), höchstens 5 GiB, höchstens 10 000
Teile, Objekt höchstens 5 TiB.

### Die Teilgröße berechnen (`planung.py`)

```python
teilgroesse = min(max(wunsch, MIN_TEILGROESSE), MAX_TEILGROESSE)
mindestens = -(-dateigroesse // MAX_TEILE)  # Aufrunden ohne Gleitkomma
if teilgroesse < mindestens:
    teilgroesse = -(-mindestens // MIB) * MIB
```

Der Trick `-(-a // b)` rundet eine Ganzzahldivision **auf**: `//` rundet in Python immer
nach unten (Richtung minus unendlich); dreht man das Vorzeichen zweimal um, erhält man das
Aufrunden. Gleitkommazahlen vermeiden wir, weil sie bei Terabyte-Werten ungenau werden
können.

Beispiel: 1 TiB mit Wunsch 16 MiB ergäbe 65 536 Teile – zu viele. Mindestens nötig sind
1 TiB / 10 000 ≈ 104,9 MiB, aufgerundet 105 MiB.

> **Übung 2:** Rechne mit `berechne_teilgroesse` in einer Python-Konsole nach, welche
> Teilgröße eine 200-GiB-Datei bei Wunsch 16 MiB erhält:
> `python -c "from s3_uploader.planung import *; print(berechne_teilgroesse(200*1024**3, 16*MIB)/MIB)"`

---

## 3. Dateien finden (`dateisuche.py`)

`finde_dateien` ist ein **Generator**: Mit `yield` gibt er eine Datei nach der anderen
heraus, statt erst eine riesige Liste zu bauen. Statt Rekursion verwendet er einen
**Stapel** (`stapel = [wurzel]`, `stapel.pop()`), denn Python bricht bei etwa 1 000
Rekursionsebenen ab.

`os.scandir` liefert Verzeichniseinträge samt bereits zwischengespeicherter Dateiinfos und
ist dadurch deutlich schneller als `os.listdir` + `os.stat` – wichtig bei Hunderttausenden
Dateien.

Symbolische Links werden bewusst **nicht** verfolgt: Ein Link auf das Elternverzeichnis
würde sonst eine Endlosschleife erzeugen.

Die Klasse `Datei` ist eine **Datenklasse**:

```python
@dataclass(frozen=True, slots=True)
class Datei:
    pfad: Path
    schluessel: str
    groesse: int
    mtime_ns: int
```

`frozen=True` macht Objekte unveränderlich (sicher zwischen Threads teilbar), `slots=True`
spart Speicher – bei einer Million Dateien ein spürbarer Unterschied.

> **Übung 3:** Lege ein Verzeichnis mit einer Datei `notiz.tmp` an und starte
> `s3-uploader hochladen … --probelauf --ausschliessen '*.tmp'`. Wie viele Dateien werden
> gezählt?

---

## 4. Wiederaufsetzen: der Zustand (`zustand.py`)

Damit ein abgebrochener Lauf weitermachen kann, muss sich das Programm merken, was schon
fertig ist – **dauerhaft**, also auf der Festplatte. Dafür nutzt s3-uploader **SQLite**,
eine Datenbank in einer einzigen Datei, die in Python schon eingebaut ist (`import sqlite3`).

Warum nicht einfach eine JSON-Datei? Bricht das Programm genau beim Schreiben ab, ist eine
JSON-Datei halb geschrieben und unbrauchbar. SQLite schreibt jede Änderung **atomar**: Sie
ist entweder vollständig da oder gar nicht.

Zwei Tabellen tragen die Arbeit:

- `dateien`: je Objektschlüssel Größe, Änderungszeit, Status (`laufend`/`erledigt`) und
  bei Multipart die UploadId.
- `teile`: je fertigem Teil Nummer und ETag.

**Wann gilt eine Datei als erledigt?** Nur wenn Status `erledigt` **und** Größe und
Änderungszeit (`mtime_ns`) noch übereinstimmen. Hat jemand die Datei inzwischen geändert,
wird sie erneut hochgeladen.

**Thread-Sicherheit:** Mehrere Threads schreiben gleichzeitig. Eine `threading.Lock` sorgt
dafür, dass immer nur einer die Datenbankverbindung benutzt:

```python
with self._sperre:
    self._db.execute("INSERT OR REPLACE INTO teile VALUES (?, ?, ?)", (schluessel, nummer, etag))
```

Die Fragezeichen sind **Platzhalter**. Werte nie per f-String in SQL einsetzen – sonst
droht SQL-Injection und Ärger mit Sonderzeichen in Dateinamen.

**Schutz vor Verwechslung:** `pruefe_kontext` speichert beim ersten Lauf Endpunkt, Bucket,
Präfix und Quelle. Wer später versehentlich dieselbe Zustandsdatei für ein anderes Ziel
verwendet, bekommt einen Fehler statt stiller Lücken im Ziel.

> **Übung 4:** Lade etwas hoch und öffne danach die Zustandsdatei:
> `sqlite3 ~/.s3-uploader/zustand-*.sqlite "SELECT schluessel, status FROM dateien LIMIT 5"`.

---

## 5. Der Kern (`uploader.py`)

### 5.1 Entscheidung je Datei

`_verarbeite` arbeitet eine feste Reihenfolge ab: erledigt? → im Ziel vorhanden
(`--pruefe-ziel`)? → klein oder groß? Das Sequenzdiagramm in
[architektur.md](architektur.md) zeigt den Ablauf grafisch.

### 5.2 Fortsetzen eines Multipart-Uploads

```python
stand = self._zustand.multipart_stand(datei)
if stand is not None:
    fertige = self._teile_auf_server(datei, stand.upload_id, stand.teilgroesse)
```

Wichtig: Was fertig ist, entscheidet der **Server** (`ListParts`), nicht allein die
Zustandsdatei. Ein Teil kann vollständig übertragen worden sein, kurz bevor das Programm
abstürzte und ihn speichern konnte. Umgekehrt kann ein Upload serverseitig gelöscht worden
sein (z. B. durch eine Aufräumregel im Bucket) – dann beginnt der Upload neu.

### 5.3 Parallelität mit Threads

```python
with ThreadPoolExecutor(self._e.parallel_teile, thread_name_prefix="teil") as pool:
    auftraege = [pool.submit(self._lade_teil, datei, upload_id, teil, gemeldet) for teil in offen]
    erledigt, _ = wait(auftraege, return_when=FIRST_EXCEPTION)
```

Ein `ThreadPoolExecutor` verwaltet eine feste Anzahl Arbeits-Threads. `submit` reicht eine
Aufgabe ein und liefert ein `Future` – ein Versprechen auf ein späteres Ergebnis.
`wait(..., FIRST_EXCEPTION)` kehrt zurück, sobald ein Teil scheitert; die übrigen noch
nicht begonnenen werden mit `cancel()` gestoppt.

Warum Threads, obwohl Python einen „Global Interpreter Lock“ (GIL) hat? Der GIL wird
freigegeben, während ein Thread auf das Netzwerk wartet. Beim Hochladen wird fast nur
gewartet – Threads bringen hier also echten Gewinn.

**Achtung, Falle:** `x += 1` ist nicht atomar (lesen, addieren, schreiben). Darum gibt es die
kleine Klasse `_Zaehler` mit eigener Sperre.

### 5.4 Integrität

```python
ContentMD5 = _md5_base64(daten)
```

Der Server berechnet den MD5-Wert der empfangenen Daten selbst und lehnt ab, wenn er nicht
passt. So fällt jede Verfälschung auf dem Übertragungsweg auf. Vor `Complete` prüft
`_pruefe_unveraendert`, ob die Datei während des Uploads verändert wurde – sonst entstünde
ein Objekt aus alten und neuen Teilen.

> **Übung 5:** Lies den Test `test_abgebrochener_multipart_wird_fortgesetzt` in
> `tests/test_uploader.py`. Wie simuliert die Klasse `StoerClient` einen Netzwerkfehler,
> ohne dass ein echtes Netzwerk nötig ist?

---

## 5a. Teilung abschalten (`--ohne-teilung`)

Die Teilung ist optional. `UploadEinstellungen.teilung` steuert sie, und eine einzige
Methode entscheidet:

```python
def _in_teilen(self, datei: Datei) -> bool:
    return self._e.teilung and braucht_multipart(datei.groesse, self._e.schwelle)
```

Ist die Teilung aus, landet jede Datei in `_einfach`. Zwei Dinge werden dort wichtig:

1. **Die 5-GiB-Grenze.** Ein einzelner `PutObject` darf nicht größer sein. Größere Dateien
   werden mit einer klaren Meldung abgewiesen. `plane()` zählt sie vorab in `zu_gross`,
   damit die Warnung schon vor dem Start erscheint.
2. **Speicher und Fortschritt.** Statt `read_bytes()` (lädt die ganze Datei) wird die
   geöffnete Datei als `Body` übergeben – boto3 liest sie dann stückweise. Die Hülle
   `_FortschrittsLeser` meldet dabei die gelesenen Bytes an die Anzeige:

```python
def read(self, anzahl: int = -1) -> bytes:
    daten = self._datei.read(anzahl)
    position = self._datei.tell()
    if position > self._weiteste:
        self._melde(position - self._weiteste)
        self._weiteste = position
    return daten
```

Warum „weiteste Position“ statt einfach `len(daten)`? Schlägt eine Anfrage fehl, springt
botocore mit `seek(0)` zurück und sendet erneut. Mit `len(daten)` würden die Bytes dann
doppelt gezählt und die Anzeige stünde bei über 100 %. Die Methode `__getattr__` reicht
alle anderen Aufrufe (`seek`, `tell` …) unverändert an die Datei weiter – ein Beispiel für
das Entwurfsmuster **Dekorierer**.

Wer einen mit Teilung begonnenen Lauf ohne Teilung fortsetzt, hinterließe sonst einen
halben Multipart-Upload im Bucket. `Zustand.offener_upload()` findet ihn, `_breche_upload_ab`
räumt ihn auf.

> **Übung 5a:** Lade dasselbe Verzeichnis einmal mit und einmal ohne `--ohne-teilung` in
> zwei verschiedene Präfixe und vergleiche die ETags der großen Datei mit
> `aws s3api head-object` oder in der Oberfläche deines Speichers. Woran erkennst du das
> Multipart-Objekt?

---

## 6. Fortschritt anzeigen (`fortschritt.py`)

Die Arbeits-Threads melden nur Ereignisse (`bytes_uebertragen`, `datei_hochgeladen` …) an
`Fortschritt`. Ein eigener Hintergrund-Thread in `Anzeige` liest zweimal pro Sekunde eine
`Momentaufnahme` und schreibt eine Zeile:

```text
[ 42,3 %] 7712/18342 Dateien | 519,4 GiB / 1,2 TiB | 98,6 MiB/s | Rest 2:05:11
```

Der Trick für die „stehende“ Zeile: `\r` springt an den Zeilenanfang, `\033[K` löscht den
Rest. Wird die Ausgabe in eine Datei umgeleitet (`isatty()` ist dann `False`), schreibt die
Anzeige stattdessen alle 30 Sekunden eine neue Zeile – ein Protokoll voller `\r` wäre
unlesbar.

Bereits vorhandene Bytes (übersprungene Dateien, fortgesetzte Teile) zählen zum Prozentwert,
aber **nicht** zur Rate. Sonst zeigte ein fortgesetzter Lauf anfangs absurde
Geschwindigkeiten.

`Anzeige` ist ein **Kontextmanager** (`__enter__`/`__exit__`): Mit `with Anzeige(...):`
startet der Thread automatisch und wird garantiert wieder beendet – auch bei einer
Ausnahme.

> **Übung 6:** Starte einen Upload und leite stderr in eine Datei um
> (`2> fortschritt.log`). Wie sieht die Ausgabe dort aus?

---

## 7. Die Kommandozeile (`cli.py`)

`argparse` baut die Befehle `test` und `hochladen`. Gemeinsame Parameter stehen in einem
„Eltern-Parser“ (`parents=[gemeinsam]`) und werden so nur einmal definiert.

Jeder Parameter hat eine Umgebungsvariable als Vorgabe:

```python
ziel.add_argument("--bucket", default=_umgebung("S3_BUCKET"), help="Ziel-Bucket (S3_BUCKET)")
```

Das Passwort wird, falls weder Parameter noch Variable gesetzt sind, mit
`getpass.getpass()` verdeckt abgefragt. In `Verbindung` steht es als
`field(repr=False)` – es erscheint deshalb nie in Fehlermeldungen oder Protokollen.

`main()` übersetzt Ausnahmen in **Exit-Codes** (0, 1, 2, 130). Skripte und Cronjobs
können damit auf das Ergebnis reagieren:

```bash
s3-uploader hochladen … || echo "Upload unvollständig – bitte erneut starten"
```

`KeyboardInterrupt` (Strg+C) wird geordnet behandelt: Der `Uploader` setzt das
`abbruch`-Ereignis, laufende Teile werden noch fertig übertragen und gespeichert, neue nicht
mehr begonnen.

> **Übung 7:** Starte einen großen Upload, brich ihn mit Strg+C ab, und starte ihn mit
> `-v` erneut. Suche die Zeile „Setze fort: …“.

---

## 7a. Zertifikate und `verify`

HTTPS schützt nur, wenn das Programm prüft, *wer* am anderen Ende sitzt. Dazu vergleicht es
das Zertifikat des Servers mit einer Liste vertrauenswürdiger Zertifizierungsstellen (CA).
Firmen betreiben oft eine eigene CA; die steht nicht in der öffentlichen Liste, die Python
mitbringt. Die Folge ist `CERTIFICATE_VERIFY_FAILED`.

boto3 steuert die Prüfung über den Parameter `verify`. `tls_pruefung()` in `client.py`
übersetzt die Einstellungen:

```python
if not verbindung.tls_pruefen:
    return False  # gar nicht prüfen
if verbindung.ca_zertifikat is not None:
    return str(verbindung.ca_zertifikat)  # nur diese CA-Datei gilt
return None  # boto3 entscheidet (AWS_CA_BUNDLE oder Standard)
```

Die Feinheit steckt in der letzten Zeile: Mit `True` würde boto3 die Umgebungsvariable
`AWS_CA_BUNDLE` übergehen, mit `None` beachtet es sie. Ein Test
(`test_aws_ca_bundle_wird_beachtet`) sichert genau das ab.

Zweite Lehre: **dauerhafte Fehler nicht wiederholen.** boto3 wiederholt Verbindungsfehler –
auch einen Zertifikatsfehler, der beim zehnten Versuch genauso auftritt. Der
Verbindungstest nutzt daher `max_versuche=2`, und `hochladen` prüft die Verbindung vorab,
statt jede Datei einzeln scheitern zu lassen.

Dritte Lehre: **Eingaben früh und verständlich prüfen.** Eine Zertifikatsdatei kann binär
(DER), doppelt kodiert oder als UTF-16 gespeichert sein – OpenSSL meldet das nur knapp als
`[X509] PEM lib`. `pruefe_ca_datei` in `konfiguration.py` erkennt diese Fälle beim Start:
Binäres DER beginnt mit dem Byte `0x30`, UTF-16 mit einer Bytefolge `FF FE`, und bei doppelter
Kodierung ergibt das Entschlüsseln des Blocks wieder `-----BEGIN`.

> **Übung 7a:** Warum wäre es gefährlich, das Zertifikat einfach vom Server selbst
> herunterzuladen und mit `--ca-zertifikat` anzugeben? (Lösung: Ein Angreifer in der
> Mitte würde dir sein eigenes Zertifikat liefern – du würdest ihm damit vertrauen. Den
> Fingerabdruck deshalb immer über einen zweiten Weg mit dem Betreiber abgleichen.)

---

## 7b. Fehler eingrenzen statt raten

„403 Forbidden“ kann vieles heißen. `verbindungstest.py` nutzt aus, dass S3 eine Anfrage
in einer festen Reihenfolge prüft: erst die Signatur (Access Key bekannt? Passwort richtig?
Uhrzeit passend?), dann die Rechte. Daraus folgt eine nützliche Schlussregel:

> Ein `AccessDenied` beweist, dass Access Key und Passwort stimmen – sonst wäre S3 gar
> nicht bis zur Rechteprüfung gekommen.

Zwei technische Details:

- `HeadBucket` ist eine HEAD-Anfrage. Deren Antwort hat keinen Inhalt – also auch keinen
  Fehlercode, nur den Status 403. Der Test fragt deshalb mit `ListObjectsV2` (GET), dessen
  Fehlerantwort den genauen Code enthält.
- Jede Antwort, auch eine Fehlerantwort, trägt den HTTP-Kopf `Date` mit der Uhrzeit des
  Servers. Daraus berechnet der Test die Abweichung der eigenen Uhr.

Getestet wird das mit moto in einer besonderen Betriebsart (`set_initial_no_auth_action_count`),
in der moto Signaturen und IAM-Rechte wirklich prüft – siehe
`tests/test_verbindungstest_iam.py`.

> **Übung 7b:** Ein Kollege meldet „403 beim Verbindungstest, Schritt Leserecht“. Liegt es
> am Passwort? (Lösung: Nein. Das Passwort ist richtig, sonst wäre der Test bei
> „Passwort (Secret Key)“ stehen geblieben. Es fehlt das Recht `s3:ListBucket`.)

---

## 8. Testen ohne echten S3-Speicher

Die Tests nutzen **moto**, eine S3-Attrappe, die alle boto3-Aufrufe im Prozess abfängt
(`with mock_aws():` in `tests/conftest.py`). Dadurch laufen alle Tests in Sekunden, ohne
Netzwerk und ohne Zugangsdaten.

Fehlerfälle werden mit einem **Stellvertreter** (Proxy) erzeugt: `StoerClient` reicht alle
Aufrufe über `__getattr__` an den echten Client durch, wirft aber bei ausgewählten Teilen
einen `ClientError`.

```bash
pytest -v                       # alle Tests mit Namen
pytest -k fortgesetzt           # nur Tests mit „fortgesetzt“ im Namen
pytest --cov=s3_uploader        # mit Abdeckung
```

> **Übung 8:** Schreibe einen Test, der prüft, dass eine leere Datei (0 Bytes) korrekt
> hochgeladen wird. Vorlage: `test_alle_dateien_kommen_unverfaelscht_an`.

---

## 8a. Ein Programm für Windows, macOS und Linux

Python läuft überall – aber nicht überall gleich. Drei Stellen in s3-uploader zeigen typische
Unterschiede:

1. **Warten unterbrechen.** `concurrent.futures.as_completed()` wartet ohne Zeitgrenze.
   Unter Windows kann Strg+C ein solches Warten nicht unterbrechen. `_fertige_auftraege`
   in `uploader.py` wartet deshalb höchstens 0,5 s am Stück und gibt Python so die
   Gelegenheit, den Abbruch zu bemerken.
2. **Pfade vergleichen.** Windows unterscheidet nicht zwischen `D:\Daten` und `d:/daten`.
   `os.path.normcase` gleicht das an (unter macOS/Linux ändert es nichts), siehe
   `quellkennung` in `konfiguration.py`.
3. **Die Konsole.** Die klassische Windows-Konsole versteht Steuerzeichen wie `\033[K` erst
   nach einem Systemaufruf (`SetConsoleMode`). `terminal.py` versucht das per `ctypes` und
   überschreibt die Zeile sonst mit Leerzeichen. Die Prüfung `if sys.platform != "win32"`
   sorgt dafür, dass `mypy` den Windows-Teil nur für Windows prüft.

> **Übung 8a:** Führe `mypy --platform win32 src` aus. Was ändert sich gegenüber `mypy src`?
> (Lösung: nichts bei den Ergebnissen – aber jetzt wird der Windows-Zweig in `terminal.py`
> geprüft, vorher der andere.)

---

## 9. Glossar

| Begriff | Bedeutung |
|---|---|
| Bucket | Oberster Behälter in S3 |
| Objekt / Schlüssel | Datei in S3 / ihr vollständiger Name |
| Präfix | Anfang des Schlüssels, wirkt wie ein Ordner |
| Endpunkt | URL des S3-Dienstes |
| Multipart-Upload | Hochladen in nummerierten Teilen |
| UploadId | Kennung eines begonnenen Multipart-Uploads |
| ETag | Vom Server vergebene Kennung eines Teils oder Objekts |
| Content-MD5 | Prüfsumme, mit der der Server die Daten kontrolliert |
| Datenklasse | Klasse für reine Daten, erzeugt mit `@dataclass` |
| Generator | Funktion mit `yield`, liefert Werte nach und nach |
| Future | Platzhalter für das Ergebnis einer Hintergrundaufgabe |
| Lock / Sperre | Verhindert gleichzeitigen Zugriff mehrerer Threads |
| Kontextmanager | Objekt für `with`, räumt garantiert auf |
| Attrappe (Mock) | Nachbildung eines Dienstes für Tests |

## Lösungshinweise

1. `endpoint_url`, `aws_access_key_id`, `aws_secret_access_key`.
2. 21 MiB (200 GiB / 10 000 ≈ 20,48 MiB, auf volle MiB aufgerundet).
3. Die `.tmp`-Datei fehlt in der Zählung.
4. Ausgabe mit Status `erledigt` je Datei.
5. Sie überschreibt `upload_part` und wirft für Teilnummern in `fehlerhafte_teile` einen
   `ClientError`; alle anderen Aufrufe leitet `__getattr__` an den echten Client weiter.
6. Je eine vollständige Zeile in größerem Abstand, ohne Steuerzeichen.
7. `INFO: Setze fort: <schluessel> (N von M Teilen vorhanden)`.
5a. Das Multipart-Objekt hat einen ETag mit Bindestrich und Teilanzahl (`"…-3"`), der
    einfache Upload in der Regel den reinen MD5-Wert der Datei.
8. Leere Datei anlegen, `_lauf(...)` aufrufen, `lies_objekt(...) == b""` prüfen.
