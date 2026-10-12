# This file is part of beets-userrating.
#
# beets-userrating is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# beets-userrating is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with beets-userrating.  If not, see <https://www.gnu.org/licenses/>.

"""Plugin configuration."""

from .ratings import DEFAULT_USER, RatingError, validate_user
from .scalers import PLAYERS, find_player
from .storage import COMMENTS_NO, COMMENTS_ONLY, COMMENTS_YES

DEFAULT_CONFIG = {
    # Fetch ratings from files at import.
    'auto': True,
    # Overwrite an existing rating (default is to skip already rated items).
    'force': False,
    # Write ratings to files: null follows the beets `import.write`
    # option, yes/no override it for this plugin.
    'write': None,
    # Known beets users. Used to restore the case of user names read from
    # case-insensitive tag formats, and as default user fallback.
    'beets_users': [DEFAULT_USER],
    # External players to import ratings from, by order of priority.
    'external_music_players': ['Banshee', 'Winamp', 'WMP'],
    # Players whose rating is synchronized with the default user's rating
    # when writing files: null/no (none), all (every player listed in
    # `external_music_players`) or a list of players.
    'sync_external_ratings': None,
    # User used when no user is given (players not handling multiple
    # users, `-u` option missing...). Defaults to the first beets user.
    'default_user': None,
    # Also store ratings in the comments tag: no, yes or only.
    'write_in_comments': COMMENTS_NO,
    # Propose ratings for unrated items based on similar rated items.
    'autorate': {
        # Propose ratings at import.
        'auto': False,
        # User whose ratings are proposed (default: the default user).
        'user': None,
        # Similarity strategies (by order of priority, see README).
        # `mbtrackid` and `acoustid` enable/disable groups of strategies
        # that can also be enabled/disabled independently.
        'mbtrackid': True,
        'mb_releasetrackid': True,
        'mb_trackid': True,
        'acoustid': True,
        'acoustid_id': True,
        'acoustid_fingerprint': True,
        'bareascii': False,
        'fuzzy': False,
        # Review all the proposals at once, at the end of the import or of
        # the command, instead of one item at a time.
        'global_review': False,
    },
}

#: Similarity strategies used by autorate, by order of priority (see
#: :mod:`beetsplug.userrating.similar`), as ``(strategy, group option,
#: strategy option)``: a strategy is used when both its group option and
#: its own option are enabled (``None``: no such option).
AUTORATE_STRATEGIES = [
    ('mb_releasetrackid', 'mbtrackid', 'mb_releasetrackid'),
    ('mb_trackid', 'mbtrackid', 'mb_trackid'),
    ('acoustid_id', 'acoustid', 'acoustid_id'),
    ('acoustid_fingerprint', 'acoustid', 'acoustid_fingerprint'),
    ('artist_title', None, None),
    ('bareascii', 'bareascii', None),
    ('fuzzy', 'fuzzy', None),
]


def autorate_options():
    """Names of the options enabling/disabling autorate strategies."""
    names = []
    for _, group, option in AUTORATE_STRATEGIES:
        for name in (group, option):
            if name is not None and name not in names:
                names.append(name)
    return names


def autorate_strategies(options, overrides=None):
    """Names of the similarity strategies enabled by the ``options``
    mapping (option name -> bool, missing options take their default
    value), by order of priority.

    ``overrides`` (option name -> bool or ``None``, e.g. command line
    flags) take precedence over ``options``; a strategy's own option given
    in ``overrides`` takes precedence over its group option, e.g.
    ``--acoustid-id`` enables the AcoustID id strategy even if the
    ``acoustid`` group is disabled.
    """
    overrides = dict((k, v) for k, v in (overrides or {}).items()
                     if v is not None)

    def value(name):
        if name in overrides:
            return overrides[name]
        return options.get(name, DEFAULT_CONFIG['autorate'][name])

    names = []
    for strategy, group, option in AUTORATE_STRATEGIES:
        if option is not None and option in overrides:
            enabled = overrides[option]
        else:
            enabled = ((group is None or value(group))
                       and (option is None or value(option)))
        if enabled:
            names.append(strategy)
    return names


class ConfigError(ValueError):
    pass


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _players(names, log):
    players = []
    for name in _as_list(names):
        player = find_player(name)
        if player is None:
            log.warning(u'unknown music player {0!r} ignored (supported: '
                        u'{1})', name, u', '.join(sorted(PLAYERS)))
        elif player.name not in players:
            players.append(player.name)
    return players


def _optional_bool(value):
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ('', 'null', 'none', 'auto'):
        return None
    if text in ('yes', 'true', 'on', '1'):
        return True
    if text in ('no', 'false', 'off', '0'):
        return False
    raise ConfigError(u'invalid boolean value {0!r}'.format(value))


class Settings(object):
    """Validated plugin configuration."""

    def __init__(self, config, log):
        self.auto = bool(config['auto'].get())
        self.force = bool(config['force'].get())
        self.write = _optional_bool(config['write'].get())

        self.beets_users = []
        for user in _as_list(config['beets_users'].get()):
            try:
                user = validate_user(str(user))
            except RatingError as exc:
                raise ConfigError(u'beets_users: {0}'.format(exc))
            if user not in self.beets_users:
                self.beets_users.append(user)

        default_user = config['default_user'].get()
        if default_user:
            try:
                self.default_user = validate_user(str(default_user))
            except RatingError as exc:
                raise ConfigError(u'default_user: {0}'.format(exc))
        elif self.beets_users:
            self.default_user = self.beets_users[0]
        else:
            self.default_user = DEFAULT_USER
        if self.default_user not in self.beets_users:
            self.beets_users.append(self.default_user)

        self.external_players = _players(
            config['external_music_players'].get(), log)

        sync = config['sync_external_ratings'].get()
        if sync is None or sync is False or (
                isinstance(sync, str)
                and sync.strip().lower() in ('', 'none', 'null', 'no')):
            self.sync_players = []
        elif sync is True or (isinstance(sync, str)
                              and sync.strip().lower() == 'all'):
            self.sync_players = list(self.external_players)
        else:
            self.sync_players = _players(sync, log)

        comments = config['write_in_comments'].get()
        if comments is True:
            comments = COMMENTS_YES
        elif comments is False or comments is None:
            comments = COMMENTS_NO
        comments = str(comments).strip().lower()
        if comments not in (COMMENTS_NO, COMMENTS_YES, COMMENTS_ONLY):
            raise ConfigError(u'write_in_comments must be one of no, yes, '
                              u'only (got {0!r})'.format(comments))
        self.comments = comments

        autorate = config['autorate']
        self.autorate_auto = bool(autorate['auto'].get())
        user = autorate['user'].get()
        if user:
            try:
                self.autorate_user = validate_user(str(user))
            except RatingError as exc:
                raise ConfigError(u'autorate.user: {0}'.format(exc))
        else:
            self.autorate_user = self.default_user
        self.autorate_options = dict(
            (option, bool(autorate[option].get()))
            for option in autorate_options())
        self.autorate_global_review = bool(autorate['global_review'].get())
