from pathlib import Path

import pytest

from s3_uploader.dateisuche import Datei
from s3_uploader.fehler import KonfigurationsFehler
from s3_uploader.zustand import Zustand


def _datei(groesse: int = 10, mtime: int = 1) -> Datei:
    return Datei(Path("/x"), "k", groesse, mtime)


def test_erledigt_nur_bei_unveraenderter_datei(tmp_path: Path) -> None:
    with Zustand(tmp_path / "z.sqlite") as z:
        z.markiere_erledigt(_datei(), "etag")
        assert z.ist_erledigt(_datei())
        assert not z.ist_erledigt(_datei(groesse=11))
        assert z.anzahl_erledigt() == 1


def test_multipart_stand_ueberlebt_neustart(tmp_path: Path) -> None:
    pfad = tmp_path / "z.sqlite"
    with Zustand(pfad) as z:
        z.starte_multipart(_datei(), "upload-1", 5)
        z.teil_erledigt("k", 1, "e1")
    with Zustand(pfad) as z:
        stand = z.multipart_stand(_datei())
        assert stand is not None
        assert (stand.upload_id, stand.teilgroesse, stand.teile) == ("upload-1", 5, {1: "e1"})


def test_veraenderte_datei_liefert_veralteten_upload(tmp_path: Path) -> None:
    with Zustand(tmp_path / "z.sqlite") as z:
        z.starte_multipart(_datei(), "upload-1", 5)
        assert z.multipart_stand(_datei(mtime=2)) is None
        assert z.veralteter_upload(_datei(mtime=2)) == "upload-1"
        z.verwerfe("k")
        assert z.veralteter_upload(_datei(mtime=2)) is None


def test_kontext_schuetzt_vor_verwechslung(tmp_path: Path) -> None:
    pfad = tmp_path / "z.sqlite"
    with Zustand(pfad) as z:
        z.pruefe_kontext("ziel-a")
        z.pruefe_kontext("ziel-a")
        with pytest.raises(KonfigurationsFehler):
            z.pruefe_kontext("ziel-b")
