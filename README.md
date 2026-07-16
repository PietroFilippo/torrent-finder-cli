# Torrent Search CLI

An interactive command-line application for searching and downloading torrents directly from your terminal. Built with Python and `rich`.

Install it from PyPI (`pipx install torrent-finder-cli`) or grab a standalone, no-Python binary from [Releases](https://github.com/PietroFilippo/torrent-finder-cli/releases) — see [Installation](#installation).

## Features

- **Multi-Category Search:** Torrents across different providers (Movies & Series, Games, Software, Anime, Manga), each with its own tailored search backends. The Movies & Series provider handles both films and TV shows — the episode-aware streaming flow kicks in automatically when a torrent contains multiple video files. **Software** is a group on the provider screen: pick it and choose a source — **Desktop** (Windows/macOS/Linux programs via The Pirate Bay's Applications categories plus SolidTorrents), **Mobile** (Android apps — APK/MOD/OBB; Android-only and says so when you search), or **RuTracker** (logs into [rutracker.org](https://rutracker.org) and searches it directly — great for software, audio, and rare content; needs an account set under the credentials menu, and stays dormant until one is configured). On the CLI these stay individually addressable: `-t software`, `-t mobile`, `-t rutracker`. **Games** is likewise a group: pick it and choose **General** (PC, consoles, ROMs & repacks from public trackers — The Pirate Bay's game categories plus SolidTorrents), **Online-Fix** (scrapes [online-fix.me](https://online-fix.me) for co-op/online game cracks), or **FitGirl** (searches the official [fitgirl-repacks.site](https://fitgirl-repacks.site) — the one trustworthy source for FitGirl repacks, since fake "FitGirl" uploads on public trackers are a known malware vector; no account needed, the magnet resolves from the post when you pick a result). On the CLI they're `-t game`, `-t online-fix`, and `-t fitgirl`. Online-Fix needs **no account** — both search and download are anonymous (the file host is referer-gated, not login-gated); picking a result downloads the `.torrent` into your download folder and opens it in your system torrent client, showing the archive password (`online-fix.me`) to unpack the game with. **Manga** is also a group: **General** (Nyaa Literature + Apibay Comics) or **Madokami** (the private [manga.madokami.al](https://manga.madokami.al) library — needs an account under the credentials menu; hits are **direct downloads**, no torrent client involved: picking a series folder opens a volume picker and the chosen archives are saved straight to your download folder). On the CLI: `-t manga` and `-t madokami`.
- **Multi-Engine Fan-Out:** Each provider queries several sources in parallel (e.g. Apibay + SolidTorrents + YTS + Nyaa live-action for Movies & Series, Nyaa for Anime, Nyaa Literature + Apibay Comics for Manga) and merges results, deduplicating by info hash and sorting by seeders.
- **Search by Creator:** Search by the people and companies behind the content instead of by title. After choosing a provider, a "choose how to search" screen offers normal keyword search **plus** by-creator options — **Anime** and **Movies & Series** by **director** or **studio**, **Manga** by **writer** or serialization **magazine**, **Games** by **developer** or **publisher** (kept separate — a company can be both). You type a name, disambiguate between matches, then multi-select which of that creator's titles to include (a paged checklist, 100 per page with `n`/`p`); the app runs a normal torrent search for each picked title and merges the results — so picking still uses all the usual download/stream/episode options. It works **keyless out of the box** (AniList for anime/manga staff, Jikan for manga magazines, Wikidata for movies/games), and an optional **TMDB** key (Movies & Series) or **Twitch/IGDB** credentials (Games) added under **🔑 Credentials** transparently upgrade those two to richer, better-ranked data. Online-Fix is included in the Games developer/publisher results. From the CLI: `--by <role> --name "<creator>"` alongside `-t`, e.g. `torrent -t anime --by director --name "Hayao Miyazaki"`.
- **Search Several at Once (multi-title):** At the keyword prompt, press **Ctrl+N** to add another title, then `Enter` to search them all together — results fan out across the provider's engines and merge into one list. A **From** column shows which searched title each result came from, so interleaved results are easy to tell apart.
- **Multi-Select & Batch Download:** In the results table, press **Space** to tick more than one torrent (`a` select all, `c` clear), then `Enter`. A batch menu lets you **open all in your torrent client**, **download all with `aria2c`** (one parallel process — no client needed), or **copy all magnet links** at once. Works for any results — several releases of one title, or picks spanning a multi-title / by-creator search. A single pick still opens the full per-torrent download menu.
- **Arrow-Key Driven UI:** Fully interactive, flicker-free terminal interface.
  - Utilizes an alternate screen buffer so your scrollback history remains flawlessly clean.
  - **Dynamic Viewport Windowing:** Capable of rendering massive 500+ item checklists (like huge anime seasons) by automatically windowing the active selection while pinning crucial action buttons tightly to the top and bottom of your screen to prevent terminal overflow.
  - **Responsive Narrow Layouts:** Selector hints, descriptions, and controls wrap without changing selectable-row height. Search results progressively collapse to the fields that fit, with hidden metadata kept under the selected row; resizing an open screen recalculates the viewport automatically.
  - **Marquee Scrolling:** Automatically scrolls long torrent names and checklist items that exceed the physical terminal width when hovered over.
  - **Contextual Footers:** Displays dynamic helper text explaining the trade-offs, speeds, and seeding behaviors of different download options as you highlight them.
- **Quick-Launch Commands:** The startup provider screen includes a **Terminal command** row for choosing `torrent-finder`, `tf`, `torrent`, `find-torrent`, or `tfind`. The canonical command remains available and `torrent` is built into pip/pipx installs; the other presets create one app-owned forwarding launcher, preserve every CLI argument, refuse unrelated command collisions, and can be removed safely from the same screen.
- **Advanced Filtering:**
  - Toggle built-in presets (preferred resolutions, known uploaders/repackers, trusted release groups) using an interactive checklist.
  - Toggle individual search engines on and off per provider from the same menu.
  - Add custom include/exclude keywords to quickly find the exact release you want.
  - **Shared keybinds with the episode picker:** `a` select all • `i` invert • `c` clear presets • `w` save • `v` / `Shift+V` visual anchor + range toggle • `Space` toggle current.
  - **Persistent across runs:** engine toggles, active filter presets, search history, usage stats, the quiet-mode flag, the chosen download folder, and the dismissed-warning state all live in `filter_state.json` in your user data folder (see [Where your data lives](#where-your-data-lives)), so configuration sticks after you close the program. Mutations are held in an in-memory cache and flushed on exit or after destructive actions (clear history, reset stats, filter-menu Confirm) — no per-event disk hit.
- **Search History:** Press `H` on the provider screen (or `Tab` then `H` at the search prompt) to browse past searches. Filter by provider (`P`), date range (`D`, today/week/month), and sort order (`S`). Each entry shows the provider, relative timestamp, and the filter presets that were active at search time. Pick an entry to re-run the query; clear history with a confirmation modal.
- **Usage Stats:** Press `S` on the provider screen (or `Tab` then `S` at the search prompt) to open a scrollable stats page showing session count, total runtime, searches, top queries, torrents picked, method picks vs. completions (with success rate), avg seeders of picks, and preset usage counters. Reset all stats from the same screen, guarded by a confirmation modal.
- **Confirmation Modals:** Destructive actions (clear history, reset stats) share a unified red Y/N panel so you can't nuke state with a stray keypress.
- **Dynamic Contextual Tips:** Random hints (`💡 Tip: ...`) are displayed in the provider selector and post-download menus. A searchable tips browser is also available from the provider screen (`T`), the search prompt (`Tab` then `T`), and the post-download menu.
- **Quiet Mode:** Toggle **🔇 Quiet mode** from the Download Method menu to suppress the native progress UIs of `aria2c`, `webtorrent-cli`, and `peerflix` (full-screen progress bars, peer lists, speed graphs) and replace them with a single minimal spinner. The toggle redraws in place with no flicker and persists across runs (stored as `hide_stream_output` in `filter_state.json`). Episode info, VLC hotkey hints, and `Ctrl+C` all still work.
- **Flexible Downloading & Streaming:**
  - **System Client:** Automatically send generated magnet links to your default system torrent client (like qBittorrent, Transmission, etc.).
  - **Direct Terminal Download:** Use `aria2c`, `webtorrent-cli`, or `peerflix` integration to download files directly within the terminal, with native progress UIs.
  - **File Browser / Episode Picker (Anime, Movies & Series, Manga):** Open **📂 Browse torrent files…** from the download menu to list every file in the torrent (videos, subs, artwork, .nfo, samples — or individual volumes/chapters for Manga) and pick any subset. Opening it fetches the torrent's file list over DHT via `aria2c`, which can take 30–60s (or stall on low-peer torrents) — press **Esc** during the load to cancel and return to the menu. Features vim-style visual range selection (`v` anchor, `Shift+V` range-toggle) and rapid hotkeys (`a`, `i`, `c`, `w`). **Selection persists across re-entries** — reopening the picker shows your existing checkboxes already ticked, so you can refine without rebuilding from scratch. Confirming with nothing checked clears the selection; `Esc` cancels and keeps the prior picks intact. Only `aria2c` honors strict file selection on download — `webtorrent` and `peerflix` ignore `--select` and pull the whole torrent (the menu warns you when a selection is active). **Streams auto-skip non-video picks** and warn about it, so you can still e.g. download the .srt + .nfo alongside the video without breaking playback. If a stream selection contains zero video files, the stream errors out instead of silently substituting another file.
  - **Torrent Info (from origin):** In the **Torrent & files** section of the download menu, **ℹ Torrent info** fetches details straight from the source page — category, uploader, date, description, and the full file list. Supported sources: Nyaa (scraped), The Pirate Bay (Apibay JSON API) and YTS (API); other engines show "not available". It also reports **whether subtitles are embedded** in the video: a filename/metadata heuristic (e.g. an anime "English-translated" category or a `[Subbed]` tag), upgraded to a definitive answer via `ffprobe` when `ffmpeg` is installed and a copy of the video has already been downloaded — useful to tell a soft-subbed MKV apart from a raw release with no separate `.srt`.
  - **Stream to VLC:** Stream media directly to VLC Media Player using `webtorrent-cli` (default) or `peerflix` (fallback). Both stream and download menus list **webtorrent before peerflix** to match this preference. Press the `v` hotkey at any time during a streaming session to reopen VLC without losing your torrent download/buffering progress. The CLI checks active processes (`tasklist` on Windows, `pgrep -x` on Mac/Linux) and silently ignores the hotkey if VLC is already running, preventing accidental duplicate windows. When an episode is selected, streams that specific file.
  - **Subtitles for streams (auto + manual):** A `📝 Source: <mode>` row in the Download Method menu controls how VLC gets subtitles for the next stream:
    - `auto-detect from torrent` *(default)* — scans the torrent for `.srt/.ass/.ssa/.vtt/.sub` files paired with each video (matched by basename, language tag like `.en.srt`, or a sibling `Subs/` folder with episode-numbered files like `01.ass`). Matches are pre-downloaded via aria2c and attached to VLC via `--sub-file` before playback starts. English subs are prioritized as the primary track when available.
    - `external file` — pick a `.srt/.ass` from a list of recent files in your chosen download folder (defaults to `downloads/`), or type a custom path. The same file is attached to every episode in the session.
    - `off` — stream with no subtitles.
    - After downloading subs via **📝 Search & download subtitles** (the existing subliminal flow), the saved file is auto-promoted to external mode so your next stream just picks it up.
  - **Auto Episode Navigation:** When streaming a torrent with ≥ 2 video files **without** pre-selecting anything, the CLI fetches metadata via `aria2c`, queues every video file in episode order (using filename patterns like `S01E01`, ` - 01`, `[01]`, `Episode 01`, or ` E01` when present; alphabetical fallback otherwise), and enables `n` (next) / `b` (previous) hotkeys so you can jump between episodes mid-session. Single-file movies still stream as-is — no forced picker, no extra wait.
  - **Subtitle Download:** Search and download the best matching subtitles directly from the terminal using `subliminal`. Enter one or more languages separated by commas (e.g. `eng, por` or `pt-BR`) — accepts ISO codes (`eng`/`en`) and regional variants (`pt-BR`, `pt-PT`). Every available language is downloaded, the first in your order becomes the primary VLC track (the rest attach as switchable tracks), and any language it couldn't find is reported. If a matching video has already been downloaded, it hash-matches the real file for frame-accurate sync; otherwise it matches on the release name. Configuring OpenSubtitles.com credentials greatly improves results (see *Subtitle providers* below). For Anime searches, a dedicated **Jimaku** lookup (jimaku.cc) runs first when a `JIMAKU_API_KEY` is set, since the western-TV providers behind subliminal don't index anime fansubs well.
  - **Configurable Download Folder:** A **📁 Save to:** row in the Download Method menu — or the **📁 Download folder** row on the Select Provider screen, which shows the current path — sets a persistent default download directory used by `aria2c`, `webtorrent`, `peerflix` downloads, the subtitle downloader, and Online-Fix / Madokami file saves. Picker offers `Default (downloads/)`, `~/Downloads`, or a custom path (created on-the-fly if missing). Streams and magnet-to-client handoff are unaffected — they use their own paths.
  - **Clipboard Integration:** Easily copy magnet links directly to your OS clipboard (Windows/macOS/Linux).
  - **Seamless Error Recovery:** If a terminal download fails, lacks dependencies, or is manually forcefully aborted by you (`Ctrl+C`), the CLI intercepts the exit and safely drops you back into the download method selector without losing your active search context.
- **Network Exposure Warning:** At startup a red panel queries `ip-api.com` and shows your public IP, ISP, ASN, location, plus flags for `proxy` / `hosting` / `mobile`. Gives you a clear go/no-go decision before joining a public swarm.
- **Install-Aware Update Check:** On startup the app checks for a newer version (at most once a day, fail-silent) and shows a notice tailored to how you installed it — a pip/pipx install compares against PyPI, a git clone against `origin`, a standalone binary against the latest Release. Press **Tab → ⬆ Install update** to update in place (`pipx upgrade`/`pip -U`, `git pull`, or open the Releases page).
- **Pagination & Navigation:** Navigate through large sets of search results cleanly, with the ability to safely go back to your previous search results after viewing download options.

## Prerequisites

- **Python 3.10+** — for the PyPI/pip install or running from source. *Not needed for the standalone binary.*
- (Optional but recommended) **Node.js** & **npm** for installing `webtorrent-cli` or `peerflix`.
- (Optional) **VLC Media Player** — required for streaming.
- (Optional) **aria2** — required for the file browser / episode picker, the in-torrent subtitle auto-detect path, auto episode navigation on the peerflix backend, and single-process multi-file downloads. Install with `winget install aria2.aria2` (Windows), `brew install aria2` (macOS), or `apt install aria2` / `dnf install aria2` (Linux).

## Installation

### With Python (3.10+) — from PyPI

Install from PyPI; **pipx** keeps it isolated in its own environment:

```bash
pipx install torrent-finder-cli      # recommended
# or
pip install torrent-finder-cli
```

Then run either built-in command from anywhere:

```bash
torrent-finder
torrent          # short form
```

### Without Python — standalone binary

Download a ready-to-run build for your OS from the
[Releases page](https://github.com/PietroFilippo/torrent-finder-cli/releases):
`torrent-finder-windows.exe`, `torrent-finder-macos`, or `torrent-finder-linux`.
On Windows, double-click it (if SmartScreen warns, **More info → Run anyway** —
it's just unsigned). On macOS/Linux, make it executable (`chmod +x <file>`) and
run it from a terminal; on macOS the first run may need **System Settings →
Privacy & Security → Open anyway**.

### From source (for development)

```bash
git clone https://github.com/PietroFilippo/torrent-finder-cli.git
cd torrent-finder-cli
pip install -e .
```

Run it with `torrent-finder`, `python -m torrent_finder`, or `torrent.bat`
(Windows). An editable install keeps pointing at your clone, so `git pull`
updates it.

### Optional direct download / streaming tools

Install these only if you want terminal-managed downloads or Stream to VLC:

```bash
npm install -g webtorrent-cli peerflix
```

`aria2c` is separate from Python/npm and is required for file browsing, strict multi-file selection, in-torrent subtitle extraction, and some auto episode metadata flows.

```bash
# Windows
winget install aria2.aria2

# macOS
brew install aria2

# Debian/Ubuntu
sudo apt install aria2
```

### Credentials (optional)

Several features improve with — or, for RuTracker and Madokami, require — an account.
Credentials are read at runtime from environment variables (preferred) or a
`subtitle_credentials.json` in your user data folder (see [Where your data
lives](#where-your-data-lives)) — **never commit real values**.

The easiest way to set them is in-program: on the **Select Provider** screen,
choose **🔑 Credentials**. For each provider you can view, enter/update,
or clear its login. Entering opens a single-screen form — edit every field in
place (Up/Down or Tab to move, Enter to advance, **Esc** to cancel) and Save
when done. Saved values are verified against the provider (where possible) and
written to `subtitle_credentials.json`; the view screen masks the password / API
key with a toggle to reveal them. Environment variables, if set, **override** the
file (the menu flags this), and **Clear only empties the file** — unset the
matching environment variables to remove a credential that's set there.

- **OpenSubtitles.com** (movies & series): a free account dramatically improves
  results and unlocks hash-accurate matching against a downloaded file.
- **Addic7ed** (TV series): a free account raises rate limits and quality for
  episodic content. Runs anonymously (limited) when no credentials are set.
- **Jimaku** (anime): a free API key (jimaku.cc → account settings) enables a
  dedicated anime subtitle lookup that runs before subliminal for Anime
  searches. Without the key, Anime falls back to subliminal automatically.
- **RuTracker** (the RuTracker provider): a free [rutracker.org](https://rutracker.org)
  account is **required** — the provider logs in to search and returns nothing
  without one.
- **Madokami** (the Madokami provider, under Manga): an account on
  [manga.madokami.al](https://manga.madokami.al) is **required** — the whole
  site sits behind HTTP Basic auth, so the provider returns nothing without
  one. Like RuTracker, this credential gates the whole provider.
- **Online-Fix** (the Online-Fix provider): **optional.** Both search and
  `.torrent` download work anonymously ([online-fix.me](https://online-fix.me)'s
  file host is referer-gated, not login-gated). A login is supported (the site's
  DataLife Engine `authtoken` flow) for completeness but isn't required.
- **TMDB** (Movies & Series "by director / studio"): **optional.** That search
  already works keyless via Wikidata; a free [TMDB](https://www.themoviedb.org)
  v3 API key (account → Settings → API) upgrades it to richer, better-ranked
  results.
- **IGDB** (Games "by developer / publisher"): **optional.** That search already
  works keyless via Wikidata; free Twitch/IGDB credentials (register an app at
  [dev.twitch.tv](https://dev.twitch.tv) → Client ID + Client Secret) upgrade it.

subliminal queries a curated set of providers — `opensubtitlescom`, `addic7ed`,
`podnapisi`, `tvsubtitles` — chosen for broad coverage and reliability. The rest
of subliminal's defaults (defunct legacy APIs, VIP-only variants, and
single-language scrapers) are skipped.

Set them as environment variables:

```powershell
# Windows (persists for new terminals)
[Environment]::SetEnvironmentVariable("OPENSUBTITLES_USERNAME", "your_user", "User")
[Environment]::SetEnvironmentVariable("OPENSUBTITLES_PASSWORD", "your_pass", "User")
[Environment]::SetEnvironmentVariable("ADDIC7ED_USERNAME", "your_user", "User")
[Environment]::SetEnvironmentVariable("ADDIC7ED_PASSWORD", "your_pass", "User")
[Environment]::SetEnvironmentVariable("JIMAKU_API_KEY", "your_key", "User")
[Environment]::SetEnvironmentVariable("RUTRACKER_USERNAME", "your_user", "User")
[Environment]::SetEnvironmentVariable("RUTRACKER_PASSWORD", "your_pass", "User")
[Environment]::SetEnvironmentVariable("ONLINE_FIX_USERNAME", "your_user", "User")
[Environment]::SetEnvironmentVariable("ONLINE_FIX_PASSWORD", "your_pass", "User")
[Environment]::SetEnvironmentVariable("MADOKAMI_USERNAME", "your_user", "User")
[Environment]::SetEnvironmentVariable("MADOKAMI_PASSWORD", "your_pass", "User")
[Environment]::SetEnvironmentVariable("TMDB_API_KEY", "your_key", "User")
[Environment]::SetEnvironmentVariable("IGDB_CLIENT_ID", "your_id", "User")
[Environment]::SetEnvironmentVariable("IGDB_CLIENT_SECRET", "your_secret", "User")
```

```bash
# macOS / Linux (add to your shell profile)
export OPENSUBTITLES_USERNAME="your_user"
export OPENSUBTITLES_PASSWORD="your_pass"
export ADDIC7ED_USERNAME="your_user"
export ADDIC7ED_PASSWORD="your_pass"
export JIMAKU_API_KEY="your_key"
export RUTRACKER_USERNAME="your_user"
export RUTRACKER_PASSWORD="your_pass"
export ONLINE_FIX_USERNAME="your_user"
export ONLINE_FIX_PASSWORD="your_pass"
export MADOKAMI_USERNAME="your_user"
export MADOKAMI_PASSWORD="your_pass"
export TMDB_API_KEY="your_key"
export IGDB_CLIENT_ID="your_id"
export IGDB_CLIENT_SECRET="your_secret"
```

Or create `subtitle_credentials.json` in your user data folder (see [Where your data lives](#where-your-data-lives)):

```json
{
  "opensubtitles_username": "your_user",
  "opensubtitles_password": "your_pass",
  "addic7ed_username": "your_user",
  "addic7ed_password": "your_pass",
  "jimaku_api_key": "your_key",
  "rutracker_username": "your_user",
  "rutracker_password": "your_pass",
  "online_fix_username": "your_user",
  "online_fix_password": "your_pass",
  "madokami_username": "your_user",
  "madokami_password": "your_pass",
  "tmdb_api_key": "your_key",
  "igdb_client_id": "your_id",
  "igdb_client_secret": "your_secret"
}
```

Environment variables take precedence over the file. All keys are optional —
anything unset just falls back to the anonymous provider set.

### Where your data lives

Settings, search history, usage stats, and provider choices live in a per-user,
machine-stable `filter_state.json`:

- **Windows:** `%USERPROFILE%\.torrent-finder-cli\filter_state.json`
- **macOS:** `~/Library/Application Support/torrent-finder-cli/filter_state.json`
- **Linux:** `$XDG_DATA_HOME/torrent-finder-cli/filter_state.json` (or `~/.local/share/torrent-finder-cli/filter_state.json`)

Credentials and the default downloads folder stay in the platform user-data
directory. On Windows that is `%LOCALAPPDATA%\torrent-finder-cli\`; on macOS
and Linux it is the same app directory shown above. Keeping Windows state under
the user profile prevents Microsoft Store Python from splitting history and
stats across interpreter-specific LocalCache directories.

On first run after upgrading, prior state copies from the old platform-data,
repository, package, and Store Python locations are consolidated into the
machine-stable file. The originals are left untouched.

### Updating

The app checks for a newer version on startup (at most once a day, fail-silent)
and shows a notice when one is available. Update from inside the program with
**Tab → ⬆ Install update**, which does the right thing for your install type:

- **pip / pipx** — runs `pipx upgrade torrent-finder-cli` (or `pip install -U`); restart the app afterward.
- **standalone binary** — opens the Releases page so you can download the new file.
- **source clone** — runs `git pull`.

Or update manually any time with `pipx upgrade torrent-finder-cli`.

## Usage

### Interactive Mode

The easiest way to use the CLI is to run it interactively. The arrow-key driven UI will guide you through selecting a category, searching, filtering, and downloading.

```bash
# After a pip/pipx install — both commands are on your PATH
torrent-finder
torrent

# From a source clone
python -m torrent_finder
torrent.bat            # Windows
```

> `torrent-finder` is canonical and `torrent` is the built-in short form. From the startup screen, **Terminal command** can also install `tf`, `find-torrent`, or `tfind` as your preferred quick command.

### Command Line Arguments

```bash
# Direct search (defaults to Movies)
torrent -q "The Matrix"

# Specify the search type (movie, game, online-fix, fitgirl, software, mobile, rutracker, anime, manga, madokami). `movie` covers both films and series.
torrent -q "Elden Ring" -t game

# Search Online-Fix (co-op / online game cracks from online-fix.me; no account needed)
torrent -q "Elden Ring" -t online-fix

# Search FitGirl repacks on the official fitgirl-repacks.site (no account needed)
torrent -q "Cyberpunk" -t fitgirl

# Search desktop software (The Pirate Bay Applications + SolidTorrents)
torrent -q "Photoshop" -t software

# Search Android apps (The Pirate Bay Android category; Android-only)
torrent -q "Spotify" -t mobile

# Search RuTracker (requires a configured rutracker.org login)
torrent -q "Photoshop" -t rutracker

# Search manga (Nyaa Literature English + Apibay Comics; Raw Nyaa available as a toggle)
torrent -q "Berserk" -t manga

# Search Madokami's manga library (requires a manga.madokami.al login; direct downloads)
torrent -q "Berserk" -t madokami

# Apply custom filters (include "1080p", exclude "cam")
torrent -q "Dune" -t movie -f "1080p" -x "cam"

# Search by creator: --by <role> --name "<creator>" with -t. Roles per provider:
#   anime/movie -> director, studio   manga -> writer, magazine   game -> developer, publisher
torrent -t anime --by director --name "Hayao Miyazaki"
torrent -t movie --by studio   --name "A24"
torrent -t game  --by developer --name "FromSoftware"
# Drops you into the disambiguation + title picker; keyless by default,
# richer with a TMDB key (movies) or IGDB creds (games).

# Skip the network exposure warning at startup
torrent -y

# Print the version and exit
torrent --version
```

You can also suppress the warning with the environment variable `TORRENT_SKIP_WARNING=1`, or permanently dismiss it from inside the panel itself (see below).

From a source clone with no pip install, replace `torrent` with `python -m torrent_finder` in the examples above.

### Network Exposure Warning

On launch you'll see a red panel listing your public IP, ISP, ASN and location, with a verdict line:

- ✓ **Proxy/VPN flagged** — detected by the IP database.
- ✓ **Hosting/datacenter IP** — likely a VPN exit (not a residential ISP).
- ✓ **VPN provider name detected** — keyword fallback (Mullvad, Proton, Nord, …).
- ⚠ **Mobile carrier IP** — your carrier and peers will see this IP.
- ⚠ **Residential ISP IP** — your real IP is visible to every peer and tracker.

Controls inside the panel:

- **Enter** — acknowledge and continue.
- **D** — don't show again (saved to `filter_state.json`).
- **Esc** — abort the program.

Even after dismissing, you can re-open the warning at any time from the **Select Provider** screen: scroll to the 🔒 **Network exposure info** item and press Enter.

### Navigating the UI

- **Lists & Menus**: Use `Up` and `Down` arrows to navigate.
- **Select**: Press `Enter` to confirm a choice or open a torrent.
- **Toggle**: In multi-select menus (like Filters), press `Enter` or `Space` on an item to toggle its checkbox.
- **Search prompt (multi-title)**: `Ctrl+N` commits the current title and starts another line; `Enter` searches them all at once. `Tab` opens quick actions, `Ctrl+F` jumps to filters, and `Up`/`Down` recall past searches.
- **Results table (multi-select / batch)**: `Space` ticks a torrent, `a` selects all results, `c` clears. With one or more ticked, `Enter` opens the batch menu (open all in client • download all with `aria2c` • copy all magnets); with nothing ticked, `Enter` opens that single torrent's download menu.
- **Range Selection (Episode Picker)**: 
  - `v`: Drop a visual anchor on the current item.
  - `Shift + V`: Instantly mass-toggle all items between the anchor and your cursor.
  - `a` (Select All) • `i` (Invert Selection) • `c` (Clear) • `w` (Save & Continue).
- **Configure filters from the provider screen**: Press `F` while a provider is highlighted to jump straight into its engines + filter presets menu, then return to the provider list.
- **Filter menu keybinds**: `a` select all, `i` invert, `c` clear presets, `w` save & confirm, `v` drop anchor, `Shift+V` range toggle between anchor and cursor, `Space` toggle current. The "Clear filters" button clears preset toggles only — your engine selections are preserved.
- **History / stats / tips / filters**: On the provider screen press `H` (history), `S` (stats), `T` (tips), or `F` (filters). At the search prompt, press `Tab` for the same quick-actions menu (then `F`/`H`/`S`/`T` or arrows) — your in-progress query is preserved. The prompt itself has no single-letter shortcuts, so queries can start with any letter.
- **Tips browser**: Use `/` to search across categories, tip text, and tags; `C` to cycle categories; `X` to clear the search/filter; and `Esc` to go back.
- **Cancel / Back**: Press `Esc` to safely cancel an action, close a menu, or go back to the previous screen.


## Project Architecture

All code lives under the `torrent_finder/` package, installed as a console script
(`torrent-finder` and `torrent` both map to `torrent_finder.main:main`). The structure is modular and
provider-based — the module paths below are relative to `torrent_finder/`:

- `main.py`: The main entry point and CLI argument parser.
- `launcher_alias.py`: Owns fixed quick-command presets, install-aware forwarding targets, managed shim creation/removal, collision checks, and optional Windows user-PATH updates.
- `__main__.py`: Enables `python -m torrent_finder` and serves as the PyInstaller binary entry point.
- `torrent.bat` *(repo root)*: Windows launcher that runs `python -m torrent_finder`.
- `providers/`: Different search categories (Movies & Series, General games, Online-Fix, FitGirl, Desktop, Mobile, RuTracker, Anime, General manga, Madokami). The display menu nests some of these under groups — **Games** (General + Online-Fix + FitGirl), **Software** (Desktop + Mobile + RuTracker), and **Manga** (General + Madokami) — via `ProviderGroup`, a display-only wrapper that changes menu shape without touching slugs. Each provider declares an immutable `slug` (used for persistence keys + CLI `-t` lookup), a display `name` (free to change), capability flags (`supports_subtitles`, `supports_episode_picker` — gate UI rows), its search engines, default filters, and toggleable presets. Nyaa-backed providers also set `nyaa_category` (the Nyaa `c` filter — e.g. `1_2` anime, `4_1` live-action, `3_1` manga). Providers may also declare a `creator_facets` list to enable search-by-creator (director/studio/writer/magazine/developer/publisher).
- `resolvers/`: The "search by creator" metadata layer that turns a person/company name into a list of works. `types.py` (`CreatorFacet` / `Entity` / `Work`), `anilist.py` (anime director & studio + manga writer, keyless GraphQL), `jikan.py` (manga serialization magazines, keyless), `wikidata.py` (keyless SPARQL fallback for movie/series director & studio and game developer & publisher), `tmdb.py` (Movies & Series, needs `TMDB_API_KEY`), `igdb.py` (Games, needs Twitch creds), and `movies.py` / `games.py` which dispatch to TMDB/IGDB when a key is configured and Wikidata otherwise. Each facet exposes `search_entities(name)` → candidates and `list_works(entity, page)` → `(works, has_more)`; `creator_search.fan_out()` then runs the normal provider search over each picked title and merges. `main._available_facets` can gate facets behind a credential when there's no keyless fallback.
- `ui/`: Interactive terminal prompts and rendering using `rich`. `prompts.py` (menus + `confirm_prompt` modal + `subtitle_source_prompt` + `download_dir_prompt` + the per-provider "choose how to search" source screen), `creator.py` (the search-by-creator flow: name → disambiguation → paged title picker with `n`/`p` + background prefetch → fan-out), `selector.py` (reusable arrow-key selector with windowing / marquee), `table.py` (paginated result table), `history.py` (search history browser), `stats.py` (usage stats page), `streaming.py` (themed Panel header + terminal-control primitives for the streaming flow), `tips.py` (categorized tip catalog), `tips_page.py` (searchable tips browser), and `launcher.py` (terminal-command selector and PATH confirmation).
- `filters.py`: Logic processing for including or excluding keywords.
- `creator_search.py`: `fan_out()` for search-by-creator — runs the provider's normal `search()` over each picked title concurrently and merges (dedupe by info hash, sort by seeders), tagging each result with the title it came from.
- `credentials.py`: Reads optional API credentials from environment variables (preferred) or the gitignored `subtitle_credentials.json`; powers the **🔑 Credentials** menu (subtitle logins, RuTracker/Online-Fix/Madokami, and the TMDB/IGDB creator-search upgrades).
- `torrent_session.py`: Post-torrent-pick state owner. Holds the picked magnet + user file selection + sub choice, and lazily resolves `files_meta` / `targets` / `stream_indexes` / `download_indexes` / `sub_paths`. Stream adapters consume the session directly; download adapters take `(magnet, indexes)` projections and stay session-unaware.
- `downloader.py`: Subprocess orchestration — `aria2c` / `webtorrent-cli` / `peerflix` execution, VLC launch + sub injection, quiet-mode plumbing, in-torrent sub batch fetch, and `v` / `n` / `b` hotkey handling. Stream adapters take a `TorrentSession`; download adapters keep an explicit `(magnet, indexes)` signature for reuse outside the menu loop.
- `subtitles.py`: Logic for searching and downloading subtitles using `subliminal`. Saves into the effective download folder via `constants.get_download_dir()`.
- `security.py`: Network exposure warning, public-IP/VPN detection via `ip-api.com`.
- `state.py`: Persists engine toggles, active presets, misc settings (dismissed-warning flag, quiet-mode flag, `download_dir`), and search history to `filter_state.json`. Backed by an in-memory cache: mutations mark dirty, disk write happens at `atexit` and at three destructive sites (`save_state`, `clear_history`, `reset_stats`). Includes a one-shot migration that rewrites legacy display-name keys (e.g. `"Movies & Series"`) to provider slugs.
- `stats.py`: Usage counter recorders and read helpers; stores under the `stats` subtree, keyed by provider slug. Same in-memory cache flow as `state.py`.
- `torrent_meta.py`: Fetches a torrent's file list from a magnet via `aria2c`. Helpers for episode-number extraction, video/subtitle classification, multi-episode detection (any torrent with ≥ 2 video files), sub-to-video matching (`match_subtitles_for`), and `--select-file` range formatting.
- `updates.py`: Install-aware update check (git clone / pip-pipx / binary). Rate-limited; compares against `origin` (git) or PyPI (`__version__`), and powers the in-app **Install update** action via `check_for_update()` / `run_update()`.
- `constants.py`: Configuration constants, trackers, UI themes, the platform user-data resolver (`user_data_dir()` / `data_path()`), the machine-stable state resolver (`machine_state_dir()` / `machine_state_path()`), legacy-location discovery, and `get_download_dir()` (returns the user's chosen `download_dir` setting or falls back to `DOWNLOADS_DIR`).

## Security Notes

This tool does **not** make torrenting safe. Some things it cannot guarantee:

- Your real IP is visible to every peer and tracker in the swarm unless you are behind a VPN.
- Trackers in `constants.py` are plain UDP — there is no "tracker-over-HTTPS" that hides your IP, since trackers exist to exchange peer IPs.
- Seed counts, file names, and uploader tags are not safety signals. The "Trusted Uploaders" preset is a convenience filter based on community reputation, not a guarantee of clean content.
- The startup `ip-api.com` call travels over plain HTTP (free tier limitation). If that matters to you, use `-y` or `TORRENT_SKIP_WARNING=1`.

Use a VPN, verify content before running installers, and treat everything in a public swarm as untrusted.

## License

Released under the [MIT License](LICENSE).
