# Torrent Finder CLI

Search torrents and direct downloads across movies and series, games,
software, anime, manga and books from one keyboard-driven terminal app, then
hand the pick to your torrent client, download it in the terminal, or stream it
to VLC with subtitles. Each category searches several sources at once and puts
the title you asked for first. Torrent Finder is written in Python with
[Rich](https://github.com/Textualize/rich).

The latest release is **v0.9.0**: see its [release notes](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/releases/v0.9.0.md).
The [user guide](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/guide.md) explains every feature in detail.

## Install

**With Python 3.10 or later**, from PyPI. pipx keeps it in its own environment:

```bash
pipx install torrent-finder-cli      # recommended
pip install torrent-finder-cli       # or this
```

**Without Python**, download `torrent-finder-windows.exe`, `torrent-finder-macos`
or `torrent-finder-linux` from [Releases](https://github.com/PietroFilippo/torrent-finder-cli/releases).
On Windows, if SmartScreen warns, choose **More info → Run anyway** (the file is
unsigned). On macOS and Linux, run `chmod +x <file>` and start it from a
terminal; macOS may need **System Settings → Privacy & Security → Open anyway**
the first time.

**From source** (see [development](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/development.md) for tests):

```bash
git clone https://github.com/PietroFilippo/torrent-finder-cli.git
cd torrent-finder-cli
pip install -e .
```

### Optional tools

| Tool | Needed for | Install |
|---|---|---|
| [aria2](https://aria2.github.io/) | Browsing a torrent's files, picking episodes, subtitles found inside torrents, episode navigation with peerflix, fast multi-file and batch downloads | `winget install aria2.aria2`, `brew install aria2`, `apt install aria2` or `dnf install aria2` |
| webtorrent-cli, peerflix (Node.js) | Streaming, and terminal downloads without aria2 | `npm install -g webtorrent-cli peerflix` |
| [VLC](https://www.videolan.org/vlc/) | Streaming | |

The interface needs a terminal that understands ANSI escape codes; any modern
one does. On Windows 10's legacy console the app prints how to fix that, best
by installing [Windows Terminal](https://aka.ms/terminal).

## Quick start

```bash
torrent-finder        # or the short form: torrent
```

A network check first shows your public IP and whether it looks like a VPN
(the IP stays masked until you press **R**; **Enter** continues). Then pick a
provider on the main menu, type a title and press **Enter**. Pick a result to
open the download menu.

| Where | Keys |
|---|---|
| Everywhere | **↑/↓** move, **Enter** choose, **Esc** back, **?** every key of the screen |
| Main menu | **F** filters of the highlighted provider, **H** history, **S** stats, **T** tips, **Tab** quick actions, **Esc** twice to quit |
| Search prompt | **Ctrl+F** filters and engines, **Ctrl+N** add another title, **Tab** quick actions |
| Results | **Space** tick, **Enter** open, **i** details, **f** refine and sort, **b** bookmark, **n** diagnostics, **r** retry, **m** load more |

## Features

### Searching

- **Eleven providers**: Movies & Series, Anime, Books, and three groups:
  **Games** (General, Online-Fix, FitGirl), **Software** (Desktop, Mobile for
  Android, RuTracker) and **Manga** (General, Madokami). See the
  [provider table](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/guide.md#providers-and-sources).
- **Several engines per provider**, searched in parallel and merged without
  duplicates. Each engine is **On**, **Auto** (only when the others find
  nothing) or **Off**.
- **Search across providers** with saved, named profiles, each with its own
  providers, engines, presets, name rules and result order.
- **Several titles at once** (**Ctrl+N**), merged with a column showing which
  title found each result.
- **Search by creator**: director, studio, writer, magazine, developer,
  publisher or author, without any account (TMDB and IGDB keys make movies and
  games richer).
- **Alternate titles**: identify a work in AniList, TMDB, IGDB or Open Library
  and search its English, native and romanized names together.
- **Topic discovery**: find works by catalog genres and tags (`time travel`,
  `co-op`), then search their releases.
- **Other spellings**: when nothing matches, digits for spelled-out numbers,
  short romanized vowels and AniList's names are searched too.

### Results

- **The title you asked for first**: films above sequels, programs above
  add-ons, the book by its author, with a **Ranked:** line saying why.
- **Presets** (resolution, release groups, languages, formats) cycle Off →
  **Require** → **Prefer**: Prefer ranks matches higher without hiding the rest.
- **Brazilian Portuguese** audio and subtitle presets that read explicit
  release tags and search the Portuguese release words too.
- **Literal name rules** (all words, any word, exact phrase, exclude) and a
  refine-and-sort menu (**f**) on the fetched results.
- **Diagnostics** (**n**) per provider, engine and query; **r** retries only
  what failed; **m** loads more pages from Nyaa and Knaben.
- **Bookmarks** (**b**) for results and searches to download later.

### Downloading and streaming

- Hand magnets to your **torrent client**, send them to **qBittorrent WebUI**
  with real progress, or download in the terminal with **aria2c**, webtorrent or
  peerflix.
- **Batch**: tick several results and open, download or copy them all at once.
- **Pick files** inside a torrent, such as single episodes or manga volumes.
- **Direct downloads** from Libgen, Madokami and F-Droid, never overwriting a file.
- **Stream to VLC** with next and previous episode keys, and subtitles found
  inside the torrent, from a file, or downloaded through OpenSubtitles,
  Addic7ed, Podnapisi, TVsubtitles and Jimaku.
- **Unpack manga archives** into folders of pages (optional).

### Appearance

- Two designs: **Athanor** (the default), a framed roguelike scriptorium with
  five colourways, and **Simple**, a quiet look with six themes including
  **Paper** for light terminals.
- Public-domain engravings behind the app, through a **Windows Terminal
  profile** with pixel fonts, or as a saved image for other terminals.
- An inspector pane in wide windows, and layouts that adapt to narrow, short
  and tall windows.

### Settings and data

- Settings, history (2,000 searches), stats and bookmarks are saved within a
  second, and several windows can be open safely.
- Settings **backup and import** between computers, with a preview first.
- **In-app updates** for pip, pipx and source installs, in the same window.
- An optional short command: `tf`, `find-torrent` or `tfind`.
- The interface in **English or Brazilian Portuguese** (Settings › Language),
  following the system's display language unless you choose.

## Command line

```bash
torrent -q "The Matrix"                      # search Movies & Series
torrent -t game -q "Elden Ring"              # choose the provider
torrent -t books -q "Dune" -f epub -x sample # keep or drop keywords
torrent -t all -q "Saki"                     # search across providers
torrent --profile "Anime + Manga" -q "Saki"  # a saved profile (implies -t all)
torrent -t all --providers anime manga -q "Saki"
torrent -t anime --by director --name "Hayao Miyazaki"
torrent --theme paper                        # a theme for this run only
torrent --lang pt-BR                         # the interface in Portuguese for this run
torrent -y                                   # skip the network check
torrent --version
```

- `-t`: `movie`, `game`, `online-fix`, `fitgirl`, `software`, `mobile`,
  `rutracker`, `anime`, `manga`, `madokami`, `books` or `all`. Without `-t`, a
  `-q` search uses Movies & Series.
- `--by` roles: `director` and `studio` (anime, movie), `writer` and `magazine`
  (manga), `developer` and `publisher` (game), `author` (books). The app then
  asks which creator and which works.
- `--theme`: `citrinitas`, `rubedo`, `albedo`, `viriditas`, `nigredo`, `quiet`,
  `iris`, `lagoon`, `ember`, `mono`, `paper`.
- `--lang`: `auto`, `en` or `pt-BR`.
- `--profile` and `--providers` affect only that session.
- From a source clone without installing, use `python -m torrent_finder`
  instead of `torrent`.

Environment variables: `TORRENT_SKIP_WARNING=1` skips the network check,
`TORRENT_FINDER_THEME=NAME` sets a theme and `TORRENT_FINDER_LANG=CODE` a
language per shell, and `NO_COLOR` is honoured.

## Credentials

Everything works without accounts except RuTracker and Madokami. Set logins in
the app under **Credentials** on the main menu, which verifies them where
possible, or with environment variables, which take precedence over the saved
file. [The guide](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/guide.md#credentials) explains each one and how to set
them.

| Integration | Account | Environment variables |
|---|---|---|
| RuTracker | required for that provider | `RUTRACKER_USERNAME`, `RUTRACKER_PASSWORD` |
| Madokami | required for that provider | `MADOKAMI_USERNAME`, `MADOKAMI_PASSWORD` |
| Online-Fix | optional | `ONLINE_FIX_USERNAME`, `ONLINE_FIX_PASSWORD` |
| OpenSubtitles.com | optional, much better subtitles | `OPENSUBTITLES_USERNAME`, `OPENSUBTITLES_PASSWORD`, `OPENSUBTITLES_APIKEY` (optional) |
| Addic7ed | optional, higher limits for series | `ADDIC7ED_USERNAME`, `ADDIC7ED_PASSWORD` |
| Jimaku | optional, anime subtitles | `JIMAKU_API_KEY` |
| TMDB | optional, movie creator search, alternate titles and topics | `TMDB_API_KEY` |
| IGDB (Twitch) | optional, game creator search, alternate titles and topics | `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` |
| qBittorrent WebUI | optional, client handoff and progress | `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD` |

Saved credentials are plain text in `subtitle_credentials.json`, beside your
settings. Never commit real values.

## Where your data lives

| System | Folder |
|---|---|
| Windows | `%USERPROFILE%\.torrent-finder-cli\` |
| macOS | `~/Library/Application Support/torrent-finder-cli/` |
| Linux | `$XDG_DATA_HOME/torrent-finder-cli/` (or `~/.local/share/torrent-finder-cli/`) |

It holds `filter_state.json` (settings, history, stats, bookmarks),
`subtitle_credentials.json` and `update.log`. Data from older versions' locations is
copied in on first run. Details: [Your data](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/guide.md#your-data).

## Updating

The app checks for updates once a day and shows a notice. Press **U** on the
main menu to update in place: pip and pipx installs upgrade and restart in the
same window, a source clone runs `git pull`, and a standalone binary opens the
Releases page. To update by hand, close every Torrent Finder window and run
`pipx upgrade torrent-finder-cli` in a separate terminal. More in
[Updating](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/guide.md#updating).

## Security notes

This tool does **not** make torrenting safe. Some things it cannot guarantee:

- Your real IP is visible to every peer and tracker in the swarm unless you are
  behind a VPN.
- Trackers in `constants.py` are plain UDP. There is no "tracker over HTTPS"
  that hides your IP, since trackers exist to exchange peer IPs.
- Seed counts, file names and uploader tags are not safety signals. The
  "Trusted Uploaders" preset is a convenience filter based on community
  reputation, not a guarantee of clean content.
- The startup `ip-api.com` check travels over plain HTTP (a free-tier
  limitation). If that matters to you, use `-y` or `TORRENT_SKIP_WARNING=1`.

Use a VPN, verify content before running installers, and treat everything in a
public swarm as untrusted.

## Documentation

- [User guide](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/guide.md): every feature, key and setting.
- [Provider reference](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/PROVIDER_REFERENCE.md): each provider's sources,
  measured results and limits, from the
  [October 2026 provider audit](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/audits/2026-10-03/README.md).
- [Release notes](https://github.com/PietroFilippo/torrent-finder-cli/tree/main/docs/releases/) for each version.
- [Development](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/development.md): tests and live source checks;
  [releasing](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/docs/releasing.md).
- [CONTEXT.md](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/CONTEXT.md) (domain model and code map) and the
  [architecture decision records](https://github.com/PietroFilippo/torrent-finder-cli/tree/main/docs/adr/).

## License and credits

Released under the [MIT License](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/LICENSE).

The Athanor paintings are public-domain works; their sources are listed in
[`torrent_finder/assets/paintings/CREDITS.md`](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/torrent_finder/assets/paintings/CREDITS.md).
The pixel fonts (IBM VGA 8x16 and 9x16, IBM XGA-AI 12x20, Toshiba TxL1 8x16 and
AST Premium Exec) are from VileR's
[Ultimate Oldschool PC Font Pack](https://int10h.org/oldschool-pc-fonts/),
licensed under [CC BY-SA 4.0](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/torrent_finder/assets/fonts/LICENSE.TXT); see
[`torrent_finder/assets/fonts/README.md`](https://github.com/PietroFilippo/torrent-finder-cli/blob/main/torrent_finder/assets/fonts/README.md).
