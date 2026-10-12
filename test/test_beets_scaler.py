from beetsplug.userrating.scalers import (
    AsfWindowsMediaPlayerScaler, Mp3BeetsScaler, VorbisQuodlibetScaler,
    find_player)


def test_beets_scaler_roundtrip_keeps_zero_distinct_from_unrated():
    scaler = Mp3BeetsScaler()
    # POPM 0 means unrated: a 0 rating is stored as 1
    assert scaler.unscale(0) == 1
    for rating in range(0, 11):
        assert scaler.scale(scaler.unscale(rating)) == rating
    assert scaler.unscale(10) == 255


def test_beets_scaler_email():
    assert Mp3BeetsScaler('djhibee').name == 'beets-djhibee'


def test_quodlibet_vorbis_scaler():
    scaler = VorbisQuodlibetScaler()
    assert scaler.scale('0.8') == 8
    assert scaler.unscale(5) == '0.5'


def test_asf_wmp_scaler():
    scaler = AsfWindowsMediaPlayerScaler()
    assert scaler.scale(99) == 10
    assert scaler.scale(50) == 6
    assert scaler.unscale(8) == 75


def test_find_player_is_case_insensitive():
    assert find_player('wmp').name == 'WMP'
    assert find_player('unknown') is None
