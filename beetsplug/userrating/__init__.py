# This file is part of beets-userrating.
#
# Copyright 2017, Michael Dorman.
# Copyright Jean-Philippe Hautin (https://github.com/jphautin).
# Copyright djhibee (https://github.com/djhibee/beets-userrating).
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
#
# Portions of this code were originally released by Michael Dorman under
# the following permission notice:
#
#   Permission is hereby granted, free of charge, to any person obtaining
#   a copy of this software and associated documentation files (the
#   "Software"), to deal in the Software without restriction, including
#   without limitation the rights to use, copy, modify, merge, publish,
#   distribute, sublicense, and/or sell copies of the Software, and to
#   permit persons to whom the Software is furnished to do so, subject to
#   the following conditions:
#
#   The above copyright notice and this permission notice shall be
#   included in all copies or substantial portions of the Software.

"""A beets plugin managing per-user track ratings.

Ratings are stored in the beets library in the ``userrating`` flexible
attribute as a ``user -> rating`` mapping (ratings are integers from 0 to
10, an unrated user is absent) and, optionally, in the media files (see
:mod:`beetsplug.userrating.storage`).
"""

from beets import config, ui
from beets.plugins import BeetsPlugin
from beets.util import displayable_path, syspath

from . import storage
from .command import build_command
from .compat import UserError
from .ratings import (USER_RATINGS_TYPE, UserRatingQuery, UserRatings,
                      UserRatingsType, as_ratings, format_ratings)
from .scalers import (Mp3BansheeScaler, Mp3BeetsScaler,  # noqa: F401
                      Mp3MediaMonkeyScaler, Mp3QuodlibetScaler,
                      Mp3WinampScaler, Mp3WindowsMediaPlayerScaler, Scaler)
from .settings import DEFAULT_CONFIG, ConfigError, Settings

__all__ = ['UserRatingsPlugin', 'UserRatings', 'UserRatingsType',
           'UserRatingQuery']

FIELD = u'userrating'
#: Library table caching the names of the users having ratings.
USERS_TABLE = u'userrating_users'


def _stored_ratings(item):
    """Raw value of the ``userrating`` flexible attribute (``None`` if
    the item was never rated)."""
    return item._values_flex.get(FIELD)


def is_managed(item):
    """Whether the item has a ``userrating`` attribute, i.e. its
    ratings are managed by beets (possibly with no rating left)."""
    return FIELD in item._values_flex


class UserRatingsPlugin(BeetsPlugin):
    """Manage per-user track ratings.

    Album ratings are not supported yet: the type, query and template
    helpers are model-agnostic so that they can be registered in
    ``album_types``/``album_template_fields`` later on.
    """

    item_types = {FIELD: USER_RATINGS_TYPE}

    def __init__(self, name=None):
        super(UserRatingsPlugin, self).__init__(name)
        self.config.add(DEFAULT_CONFIG)
        try:
            self.settings = Settings(self.config, self._log)
        except ConfigError as exc:
            raise UserError(u'userrating: {0}'.format(exc))
        UserRatings.default_user = self.settings.default_user

        if self.settings.auto:
            self.import_stages = [self.imported]

        self.register_listener('after_write', self.on_after_write)
        self.register_listener('library_opened', self.on_library_opened)
        self.register_listener('database_change', self.on_database_change)
        self._cache_lib = None
        self._cached_users = set()

        # `$userrating` is backed by a computed field reading the flexible
        # attribute so that unrated items are formatted as an empty string
        # (instead of a literal "$userrating").
        self.template_fields[FIELD] = _stored_ratings
        self.template_fields[u'userratings'] = self._all_ratings_field
        for user in self.settings.beets_users:
            self.register_user(user)

    # Templates -------------------------------------------------------

    @staticmethod
    def _all_ratings_field(item):
        return format_ratings(as_ratings(item.get(FIELD)))

    def register_user(self, user):
        """Expose ``${userrating[<user>]}`` in templates."""
        key = u'{0}[{1}]'.format(FIELD, user)
        if key not in self.template_fields:
            self.template_fields[key] = \
                lambda item, user=user: as_ratings(item.get(FIELD)).get(user)

    def on_library_opened(self, lib):
        """Register the template fields of the users having ratings in
        the library.

        The user names are cached in the ``userrating_users`` table so
        that the (potentially slow) scan of all the ratings is only done
        once, when the cache table is created. The cache is then kept up
        to date on each database change.
        """
        self._cache_lib = None
        self._cached_users = set()
        with lib.transaction() as tx:
            exists = tx.query(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = ?", (USERS_TABLE,))
            if exists:
                users = {row[0] for row in tx.query(
                    'SELECT user FROM {0}'.format(USERS_TABLE))}
            else:
                users = set()
                for row in tx.query(
                        'SELECT DISTINCT value FROM item_attributes '
                        'WHERE key = ?', (FIELD,)):
                    users.update(USER_RATINGS_TYPE.from_sql(row[0]))
                tx.mutate('CREATE TABLE IF NOT EXISTS {0} '
                          '(user TEXT PRIMARY KEY)'.format(USERS_TABLE))
                self._cache_users(tx, users)
        self._cache_lib = lib
        self._cached_users = users
        for user in users:
            self.register_user(user)

    @staticmethod
    def _cache_users(tx, users):
        for user in users:
            tx.mutate('INSERT OR IGNORE INTO {0} (user) VALUES (?)'
                      .format(USERS_TABLE), (user,))

    def on_database_change(self, lib, model):
        """Register and cache the users of a stored model's ratings."""
        values = getattr(model, '_values_flex', {})
        if FIELD not in values:
            return
        new = [user for user in as_ratings(values[FIELD])
               if user not in self._cached_users]
        if not new:
            return
        for user in new:
            self.register_user(user)
        # Only the library whose cache was loaded is updated (another
        # library would not have been scanned).
        if lib is not None and lib is self._cache_lib:
            with lib.transaction() as tx:
                self._cache_users(tx, new)
            self._cached_users.update(new)

    # Commands --------------------------------------------------------

    def commands(self):
        return [build_command(self)]

    # Files -----------------------------------------------------------

    def should_write(self, write_opt=None):
        """Whether ratings must be written to files after a change made
        by this plugin: the command line option wins over the plugin's
        ``write`` option, which wins over the beets ``import.write``
        option."""
        if write_opt is not None:
            return write_opt
        if self.settings.write is not None:
            return self.settings.write
        return ui.should_write()

    def write_item(self, item, path=None):
        """Write the item's ratings to its file. Return ``True`` on
        success."""
        path = path or item.path
        ratings = as_ratings(item.get(FIELD))
        try:
            storage.write_file(
                syspath(path), ratings, self.settings.default_user,
                sync_players=self.settings.sync_players,
                comments=self.settings.comments,
                id3v23=config['id3v23'].get(bool))
        except storage.UnsupportedFormatError:
            self._log.debug(u'ratings not written, unsupported format: {0}',
                            displayable_path(path))
            return False
        except storage.FILE_ERRORS as exc:
            self._log.error(u'could not write ratings to {0}: {1}',
                            displayable_path(item.path), exc)
            return False
        self._log.debug(u'wrote ratings {0} to {1}', ratings,
                        displayable_path(item.path))
        return True

    def on_after_write(self, item, path, **kwargs):
        """Write ratings whenever beets writes tags of a rated item."""
        if self.settings.write is False or not is_managed(item):
            return
        if self.write_item(item, path) and path == item.path:
            item.mtime = item.current_mtime()

    def read_item(self, item):
        """Return the ratings found in the item's file as a dict, or
        ``None`` if the file can not be read.

        Ratings of beets users come first; if the default user is not
        rated, the rating of the first external player (by order of
        priority) found in the file is used for the default user.
        """
        try:
            found = storage.read_file(syspath(item.path),
                                      self.settings.beets_users)
        except storage.UnsupportedFormatError:
            self._log.debug(u'ratings not read, unsupported format: {0}',
                            displayable_path(item.path))
            return None
        except storage.FILE_ERRORS as exc:
            self._log.error(u'could not read ratings from {0}: {1}',
                            displayable_path(item.path), exc)
            return None
        ratings = found.users()
        default = self.settings.default_user
        if default not in ratings:
            for player in self.settings.external_players:
                if player in found.players:
                    self._log.debug(u'using {0} rating for {1}', player,
                                    displayable_path(item.path))
                    ratings[default] = found.players[player]
                    break
        return ratings

    def import_item(self, item, force=None):
        """Merge the ratings found in the item's file into the item.
        Existing ratings are kept unless ``force`` is set. Return whether
        the item changed (it is not stored)."""
        if force is None:
            force = self.settings.force
        found = self.read_item(item)
        if not found:
            return False
        current = as_ratings(item.get(FIELD))
        new = current.copy()
        for user, rating in found.items():
            if user in current and current[user] != rating and not force:
                self._log.info(u'skipping {0}: already rated {1} by {2}',
                               item, current[user], user)
                continue
            new[user] = rating
            self.register_user(user)
        if new == current and is_managed(item):
            return False
        item[FIELD] = new
        return True

    def imported(self, session, task):
        """Import stage: fetch ratings from the imported files."""
        for item in task.imported_items():
            if self.import_item(item):
                self._log.info(u'imported ratings {0} for {1}',
                               format_ratings(item[FIELD]), item)
                item.store()
