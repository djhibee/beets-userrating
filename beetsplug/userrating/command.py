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

"""The ``beet userrating`` command."""

from beets import ui

from .compat import UserError
from .ratings import RatingError, as_ratings, validate_rating, validate_user

USAGE = u"""%prog [options] [QUERY...]

List, modify, remove or import user ratings (integers from 0 to 10) of the
tracks matching QUERY.

  %prog --list [-u USER]... [-r RATING]...
  %prog --modify [-u USER -r RATING]... [-f]
  %prog --modify [-u USER]... -d
  %prog --remove [-u USER]...
  %prog --import [-f]

When -u/--user is missing, the default user is used. Users and ratings are
paired in order; when there are fewer of one than of the other, the last
one given is repeated, e.g. "-u a -u b -u c -r 2 -r 1" is equivalent to
"-u a -r 2 -u b -r 1 -u c -r 1"."""


def build_command(plugin):
    cmd = ui.Subcommand(u'userrating',
                        help=u'manage per-user ratings of tracks')
    cmd.parser.usage = USAGE
    parser = cmd.parser
    parser.add_option(
        u'-l', u'--list', dest='list', action='store_true', default=False,
        help=u'list ratings (default action). With -r, only list tracks '
             u'with the given rating(s)')
    parser.add_option(
        u'-m', u'--modify', dest='modify', action='store_true',
        default=False, help=u'set (or with -d, delete) ratings')
    parser.add_option(
        u'--remove', dest='remove', action='store_true', default=False,
        help=u'delete ratings (same as --modify --delete)')
    parser.add_option(
        u'-i', u'--import', dest='import_', action='store_true',
        default=False,
        help=u'import ratings from the files (beets users, then external '
             u'players)')
    parser.add_option(
        u'-u', u'--user', dest='users', action='append', default=[],
        metavar='USER', help=u'user (repeatable; default: default user)')
    parser.add_option(
        u'-r', u'--rating', dest='ratings', action='append', default=[],
        metavar='RATING',
        help=u'rating between 0 and 10 or "none" (repeatable)')
    parser.add_option(
        u'-d', u'--delete', dest='delete', action='store_true',
        default=False, help=u'with --modify, delete the rating(s)')
    parser.add_option(
        u'-f', u'--force', dest='force', action='store_true', default=None,
        help=u'overwrite existing ratings (overrides the "force" option)')
    parser.add_option(
        u'--no-force', dest='force', action='store_false',
        help=u'do not overwrite existing ratings (overrides the "force" '
             u'option)')
    parser.add_option(
        u'-w', u'--write', dest='write', action='store_true', default=None,
        help=u'write ratings to files (overrides the "write" options)')
    parser.add_option(
        u'-W', u'--nowrite', dest='write', action='store_false',
        help=u"don't write ratings to files (overrides the \"write\" "
             u"options)")
    cmd.func = lambda lib, opts, args: RatingCommand(plugin, opts).run(
        lib, args)
    return cmd


def pair_users_ratings(users, ratings, default_user):
    """Pair users with ratings in order. The shorter list is padded with
    its last element; missing users default to ``default_user``.

    Ratings may be empty: every user is then paired with ``None``.
    """
    users = list(users) or [default_user]
    if not ratings:
        return [(user, None) for user in users]
    ratings = list(ratings)
    size = max(len(users), len(ratings))
    users += [users[-1]] * (size - len(users))
    ratings += [ratings[-1]] * (size - len(ratings))
    return list(zip(users, ratings))


def _display(rating):
    return u'none' if rating is None else str(rating)


class RatingCommand(object):

    def __init__(self, plugin, opts):
        self.plugin = plugin
        self.settings = plugin.settings
        self.opts = opts
        try:
            self.users = [validate_user(u) for u in opts.users]
            self.ratings = [validate_rating(r) for r in opts.ratings]
        except RatingError as exc:
            raise UserError(u'userrating: {0}'.format(exc))
        self.force = (opts.force if opts.force is not None
                      else self.settings.force)
        self.write = plugin.should_write(opts.write)

    def _action(self):
        opts = self.opts
        actions = [name for name in ('list', 'modify', 'remove', 'import_')
                   if getattr(opts, name)]
        if len(actions) > 1:
            raise UserError(u'userrating: --list, --modify, --remove and '
                            u'--import are mutually exclusive')
        if actions:
            return actions[0]
        return 'modify' if opts.delete else 'list'

    def run(self, lib, args):
        action = self._action()
        if action != 'modify' and self.opts.delete:
            raise UserError(u'userrating: -d/--delete requires --modify')
        if action == 'list':
            return self.list(lib, args)
        if action == 'import_':
            if self.users or self.ratings:
                raise UserError(u'userrating: --import does not accept '
                                u'-u/--user or -r/--rating')
            return self.import_(lib, args)
        delete = action == 'remove' or self.opts.delete
        if delete and self.ratings:
            raise UserError(u'userrating: -r/--rating can not be used to '
                            u'delete ratings')
        if not delete and not self.ratings:
            raise UserError(u'userrating: --modify requires -r/--rating or '
                            u'-d/--delete')
        return self.modify(lib, args, delete)

    # Actions ---------------------------------------------------------

    def list(self, lib, args):
        default = self.settings.default_user
        pairs = (pair_users_ratings(self.users, self.ratings, default)
                 if self.ratings else [])
        for item in lib.items(args):
            ratings = as_ratings(item.get('userrating'))
            if pairs:
                if not all(ratings.get(u) == r for u, r in pairs):
                    continue
                shown = []
                for user, _ in pairs:
                    if user not in shown:
                        shown.append(user)
            elif self.users:
                shown = [u for u in self.users if u in ratings]
                if not shown:
                    continue
            else:
                shown = sorted(ratings)
                if not shown:
                    continue
            ui.print_(u'{0}: {1}'.format(format(item), u', '.join(
                u'{0}:{1}'.format(u, _display(ratings.get(u)))
                for u in shown)))

    def modify(self, lib, args, delete):
        pairs = pair_users_ratings(
            self.users, [] if delete else self.ratings,
            self.settings.default_user)
        items = list(lib.items(args))
        if not items:
            self.plugin._log.warning(u'no item found.')
        for item in items:
            current = as_ratings(item.get('userrating'))
            new = current.copy()
            for user, rating in pairs:
                if delete or rating is None:
                    new.pop(user, None)
                elif (user in current and current[user] != rating
                      and not self.force):
                    self.plugin._log.info(
                        u'skipping {0}: already rated {1} by {2} (use '
                        u'-f/--force to overwrite)', item, current[user],
                        user)
                else:
                    new[user] = rating
            self._apply(lib, item, current, new)

    def import_(self, lib, args):
        for item in lib.items(args):
            current = as_ratings(item.get('userrating'))
            if self.plugin.import_item(item, self.force):
                self._apply(lib, item, current, item['userrating'])

    # Helpers ---------------------------------------------------------

    def _apply(self, lib, item, current, new):
        if new == current:
            return
        if new:
            item['userrating'] = new
        elif 'userrating' in item._values_flex:
            # Unrated: no stored value at all.
            del item['userrating']
        changes = [u'  userrating[{0}]: {1} -> {2}'.format(
            user, _display(current.get(user)), _display(new.get(user)))
            for user in sorted(set(current) | set(new))
            if current.get(user) != new.get(user)]
        if changes:
            ui.print_(format(item))
            ui.print_(u'\n'.join(changes))
        for user in new:
            self.plugin.register_user(user)
        with lib.transaction():
            item.store()
            if self.write and self.plugin.write_item(item):
                item.mtime = item.current_mtime()
                item.store()
