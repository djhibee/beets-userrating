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

"""Propose ratings for unrated items based on similar rated items (the
``autorate`` import option and ``beet autorate`` command)."""

from collections import Counter

from beets import config, ui

from .command import apply_ratings
from .compat import UserError
from .ratings import (MAX_RATING, MIN_RATING, RatingError, as_ratings,
                      validate_user)
from .settings import autorate_options, autorate_strategies
from .similar import get_similar_items, get_strategy

USAGE = u"""%prog [options] [QUERY...]

Propose a rating for the tracks matching QUERY that the user did not rate
yet (neither in beets nor in the files, including external players'
ratings), based on the ratings of similar tracks of the library: same
MusicBrainz release track (--mb-releasetrackid) or recording (--mb-trackid),
both enabled by --mbtrackid, same AcoustID (--acoustid-id) or AcoustID
fingerprint (--acoustid-fingerprint), both enabled by --acoustid, same
artist and title, same artist and
title in bare ASCII (--bareascii, requires the bareasc plugin) or fuzzily
matching (--fuzzy, requires the fuzzy plugin), in this order.

For each track, similar tracks are listed, grouped by rating, and the most
frequent rating is proposed. Enter a rating (0-10, Enter for the proposed
one), S to skip the track or X to fix: rate the track and all its similar
tracks with the same rating."""


def proposed_rating(items, user):
    """The most frequent rating of ``user`` among ``items`` (ties are
    broken by the highest rating), or ``None``."""
    counts = Counter(as_ratings(i.get('userrating')).get(user)
                     for i in items)
    counts.pop(None, None)
    if not counts:
        return None
    return max(counts, key=lambda rating: (counts[rating], rating))


class Proposal(object):
    """A rating proposed for ``item`` based on the ``similar`` items (a
    :class:`~beetsplug.userrating.similar.SimilarItems`)."""

    def __init__(self, item, user, similar, write):
        self.item = item
        self.user = user
        self.strategy = similar.strategy
        self.similar = similar.items
        self.write = write
        self.rating = proposed_rating(self.similar, user)
        groups = {}
        for similar_item in self.similar:
            rating = as_ratings(similar_item.get('userrating')).get(user)
            if rating is None:
                continue
            groups.setdefault(rating, []).append(similar_item)
        #: ``(rating, items)`` pairs, most frequent rating first.
        self.groups = sorted(groups.items(),
                             key=lambda g: (-len(g[1]), -g[0]))


def _plural(count, word):
    return u'{0} {1}{2}'.format(count, word, u'' if count == 1 else u's')


def _describe(item):
    return u'{0} [{1}]'.format(format(item), item.get('format') or u'?')


class AutoRater(object):
    """Find, review and apply rating proposals.

    ``strategies``: names of the similarity strategies to use,
    ``write``: write ratings to the files,
    ``pretend``: only show the proposals,
    ``yes``: apply the proposed ratings without asking,
    ``global_review``: review the proposals in :meth:`finish` instead of
    as soon as they are found,
    ``interactive``: ask the user (otherwise proposals are skipped unless
    ``yes``).
    """

    def __init__(self, plugin, lib, user, strategies, write, pretend=False,
                 yes=False, global_review=False, interactive=True):
        self.plugin = plugin
        self.log = plugin._log
        self.lib = lib
        self.user = user
        self.strategies = []
        for name in strategies:
            strategy = get_strategy(name)
            if strategy.available():
                self.strategies.append(strategy)
            else:
                self.log.warning(
                    u'autorate: {0} matching requires the {1} plugin, '
                    u'ignored', name, strategy.requires)
        self.write = write
        self.pretend = pretend
        self.yes = yes
        self.global_review = global_review
        self.interactive = interactive
        self.pending = []

    # Finding ---------------------------------------------------------

    def is_rated(self, item, check_file=True):
        """Whether the user rated the item, in beets or in its file
        (including the ratings of external music players)."""
        if as_ratings(item.get('userrating')).get(self.user) is not None:
            return True
        if check_file:
            found = self.plugin.read_item(item) or {}
            if found.get(self.user) is not None:
                self.log.info(
                    u'autorate: {0} is rated {1} in its file, skipped (use '
                    u'"beet userrating --import" to import it)', item,
                    found[self.user])
                return True
        return False

    def find(self, item, write=None):
        """Return a :class:`Proposal` for ``item`` or ``None``."""
        user = self.user
        similar = get_similar_items(
            self.lib, item, strategies=self.strategies, log=self.log,
            predicate=lambda i: as_ratings(i.get('userrating')).get(user)
            is not None)
        if similar is None:
            self.log.debug(u'autorate: no rated similar item for {0}', item)
            return None
        return Proposal(item, user, similar,
                        self.write if write is None else write)

    def process(self, item, write=None, check_file=True):
        """Propose a rating for ``item`` if the user did not rate it.

        ``write`` overrides the ``write`` option for ``item`` (not for its
        similar items) when the proposal is reviewed immediately.
        """
        if self.is_rated(item, check_file):
            return
        proposal = self.find(item, None if self.global_review else write)
        if proposal is None:
            return
        if self.global_review and not self.pretend:
            self.pending.append(proposal)
        else:
            self.review(proposal)

    def finish(self):
        """Review the pending proposals (global review)."""
        pending, self.pending = self.pending, []
        if pending:
            ui.print_(u'autorate: {0} to review'.format(
                _plural(len(pending), u'rating proposal')))
        for proposal in pending:
            # The item may have been rated since the proposal was made.
            current = self.lib.get_item(proposal.item.id) or proposal.item
            if as_ratings(current.get('userrating')).get(self.user) \
                    is not None:
                continue
            # Similar items may have been rated (or fixed) since: refresh
            # the proposal.
            proposal = self.find(current, proposal.write)
            if proposal is not None:
                self.review(proposal)

    # Reviewing -------------------------------------------------------

    def show(self, proposal):
        ui.print_(u'')
        ui.print_(_describe(proposal.item))
        ui.print_(u'  not rated by {0}; {1} rated by {0} ({2}):'.format(
            proposal.user, _plural(len(proposal.similar), u'similar item'),
            proposal.strategy.label))
        for rating, items in proposal.groups:
            ui.print_(u'    {0} ({1}):'.format(
                rating, _plural(len(items), u'item')))
            for item in items:
                ui.print_(u'      - {0}'.format(_describe(item)))
        ui.print_(u'  proposed rating: {0}'.format(proposal.rating))

    def review(self, proposal):
        self.show(proposal)
        if self.pretend:
            ui.print_(u'  (pretend: not rated)')
            return
        if self.yes:
            return self.rate(proposal, proposal.rating)
        if not self.interactive:
            self.log.info(u'autorate: {0} not rated (non-interactive '
                          u'mode)', proposal.item)
            return
        choice = ui.input_options(
            (u'Skip', u'fiX'), numrange=(MIN_RATING, MAX_RATING),
            default=proposal.rating,
            prompt=u'Rating of {0} ({1}-{2}, Enter for {3}), Skip or fiX '
                   u'(rate similar items too)?'.format(
                       proposal.user, MIN_RATING, MAX_RATING,
                       proposal.rating),
            fallback_prompt=u'Enter a rating ({0}-{1}), S or X:'.format(
                MIN_RATING, MAX_RATING))
        if choice == u's':
            return
        if choice == u'x':
            rating = ui.input_options(
                (), numrange=(MIN_RATING, MAX_RATING),
                default=proposal.rating,
                prompt=u'Rating of {0} for this item and its {1} ({2}-{3}, '
                       u'Enter for {4})?'.format(
                           proposal.user,
                           _plural(len(proposal.similar), u'similar item'),
                           MIN_RATING, MAX_RATING, proposal.rating),
                fallback_prompt=u'Enter a rating ({0}-{1}):'.format(
                    MIN_RATING, MAX_RATING))
            return self.rate(proposal, rating, fix=True)
        return self.rate(proposal, choice)

    def rate(self, proposal, rating, fix=False):
        """Rate the item and, if ``fix``, its similar items."""
        user = self.user
        targets = [(proposal.item, proposal.write)]
        if fix:
            targets += [(i, self.write) for i in proposal.similar]
        for item, write in targets:
            current = as_ratings(item.get('userrating'))
            new = current.copy()
            new[user] = rating
            apply_ratings(self.plugin, self.lib, item, current, new, write)


def build_command(plugin):
    cmd = ui.Subcommand(
        u'autorate',
        help=u'propose ratings for unrated tracks based on similar rated '
             u'tracks')
    cmd.parser.usage = USAGE
    parser = cmd.parser
    parser.add_option(
        u'-u', u'--user', dest='user', metavar='USER',
        help=u'user to rate for (default: autorate "user" option, or the '
             u'default user)')
    for option in autorate_options():
        flag = option.replace(u'_', u'-')
        parser.add_option(
            u'--' + flag, dest=option, action='store_true', default=None,
            help=u'enable {0} matching (overrides the autorate "{0}" '
                 u'option)'.format(option))
        parser.add_option(
            u'--no-' + flag, dest=option, action='store_false',
            help=u'disable {0} matching'.format(option))
    parser.add_option(
        u'-g', u'--global-review', dest='global_review',
        action='store_true', default=None,
        help=u'review all the proposals at the end (overrides the '
             u'autorate "global_review" option)')
    parser.add_option(
        u'--no-global-review', dest='global_review', action='store_false',
        help=u'review each proposal as soon as it is found')
    parser.add_option(
        u'-p', u'--pretend', dest='pretend', action='store_true',
        default=False, help=u'only show the proposals, change nothing')
    parser.add_option(
        u'-y', u'--yes', dest='yes', action='store_true', default=False,
        help=u'apply the proposed ratings without asking')
    parser.add_option(
        u'-w', u'--write', dest='write', action='store_true', default=None,
        help=u'write ratings to files (overrides the "write" options)')
    parser.add_option(
        u'-W', u'--nowrite', dest='write', action='store_false',
        help=u"don't write ratings to files (overrides the \"write\" "
             u"options)")

    def func(lib, opts, args):
        rater = command_rater(plugin, lib, opts)
        for item in lib.items(args):
            rater.process(item)
        rater.finish()

    cmd.func = func
    return cmd


def command_rater(plugin, lib, opts):
    settings = plugin.settings
    user = settings.autorate_user
    if opts.user:
        try:
            user = validate_user(opts.user)
        except RatingError as exc:
            raise UserError(u'autorate: {0}'.format(exc))
    overrides = dict((option, getattr(opts, option))
                     for option in autorate_options())
    global_review = (settings.autorate_global_review
                     if opts.global_review is None else opts.global_review)
    strategies = autorate_strategies(settings.autorate_options, overrides)
    return AutoRater(plugin, lib, user, strategies,
                     plugin.should_write(opts.write), pretend=opts.pretend,
                     yes=opts.yes, global_review=global_review)


def import_rater(plugin, lib):
    """The :class:`AutoRater` used at import."""
    settings = plugin.settings
    return AutoRater(
        plugin, lib, settings.autorate_user,
        autorate_strategies(settings.autorate_options),
        plugin.should_write(), global_review=settings.autorate_global_review,
        interactive=not config['import']['quiet'].get(bool))
