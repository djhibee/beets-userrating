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

from beets import config, plugins, ui
from beets.util import displayable_path

from .command import apply_ratings
from .compat import UserError
from .ratings import (MAX_RATING, MIN_RATING, RatingError, as_ratings,
                      validate_user)
from .settings import (ALGORITHMS, ConfigError, REVIEW_AT_ALBUM, REVIEW_AT_ITEM,
                       REVIEW_AT_VALUES, autorate_options, autorate_strategies,
                       similarity_threshold)
from .similar import SimilarItems, Strategy, get_similar_items, get_strategy

USAGE = u"""%prog [options] [QUERY...]

Propose a rating for the tracks matching QUERY that the user did not rate
yet (neither in beets nor in the files, including external players'
ratings), using the beets-similarity matrix by default. Candidates at or
above --min-threshold are listed by increasing distance. Strong matches
are accepted automatically unless --timid; --quiet skips and logs those
requiring review. Both options honor beets' import quiet/timid settings.

With --algorithm legacy, use the historical strategies: same
MusicBrainz release track (--mb-releasetrackid) or recording (--mb-trackid),
both enabled by --mbtrackid, same AcoustID (--acoustid-id) or AcoustID
fingerprint (--acoustid-fingerprint), both enabled by --acoustid, same
artist and title, same artist and
title in bare ASCII (--bareascii, requires the bareasc plugin) or fuzzily
matching (--fuzzy, requires the fuzzy plugin), in this order.

The most frequent rating is proposed (legacy results are grouped by rating).
Enter a rating (0-10, Enter for the proposed
one), S to skip the track or X to fix: rate the track and all its similar
tracks with the same rating. Proposals are reviewed as soon as they are
found, after each album or at the end, according to --review-at."""


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

    def __init__(self, item, user, similar, write, scores=None):
        self.item = item
        self.user = user
        self.strategy = similar.strategy if similar is not None else None
        self.similar = similar.items if similar is not None else []
        self.write = write
        self.rating = proposed_rating(self.similar, user)
        self.scores = scores
        # Confidence must support the proposed rating, not another candidate's.
        self.distance = min(
            (1 - scores[i.id] for i in self.similar
             if as_ratings(i.get('userrating')).get(user) == self.rating),
            default=None) if scores is not None else None
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
    ``review_at``: ``item`` to review each proposal as soon as it is
    found, ``album`` or ``import`` to keep the proposals pending until
    :meth:`finish` is called (once per album, or at the end),
    ``algorithm``: ``similarity_score`` for the stored similarity matrix,
    or ``legacy`` for the historical strategies,
    ``min_threshold``: minimum matrix similarity score,
    ``strong_rec_thresh``: maximum distance for automatic acceptance
    (``None`` inherits beets' match setting),
    ``quiet``: skip and log proposals requiring interaction,
    ``timid``: disable automatic acceptance of strong proposals,
    ``interactive``: allow prompts (``yes`` and strong matches can still
    apply ratings without prompting).
    """

    def __init__(self, plugin, lib, user, strategies, write, pretend=False,
                 yes=False, review_at=REVIEW_AT_ITEM, interactive=True,
                 algorithm='similarity_score', min_threshold=0.8,
                 strong_rec_thresh=None, quiet=False, timid=False):
        self.plugin = plugin
        self.log = plugin._log
        self.lib = lib
        self.user = user
        self.min_threshold = min_threshold
        self.strong_rec_thresh = (
            config['match']['strong_rec_thresh'].as_number()
            if strong_rec_thresh is None else strong_rec_thresh)
        self.timid = timid
        self.similarity = None
        if algorithm == 'similarity_score':
            self.similarity = next(
                (p for p in plugins.find_plugins()
                 if p.name == 'similarity'), None)
            if self.similarity is None:
                raise UserError(
                    u'autorate: similarity_score requires the similarity '
                    u'plugin; add similarity to plugins or use '
                    u'--algorithm legacy')
        self.strategies = []
        for name in strategies if algorithm == 'legacy' else ():
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
        self.review_at = review_at
        self.interactive = interactive and not quiet
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
        scores = None
        if self.similarity is not None:
            matches = [
                (other, score) for other, score in self.similarity.similar_items(
                    self.lib, item, threshold=self.min_threshold)
                if other.id != item.id
                and as_ratings(other.get('userrating')).get(user) is not None]
            matches.sort(key=lambda pair: (-pair[1], pair[0].id))
            scores = {other.id: score for other, score in matches}
            similar = SimilarItems(
                Strategy('similarity_score', 'similarity score', ()),
                [other for other, _ in matches]) if matches else None
        else:
            similar = get_similar_items(
                self.lib, item, strategies=self.strategies, log=self.log,
                predicate=lambda i: as_ratings(i.get('userrating')).get(user)
                is not None)
        if similar is None:
            self.log.debug(u'autorate: no rated similar item for {0}', item)
        return Proposal(item, user, similar,
                        self.write if write is None else write, scores=scores)

    def process(self, item, write=None, check_file=True):
        """Propose a rating for ``item`` if the user did not rate it.

        ``write`` overrides the ``write`` option for ``item`` (not for its
        similar items) when the proposal is reviewed immediately.
        """
        if self.is_rated(item, check_file):
            return
        deferred = self.review_at != REVIEW_AT_ITEM
        proposal = self.find(item, None if deferred else write)
        if proposal is None:
            return
        if deferred and not self.pretend:
            self.pending.append(proposal)
        else:
            self.review(proposal)

    def finish(self, items=None):
        """Review the pending proposals: all of them, or only those of
        ``items`` when given (e.g. the items of an imported album)."""
        if items is None:
            pending, self.pending = self.pending, []
        else:
            ids = set(item.id for item in items)
            pending = [p for p in self.pending if p.item.id in ids]
            self.pending = [p for p in self.pending if p.item.id not in ids]
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
        if proposal.similar:
            ui.print_(u'  not rated by {0}; {1} rated by {0} ({2}):'.format(
                proposal.user, _plural(len(proposal.similar), u'similar item'),
                proposal.strategy.label))
        else:
            ui.print_(u'  not rated by {0}; no similar items rated by {0}'
                      .format(proposal.user))
        if proposal.scores is not None:
            for item in proposal.similar:
                score = proposal.scores[item.id]
                ui.print_(u'    - {0}: rating {1}, distance {2:.6f} '
                          u'(similarity {3:.6f})'.format(
                              _describe(item),
                              as_ratings(item.get('userrating'))[proposal.user],
                              1 - score, score))
        else:
            for rating, items in proposal.groups:
                ui.print_(u'    {0} ({1}):'.format(
                    rating, _plural(len(items), u'item')))
                for item in items:
                    ui.print_(u'      - {0}'.format(_describe(item)))
        if proposal.rating is None:
            ui.print_(u'  no rating proposed')
        else:
            ui.print_(u'  proposed rating: {0}'.format(proposal.rating))

    def review(self, proposal):
        self.show(proposal)
        if self.pretend:
            ui.print_(u'  (pretend: not rated)')
            return
        if self.yes:
            if proposal.rating is not None:
                return self.rate(proposal, proposal.rating)
            return
        if (not self.timid and proposal.distance is not None
                and proposal.distance < self.strong_rec_thresh):
            return self.rate(proposal, proposal.rating)
        if not self.interactive:
            self.log.info(
                u'autorate: deferred for offline review: id:{0}, user={1}, '
                u'proposed={2}, distance={3}, path={4} (non-interactive mode)',
                proposal.item.id, proposal.user, proposal.rating,
                proposal.distance, displayable_path(proposal.item.path))
            return
        if proposal.rating is None:
            choice = ui.input_options(
                (u'Skip',), numrange=(MIN_RATING, MAX_RATING),
                prompt=u'Rating of {0} ({1}-{2}), Skip?'.format(
                    proposal.user, MIN_RATING, MAX_RATING),
                fallback_prompt=u'Enter a rating ({0}-{1}) or S:'.format(
                    MIN_RATING, MAX_RATING))
            if choice is not None and choice != u's':
                self.rate(proposal, choice)
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
        u'--algorithm', choices=list(ALGORITHMS), default=None,
        help=u'similarity algorithm: similarity_score (default) or legacy')
    parser.add_option(
        u'--min-threshold', type='float', default=None,
        help=u'minimum similarity score in (0, 1]')
    parser.add_option(
        u'-q', u'--quiet', action='store_true', default=False,
        help=u'skip and log proposals requiring a prompt')
    parser.add_option(
        u'-t', u'--timid', action='store_true', default=False,
        help=u'ask even for strong matches (unless --yes)')
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
        u'--review-at', dest='review_at', metavar='WHEN',
        choices=list(REVIEW_AT_VALUES), default=None,
        help=u'when to review the proposals: item (as soon as found), '
             u'album (after each album) or import (at the end) '
             u'(overrides the autorate "review_at" option)')
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
        by_album = rater.review_at == REVIEW_AT_ALBUM
        album = []
        for item in lib.items(args):
            # Singletons are albums of their own.
            if by_album and album and (not item.album_id or
                                       item.album_id != album[0].album_id):
                rater.finish(album)
                album = []
            album.append(item)
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
    review_at = opts.review_at or settings.autorate_review_at
    strategies = autorate_strategies(settings.autorate_options, overrides)
    try:
        threshold = (settings.autorate_min_threshold
                     if opts.min_threshold is None else similarity_threshold(
                         opts.min_threshold, 'min_threshold'))
    except ConfigError as exc:
        raise UserError(u'autorate: {0}'.format(exc))
    return AutoRater(plugin, lib, user, strategies,
                     plugin.should_write(opts.write), pretend=opts.pretend,
                     yes=opts.yes, review_at=review_at,
                     algorithm=opts.algorithm or settings.autorate_algorithm,
                     min_threshold=threshold,
                     strong_rec_thresh=settings.autorate_strong_rec_thresh,
                     quiet=(opts.quiet or settings.autorate_quiet
                            or config['import']['quiet'].get(bool)),
                     timid=(opts.timid or settings.autorate_timid
                            or config['import']['timid'].get(bool)))


def import_rater(plugin, lib):
    """The :class:`AutoRater` used at import."""
    settings = plugin.settings
    return AutoRater(
        plugin, lib, settings.autorate_user,
        autorate_strategies(settings.autorate_options),
        plugin.should_write(), review_at=settings.autorate_review_at,
        algorithm=settings.autorate_algorithm,
        min_threshold=settings.autorate_min_threshold,
        strong_rec_thresh=settings.autorate_strong_rec_thresh,
        quiet=settings.autorate_quiet or config['import']['quiet'].get(bool),
        timid=settings.autorate_timid or config['import']['timid'].get(bool))
