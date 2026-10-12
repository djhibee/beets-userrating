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
}


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
