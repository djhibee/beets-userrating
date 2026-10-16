import logging
import os
from types import SimpleNamespace

from beets import config
import beets.plugins
import mutagen
import pytest

from beetsplug.userrating.command import pair_users_ratings
from beetsplug.userrating.compat import UserError
from beetsplug.userrating.ratings import UserRatings


def _ratings(env):
    return {item.title: dict(item.get('userrating') or {})
            for item in env.lib.items()}


def _popm(item):
    return {frame.email: frame.rating
            for frame in mutagen.File(item.path).tags.getall('POPM')}


@pytest.mark.parametrize('users, ratings, expected', [
    ([], [5], [('djhibee', 5)]),
    (['a'], [], [('a', None)]),
    (['a', 'b'], [5, 4], [('a', 5), ('b', 4)]),
    (['a', 'b', 'c'], [2, 1], [('a', 2), ('b', 1), ('c', 1)]),
    (['a'], [2, 1], [('a', 2), ('a', 1)]),
])
def test_pair_users_ratings(users, ratings, expected):
    assert pair_users_ratings(users, ratings, 'djhibee') == expected


def test_default_user_from_beets_users(env):
    assert env.plugin.settings.default_user == 'djhibee'
    assert UserRatings.default_user == 'djhibee'
    env.setup({'beets_users': ['a', 'b'], 'default_user': 'b'})
    assert env.plugin.settings.default_user == 'b'


def test_invalid_config(env):
    # beets logs the error and does not load the plugin
    env.setup({'write_in_comments': 'maybe'})
    assert list(beets.plugins.find_plugins()) == []


def test_modify_with_pairing(env):
    env.add_item(title='one')
    env.add_item(title='two')
    env.run('userrating', '--modify', '-u', 'djhibee', '-r', '5',
            '-u', 'toto', '-r', '4', 'title:one')
    env.run('userrating', '-m', '-u', 'djhibee', '-u', 'toto', '-u', 'titi',
            '-r', '2', '-r', '1', 'title:two')
    assert _ratings(env) == {
        'one': {'djhibee': 5, 'toto': 4},
        'two': {'djhibee': 2, 'toto': 1, 'titi': 1},
    }


def test_modify_default_user_and_force(env):
    env.add_item(title='one')
    env.run('userrating', '--modify', '--rating', '5')
    assert _ratings(env) == {'one': {'djhibee': 5}}
    # already rated: skipped unless forced
    env.run('userrating', '--modify', '--rating', '3')
    assert _ratings(env) == {'one': {'djhibee': 5}}
    env.run('userrating', '--modify', '--rating', '3', '-f')
    assert _ratings(env) == {'one': {'djhibee': 3}}
    env.setup({'beets_users': ['djhibee'], 'force': True})
    env.run('userrating', '--modify', '--rating', '0')
    assert _ratings(env) == {'one': {'djhibee': 0}}
    env.run('userrating', '--modify', '--rating', '1', '--no-force')
    assert _ratings(env) == {'one': {'djhibee': 0}}


def test_modify_prints_changes(env):
    env.add_item(title='one', artist='a', album='b')
    out = env.run('userrating', '-m', '-u', 'toto', '-r', '7')
    assert out == 'a - b - one\n  userrating[toto]: none -> 7\n'


def test_delete_and_remove(env):
    env.add_item(title='one')
    env.run('userrating', '-m', '-u', 'djhibee', '-r', '5', '-u', 'toto',
            '-r', '4', '-u', 'titi', '-r', '0')
    env.run('userrating', '--modify', '-u', 'djhibee', '-d')
    assert _ratings(env) == {'one': {'toto': 4, 'titi': 0}}
    env.run('userrating', '--remove', '-u', 'toto')
    assert _ratings(env) == {'one': {'titi': 0}}
    env.run('userrating', '-m', '-u', 'titi', '-r', 'none')
    assert _ratings(env) == {'one': {}}


@pytest.mark.parametrize('args', [
    ('--modify',),
    ('--modify', '-r', '3', '-d'),
    ('--remove', '-r', '3'),
    ('--list', '--modify', '-r', '3'),
    ('--modify', '-r', '11'),
    ('--modify', '-u', 'bad:user', '-r', '1'),
    ('--list', '-d'),
])
def test_invalid_arguments(env, args):
    env.add_item(title='one')
    with pytest.raises(UserError):
        env.run('userrating', *args)


def test_list(env):
    env.add_item(title='one', artist='a', album='b')
    env.add_item(title='two', artist='a', album='b')
    env.add_item(title='three', artist='a', album='b')
    env.run('userrating', '-m', '-u', 'djhibee', '-r', '5', '-u', 'toto',
            '-r', '4', 'title:one')
    env.run('userrating', '-m', '-u', 'djhibee', '-r', '5', 'title:two')
    assert env.run('userrating', '--list') == (
        'a - b - one: djhibee:5, toto:4\n'
        'a - b - two: djhibee:5\n')
    assert env.run('userrating') == env.run('userrating', '--list')
    assert env.run('userrating', '--list', '-u', 'toto') == \
        'a - b - one: toto:4\n'
    assert env.run('userrating', '--list', '-u', 'djhibee', '-r', '5') == (
        'a - b - one: djhibee:5\n'
        'a - b - two: djhibee:5\n')
    assert env.run('userrating', '--list', '-r', '5', 'title:two') == \
        'a - b - two: djhibee:5\n'
    assert env.run('userrating', '-l', '-u', 'toto', '-r', '5') == ''


def test_queries(env):
    env.add_item(title='one')
    env.add_item(title='two')
    env.add_item(title='three')
    env.run('userrating', '-m', '-u', 'user1', '-r', '3', '-u', 'user2',
            '-r', '4', 'title:one')
    env.run('userrating', '-m', '-u', 'user1', '-r', '3', '-u', 'djhibee',
            '-r', '4', 'title:two')

    def titles(*query):
        return sorted(item.title for item in env.lib.items(list(query)))

    assert titles('userrating:user1: 3') == ['one', 'two']
    assert titles('userrating:user1:3') == ['one', 'two']
    assert titles("userrating:{'user1':3}") == ['one', 'two']
    assert titles("userrating:{'user2':4,'user1': 3}") == ['one']
    assert titles('userrating:4') == ['two']
    assert titles('userrating:') == ['one', 'two']
    assert titles('userrating:user2:none') == ['three', 'two']
    assert titles('^userrating:') == ['three']
    assert titles('userrating:3..4') == ['two']
    # sorting by default user rating does not crash on unrated items
    assert [i.title for i in env.lib.items('userrating+')][-1] == 'two'


def test_templates(env):
    env.add_item(title='one')
    env.add_item(title='two')
    env.run('userrating', '-m', '-u', 'djhibee', '-r', '0', '-u', 'toto',
            '-r', '4', '-u', 'newuser', '-r', '9', 'title:one')
    out = env.run('ls', '-f',
                  '$title|$userrating|$userratings|${userrating[toto]}|'
                  '${userrating[newuser]}')
    assert out == ('one|0|djhibee:0, newuser:9, toto:4|4|9\n'
                   'two||||\n')


def test_beet_modify(env):
    env.add_item(title='one')
    env.run('modify', '-y', "userrating={'user2':4,'user1': 3}")
    assert _ratings(env) == {'one': {'user1': 3, 'user2': 4}}
    env.run('modify', '-y', 'userrating=7')
    assert _ratings(env) == {'one': {'djhibee': 7}}
    env.run('remove', '-f', 'userrating:7')
    assert list(env.lib.items()) == []


def test_write_to_file_on_modify(env):
    item = env.add_item(title='one', fixture='full-with-wmp-rating')
    env.run('userrating', '-m', '-u', 'toto', '-r', '10', '-r', '2', '-u',
            'djhibee')
    assert _popm(env.reload(item)) == {
        'Windows Media Player 9 Series': 196,
        'beets-toto': 255, 'beets-djhibee': 51}
    env.run('userrating', '--remove', '-u', 'toto', '--nowrite')
    assert 'beets-toto' in _popm(env.reload(item))
    env.run('write')
    assert _popm(env.reload(item)) == {
        'Windows Media Player 9 Series': 196, 'beets-djhibee': 51}


def test_write_disabled_by_plugin_config(env):
    env.setup({'beets_users': ['djhibee'], 'write': False})
    item = env.add_item(title='one')
    env.run('userrating', '-m', '-r', '2')
    assert _popm(env.reload(item)) == {}
    env.run('modify', '-y', 'userrating=3')
    assert _popm(env.reload(item)) == {}
    env.run('userrating', '-m', '-r', '4', '-f', '-w')
    assert _popm(env.reload(item)) == {'beets-djhibee': 102}


def test_sync_external_and_comments(env):
    env.setup({'beets_users': ['djhibee'],
               'sync_external_ratings': 'all',
               'external_music_players': ['WMP', 'Banshee'],
               'write_in_comments': 'yes'})
    item = env.add_item(title='one', fixture='full-with-wmp-rating')
    env.run('userrating', '-m', '-r', '10', '-u', 'toto', '-r', '4',
            '-u', 'djhibee')
    assert _popm(env.reload(item)) == {
        'Windows Media Player 9 Series': 64, 'Banshee': 64,
        'beets-toto': 255, 'beets-djhibee': 102}
    comments = mutagen.File(item.path).tags.getall('COMM')
    assert any('[beets-userrating: djhibee=4, toto=10]' in text
               for frame in comments for text in frame.text)


def test_import_from_file(env):
    item = env.add_item(title='one', fixture='full-with-wmp-rating')
    other = env.add_item(title='two', ext='flac')
    assert 'userrating' not in item._values_flex
    env.run('userrating', '--import', '--nowrite')
    assert _ratings(env) == {'one': {'djhibee': 8}, 'two': {}}
    assert 'userrating' not in env.reload(other)._values_flex

    # beets users' ratings in files are imported; existing ratings are
    # kept unless forced
    from beetsplug.userrating import storage
    storage.write_file(item.path, {'djhibee': 1, 'Toto': 6}, 'djhibee')
    env.run('userrating', '--import', '--nowrite')
    assert _ratings(env)['one'] == {'djhibee': 8, 'toto': 6}
    env.run('userrating', '--import', '--force')
    assert _ratings(env)['one'] == {'djhibee': 1, 'toto': 6}


def test_import_external_players_priority(env, copy_rsrc):
    item = env.add_item(title='one', fixture='full-with-wmp-rating')
    mf = mutagen.File(item.path)
    mf.tags.add(mutagen.id3.POPM(email='Banshee', rating=64))
    mf.save()
    env.run('userrating', '--import', '-W')
    assert _ratings(env)['one'] == {'djhibee': 4}  # Banshee first
    env.setup({'beets_users': ['djhibee'],
               'external_music_players': ['WMP', 'Banshee']})
    env.run('userrating', '--import', '-f')
    assert _ratings(env)['one'] == {'djhibee': 8}
    env.setup({'beets_users': ['djhibee'], 'external_music_players': []})
    env.run('userrating', '--remove')
    env.run('userrating', '--import', '-W')
    assert _ratings(env)['one'] == {}


def test_import_external_zero_is_unrated(env):
    env.setup({'beets_users': ['djhibee'],
               'external_music_players': ['Quodlibet', 'Banshee'],
               'sync_external_ratings': 'all'})
    item = env.add_item(title='one', ext='flac')
    flac = mutagen.File(item.path)
    flac['rating:quodlibet@lists.sacredchao.net'] = ['0.0']
    flac.save()
    env.run('userrating', '--import')
    assert _ratings(env)['one'] == {}
    other = env.add_item(title='two')
    mf = mutagen.File(other.path)
    mf.tags.add(mutagen.id3.POPM(email='Banshee', rating=0))
    mf.save()
    env.run('userrating', '--import')
    assert _ratings(env)['two'] == {}
    # unrated items are not synchronized with external players: their
    # tags are left as-is and no tag is created
    env.run('write', '-f')
    assert _popm(env.reload(other)) == {'Banshee': 0}
    tags = mutagen.File(item.path)
    assert tags['rating:quodlibet@lists.sacredchao.net'] == ['0.0']
    assert not any('beets-' in key.lower() for key in tags.keys())


@pytest.mark.parametrize('verbosity', [0, 1, 3])
def test_import_stage(env, verbosity):
    config['verbose'] = verbosity
    original = env.add_item(title='one', ext='flac')
    item = env.add_item(title='one', fixture='full-with-wmp-rating')
    beets.plugins.send('library_opened', lib=env.lib)

    class Task(object):
        def imported_items(self):
            return [item]

    env.plugin.get_import_stages()[0](SimpleNamespace(lib=env.lib), Task())
    assert env.reload(item)['userrating'] == {'djhibee': 8}
    assert 'userrating' not in env.reload(original)._values_flex
    assert _cached_users(env) == ['djhibee']
    assert env.plugin._log.level == logging.NOTSET


@pytest.mark.parametrize('verbosity', [0, 1, 3])
@pytest.mark.parametrize('raises', [False, True])
def test_nested_callback_log_levels(env, verbosity, raises):
    config['verbose'] = verbosity
    plugin = env.plugin
    outer_level = max(logging.DEBUG, logging.WARNING - 10 * verbosity)
    inner_level = max(logging.DEBUG, logging.ERROR - 10 * verbosity)
    env.monkeypatch.setattr(plugin._log, 'level', logging.INFO)

    def inner(value):
        assert plugin._log.level == inner_level
        if raises:
            raise ValueError('callback failed')
        return value

    wrapped_inner = plugin._set_log_level_and_params(logging.ERROR, inner)

    def outer():
        assert plugin._log.level == outer_level
        try:
            return wrapped_inner(value=8, future_event_argument=True)
        finally:
            assert plugin._log.level == outer_level

    wrapped_outer = plugin._set_log_level_and_params(logging.WARNING, outer)
    assert wrapped_outer.__name__ == outer.__name__
    if raises:
        with pytest.raises(ValueError, match='callback failed'):
            wrapped_outer()
    else:
        assert wrapped_outer() == 8
    assert plugin._log.level == logging.INFO


def test_callback_accepts_extra_keyword_arguments(env):
    def callback(**kwargs):
        return kwargs

    wrapped = env.plugin._set_log_level_and_params(logging.WARNING, callback)
    assert wrapped(future_event_argument=True) == {
        'future_event_argument': True}
    assert env.plugin._log.level == logging.NOTSET


def test_auto_disabled(env):
    env.setup({'auto': False})
    assert env.plugin.import_stages == []


def _cached_users(env):
    with env.lib.transaction() as tx:
        return sorted(row[0] for row in
                      tx.query('SELECT user FROM userrating_users'))


def test_users_cache(env):
    env.add_item(title='one', userrating=UserRatings({'scanned': 3}))
    # The first run scans the library and creates the cache.
    env.run('ls', '-f', '${userrating[scanned]}')
    assert _cached_users(env) == ['scanned']

    # Stored ratings update the cache.
    env.run('userrating', '-m', '-u', 'newuser', '-r', '5')
    assert _cached_users(env) == ['newuser', 'scanned']
    env.run('modify', '-y', "userrating={'other':1}")
    assert _cached_users(env) == ['newuser', 'other', 'scanned']

    # Later runs only read the cache instead of scanning the library.
    with env.lib.transaction() as tx:
        tx.mutate('UPDATE item_attributes SET value = ? WHERE key = ?',
                  ('{"hidden": 1}', 'userrating'))
    env.setup({'beets_users': ['djhibee', 'toto']})
    out = env.run('ls', '-f', '${userrating[other]}|${userrating[hidden]}')
    assert out == '|${userrating[hidden]}\n'


def _mp4_ratings(path):
    tags = mutagen.File(path).tags
    return {key: bytes(tags[key][0]) for key in tags.keys()
            if key.startswith('----:')}


def test_m4a_supported_mp4_skipped(env):
    m4a = env.add_item(title='audio', fixture='full', ext='m4a')
    env.run('userrating', '-m', '-u', 'toto', '-r', '7', 'title:audio')
    assert _mp4_ratings(env.reload(m4a).path) == {
        '----:com.apple.iTunes:RATING:beets-toto': b'7'}

    mp4 = env.add_item(title='video', fixture='full', ext='m4a')
    mp4_path = mp4.path[:-len(b'.m4a')] + b'.mp4'
    os.rename(mp4.path, mp4_path)
    mp4.path = mp4_path
    mp4.store()
    env.run('userrating', '-m', '-u', 'toto', '-r', '5', 'title:video')
    env.run('userrating', '--import', '-f', 'title:video')
    assert _mp4_ratings(mp4_path) == {}
    assert env.reload(mp4)['userrating'] == {'toto': 5}


def test_unrated_has_no_stored_value(env):
    item = env.add_item(title='one')
    env.run('userrating', '-m', '-u', 'toto', '-r', '0')
    assert env.reload(item)['userrating'] == {'toto': 0}
    assert _popm(env.reload(item)) == {'beets-toto': 0}
    env.run('userrating', '--remove', '-u', 'toto')
    assert 'userrating' not in env.reload(item)._values_flex
    with env.lib.transaction() as tx:
        assert tx.query('SELECT * FROM item_attributes '
                        "WHERE key = 'userrating'") == []
    assert _popm(env.reload(item)) == {}
