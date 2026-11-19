import pytest

from s3_uploader.fehler import KonfigurationsFehler, UploadFehler
from s3_uploader.planung import (
    MAX_TEILE,
    MIB,
    MIN_TEILGROESSE,
    berechne_teilgroesse,
    braucht_multipart,
    pruefe_schwelle,
    zerlege,
)


def test_wunsch_wird_uebernommen_wenn_zulaessig() -> None:
    assert berechne_teilgroesse(100 * MIB, 16 * MIB) == 16 * MIB


def test_teilgroesse_nie_unter_5_mib() -> None:
    assert berechne_teilgroesse(100 * MIB, 1 * MIB) == MIN_TEILGROESSE


def test_teilgroesse_waechst_bei_sehr_grossen_dateien() -> None:
    groesse = 1024**4  # 1 TiB
    teil = berechne_teilgroesse(groesse, 16 * MIB)
    assert teil % MIB == 0
    assert -(-groesse // teil) <= MAX_TEILE


def test_dateien_ueber_5_tib_werden_abgelehnt() -> None:
    with pytest.raises(UploadFehler):
        berechne_teilgroesse(5 * 1024**4 + 1, 16 * MIB)


def test_zerlegen_deckt_datei_luecklos_ab() -> None:
    teile = zerlege(12 * MIB + 3, 5 * MIB)
    assert [t.nummer for t in teile] == [1, 2, 3]
    assert sum(t.laenge for t in teile) == 12 * MIB + 3
    assert teile[2].start == 10 * MIB and teile[2].laenge == 2 * MIB + 3


def test_multipart_erst_oberhalb_der_schwelle() -> None:
    assert not braucht_multipart(64 * MIB, 64 * MIB)
    assert braucht_multipart(64 * MIB + 1, 64 * MIB)


@pytest.mark.parametrize("schwelle", [1 * MIB, 6 * 1024**3])
def test_unzulaessige_schwelle(schwelle: int) -> None:
    with pytest.raises(KonfigurationsFehler):
        pruefe_schwelle(schwelle)
