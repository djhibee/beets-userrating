import pytest

from beets import config, plugins, ui
from beetsplug.similarity import SimilarityStore
from beetsplug.userrating import autorate
from beetsplug.userrating.compat import UserError
from beetsplug.userrating.settings import Settings


@pytest.fixture
def scored_env(env):
    env.setup({
        'beets_users': ['djhibee'],
        'autorate': {'strong_rec_thresh': 0.04},
    }, plugins=['similarity'])
    return env


def add(env, title, rating=None, user='djhibee', **values):
    item = env.add_item(title=title, artist='artist', **values)
    if rating is not None:
        item['userrating'] = {user: rating}
        item.store()
    return item


def rating(env, item):
    return (env.reload(item).get('userrating') or {}).get('djhibee')


def run(env, target, *options):
    return env.run('autorate', '-W', *options, 'id:{}'.format(target.id))


def configure(env, **options):
    for key, value in options.items():
        env.plugin.config['autorate'][key] = value
    env.plugin.settings = Settings(env.plugin.config, env.plugin._log)


@pytest.fixture
def no_prompt(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('unexpected interactive prompt')
    monkeypatch.setattr(ui, 'input_options', unexpected)


def test_default_and_missing_plugin(env):
    assert env.plugin.settings.autorate_algorithm == 'similarity_score'
    target = add(env, 'song')
    with pytest.raises(UserError, match='requires the similarity plugin'):
        run(env, target, '-p')
    add(env, 'song', rating=5)
    run(env, target, '--algorithm', 'legacy', '-y')
    assert rating(env, target) == 5


def test_scores_sorted_filtered_and_inclusive(scored_env):
    env = scored_env
    target = add(env, 'target')
    far = add(env, 'far', rating=9)
    close = add(env, 'close', rating=4)
    tied = add(env, 'tied', rating=5)
    excluded = add(env, 'excluded', rating=8)
    unrated = add(env, 'unrated')
    other_user = add(env, 'other user', rating=10, user='toto')
    store = SimilarityStore(env.lib)
    for item, score in [(far, .8), (close, .95), (tied, .95),
                        (excluded, .79), (unrated, 1), (other_user, 1)]:
        store.put(target.id, item.id, score)
    out = run(env, target, '-p')
    assert out.index('close') < out.index('tied') < out.index('far')
    assert 'distance 0.050000 (similarity 0.950000)' in out
    assert 'distance 0.200000 (similarity 0.800000)' in out
    assert 'excluded' not in out
    assert 'unrated' not in out
    assert 'other user' not in out
    assert rating(env, target) is None
    out = run(env, target, '-p', '--min-threshold', '.95')
    assert 'far' not in out
    assert '2 similar items' in out


def test_config_threshold(scored_env):
    env = scored_env
    configure(env, min_threshold=.9)
    target = add(env, 'target')
    source = add(env, 'source', rating=7)
    SimilarityStore(env.lib).put(target.id, source.id, .85)
    out = run(env, target, '-p')
    assert 'no similar items' in out
    assert '1 similar item' in run(env, target, '-p', '--min-threshold', '.8')


@pytest.mark.parametrize('quiet', [False, True])
def test_strong_autoaccept(scored_env, no_prompt, quiet):
    env = scored_env
    target = add(env, 'target')
    source = add(env, 'source', rating=0)
    SimilarityStore(env.lib).put(target.id, source.id, .99)
    run(env, target, *(['-q'] if quiet else []))
    assert rating(env, target) == 0


@pytest.mark.parametrize('mode', ['local', 'plugin', 'global'])
def test_timid_honors_all_sources(scored_env, monkeypatch, mode):
    env = scored_env
    target = add(env, 'target')
    source = add(env, 'source', rating=6)
    SimilarityStore(env.lib).put(target.id, source.id, 1)
    if mode == 'global':
        config['import']['timid'] = True
    elif mode == 'plugin':
        configure(env, timid=True)
    prompts = []
    monkeypatch.setattr(ui, 'input_options',
                        lambda *a, **k: prompts.append(k) or 3)
    run(env, target, *(['-t'] if mode == 'local' else []))
    assert len(prompts) == 1
    assert rating(env, target) == 3


@pytest.mark.parametrize('mode', ['local', 'plugin', 'global'])
def test_quiet_logs_weak_match(scored_env, no_prompt, monkeypatch, mode):
    env = scored_env
    target = add(env, 'target')
    source = add(env, 'source', rating=6)
    SimilarityStore(env.lib).put(target.id, source.id, .9)
    if mode == 'global':
        config['import']['quiet'] = True
    elif mode == 'plugin':
        configure(env, quiet=True)
    calls = []
    monkeypatch.setattr(env.plugin._log, 'info',
                        lambda *args: calls.append(args))
    run(env, target, *(['-q'] if mode == 'local' else []))
    assert rating(env, target) is None
    assert any('offline review' in call[0] and target.id in call[1:]
               for call in calls)


def test_quiet_timid_and_yes(scored_env, no_prompt):
    env = scored_env
    target = add(env, 'target')
    source = add(env, 'source', rating=6)
    SimilarityStore(env.lib).put(target.id, source.id, 1)
    run(env, target, '-q', '-t')
    assert rating(env, target) is None
    run(env, target, '-q', '-t', '-y')
    assert rating(env, target) == 6


def test_pretend_never_accepts_strong_match(scored_env, no_prompt):
    env = scored_env
    target = add(env, 'target')
    source = add(env, 'source', rating=6)
    SimilarityStore(env.lib).put(target.id, source.id, 1)
    run(env, target, '-p', '-y')
    assert rating(env, target) is None


def test_no_match_manual_rating_or_quiet_log(scored_env, no_prompt,
                                           monkeypatch):
    env = scored_env
    target = add(env, 'target')
    calls = []
    monkeypatch.setattr(env.plugin._log, 'info',
                        lambda *args: calls.append(args))
    run(env, target, '-q')
    assert rating(env, target) is None
    assert any('offline review' in call[0] and target.id in call[1:]
               for call in calls)
    monkeypatch.setattr(ui, 'input_options', lambda *a, **k: 7)
    run(env, target)
    assert rating(env, target) == 7


@pytest.mark.parametrize('review_at', ['album', 'import'])
def test_command_deferred_review_refreshes_scores(scored_env, monkeypatch,
                                                 review_at):
    env = scored_env
    first = add(env, 'first')
    second = add(env, 'second')
    source = add(env, 'source', rating=6)
    env.lib.add_album([first, second])
    store = SimilarityStore(env.lib)
    store.put(first.id, source.id, .9)
    store.put(second.id, source.id, .9)
    store.put(second.id, first.id, 1)
    prompts = []

    def choose(*args, **kwargs):
        prompts.append(kwargs)
        return 9

    monkeypatch.setattr(ui, 'input_options', choose)
    env.run('autorate', '-W', '--review-at', review_at,
            'album_id:{}'.format(first.album_id))
    # First is reviewed; its new rating becomes a strong candidate for second.
    assert len(prompts) == 1
    assert [rating(env, item) for item in [first, second]] == [9, 9]


def test_weak_interactive_and_fix(scored_env, monkeypatch):
    env = scored_env
    target = add(env, 'target')
    first = add(env, 'first', rating=5)
    second = add(env, 'second', rating=8)
    store = SimilarityStore(env.lib)
    store.put(target.id, first.id, .9)
    store.put(target.id, second.id, .85)
    answers = iter(['x', 7])
    monkeypatch.setattr(ui, 'input_options', lambda *a, **k: next(answers))
    run(env, target)
    assert [rating(env, i) for i in [target, first, second]] == [7, 7, 7]


def test_manual_association_and_dissociation(scored_env, no_prompt):
    env = scored_env
    target = add(env, 'target')
    associated = add(env, 'associated', rating=4)
    dissociated = add(env, 'dissociated', rating=9)
    store = SimilarityStore(env.lib)
    store.put(target.id, associated.id, .3, manual=1)
    store.put(target.id, dissociated.id, 1, manual=-1)
    out = run(env, target)
    assert 'associated' in out and 'dissociated' not in out
    assert rating(env, target) == 4


def test_confidence_supports_modal_rating(scored_env, no_prompt):
    env = scored_env
    target = add(env, 'target')
    store = SimilarityStore(env.lib)
    for score, value in [(1, 10), (.9, 3), (.85, 3)]:
        source = add(env, 'source', rating=value)
        store.put(target.id, source.id, score)
    run(env, target, '-q')
    assert rating(env, target) is None


def test_inherit_global_strong_threshold_and_boundary(scored_env, no_prompt):
    env = scored_env
    configure(env, strong_rec_thresh=None)
    config['match']['strong_rec_thresh'] = .25
    target = add(env, 'target')
    source = add(env, 'source', rating=4)
    store = SimilarityStore(env.lib)
    store.put(target.id, source.id, .75)
    run(env, target, '-q', '--min-threshold', '.7')
    assert rating(env, target) is None
    store.put(target.id, source.id, .76)
    run(env, target, '-q', '--min-threshold', '.7')
    assert rating(env, target) == 4


@pytest.mark.parametrize('review_at', ['item', 'album', 'import'])
@pytest.mark.parametrize('quiet,timid,expected', [
    (False, False, 6), (True, False, 6), (True, True, None),
])
def test_import_refresh_and_modes(scored_env, no_prompt, review_at,
                                  quiet, timid, expected):
    env = scored_env
    configure(env, auto=True, review_at=review_at)
    config['import']['quiet'] = quiet
    config['import']['timid'] = timid
    source = add(env, 'same song', rating=6)
    target = add(env, 'same song')

    class Task:
        def imported_items(self):
            return [target]

    class Session:
        lib = env.lib

    # userrating is loaded first and similarity.auto is disabled: the
    # autorating stage still populates the matrix before searching.
    env.plugin.imported(Session(), Task())
    if review_at == 'album':
        env.plugin.on_item_imported(env.lib, target)
    env.plugin.on_import_end(env.lib, [])
    assert rating(env, target) == expected
    assert list(SimilarityStore(env.lib).neighbors(source.id))


@pytest.mark.parametrize('value', ['0', '-.1', '1.1', 'nan', 'inf'])
def test_invalid_command_threshold(scored_env, value):
    target = add(scored_env, 'target')
    with pytest.raises(UserError, match='min_threshold'):
        run(scored_env, target, '--min-threshold', value)


@pytest.mark.parametrize('options', [
    {'algorithm': 'unknown'}, {'min_threshold': 0}, {'min_threshold': True},
    {'min_threshold': float('nan')}, {'strong_rec_thresh': -1},
    {'strong_rec_thresh': float('inf')},
])
def test_invalid_configuration(env, options):
    env.setup({'autorate': options})
    assert plugins.find_plugins() == []
