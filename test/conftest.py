import os
import shutil
from pathlib import Path

import pytest

import beets
import beets.plugins
import beets.ui
from beets import config
from beets.library import Library

RSRC = Path(__file__).parent / 'rsrc'


def _reset_caches():
    try:
        from beets.util import cached_classproperty
        cached_classproperty.cache.clear()
    except (ImportError, AttributeError):  # pragma: no cover
        pass


def _unload_plugins():
    beets.plugins.BeetsPlugin.listeners.clear()
    if hasattr(beets.plugins.BeetsPlugin, '_raw_listeners'):
        beets.plugins.BeetsPlugin._raw_listeners.clear()
    beets.plugins._instances.clear()
    config['plugins'] = []
    _reset_caches()


class Env(object):
    """A beets test environment with the userrating plugin loaded."""

    def __init__(self, tmp_path, monkeypatch, capsys):
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.capsys = capsys
        self.libdir = tmp_path / 'lib'
        self.libdir.mkdir()
        self.lib = None

    def setup(self, plugin_config=None, plugins=()):
        _unload_plugins()
        config.clear()
        config.read(user=False, defaults=True)
        config['directory'] = str(self.libdir)
        config['ui']['color'] = False
        config['threaded'] = False
        config['import']['write'] = True
        if 'create_backup_before_migrations' in config.keys():
            config['create_backup_before_migrations'] = False
        config['userrating'].set(plugin_config or {})
        config['plugins'] = ['userrating'] + list(plugins)
        beets.plugins.load_plugins()
        _reset_caches()
        if self.lib is None:
            self.lib = Library(':memory:', str(self.libdir))
            self.monkeypatch.setattr(self.lib, '_close', lambda: None)
        self.monkeypatch.setattr(beets.ui, '_open_library',
                                 lambda *args, **kwargs: self.lib)
        return self

    @property
    def plugin(self):
        return beets.plugins.find_plugins()[0]

    def add_item(self, fixture='full', ext='mp3', **values):
        src = RSRC / '{0}.{1}'.format(fixture, ext)
        dst = self.libdir / '{0}-{1}.{2}'.format(
            fixture, len(list(self.libdir.iterdir())), ext)
        shutil.copy(str(src), str(dst))
        item = beets.library.Item.from_path(os.fsencode(str(dst)))
        item.update(values)
        self.lib.add(item)
        return item

    def run(self, *args):
        self.capsys.readouterr()
        beets.ui._raw_main(list(args))
        return self.capsys.readouterr().out

    def reload(self, item):
        return self.lib.get_item(item.id)


@pytest.fixture
def env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('BEETSDIR', str(tmp_path))
    monkeypatch.setenv('HOME', str(tmp_path))
    environment = Env(tmp_path, monkeypatch, capsys)
    environment.setup({'beets_users': ['djhibee', 'toto']})
    yield environment
    _unload_plugins()
    config.clear()
    config.read(user=False, defaults=True)


@pytest.fixture
def copy_rsrc(tmp_path):
    def _copy(name):
        dst = tmp_path / name
        shutil.copy(str(RSRC / name), str(dst))
        return str(dst)
    return _copy
