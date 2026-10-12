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

"""Per-user ratings model, human-friendly parsing/formatting, and the
dbcore type and query used to store and search ratings in the beets
library.

Nothing in this module is specific to items: the same type and query can
be registered for albums (``album_types``) once album ratings are
supported.
"""

import ast
import json
import re
from collections.abc import Mapping

from beets.dbcore import query, types

MIN_RATING = 0
MAX_RATING = 10

DEFAULT_USER = 'defaultUser'

# User names end up in tags (``beets-<user>``), template fields
# (``${userrating[<user>]}``) and in the human-friendly syntax, so they
# must not contain separators used by those formats.
_USER_RE = re.compile(r'^[A-Za-z0-9_.@+-]+$')
_NONE_WORDS = ('none', 'null', 'unrated')
_ANY_WORDS = ('', '*', 'any')
_RANGE_RE = re.compile(r'^(-?\d+)?\.\.(-?\d+)?$')
_SPLIT_RE = re.compile(r'[,;]')


class RatingError(ValueError):
    """Raised when a rating or user name can not be parsed."""


def _looks_like_value(text):
    text = text.strip().lower()
    return (text in _NONE_WORDS or text in _ANY_WORDS
            or bool(_RANGE_RE.match(text)) or _is_number(text))


def _is_number(text):
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def validate_user(user):
    """Return the stripped user name or raise :class:`RatingError`."""
    if not isinstance(user, str):
        raise RatingError(u'invalid user name {0!r}'.format(user))
    user = user.strip()
    if not _USER_RE.match(user) or _looks_like_value(user):
        raise RatingError(
            u'invalid user name {0!r} (allowed: ASCII letters, digits, '
            u'".", "_", "@", "+" and "-"; must not look like a rating)'
            .format(user))
    return user


def validate_rating(value):
    """Return ``value`` as an integer rating in ``[MIN_RATING, MAX_RATING]``
    or ``None`` for a null rating. Raise :class:`RatingError` otherwise.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise RatingError(u'invalid rating {0!r}'.format(value))
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in _NONE_WORDS:
            return None
        try:
            value = float(text)
        except ValueError:
            raise RatingError(u'invalid rating {0!r}'.format(value))
    if isinstance(value, float):
        if not value.is_integer():
            raise RatingError(u'rating {0!r} is not an integer'.format(value))
        value = int(value)
    if not isinstance(value, int):
        raise RatingError(u'invalid rating {0!r}'.format(value))
    if not MIN_RATING <= value <= MAX_RATING:
        raise RatingError(u'rating {0} is out of range [{1}-{2}]'.format(
            value, MIN_RATING, MAX_RATING))
    return value


def tokenize(text):
    """Split a human-written ratings string into ``(user, value)`` pairs.

    ``user`` is ``None`` when the token only holds a value (meaning the
    default user) and ``value`` is ``None`` when only a user name is
    given. Supported syntaxes::

        4
        user1:3      user1: 3      user1=3
        user1:3, user2:4           user1:3; user2:4
        {'user1': 3, 'user2': 4}   {"user1": 3}
    """
    if isinstance(text, bytes):
        text = text.decode('utf-8', 'ignore')
    text = text.strip()
    if text.startswith('{'):
        try:
            data = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            raise RatingError(u'invalid ratings dictionary {0!r}'.format(text))
        if not isinstance(data, dict):
            raise RatingError(u'invalid ratings dictionary {0!r}'.format(text))
        return [(str(k), v if v is None or isinstance(v, (int, float))
                 else str(v)) for k, v in data.items()]
    tokens = []
    for part in _SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        match = re.match(r'^([^:=]*)[:=](.*)$', part)
        if match:
            tokens.append((match.group(1).strip(), match.group(2).strip()))
        elif _looks_like_value(part):
            tokens.append((None, part))
        else:
            tokens.append((part, None))
    return tokens


class UserRatings(dict):
    """A mapping ``user -> rating`` (integer between 0 and 10).

    A user without a rating is simply absent (null rating), which is
    different from a ``0`` rating explicitly set by the user.

    The constructor accepts another mapping, a single number (rating of
    the default user) or any human-friendly string understood by
    :func:`tokenize`, as well as the JSON form used for storage.
    """

    #: The user whose rating is exposed by ``$userrating`` and used for
    #: queries/assignments without an explicit user. Set by the plugin.
    default_user = DEFAULT_USER

    def __init__(self, value=None):
        super().__init__()
        if value is None:
            return
        if isinstance(value, Mapping):
            pairs = list(value.items())
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            pairs = [(None, value)]
        elif isinstance(value, (str, bytes)):
            pairs = tokenize(value)
        else:
            raise RatingError(u'invalid ratings {0!r}'.format(value))
        for user, rating in pairs:
            if user is None or (isinstance(user, str) and not user.strip()):
                user = self.default_user
            user = validate_user(user)
            rating = validate_rating(rating)
            if rating is None:
                self.pop(user, None)
            else:
                self[user] = rating

    @property
    def default(self):
        """Rating of the default user (``None`` if unrated)."""
        return self.get(self.default_user)

    def copy(self):
        return UserRatings(self)

    def to_json(self):
        return json.dumps(dict(sorted(self.items())), sort_keys=True)

    def __str__(self):
        return format_ratings(self)

    def __repr__(self):
        return 'UserRatings({0})'.format(dict.__repr__(self))

    # Sorting (``beet ls userrating+``) orders by the default user's rating,
    # unrated items first.
    def _sort_key(self):
        rating = self.default
        return -1 if rating is None else rating

    def __lt__(self, other):
        if not isinstance(other, UserRatings):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __gt__(self, other):
        if not isinstance(other, UserRatings):
            return NotImplemented
        return self._sort_key() > other._sort_key()

    __hash__ = None


def format_ratings(ratings, users=None):
    """Human-friendly representation: ``user1:3, user2:4``.

    The output can be parsed back by :class:`UserRatings`.
    """
    if not ratings:
        return u''
    keys = users if users is not None else sorted(ratings)
    return u', '.join(u'{0}:{1}'.format(user, ratings[user])
                      for user in keys if user in ratings)


class RatingCondition(object):
    """A condition on the rating of one user used by queries."""

    ANY = 'any'
    NONE = 'none'
    RANGE = 'range'

    def __init__(self, kind, low=None, high=None):
        self.kind = kind
        self.low = low
        self.high = high

    @classmethod
    def parse(cls, value):
        if value is None:
            return cls(cls.ANY)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            rating = validate_rating(value)
            return cls(cls.RANGE, rating, rating)
        text = str(value).strip().lower()
        if text in _ANY_WORDS:
            return cls(cls.ANY)
        if text in _NONE_WORDS:
            return cls(cls.NONE)
        match = _RANGE_RE.match(text)
        if match:
            low = validate_rating(match.group(1)) if match.group(1) else None
            high = validate_rating(match.group(2)) if match.group(2) else None
            return cls(cls.RANGE, low, high)
        rating = validate_rating(text)
        return cls(cls.RANGE, rating, rating)

    def matches(self, rating):
        if self.kind == self.ANY:
            return rating is not None
        if self.kind == self.NONE:
            return rating is None
        if rating is None:
            return False
        if self.low is not None and rating < self.low:
            return False
        if self.high is not None and rating > self.high:
            return False
        return True


def parse_query_pattern(pattern):
    """Parse a query pattern into a ``{user: RatingCondition}`` dict.

    An empty pattern returns an empty dict meaning "rated by anyone".
    """
    conditions = {}
    for user, value in tokenize(pattern or u''):
        if user is None or not user.strip():
            user = UserRatings.default_user
        conditions[validate_user(user)] = RatingCondition.parse(value)
    return conditions


def as_ratings(value):
    """Coerce a model value (possibly ``None``) to :class:`UserRatings`."""
    if isinstance(value, UserRatings):
        return value
    if not value:
        return UserRatings()
    try:
        return UserRatings(value)
    except RatingError:
        return UserRatings()


class UserRatingQuery(query.FieldQuery):
    """Query per-user ratings.

    Examples of patterns: ``4`` (default user), ``3..5``, ``user1:3``,
    ``user1: 3, user2:4``, ``{'user2':4,'user1': 3}``, ``user1:none``
    (not rated by user1), ``user1`` (rated by user1), empty (rated by
    anyone). All conditions must match.
    """

    def __init__(self, field_name, pattern, fast=True):
        # Ratings are stored as a flexible attribute: always a slow query.
        super().__init__(field_name, pattern, False)
        try:
            self.conditions = parse_query_pattern(pattern)
        except RatingError as exc:
            raise query.InvalidQueryArgumentValueError(
                pattern, u'a valid user rating query', str(exc))

    @classmethod
    def _match(cls, conditions, value):
        ratings = as_ratings(value)
        if not conditions:
            return bool(ratings)
        return all(cond.matches(ratings.get(user))
                   for user, cond in conditions.items())

    @classmethod
    def value_match(cls, pattern, value):
        try:
            conditions = parse_query_pattern(pattern)
        except RatingError:
            return False
        return cls._match(conditions, value)

    def match(self, obj):
        return self._match(self.conditions, obj.get(self.field_name))


class UserRatingsType(types.Type):
    """dbcore type for :class:`UserRatings`.

    Stored as JSON in the database. Formatting (``$userrating``) shows
    the default user's rating only; parsing accepts any syntax understood
    by :class:`UserRatings`. Legacy plain integer values (from previous
    versions of this plugin) are read as the default user's rating.
    """

    sql = u'TEXT'
    query = UserRatingQuery
    model_type = UserRatings

    @property
    def null(self):
        return UserRatings()

    def format(self, value):
        rating = as_ratings(value).default
        return u'' if rating is None else str(rating)

    def parse(self, string):
        try:
            return UserRatings(string)
        except RatingError as exc:
            from .compat import UserError
            raise UserError(u'userrating: {0}'.format(exc))

    def normalize(self, value):
        if value is None:
            return self.null
        if isinstance(value, UserRatings):
            return value
        return UserRatings(value)

    def from_sql(self, sql_value):
        if isinstance(sql_value, memoryview):
            sql_value = bytes(sql_value).decode('utf-8', 'ignore')
        if sql_value is None:
            return self.null
        if isinstance(sql_value, str) and sql_value.strip().startswith('{'):
            try:
                return UserRatings(json.loads(sql_value))
            except (ValueError, RatingError):
                pass
        try:
            return UserRatings(sql_value)
        except RatingError:
            return self.null

    def to_sql(self, model_value):
        if model_value is None:
            return None
        return as_ratings(model_value).to_json()


USER_RATINGS_TYPE = UserRatingsType()
