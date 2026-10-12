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
  Media Player, MediaMonkey, Quod Libet).

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

## Development

    $ pip install -e . pytest
    $ python -m pytest test

## FAQ

### Why not `beet rating`?

The `mpdstats` plugin already maintains a `rating` attribute, so this
plugin uses the `userrating` nomenclature.
