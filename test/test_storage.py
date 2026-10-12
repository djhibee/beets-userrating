import shutil

import mutagen
import pytest
from mutagen.id3 import POPM
from mutagen.mp4 import MP4, MP4Tags

from beetsplug.userrating import storage


def _popm(path):
    return {frame.email: frame.rating
            for frame in mutagen.File(path).tags.getall('POPM')}


def test_mp3_read_external_rating(copy_rsrc):
    path = copy_rsrc('full-with-wmp-rating.mp3')
    found = storage.read_file(path)
    assert found.beets == {}
    assert found.players == {'WMP': 8}


def test_mp3_write_keeps_other_popm_frames(copy_rsrc):
    path = copy_rsrc('full-with-wmp-rating.mp3')
    storage.write_file(path, {'djhibee': 0, 'toto': 10}, 'djhibee')
    frames = _popm(path)
    assert frames == {'Windows Media Player 9 Series': 196,
                      'beets-djhibee': 0, 'beets-toto': 255}
    found = storage.read_file(path, ['djhibee', 'toto'])
    assert found.beets == {'djhibee': 0, 'toto': 10}

    # removed users are deleted from the file, other frames are kept
    storage.write_file(path, {'toto': 4}, 'djhibee')
    assert _popm(path) == {'Windows Media Player 9 Series': 196,
                           'beets-toto': 102}


def test_mp3_preserves_play_count(copy_rsrc):
    path = copy_rsrc('full.mp3')
    mf = mutagen.File(path)
    mf.tags.add(POPM(email='beets-toto', rating=10, count=42))
    mf.save()
    storage.write_file(path, {'toto': 5}, 'djhibee')
    frame = mutagen.File(path).tags.getall('POPM:beets-toto')[0]
    assert frame.count == 42
    assert frame.rating == 128


def test_mp3_sync_external_players(copy_rsrc):
    path = copy_rsrc('full-with-wmp-rating.mp3')
    storage.write_file(path, {'djhibee': 4, 'toto': 2}, 'djhibee',
                       sync_players=['WMP', 'Banshee'])
    assert _popm(path) == {'Windows Media Player 9 Series': 64,
                           'Banshee': 64,
                           'beets-djhibee': 102, 'beets-toto': 51}
    # unrated default user: synchronized players' ratings are removed
    storage.write_file(path, {'toto': 2}, 'djhibee',
                       sync_players=['WMP', 'Banshee'])
    assert _popm(path) == {'beets-toto': 51}


def test_flac_restores_user_case(copy_rsrc):
    path = copy_rsrc('full.flac')
    storage.write_file(path, {'DjHibee': 7}, 'DjHibee',
                       sync_players=['Quodlibet'])
    tags = mutagen.File(path).tags
    assert tags['RATING:beets-DjHibee'] == ['7']
    assert tags['rating:quodlibet@lists.sacredchao.net'] == ['0.7']
    found = storage.read_file(path, ['DjHibee'])
    assert found.beets == {'DjHibee': 7}
    assert found.players == {'Quodlibet': 7}
    assert storage.read_file(path).beets == {'djhibee': 7}


def test_ogg_and_wma_roundtrip(copy_rsrc):
    for name in ('full.ogg', 'full.wma'):
        path = copy_rsrc(name)
        storage.write_file(path, {'toto': 0, 'djhibee': 9}, 'djhibee',
                           sync_players=['WMP'])
        found = storage.read_file(path, ['toto', 'djhibee'])
        assert found.beets == {'toto': 0, 'djhibee': 9}, name
        storage.write_file(path, {}, 'djhibee')
        assert storage.read_file(path).beets == {}, name
    tags = mutagen.File(path).tags
    assert 'WM/SharedUserRating' in tags.keys()


def test_wma_sync_wmp():
    from mutagen.asf import ASFTags
    from beetsplug.userrating.scalers import PLAYERS
    tags = ASFTags()
    assert storage.write_player_tag(tags, PLAYERS['WMP'], 10)
    assert storage.read_tags(tags)[1] == {'WMP': 10}


def test_mp4_tags_roundtrip():
    tags = MP4Tags()
    assert storage.write_user_tags(tags, {'DjHibee': 6, 'toto': 0})
    assert sorted(tags.keys()) == [
        '----:com.apple.iTunes:RATING:beets-DjHibee',
        '----:com.apple.iTunes:RATING:beets-toto']
    assert storage.read_tags(tags) == ({'DjHibee': 6, 'toto': 0}, {})
    storage.write_user_tags(tags, {'toto': 1})
    assert storage.read_tags(tags) == ({'toto': 1}, {})


def test_m4a_file_roundtrip(copy_rsrc):
    path = copy_rsrc('full.m4a')
    storage.write_file(path, {'DjHibee': 6, 'toto': 0}, 'DjHibee',
                       comments=storage.COMMENTS_YES)
    found = storage.read_file(path)
    assert found.beets == {'DjHibee': 6, 'toto': 0}
    assert found.comment == {'DjHibee': 6, 'toto': 0}
    assert '----:com.apple.iTunes:RATING:beets-toto' in MP4(path).tags


def test_mp4_file_not_supported(tmp_path, copy_rsrc):
    path = str(tmp_path / 'video.mp4')
    shutil.copy(copy_rsrc('full.m4a'), path)
    with pytest.raises(storage.UnsupportedFormatError):
        storage.write_file(path, {'toto': 3}, 'toto')
    with pytest.raises(storage.UnsupportedFormatError):
        storage.read_file(path)
    assert not any(key.startswith('----:') for key in MP4(path).tags)


def test_zero_rating_vs_unrated(copy_rsrc):
    for name in ('full.mp3', 'full.flac', 'full.m4a'):
        path = copy_rsrc(name)
        storage.write_file(path, {'toto': 0}, 'toto')
        assert storage.read_file(path, ['toto']).beets == {'toto': 0}, name
        # unrated: no tag at all
        storage.write_file(path, {}, 'toto')
        assert storage.read_file(path, ['toto']).beets == {}, name
        tags = mutagen.File(path).tags
        assert not any('beets-' in str(key) for key in tags.keys()), name


def test_external_zero_rating(copy_rsrc):
    path = copy_rsrc('full.mp3')
    tags = mutagen.File(path)
    tags.tags.add(POPM(email='Banshee', rating=0))
    tags.save()
    # POPM 0 means unrated for external players
    assert storage.read_file(path).players == {}

    from mutagen.flac import FLAC
    path = copy_rsrc('full.flac')
    flac = FLAC(path)
    flac['rating:quodlibet@lists.sacredchao.net'] = ['0.0']
    flac.save()
    # Quod Libet: 0.0 is a 0 rating (unrated tracks have no tag)
    assert storage.read_file(path).players == {'Quodlibet': 0}


def test_update_comment():
    assert storage.update_comment(None, {'toto': 3}) == \
        '[beets-userrating: toto=3]'
    comment = storage.update_comment('my comment', {'toto': 3, 'a': 0})
    assert comment == 'my comment\n[beets-userrating: a=0, toto=3]'
    comment = storage.update_comment(comment, {'toto': 5})
    assert comment == 'my comment\n[beets-userrating: toto=5]'
    assert storage.read_comment_ratings(comment) == {'toto': 5}
    assert storage.update_comment(comment, {}) == 'my comment'
    middle = 'before [beets-userrating: toto=1] after'
    assert storage.update_comment(middle, {'toto': 2}) == \
        'before [beets-userrating: toto=2] after'
    assert storage.update_comment(middle, {}) == 'before after'


def test_write_in_comments(copy_rsrc):
    path = copy_rsrc('full.mp3')
    storage.write_file(path, {'toto': 3}, 'djhibee',
                       comments=storage.COMMENTS_YES)
    found = storage.read_file(path, ['toto'])
    assert found.beets == {'toto': 3}
    assert found.comment == {'toto': 3}

    path = copy_rsrc('full.flac')
    storage.write_file(path, {'toto': 3}, 'djhibee',
                       comments=storage.COMMENTS_ONLY)
    found = storage.read_file(path, ['toto'])
    assert found.beets == {}
    assert found.comment == {'toto': 3}
    assert found.users() == {'toto': 3}
    comment = mutagen.File(path).tags['comment'][0]
    assert comment == 'the comments\n[beets-userrating: toto=3]'
    storage.write_file(path, {'toto': 4}, 'djhibee',
                       comments=storage.COMMENTS_ONLY)
    comment = mutagen.File(path).tags['comment'][0]
    assert comment == 'the comments\n[beets-userrating: toto=4]'
