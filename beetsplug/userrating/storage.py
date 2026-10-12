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

"""Read and write per-user ratings in media files.

Storage formats
---------------

* ID3v2 (MP3, AIFF, WAV...): one Popularimeter (``POPM``) frame per beets
  user, whose "email" is ``beets-<user>``. Values are 0-255 (a 0 rating
  is stored as POPM 0). POPM frames of other players are left untouched
  unless they are synchronized.
* In all formats, an unrated user has no tag at all: there is no stored
  value for "unrated", which keeps it distinct from a 0 rating.
* Vorbis comments (FLAC, Ogg Vorbis, Opus, Speex), APEv2 (Musepack,
  WavPack, Monkey's Audio) and ASF (WMA): one ``RATING:beets-<user>`` tag
  per user holding the rating as a plain 0-10 integer. This mimics the
  ``RATING:<email>`` convention used by Quod Libet for Vorbis comments.
* M4A (AAC, ALAC): one freeform atom
  ``----:com.apple.iTunes:RATING:beets-<user>`` per user holding the
  rating as a plain 0-10 integer. Other MP4 container files (``.mp4``
  videos, ``.m4b``...) are not supported: their ratings are neither read
  nor written.
* Optionally, all formats: a marker appended to the comments tag, like
  ``[beets-userrating: user1=3, user2=4]``.
"""

import os
import re

from mutagen import MutagenError
from mutagen._vorbis import VComment
from mutagen.apev2 import APEv2
from mutagen.asf import ASFDWordAttribute, ASFTags
from mutagen.id3 import ID3, POPM
from mutagen.mp4 import MP4, AtomDataType, MP4FreeForm, MP4Tags

try:
    import mediafile
except ImportError:  # pragma: no cover - old beets bundling mediafile
    from beets import mediafile

from .ratings import RatingError, UserRatings, validate_rating, validate_user
from .scalers import PLAYERS, Mp3BeetsScaler

BEETS_PREFIX = Mp3BeetsScaler.EMAIL_PREFIX
TEXT_TAG_PREFIX = u'RATING:' + BEETS_PREFIX
MP4_TAG_PREFIX = u'----:com.apple.iTunes:' + TEXT_TAG_PREFIX

COMMENTS_NO = u'no'
COMMENTS_YES = u'yes'
COMMENTS_ONLY = u'only'

COMMENT_MARKER = u'beets-userrating'
_COMMENT_RE = re.compile(r'\[' + re.escape(COMMENT_MARKER) + r':([^\]]*)\]')
# The marker and the blanks/line break separating it from the comment.
_COMMENT_REMOVE_RE = re.compile(r'[ \t]*\n?[ \t]*' + _COMMENT_RE.pattern)

#: Extensions of the supported MP4 container files.
MP4_EXTENSIONS = (u'.m4a',)

#: Errors that may be raised while reading/writing a media file.
FILE_ERRORS = (mediafile.UnreadableFileError, MutagenError, OSError)

_BEETS_SCALER = Mp3BeetsScaler()


class UnsupportedFormatError(Exception):
    """The ratings of this media file can not be stored."""


class FileRatings(object):
    """Ratings found in a media file.

    ``beets``: ratings of beets users found in rating tags,
    ``players``: ratings of external players, by player name,
    ``comment``: ratings of beets users found in the comments marker.
    """

    def __init__(self, beets=None, players=None, comment=None):
        self.beets = beets or {}
        self.players = players or {}
        self.comment = comment or {}

    def users(self):
        """Ratings of beets users (rating tags take precedence over the
        comments marker)."""
        ratings = dict(self.comment)
        ratings.update(self.beets)
        return ratings

    def __repr__(self):
        return 'FileRatings(beets={0!r}, players={1!r}, comment={2!r})'.format(
            self.beets, self.players, self.comment)


def _resolve_user(name, known_users):
    """Restore the case of user names read from case-insensitive tag
    formats (e.g. Vorbis comments keys are lowercased)."""
    for user in known_users:
        if user.lower() == name.lower():
            return user
    return name


def _raw_text(value):
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, MP4FreeForm):
        return bytes(value).decode('utf-8', 'ignore')
    value = getattr(value, 'value', value)
    if isinstance(value, bytes):
        return value.decode('utf-8', 'ignore')
    return value


def _parse_text_rating(raw):
    try:
        return validate_rating(str(raw))
    except RatingError:
        return None


# ID3 / POPM ---------------------------------------------------------------

def _id3_read(tags, known_users):
    beets, players = {}, {}
    for frame in tags.getall('POPM'):
        email, raw = frame.email, frame.rating
        if email.startswith(BEETS_PREFIX):
            try:
                user = validate_user(email[len(BEETS_PREFIX):])
            except RatingError:
                continue
            beets[_resolve_user(user, known_users)] = _BEETS_SCALER.scale(raw)
            continue
        for player in PLAYERS.values():
            scaler = player.popm
            if scaler is not None and scaler.name == email:
                if raw or not scaler.ZERO_IS_UNRATED:
                    players[player.name] = scaler.scale(raw)
    return beets, players


def _popm_set(tags, email, raw):
    existing = tags.get(u'POPM:' + email)
    kwargs = {}
    count = getattr(existing, 'count', None)
    if count is not None:
        kwargs['count'] = count
    tags.add(POPM(email=email, rating=raw, **kwargs))


def _id3_write_users(tags, ratings):
    for frame in list(tags.getall('POPM')):
        if (frame.email.startswith(BEETS_PREFIX)
                and frame.email[len(BEETS_PREFIX):] not in ratings):
            tags.delall(frame.HashKey)
    for user, rating in ratings.items():
        _popm_set(tags, Mp3BeetsScaler.email(user),
                  _BEETS_SCALER.unscale(rating))


def _id3_write_player(tags, player, rating):
    if player.popm is None:
        return False
    email = player.popm.name
    if rating is None:
        tags.delall(u'POPM:' + email)
    else:
        _popm_set(tags, email, player.popm.unscale(rating))
    return True


# Text tags (Vorbis comments, APEv2, ASF) ----------------------------------

def _text_read(tags, known_users, player_attr):
    beets, players = {}, {}
    prefix = TEXT_TAG_PREFIX.lower()
    for key in list(tags.keys()):
        if key.lower().startswith(prefix):
            try:
                user = validate_user(key[len(prefix):])
            except RatingError:
                continue
            rating = _parse_text_rating(_raw_text(tags[key]))
            if rating is not None:
                beets[_resolve_user(user, known_users)] = rating
    for player in PLAYERS.values():
        scaler = getattr(player, player_attr) if player_attr else None
        if scaler is None:
            continue
        for key in list(tags.keys()):
            if key.lower() == scaler.key.lower():
                raw = _raw_text(tags[key])
                try:
                    value = float(raw)
                    if value > 0 or (value == 0
                                     and not scaler.ZERO_IS_UNRATED):
                        players[player.name] = scaler.scale(raw)
                except (TypeError, ValueError):
                    pass
                break
    return beets, players


def _text_write_users(tags, ratings, as_list):
    prefix = TEXT_TAG_PREFIX.lower()
    for key in list(tags.keys()):
        if key.lower().startswith(prefix):
            del tags[key]
    for user, rating in ratings.items():
        value = str(rating)
        tags[TEXT_TAG_PREFIX + user] = [value] if as_list else value


def _text_write_player(tags, player, rating, player_attr):
    scaler = getattr(player, player_attr) if player_attr else None
    if scaler is None:
        return False
    for key in list(tags.keys()):
        if key.lower() == scaler.key.lower():
            del tags[key]
    if rating is not None:
        raw = scaler.unscale(rating)
        if isinstance(tags, ASFTags):
            tags[scaler.key] = [ASFDWordAttribute(raw)]
        else:
            tags[scaler.key] = [str(raw)]
    return True


# MP4 ----------------------------------------------------------------------

def _mp4_read(tags, known_users):
    beets = {}
    for key in list(tags.keys()):
        if key.startswith(MP4_TAG_PREFIX):
            try:
                user = validate_user(key[len(MP4_TAG_PREFIX):])
            except RatingError:
                continue
            rating = _parse_text_rating(_raw_text(tags[key]))
            if rating is not None:
                beets[_resolve_user(user, known_users)] = rating
    return beets, {}


def _mp4_write_users(tags, ratings):
    for key in list(tags.keys()):
        if key.startswith(MP4_TAG_PREFIX):
            del tags[key]
    for user, rating in ratings.items():
        tags[MP4_TAG_PREFIX + user] = [MP4FreeForm(
            str(rating).encode('utf-8'), dataformat=AtomDataType.UTF8)]


# Dispatch -----------------------------------------------------------------

def _player_attr(tags):
    if isinstance(tags, VComment):
        return 'vorbis'
    if isinstance(tags, ASFTags):
        return 'asf'
    return None


def read_tags(tags, known_users=()):
    """Return ``(beets_ratings, player_ratings)`` read from a mutagen tags
    object."""
    if tags is None:
        return {}, {}
    if isinstance(tags, ID3):
        return _id3_read(tags, known_users)
    if isinstance(tags, MP4Tags):
        return _mp4_read(tags, known_users)
    if isinstance(tags, (VComment, APEv2, ASFTags)):
        return _text_read(tags, known_users, _player_attr(tags))
    return {}, {}


def write_user_tags(tags, ratings):
    """Write beets users' ratings in a mutagen tags object. Ratings of
    beets users not in ``ratings`` are removed. Return ``False`` if the
    format is not supported."""
    if isinstance(tags, ID3):
        _id3_write_users(tags, ratings)
    elif isinstance(tags, MP4Tags):
        _mp4_write_users(tags, ratings)
    elif isinstance(tags, (VComment, APEv2, ASFTags)):
        _text_write_users(tags, ratings, as_list=not isinstance(tags, APEv2))
    else:
        return False
    return True


def write_player_tag(tags, player, rating):
    """Write (or remove if ``rating`` is ``None``) the rating of an
    external player. Return ``False`` if the player does not support the
    format."""
    if isinstance(tags, ID3):
        return _id3_write_player(tags, player, rating)
    if isinstance(tags, (VComment, ASFTags)):
        return _text_write_player(tags, player, rating, _player_attr(tags))
    return False


# Comments -----------------------------------------------------------------

def read_comment_ratings(comment, known_users=()):
    """Return the ratings found in the plugin marker of a comment."""
    if not comment:
        return {}
    match = _COMMENT_RE.search(comment)
    if not match:
        return {}
    try:
        ratings = UserRatings(match.group(1))
    except RatingError:
        return {}
    return dict((_resolve_user(user, known_users), rating)
                for user, rating in ratings.items())


def format_comment_marker(ratings):
    return u'[{0}: {1}]'.format(COMMENT_MARKER, u', '.join(
        u'{0}={1}'.format(user, ratings[user]) for user in sorted(ratings)))


def update_comment(comment, ratings):
    """Return ``comment`` with the plugin marker added, updated or (when
    ``ratings`` is empty) removed. The rest of the comment is kept as-is.
    """
    comment = comment or u''
    if ratings:
        marker = format_comment_marker(ratings)
        if _COMMENT_RE.search(comment):
            return _COMMENT_RE.sub(lambda m: marker, comment, count=1)
        if comment.strip():
            return comment.rstrip() + u'\n' + marker
        return marker
    return _COMMENT_REMOVE_RE.sub(u'', comment)


# Files --------------------------------------------------------------------

def is_supported(path, mgfile):
    """Whether ratings can be stored in the (mutagen) file: MP4
    container files are only supported as ``.m4a`` audio files."""
    if isinstance(mgfile, MP4):
        ext = os.path.splitext(os.fsdecode(path))[1].lower()
        return ext in MP4_EXTENSIONS
    return True


def _open(path, id3v23=False):
    """Open a media file, raising :class:`UnsupportedFormatError` if
    ratings can not be stored in it."""
    mf = mediafile.MediaFile(path, id3v23=id3v23)
    if not is_supported(path, mf.mgfile):
        raise UnsupportedFormatError(
            u'unsupported file format: {0}'.format(os.fsdecode(path)))
    return mf


def read_file(path, known_users=()):
    """Read all the ratings of a media file as :class:`FileRatings`.

    May raise :class:`UnsupportedFormatError` or one of
    :data:`FILE_ERRORS`.
    """
    mf = _open(path)
    beets, players = read_tags(mf.mgfile.tags, known_users)
    comment = read_comment_ratings(mf.comments, known_users)
    return FileRatings(beets, players, comment)


def write_file(path, ratings, default_user, sync_players=(),
               comments=COMMENTS_NO, id3v23=False):
    """Write ``ratings`` (``user -> rating``) to a media file.

    * beets users' rating tags are updated (unless ``comments`` is
      ``only``); ratings of beets users not in ``ratings`` are removed,
      other players' tags are kept as-is,
    * the ``default_user`` rating is copied to the rating tags of the
      players in ``sync_players`` (removed if the default user is not
      rated),
    * the comments marker is added/updated if ``comments`` is ``yes`` or
      ``only``.

    May raise :class:`UnsupportedFormatError` or one of
    :data:`FILE_ERRORS`.
    """
    mf = _open(path, id3v23=id3v23)
    mgfile = mf.mgfile
    if mgfile.tags is None:
        mgfile.add_tags()
    tags = mgfile.tags
    if comments != COMMENTS_ONLY:
        write_user_tags(tags, ratings)
        for name in sync_players:
            player = PLAYERS.get(name)
            if player is not None:
                write_player_tag(tags, player, ratings.get(default_user))
    if comments in (COMMENTS_YES, COMMENTS_ONLY):
        current = mf.comments
        updated = update_comment(current, ratings)
        if updated != (current or u''):
            mf.comments = updated or None
    mf.save()
