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

"""Find the library items similar to a given item.

This module does not depend on ratings and can be reused by other plugins,
e.g. to find the lossless version of a lossy track::

    from beetsplug.userrating.similar import get_similar_items

    found = get_similar_items(lib, item, format='FLAC')
    if found:
        best = max(found.items, key=lambda i: i.bitrate)

Similarity is evaluated by :class:`Strategy` objects, tried in order of
priority (see :data:`STRATEGIES`): the most reliable ones first (same
MusicBrainz release track, same recording, same AcoustID fingerprint), then
the less reliable ones (same artist and title, compared exactly, in bare
ASCII or fuzzily).
"""

import difflib
from collections import namedtuple

from beets import config, plugins
from beets.dbcore.query import AndQuery, MatchQuery, StringQuery

try:
    from unidecode import unidecode
except ImportError:  # pragma: no cover - unidecode is a beets dependency
    def unidecode(text):
        return text


def plugin_loaded(name):
    """Whether the beets plugin ``name`` is loaded."""
    return any(getattr(p, 'name', None) == name
               for p in plugins.find_plugins())


def _text(value):
    return u'' if value is None else str(value).strip()


def _bare(value):
    return unidecode(_text(value)).lower()


class Strategy(object):
    """A way to find similar items.

    ``name``: identifier of the strategy,
    ``label``: human-friendly description ("same ..."),
    ``fields``: the item fields that must be set (non-empty) to use it,
    ``requires``: name of the beets plugin that must be loaded (or None).

    Subclasses (or instances) implement :meth:`query` (a beets query
    pre-selecting the candidates, ``None`` to scan all items) and
    :meth:`match` (the final check of a candidate).
    """

    def __init__(self, name, label, fields, requires=None):
        self.name = name
        self.label = label
        self.fields = tuple(fields)
        self.requires = requires

    def available(self):
        return self.requires is None or plugin_loaded(self.requires)

    def applies_to(self, item):
        return all(_text(item.get(field)) for field in self.fields)

    def query(self, item):
        return AndQuery([MatchQuery(field, item.get(field))
                         for field in self.fields])

    def match(self, item, candidate):
        return all(item.get(field) == candidate.get(field)
                   for field in self.fields)

    def __repr__(self):
        return 'Strategy({0!r})'.format(self.name)


class ArtistTitleStrategy(Strategy):
    """Same artist and title (case-insensitive)."""

    def __init__(self, name=u'artist_title',
                 label=u'same artist and title', requires=None):
        super(ArtistTitleStrategy, self).__init__(
            name, label, ('artist', 'title'), requires)

    def query(self, item):
        return AndQuery([StringQuery(field, _text(item.get(field)))
                         for field in self.fields])

    def normalize(self, value):
        return _text(value).lower()

    def match(self, item, candidate):
        return all(self.normalize(item.get(field))
                   == self.normalize(candidate.get(field))
                   for field in self.fields)


class BareAsciiStrategy(ArtistTitleStrategy):
    """Same artist and title once converted to bare ASCII (accents
    removed, case-insensitive). Requires the ``bareasc`` plugin."""

    def __init__(self):
        super(BareAsciiStrategy, self).__init__(
            u'bareascii', u'same artist and title (bare ASCII)',
            requires=u'bareasc')

    def query(self, item):
        from beetsplug.bareasc import BareascQuery
        return AndQuery([BareascQuery(field, _bare(item.get(field)))
                         for field in self.fields])

    def normalize(self, value):
        return _bare(value)


class FuzzyStrategy(ArtistTitleStrategy):
    """Similar artist and title (``difflib`` ratio of the lower-cased
    values above the ``fuzzy.threshold`` option). Requires the ``fuzzy``
    plugin. All the items are scanned: this is the slowest strategy."""

    def __init__(self):
        super(FuzzyStrategy, self).__init__(
            u'fuzzy', u'similar artist and title (fuzzy)', requires=u'fuzzy')

    def query(self, item):
        # Called once per search: read the threshold here rather than for
        # each candidate.
        self._threshold = config['fuzzy']['threshold'].as_number()
        return None

    def match(self, item, candidate):
        threshold = getattr(self, '_threshold', None)
        if threshold is None:
            threshold = config['fuzzy']['threshold'].as_number()
        for field in self.fields:
            a = self.normalize(item.get(field))
            b = self.normalize(candidate.get(field))
            if not b or difflib.SequenceMatcher(None, a, b).ratio() \
                    < threshold:
                return False
        return True


#: Built-in strategies, by order of priority.
STRATEGIES = [
    Strategy(u'mb_releasetrackid', u'same MusicBrainz release track',
             ('mb_releasetrackid',)),
    Strategy(u'mb_trackid', u'same MusicBrainz recording', ('mb_trackid',)),
    Strategy(u'acoustid', u'same AcoustID fingerprint',
             ('acoustid_fingerprint',)),
    ArtistTitleStrategy(),
    BareAsciiStrategy(),
    FuzzyStrategy(),
]


def get_strategy(name):
    for strategy in STRATEGIES:
        if strategy.name == name:
            return strategy
    raise ValueError(u'unknown similarity strategy {0!r} (known: {1})'.format(
        name, u', '.join(s.name for s in STRATEGIES)))


#: Result of :func:`get_similar_items`: the strategy that found the items
#: and the similar items.
SimilarItems = namedtuple('SimilarItems', ['strategy', 'items'])


def _field_filter(field, expected):
    if callable(expected):
        return lambda item: expected(item.get(field))
    return lambda item: item.get(field) == expected


def get_similar_items(lib, item, strategies=None, query=None,
                      predicate=None, all_strategies=False, log=None,
                      **field_filters):
    """Find the library items similar to ``item`` (``item`` itself is
    never returned).

    ``strategies``: strategies to try, by order of priority, as
    :class:`Strategy` objects or names (default: all the built-in
    :data:`STRATEGIES`). Strategies whose required plugin is not loaded or
    whose fields are not set on ``item`` are skipped.

    Candidates may be filtered with:

    * ``query``: a beets query (string, list of strings or query object),
    * ``predicate``: a function ``candidate -> bool``,
    * ``field_filters``: ``field=value`` (the candidate's field must be
      equal to ``value``) or ``field=function`` (``function(value)`` must
      be true), e.g. ``format='FLAC'`` or
      ``bitrate=lambda b: b >= 320000``. Computed fields of other plugins
      may be used.

    Return the :class:`SimilarItems` found by the first strategy giving
    results, or ``None``. With ``all_strategies``, return the list of the
    :class:`SimilarItems` of every strategy giving results (an item is
    only returned by the first strategy finding it).
    """
    if strategies is None:
        strategies = STRATEGIES
    strategies = [get_strategy(s) if isinstance(s, str) else s
                  for s in strategies]
    filters = [_field_filter(f, v) for f, v in field_filters.items()]
    if predicate is not None:
        filters.append(predicate)
    allowed = None
    if query is not None:
        allowed = set(i.id for i in lib.items(query))

    results, seen = [], set()
    for strategy in strategies:
        if not strategy.available():
            if log is not None:
                log.debug(u'similarity strategy {0} skipped: plugin {1} '
                          u'not loaded', strategy.name, strategy.requires)
            continue
        if not strategy.applies_to(item):
            continue
        found = []
        for candidate in lib.items(strategy.query(item)):
            if (candidate.id == item.id or candidate.id in seen
                    or (allowed is not None and candidate.id not in allowed)
                    or not strategy.match(item, candidate)
                    or not all(f(candidate) for f in filters)):
                continue
            found.append(candidate)
        if found:
            if not all_strategies:
                return SimilarItems(strategy, found)
            seen.update(i.id for i in found)
            results.append(SimilarItems(strategy, found))
    return results if all_strategies else None


#: camelCase alias.
getSimilarItems = get_similar_items
