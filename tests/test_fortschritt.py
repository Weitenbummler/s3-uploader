import io

from s3_uploader.fortschritt import (
    Anzeige,
    Fortschritt,
    formatiere_bytes,
    formatiere_dauer,
)


def test_bytes_lesbar() -> None:
    assert formatiere_bytes(512) == "512 B"
    assert formatiere_bytes(1536) == "1,5 KiB"
    assert formatiere_bytes(3 * 1024**3) == "3,0 GiB"


def test_dauer() -> None:
    assert formatiere_dauer(3723) == "1:02:03"
    assert formatiere_dauer(None) == "–:––:––"


def test_zaehlung_und_prozent() -> None:
    f = Fortschritt()
    f.beginne(dateien=3, bytes_gesamt=300)
    f.datei_uebersprungen(100)
    f.bytes_uebertragen(50)
    f.datei_fehlgeschlagen(100, bereits_gezaehlt=50)
    stand = f.momentaufnahme()
    assert stand.dateien_bearbeitet == 2
    assert stand.prozent == 200 / 3
    assert stand.bytes_uebertragen == 50  # übersprungene zählen nicht zur Rate
    assert "Fehler 1" in stand.als_zeile()


def test_anzeige_schreibt_zeilen_ohne_terminal() -> None:
    f = Fortschritt()
    f.beginne(1, 10)
    puffer = io.StringIO()
    with Anzeige(f, puffer, intervall_protokoll=0.01):
        f.bytes_uebertragen(10)
    assert "100,0 %" in puffer.getvalue().splitlines()[-1]
