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
#
# Scalers originally written by Jean-Philippe Hautin for
# https://github.com/jphautin/beets-userrating (GNU GPL v3.0).

"""Scalers convert raw rating values stored by a given player/format
from/to the internal beets rating scale (integers between 0 and 10).

To support a new player storing its rating in a POPM frame, create a
:class:`Scaler` whose ``name`` is the POPM "email" used by the player and
register it in :data:`PLAYERS`.
"""

from .ratings import MAX_RATING, MIN_RATING


class Scaler(object):
    """Scale a value from/to a specific player to/from a value usable for
    the rating, whose range is 0-10.

    ``name`` is the identifier of the player in the file (e.g. the POPM
    email).
    """
    MAX_ACCEPTED_VALUE = MAX_RATING

    def __init__(self, name, max_value=255):
        self.name = name
        self.max_value = max_value

    def scale(self, popm_value):
        """Scale a raw value stored by another player to the internal value
        (0-10). The raw value range depends on player and media type.
        """
        value = round(popm_value / self.max_value * Scaler.MAX_ACCEPTED_VALUE)
        return max(MIN_RATING, min(MAX_RATING, value))

    def unscale(self, userrating_value):
        """Scale an internal value (0-10) to a value understandable by the
        player.
        """
        return round(userrating_value * self.max_value
                     / Scaler.MAX_ACCEPTED_VALUE)


class TableScaler(Scaler):
    """Scaler using a lookup table ``internal value -> raw value`` (index
    is the internal value), falling back to linear scaling for raw values
    not in the table.
    """
    _rating_table = []

    def scale(self, popm_value):
        try:
            return self._rating_table.index(popm_value)
        except ValueError:
            return super(TableScaler, self).scale(popm_value)

    def unscale(self, userrating_value):
        try:
            return self._rating_table[userrating_value]
        except (IndexError, TypeError):
            return super(TableScaler, self).unscale(userrating_value)


class Mp3BeetsScaler(Scaler):
    """Scaler for the POPM frames written by beets for its users
    (email ``beets-<user>``).

    POPM value 0 means "unrated" so a 0 rating explicitly set by a user is
    stored as 1 (which is scaled back to 0) to keep it distinct from a null
    rating.
    """
    EMAIL_PREFIX = u'beets-'

    def __init__(self, user=None):
        super(Mp3BeetsScaler, self).__init__(self.email(user or u''))

    @classmethod
    def email(cls, user):
        return cls.EMAIL_PREFIX + user

    def unscale(self, userrating_value):
        return max(1, super(Mp3BeetsScaler, self).unscale(userrating_value))


class Mp3WindowsMediaPlayerScaler(TableScaler):
    """Windows Media Player 9, 10, 11, 12 compliant scaler::

        0 → POPM=0 (unrated)
        1 → POPM=1
        2 → POPM=64
        3 → POPM=128
        4 → POPM=196
        5 → POPM=255
    """
    _rating_table = [0, 0, 1, 1, 64, 64, 128, 128, 196, 196, 255]

    def __init__(self):
        super(Mp3WindowsMediaPlayerScaler, self).__init__(
            u'Windows Media Player 9 Series')


class Mp3BansheeScaler(Scaler):
    """Scaler to be able to manage Banshee rating.

    source: https://gitlab.gnome.org/GNOME/banshee/blob/master/src/Core/Banshee.Core/Banshee.Streaming/StreamRatingTagger.cs#L66-67
    """

    def __init__(self):
        super(Mp3BansheeScaler, self).__init__(u'Banshee')

    def scale(self, popm_value):
        if popm_value <= 0:
            return 0
        if popm_value < 64:
            return 2
        if popm_value < 128:
            return 4
        if popm_value < 192:
            return 6
        if popm_value < 255:
            return 8
        return 10

    def unscale(self, userrating_value):
        if userrating_value <= 1:
            return 0
        if userrating_value <= 3:
            return 1
        if userrating_value <= 5:
            return 64
        if userrating_value <= 7:
            return 128
        if userrating_value < 10:
            return 192
        if userrating_value == 10:
            return 255
        return 0


class Mp3MediaMonkeyScaler(Scaler):
    """Scaler to be able to manage MediaMonkey rating (linear scaling).

    source: https://gitlab.gnome.org/GNOME/banshee/blob/master/src/Core/Banshee.Core/Banshee.Streaming/StreamRatingTagger.cs#L60-62
    0.5=26, 1=51, 1.5=76, 2=102, 2.5=128, 3=153, 3.5=178, 4=204, 4.5=230, 5=255
    """

    def __init__(self):
        super(Mp3MediaMonkeyScaler, self).__init__(u'no@email')


class Mp3QuodlibetScaler(Scaler):
    def __init__(self):
        super(Mp3QuodlibetScaler, self).__init__(
            u'quodlibet@lists.sacredchao.net')


class Mp3WinampScaler(Scaler):
    def __init__(self):
        super(Mp3WinampScaler, self).__init__(u'rating@winamp.com')


class VorbisQuodlibetScaler(Scaler):
    """Quod Libet stores ``RATING:<email>`` in Vorbis comments as a float
    between 0.0 and 1.0.
    """

    def __init__(self):
        super(VorbisQuodlibetScaler, self).__init__(
            u'quodlibet@lists.sacredchao.net', max_value=1.0)

    @property
    def key(self):
        return u'rating:' + self.name

    def scale(self, popm_value):
        return super(VorbisQuodlibetScaler, self).scale(float(popm_value))

    def unscale(self, userrating_value):
        return u'{0:g}'.format(userrating_value / Scaler.MAX_ACCEPTED_VALUE)


class AsfWindowsMediaPlayerScaler(TableScaler):
    """Windows Media Player ``WM/SharedUserRating`` attribute in ASF/WMA
    files (0=unrated, 1, 25, 50, 75, 99).
    """
    _rating_table = [0, 0, 1, 1, 25, 25, 50, 50, 75, 75, 99]

    def __init__(self):
        super(AsfWindowsMediaPlayerScaler, self).__init__(
            u'Windows Media Player', max_value=99)

    @property
    def key(self):
        return u'WM/SharedUserRating'


class Player(object):
    """An external music player and the scalers used to read/write its
    ratings, per tag format.
    """

    def __init__(self, name, popm=None, vorbis=None, asf=None):
        self.name = name
        self.popm = popm
        self.vorbis = vorbis
        self.asf = asf


#: Supported external players, by name. Keys are the names to be used
#: in the ``external_music_players`` and ``sync_external_ratings``
#: options.
PLAYERS = dict((player.name, player) for player in (
    Player(u'Banshee', popm=Mp3BansheeScaler()),
    Player(u'Winamp', popm=Mp3WinampScaler()),
    Player(u'WMP', popm=Mp3WindowsMediaPlayerScaler(),
           asf=AsfWindowsMediaPlayerScaler()),
    Player(u'MediaMonkey', popm=Mp3MediaMonkeyScaler()),
    Player(u'Quodlibet', popm=Mp3QuodlibetScaler(),
           vorbis=VorbisQuodlibetScaler()),
))


def find_player(name):
    """Return the :class:`Player` named ``name`` (case-insensitive), or
    ``None``."""
    for key, player in PLAYERS.items():
        if key.lower() == str(name).strip().lower():
            return player
    return None
