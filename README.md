# Per-user rating support for Beets

The *userrating* plugin manages **per-user track ratings** in your
[beets](https://beets.io) library and in your music files.

* ratings are integers from `0` to `10`, stored per user
  (e.g. `userrating["djhibee"] = 8`);
* a user who did not rate a track has a *null* rating, which is different
  from a `0` rating explicitly set by the user: a `0` rating is stored
  like any other rating, while nothing at all is stored for an unrated
  track (no library attribute, no file tag);
* ratings can be queried, displayed and modified with human-friendly
  syntaxes;
* ratings are imported from / written to the files (ID3 `POPM` frames,
  Vorbis comments, M4A atoms, ASF attributes and optionally the comments
  tag), including ratings of external players (Banshee, Winamp, Windows
  Media Player, MediaMonkey, Quod Libet);
* ratings can be proposed for unrated tracks based on the ratings of
  similar tracks of the library (`autorate`).

Album ratings are not supported yet (the design allows adding them later).

This plugin is based on the work of Jean-Philippe Hautin
([jphautin/beets-userrating](https://github.com/jphautin/beets-userrating)),
itself based on the work of Michael Dorman. It is released under the
[GNU General Public License v3.0](LICENSE).

## Installation

Requires beets 2.0 or later (Python 3.9+).

    $ pip install https://github.com/djhibee/beets-userrating/archive/master.zip

Add the plugin to the beets configuration file:

```yaml
plugins: (...) userrating
```

## Configuration

```yaml
userrating:
    # Fetch ratings from the files at import.
    auto: yes
    # Overwrite an existing rating (at import, with --modify/--import).
    # Default is to skip already rated items. Overridden by -f/--no-force.
    force: no
    # Write ratings to the files: null (default) follows the beets
    # `import.write` option, yes/no override it for this plugin.
    # Overridden by -w/-W.
    write: null
    # Known beets users. Used to restore the case of user names read from
    # case-insensitive tag formats (Vorbis comments, APEv2) and as a
    # fallback for default_user.
    beets_users: [defaultUser]
    # Beets user selected for players not handling multiple users and when
    # no -u/--user option is given. Defaults to the first beets_users.
    default_user: null
    # External players to import ratings from (for the default user, when
    # no beets rating is found in the file), by order of priority.
    # Supported: Banshee, Winamp, WMP, MediaMonkey, Quodlibet.
    external_music_players: [Banshee, Winamp, WMP]
    # Players whose rating is synchronized with the default user's rating
    # when writing files: null (none), all (all external_music_players) or
    # a list of players.
    sync_external_ratings: null
    # Also store the ratings in the comments tag: no, yes or only.
    write_in_comments: no
    # Propose ratings for unrated tracks (see "Automatic rating proposals").
    autorate:
        # Propose ratings at import.
        auto: no
        # User whose ratings are proposed (default: default_user).
        user: null
        # Similarity strategies (the "same artist and title" one is always
        # enabled). A strategy of a group is used only when both the group
        # option and its own option are enabled.
        mbtrackid: yes              # group: both MusicBrainz strategies
        mb_releasetrackid: yes      #   same MusicBrainz release track
        mb_trackid: yes             #   same MusicBrainz recording
        acoustid: yes               # group: both AcoustID strategies
        acoustid_id: yes            #   same AcoustID
        acoustid_fingerprint: yes   #   same AcoustID fingerprint
        bareascii: no       # same artist and title in bare ASCII (bareasc plugin)
        fuzzy: no           # fuzzily matching artist and title (fuzzy plugin)
        # Review all the proposals at once, at the end of the import or
        # command, instead of one track at a time.
        global_review: no
```

## Usage

### Queries

The `userrating` field can be queried with human-friendly formats:

    beet list userrating:4                           # default user rated 4
    beet list userrating:"user1: 3"
    beet list userrating:user1:3
    beet list userrating:"{'user1':3}"
    beet list userrating:"{'user2':4,'user1': 3}"     # all conditions must match
    beet list userrating:"user1:3, user2:4"
    beet list userrating:3..5                        # ranges: 3..5, 3.., ..5
    beet list userrating:user1                       # rated by user1
    beet list userrating:user1:none                  # not rated by user1
    beet list userrating:                            # rated by anyone
    beet list ^userrating:                           # rated by nobody
    beet list userrating-                            # sort by default user's rating
    beet remove userrating:"user1: 1"

### Display

    beet ls -f '$title $userrating'                  # default user's rating
    beet ls -f '$title $userratings'                 # all ratings: "djhibee:8, toto:4"
    beet ls -f '$title ${userrating[djhibee]}'       # rating of a given user

Note that per-user fields need braces: `${userrating[djhibee]}`
(`$userrating[djhibee]` would be read as `$userrating` followed by the
text `[djhibee]`). Unrated values are displayed as an empty string.

Per-user fields are available for the `beets_users` and for every user
having ratings in the library. To keep startup fast, the user names are
cached in a `userrating_users` table of the library database: the
library is scanned only once (when this table is created) and the cache
is then updated whenever ratings are stored. Users whose ratings were all
removed stay in the cache (their field is simply empty); drop the table
(`sqlite3 library.db 'DROP TABLE userrating_users'`) to rebuild it on
the next run.

### `beet modify`

Assignments (`field=value`) accept the same formats as queries but
**replace all the ratings** of the item:

    beet modify userrating="{'user2':4,'user1': 3}" QUERY
    beet modify userrating=5 QUERY                   # only default user rated 5
    beet modify userrating! QUERY                    # forget all ratings (files untouched)

Use `beet userrating --modify` to change the rating of some users only.

### `beet userrating` command

    beet userrating [options] [QUERY...]

| Option                 | Description |
| ---------------------- | ----------- |
| `-l`, `--list`         | list ratings (default action) |
| `-m`, `--modify`       | set ratings (`-r`) or delete them (`-d`) |
| `--remove`             | delete ratings (same as `--modify --delete`) |
| `-i`, `--import`       | import ratings from the files |
| `-u`, `--user USER`    | user (repeatable, default: `default_user`) |
| `-r`, `--rating VALUE` | rating from 0 to 10, or `none` (repeatable) |
| `-d`, `--delete`       | with `--modify`, delete the ratings |
| `-f`, `--force` / `--no-force` | overwrite existing ratings (overrides the `force` option) |
| `-w`, `--write` / `-W`, `--nowrite` | write / don't write ratings to the files (overrides the `write` options) |

Users and ratings are paired in order. When there are fewer of one than of
the other, the last one given is repeated:
`-u djhibee -u toto -u titi -r 2 -r 1` is equivalent to
`-u djhibee -r 2 -u toto -r 1 -u titi -r 1`.

Examples:

    beet userrating --modify --rating 5 QUERY        # default user rates 5
    beet userrating --modify -u djhibee -r 5 -u toto -r 4 QUERY
    beet userrating --modify -u djhibee -r 2 -f QUERY  # overwrite existing rating
    beet userrating --modify -u djhibee -d QUERY     # delete djhibee's rating
    beet userrating --remove -u toto QUERY           # same as --modify -u toto -d
    beet userrating --list                           # all users' ratings
    beet userrating --list -u djhibee                # djhibee's ratings
    beet userrating --list -u djhibee -r 5           # tracks rated 5 by djhibee
    beet userrating --import -f QUERY                # re-import ratings from files

## Storage in files

When ratings are changed by the plugin (or when beets writes tags, e.g.
`beet modify`, `beet write`, import with `write: yes`), ratings are written
to the files, unless disabled by the `write` options. The beets library is
the reference: ratings of beets users not in the library are removed from
the file. Tags of other players are kept as-is unless synchronized (see
`sync_external_ratings`).

Whatever the format, an unrated user has no tag at all in the file. For
external players, their own conventions are kept: POPM `0` and WMP's
`WM/SharedUserRating` `0` mean "unrated" for those players and are
ignored when reading, while Quod Libet's Vorbis `0.0` is a `0` rating.

| Format | Beets users | External players |
| ------ | ----------- | ---------------- |
| ID3v2 (MP3, AIFF, WAV) | one `POPM` frame per user, email `beets-<user>`, value 0-255 (a `0` rating is stored as POPM `0`; unrated users have no frame). The play counter is preserved. | `POPM` frames: `Banshee`, `rating@winamp.com` (Winamp), `Windows Media Player 9 Series` (WMP), `no@email` (MediaMonkey), `quodlibet@lists.sacredchao.net` (Quodlibet) |
| Vorbis comments (FLAC, Ogg, Opus) | `RATING:beets-<user>=<0-10>` | `RATING:quodlibet@lists.sacredchao.net` (Quodlibet, 0.0-1.0) |
| M4A (AAC, ALAC) | freeform atom `----:com.apple.iTunes:RATING:beets-<user>` = `<0-10>` | - |
| ASF (WMA) | attribute `RATING:beets-<user>` = `<0-10>` | `WM/SharedUserRating` (WMP) |
| APEv2 (Musepack, WavPack, Monkey's Audio) | `RATING:beets-<user>` = `<0-10>` | - |

Other MP4 container files (`.mp4`, `.m4b`, `.m4v`...) are not supported:
ratings are kept in the beets library but are neither read from nor
written to these files. Only `.m4a` files are handled.

User names may contain ASCII letters, digits, `.`, `_`, `@`, `+` and `-`.

With `write_in_comments: yes` (or `only`, which does not write the rating
tags), a marker is appended to the comments tag, or updated if already
present, without altering the rest of the comment:

    My own comment
    [beets-userrating: djhibee=8, toto=4]

### Importing ratings

At import (`auto: yes`) or with `beet userrating --import`, for each track:

1. ratings of beets users are read from the rating tags (and from the
   comments marker);
2. if the default user is not rated, the rating of the first external
   player of `external_music_players` found in the file is used for the
   default user;
3. existing ratings in the library are kept unless `force` is set.

### Implications

* Ratings are stored persistently in the music files: they are preserved
  when the files are removed from the library, moved or copied between
  machines. Former WMP, Vista, MediaMonkey, Banshee, Winamp or Quod Libet
  users get their ratings imported automatically.
* Players reading the embedded `POPM` tag only know one rating: use
  `sync_external_ratings` to copy the default user's rating to their tags.
  All users' ratings are only available to players/tools reading the
  beets tags or database.
* To support another player storing its rating in a `POPM` frame, add a
  scaler and a `Player` entry in `beetsplug/userrating/scalers.py`.

## Automatic rating proposals (autorate)

When a track has not been rated yet by a user, the plugin can propose a
rating based on the tracks of the library that are similar to it and that
this user already rated: the same song in another format, another release
of the same recording, a live version you probably like the same...

It runs at import (`autorate: {auto: yes}`) and with the `beet autorate`
command:

    beet autorate [QUERY]                 # review proposals for unrated tracks
    beet autorate -p [QUERY]              # pretend: only show the proposals
    beet autorate -y [QUERY]              # apply the proposed ratings without asking
    beet autorate -u toto [QUERY]         # propose toto's ratings
    beet autorate -g [QUERY]              # global review (all proposals at the end)
    beet autorate --fuzzy --no-acoustid   # enable/disable similarity strategies
    beet autorate --no-acoustid-fingerprint --no-mb-trackid  # ... individually
    beet autorate -w / -W                 # write / don't write ratings to files

### 1. Unrated tracks

The chosen user is the `-u/--user` option, otherwise the `autorate.user`
option, otherwise the `default_user`. A track is a candidate when this user
has no rating for it:

* not in the beets library,
* nor in its file: neither in the beets users' tags nor, for the default
  user, in the tags of the `external_music_players` (a track rated in its
  file is skipped with a hint to run `beet userrating --import`; at import
  with `auto: yes`, these ratings have just been imported).

### 2. Finding similar rated tracks

Similar tracks are looked for in the library with the following
strategies, by order of priority. Only the tracks rated by the chosen user
are considered (and never the track itself). The first strategy finding
at least one similar track wins; the next ones are not tried.

| # | Strategy | Finds | Option |
| - | -------- | ----- | ------ |
| 1 | same MusicBrainz release track id (`mb_releasetrackid`) | the same track of the same release, e.g. in another format | `mbtrackid` and `mb_releasetrackid` |
| 2 | same MusicBrainz recording id (`mb_trackid`) | the same recording on another release (compilation, reissue...) | `mbtrackid` and `mb_trackid` |
| 3 | same AcoustID (`acoustid_id`, set by the `chroma` plugin) | the same audio, even encoded differently: AcoustID groups the slightly different fingerprints of the same recording under one id | `acoustid` and `acoustid_id` |
| 4 | same AcoustID fingerprint (`acoustid_fingerprint`, set by the `chroma` plugin) | the same audio, when the AcoustID lookup gave no id (fingerprints of different encodings rarely match exactly) | `acoustid` and `acoustid_fingerprint` |
| 5 | same artist and title (case-insensitive) | albums imported as-is (no MusicBrainz ids), other albums, other versions of the song you potentially like the same | always |
| 6 | same artist and title in bare ASCII (accents removed, case-insensitive) | accents wrong in the library or in the CD information | `bareascii` (requires the `bareasc` plugin) |
| 7 | fuzzily matching artist and title: both `difflib` similarity ratios (lower-cased) must reach the `fuzzy` plugin's `threshold` (default 0.7) | typos | `fuzzy` (requires the `fuzzy` plugin; scans the whole library, slower) |

Each option has a `--<option>` / `--no-<option>` command flag (underscores
written as dashes, e.g. `--no-acoustid-fingerprint`) overriding the
configuration. A strategy's own flag wins over its group flag:
`--no-acoustid --acoustid-id` only uses the AcoustID id.

Disabling individual strategies is mostly about precision, e.g. keeping
only `mb_releasetrackid` to rate only other copies of the very same release
track, or dropping `acoustid_fingerprint` if exact fingerprint matches are
useless for you. The performance gain is small for the MusicBrainz and
AcoustID strategies: they are simple equality queries on library fields,
and are skipped anyway when the track has no value for the field or when a
previous strategy found similar tracks. The `fuzzy` strategy, which scans
the whole library, is the one worth disabling for speed.

Strategies whose fields are empty on the track are skipped. Enabling
`bareascii` or `fuzzy` without loading the corresponding plugin logs a
warning and skips the strategy.

### 3. Proposal and review

The similar tracks are displayed grouped by rating, the most frequent
rating first, and the **most frequent rating** is proposed (ties are
broken by the highest rating):

    the artist - the album - song [FLAC]
      not rated by djhibee; 3 similar items rated by djhibee (same MusicBrainz recording):
        8 (2 items):
          - the artist - the album - song [MP3]
          - the artist - best of - song [MP3]
        6 (1 item):
          - the artist - live - song [MP3]
      proposed rating: 8
    Rating of djhibee (0-10, Enter for 8), Skip or fiX (rate similar items too)?

When no similar rated tracks are found, autorate asks for a rating manually
instead. Enter a rating from 0 to 10 or choose **Skip**. With `-y/--yes`,
tracks without a proposed rating are left unrated.

Choices:

* **Enter**: rate the track with the proposed rating;
* **a number from 0 to 10**: rate the track with this rating (it does not
  need to be one of the similar tracks' ratings);
* **S** (skip): leave the track unrated;
* **X** (fix): unify the ratings: the rating to use is asked (the most
  frequent one by default), then the track **and all its similar tracks**
  are rated with it.

With `-p/--pretend`, proposals are only displayed. With `-y/--yes`, the
proposed ratings are applied without asking. At import in quiet mode
(`import -q`), proposals are skipped.

With **global review** (`global_review: yes` or `-g`), all the proposals
are first computed, then reviewed one after the other at the end of the
command or, at import, once each album is imported (`album_imported`
event): the proposals of an album's tracks are reviewed and applied right
after the album has been added to the library and its files written, so
the chosen ratings are written to the files according to the `write`
options. The proposals of tracks not imported as part of an album
(singletons) are reviewed at the end of the import.
Each proposal is refreshed just before being reviewed, so ratings chosen
(or fixed) earlier in the review are taken into account. Without global
review, each proposal is reviewed as soon as it is found. At import, global
review is recommended, as questions would otherwise be mixed with the
importer's ones.

### 4. Rating

The chosen ratings are stored in the library like with `beet userrating
--modify`, and written to the files according to the `write` options
(`-w/-W` for the command). At import, the imported tracks' ratings are
written along with their other tags by the importer.

### Reusing the similarity search in another plugin

The search is available as a parameterized function (also available as
`getSimilarItems`):

```python
from beetsplug.userrating.similar import get_similar_items

found = get_similar_items(
    lib, item,
    strategies=['mb_trackid', 'acoustid_id'],  # default: all, in priority order
    format='FLAC',                          # field=value filters...
    bitrate=lambda b: b >= 320000,          # ...or field=function filters
    query='^genre:podcast',                 # beets query the results must match
    predicate=lambda i: i.length > 60,      # any other check
)
if found:
    print(found.strategy.label, found.items)
```

It returns the similar items found by the first strategy giving results
(`all_strategies=True` returns the results of all strategies). Field
filters accept any item field, including flexible attributes and other
plugins' computed fields. Custom strategies may be passed as
`beetsplug.userrating.similar.Strategy` objects. For instance, a plugin
pairing lossy and lossless versions of tracks could call
`get_similar_items(lib, item, quality=chosen_quality)` (where `quality` is
a field it computes) and pick the best of the returned items.

## Development

    $ pip install -e . pytest
    $ python -m pytest test

## FAQ

### Why not `beet rating`?

The `mpdstats` plugin already maintains a `rating` attribute, so this
plugin uses the `userrating` nomenclature.
