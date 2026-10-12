import pytest

import beets.ui

from beetsplug.userrating import autorate
from beetsplug.userrating.similar import (STRATEGIES, Strategy,
                                          get_similar_items, getSimilarItems)

IDS = ('mb_releasetrackid', 'mb_trackid', 'acoustid_id',
       'acoustid_fingerprint')


def _add(env, title, artist='artist', rating=None, fixture='full', ext='mp3',
         **values):
    values.update({'title': title, 'artist': artist})
    for field in IDS:
        values.setdefault(field, '')
    item = env.add_item(fixture=fixture, ext=ext, **values)
    if rating is not None:
        item['userrating'] = {'djhibee': rating}
        item.store()
    return item


def _rating(env, item, user='djhibee'):
    return (env.reload(item).get('userrating') or {}).get(user)


@pytest.fixture
def answers(monkeypatch):
    queue = []

    def input_(prompt=None):
        if prompt:
            print(prompt)
        assert queue, 'unexpected prompt: {0}'.format(prompt)
        return queue.pop(0)
    monkeypatch.setattr(beets.ui, 'input_', input_)
    return queue


def test_similar_items_strategies_priority(env):
    target = _add(env, 'song', mb_releasetrackid='T', mb_trackid='R',
                  acoustid_id='A', acoustid_fingerprint='F')
    same_track = _add(env, 'other', mb_releasetrackid='T')
    same_recording = _add(env, 'other', mb_trackid='R')
    same_acoustid = _add(env, 'other', acoustid_id='A')
    same_fingerprint = _add(env, 'other', acoustid_fingerprint='F')
    same_title = _add(env, 'SONG')
    _add(env, 'song', artist='someone else')

    found = get_similar_items(env.lib, target)
    assert found.strategy.name == 'mb_releasetrackid'
    assert [i.id for i in found.items] == [same_track.id]

    found = get_similar_items(env.lib, target,
                              strategies=['mb_trackid', 'artist_title'])
    assert [i.id for i in found.items] == [same_recording.id]

    found = get_similar_items(env.lib, target, all_strategies=True)
    assert [(r.strategy.name, [i.id for i in r.items]) for r in found] == [
        ('mb_releasetrackid', [same_track.id]),
        ('mb_trackid', [same_recording.id]),
        ('acoustid_id', [same_acoustid.id]),
        ('acoustid_fingerprint', [same_fingerprint.id]),
        ('artist_title', [same_title.id])]
    assert getSimilarItems is get_similar_items

    # --no-acoustid disables both AcoustID strategies
    from beetsplug.userrating.settings import autorate_strategies
    assert autorate_strategies({'mbtrackid': True, 'acoustid': True}) == [
        'mb_releasetrackid', 'mb_trackid', 'acoustid_id',
        'acoustid_fingerprint', 'artist_title']
    assert 'acoustid_id' not in autorate_strategies({'acoustid': False})


def test_similar_items_filters(env):
    target = _add(env, 'song')
    mp3 = _add(env, 'song')
    flac = _add(env, 'song', fixture='full', ext='flac')
    assert [i.id for i in get_similar_items(
        env.lib, target, format='FLAC').items] == [flac.id]
    assert [i.id for i in get_similar_items(
        env.lib, target, format=lambda f: f == 'MP3').items] == [mp3.id]
    assert [i.id for i in get_similar_items(
        env.lib, target, query='format:MP3').items] == [mp3.id]
    assert [i.id for i in get_similar_items(
        env.lib, target, predicate=lambda i: i.id == flac.id).items] == \
        [flac.id]
    assert get_similar_items(env.lib, target, format='OGG') is None
    # strategies needing missing fields are skipped
    assert get_similar_items(env.lib, target, strategies=['mb_trackid']) \
        is None
    # custom strategy
    custom = Strategy('same_album', 'same album', ('album',))
    assert len(get_similar_items(env.lib, target,
                                 strategies=[custom]).items) == 2
    with pytest.raises(ValueError):
        get_similar_items(env.lib, target, strategies=['unknown'])


def test_bareascii_and_fuzzy_require_plugins(env):
    target = _add(env, 'Tele', artist='Andre')
    accented = _add(env, u'Télé', artist=u'André')
    assert get_similar_items(env.lib, target) is None

    env.setup({'beets_users': ['djhibee']}, plugins=['bareasc'])
    found = get_similar_items(env.lib, target)
    assert found.strategy.name == 'bareascii'
    assert [i.id for i in found.items] == [accented.id]

    typo = _add(env, 'Telle', artist='Andre')
    env.setup({'beets_users': ['djhibee']}, plugins=['fuzzy'])
    found = get_similar_items(env.lib, target, strategies=['fuzzy'])
    # "Telle" is close enough to "Tele", "Télé" is not (no accent folding)
    assert [i.id for i in found.items] == [typo.id]
    assert {s.name for s in STRATEGIES} >= {'bareascii', 'fuzzy'}


def test_proposed_rating():
    class FakeItem(dict):
        pass
    items = [FakeItem(userrating={'a': r}) for r in (3, 5, 5, 3, 2)]
    # ties are broken by the highest rating
    assert autorate.proposed_rating(items, 'a') == 5
    assert autorate.proposed_rating(items, 'b') is None


def test_autorate_pretend(env):
    target = _add(env, 'song')
    _add(env, 'song', rating=6)
    _add(env, 'song', rating=6)
    _add(env, 'song', rating=9)
    out = env.run('autorate', '-p', '-W', 'title:song')
    assert ('  not rated by djhibee; 3 similar items rated by djhibee '
            '(same artist and title):\n    6 (2 items):\n') in out
    assert '    9 (1 item):\n' in out
    assert '  proposed rating: 6\n  (pretend: not rated)' in out
    assert _rating(env, target) is None


def test_autorate_yes_and_options(env):
    target = _add(env, 'song', mb_trackid='R')
    _add(env, 'other', mb_trackid='R', rating=4)
    _add(env, 'song', rating=7)
    unrelated = _add(env, 'nothing')
    env.run('autorate', '-y', '-W', '--no-mbtrackid', 'id:{0}'.format(
        target.id))
    assert _rating(env, target) == 7
    env.run('userrating', '--remove', '-W', 'id:{0}'.format(target.id))
    env.run('autorate', '-y', '-W')
    assert _rating(env, target) == 4
    assert _rating(env, unrelated) is None
    # other user
    env.run('autorate', '-y', '-W', '-u', 'toto')
    assert _rating(env, target, 'toto') is None


def test_autorate_interactive_choices(env, answers):
    first = _add(env, 'song')
    second = _add(env, 'tune')
    similar = [_add(env, 'song', rating=8), _add(env, 'song', rating=6)]
    _add(env, 'tune', rating=2)

    answers.extend(['', 's'])  # accept proposal, skip
    env.run('autorate', '-W')
    assert _rating(env, first) == 8
    assert _rating(env, second) is None

    answers.extend(['10'])  # custom rating
    env.run('autorate', '-W', 'title:tune')
    assert _rating(env, second) == 10

    env.run('userrating', '--remove', '-W', 'id:{0}'.format(first.id))
    answers.extend(['x', ''])  # fix with the proposed rating
    out = env.run('autorate', '-W', 'title:song')
    assert 'Rating of djhibee for this item and its 2 similar items' in out
    assert [_rating(env, i) for i in [first] + similar] == [8, 8, 8]
    assert not answers


def test_autorate_global_review(env, answers):
    first = _add(env, 'song')
    second = _add(env, 'song')
    _add(env, 'song', rating=5)
    answers.extend(['3', ''])
    out = env.run('autorate', '-W', '-g')
    # both proposals are found before the review
    assert out.index('autorate: 2 rating proposals to review') \
        < out.index('Rating of djhibee')
    assert _rating(env, first) == 3
    # proposals are refreshed before review: the second item's similar
    # items now include the first one (3 and 5: tie broken by highest)
    assert 'Rating of djhibee (0-10, Enter for 5)' in out
    assert '    3 (1 item):' in out
    assert _rating(env, second) == 5


def test_autorate_skips_items_rated_in_file(env):
    target = _add(env, 'song', fixture='full-with-wmp-rating')
    _add(env, 'song', rating=2)
    env.run('autorate', '-y', '-W')
    assert _rating(env, target) is None


def test_autorate_import(env, answers):
    env.setup({'beets_users': ['djhibee'],
               'autorate': {'auto': True, 'global_review': True}})
    _add(env, 'song', rating=4)
    imported = _add(env, 'song')

    class Task(object):
        def imported_items(self):
            return [imported]

    class Session(object):
        lib = env.lib

    env.plugin.imported(Session(), Task())
    assert _rating(env, imported) is None
    answers.append('')
    env.plugin.on_import_end(env.lib, [])
    assert _rating(env, imported) == 4


def test_autorate_import_quiet(env):
    env.setup({'beets_users': ['djhibee'], 'autorate': {'auto': True}})
    beets.config['import']['quiet'] = True
    _add(env, 'song', rating=4)
    imported = _add(env, 'song')

    class Task(object):
        def imported_items(self):
            return [imported]

    class Session(object):
        lib = env.lib

    env.plugin.imported(Session(), Task())
    assert _rating(env, imported) is None


def test_autorate_config_validation(env):
    import beets.plugins
    env.setup({'autorate': {'user': 'bad user'}})
    assert beets.plugins.find_plugins() == []
