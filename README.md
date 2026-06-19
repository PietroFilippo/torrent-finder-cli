# Torrent Search CLI

An interactive command-line application for searching and downloading torrents directly from your terminal. Built with Python and `rich`.

On Windows, the included `torrent.bat` launcher can be added to your `PATH` so you can run `torrent` from any terminal directory.

## Features

- **Multi-Category Search:** Torrents across different providers (Movies & Series, Games, Software, Anime, Manga), each with its own tailored search backends. The Movies & Series provider handles both films and TV shows — the episode-aware streaming flow kicks in automatically when a torrent contains multiple video files. The Software provider covers desktop programs (Windows/macOS/Linux) via The Pirate Bay's Applications categories plus SolidTorrents.
- **Multi-Engine Fan-Out:** Each provider queries several sources in parallel (e.g. Apibay + SolidTorrents + YTS + Nyaa live-action for Movies & Series, Nyaa for Anime, Nyaa Literature + Apibay Comics for Manga) and merges results, deduplicating by info hash and sorting by seeders.
- **Arrow-Key Driven UI:** Fully interactive, flicker-free terminal interface.
  - Utilizes an alternate screen buffer so your scrollback history remains flawlessly clean.
  - **Dynamic Viewport Windowing:** Capable of rendering massive 500+ item checklists (like huge anime seasons) by automatically windowing the active selection while pinning crucial action buttons tightly to the top and bottom of your screen to prevent terminal overflow.
  - **Marquee Scrolling:** Automatically scrolls long torrent names and checklist items that exceed the physical terminal width when hovered over.
  - **Contextual Footers:** Displays dynamic helper text explaining the trade-offs, speeds, and seeding behaviors of different download options as you highlight them.
- **Advanced Filtering:**
  - Toggle built-in presets (preferred resolutions, known uploaders/repackers, trusted release groups) using an interactive checklist.
  - Toggle individual search engines on and off per provider from the same menu.
  - Add custom include/exclude keywords to quickly find the exact release you want.
  - **Shared keybinds with the episode picker:** `a` select all • `i` invert • `c` clear presets • `w` save • `v` / `Shift+V` visual anchor + range toggle • `Space` toggle current.
  - **Persistent across runs:** engine toggles, active filter presets, search history, usage stats, the quiet-mode flag, the chosen download folder, and the dismissed-warning state all live in `filter_state.json` next to the script, so configuration sticks after you close the program. Mutations are held in an in-memory cache and flushed on exit or after destructive actions (clear history, reset stats, filter-menu Confirm) — no per-event disk hit.
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
  - **Configurable Download Folder:** A **📁 Save to:** row in the Download Method menu lets you set a persistent default download directory used by `aria2c`, `webtorrent`, `peerflix` downloads and the subtitle downloader. Picker offers `Default (downloads/)`, `~/Downloads`, or a custom path (created on-the-fly if missing). Streams and magnet-to-client handoff are unaffected — they use their own paths.
  - **Clipboard Integration:** Easily copy magnet links directly to your OS clipboard (Windows/macOS/Linux).
  - **Seamless Error Recovery:** If a terminal download fails, lacks dependencies, or is manually forcefully aborted by you (`Ctrl+C`), the CLI intercepts the exit and safely drops you back into the download method selector without losing your active search context.
- **Network Exposure Warning:** At startup a red panel queries `ip-api.com` and shows your public IP, ISP, ASN, location, plus flags for `proxy` / `hosting` / `mobile`. Gives you a clear go/no-go decision before joining a public swarm.
- **Update Notice for Git Clones:** When the project is installed from a git clone, the provider screen can show a lightweight update notice when the local branch is behind `origin`.
- **Pagination & Navigation:** Navigate through large sets of search results cleanly, with the ability to safely go back to your previous search results after viewing download options.

## Prerequisites

- **Python 3.10+**
- (Optional but recommended) **Node.js** & **npm** for installing `webtorrent-cli` or `peerflix`.
- (Optional) **VLC Media Player** — required for streaming.
- (Optional) **aria2** — required for the file browser / episode picker, the in-torrent subtitle auto-detect path, auto episode navigation on the peerflix backend, and single-process multi-file downloads. Install with `winget install aria2.aria2` (Windows), `brew install aria2` (macOS), or `apt install aria2` / `dnf install aria2` (Linux).

## Installation

### Clone and install Python dependencies

```bash
git clone https://github.com/PietroFilippo/movie-finder-cli.git
cd movie-finder-cli
python -m pip install -r requirements.txt
```

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

### Subtitle providers (optional, recommended)

Subtitle search works anonymously, but matches are far better with credentials.
Credentials are read at runtime from environment variables (preferred) or a
gitignored `subtitle_credentials.json` next to the code — **never commit real
values**.

The easiest way to set them is in-program: on the **Select Provider** screen,
choose **🔑 Subtitle credentials**. For each provider you can view, enter/update,
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
```

```bash
# macOS / Linux (add to your shell profile)
export OPENSUBTITLES_USERNAME="your_user"
export OPENSUBTITLES_PASSWORD="your_pass"
export ADDIC7ED_USERNAME="your_user"
export ADDIC7ED_PASSWORD="your_pass"
export JIMAKU_API_KEY="your_key"
```

Or create `subtitle_credentials.json` (already gitignored) in the repo folder:

```json
{
  "opensubtitles_username": "your_user",
  "opensubtitles_password": "your_pass",
  "addic7ed_username": "your_user",
  "addic7ed_password": "your_pass",
  "jimaku_api_key": "your_key"
}
```

Environment variables take precedence over the file. All keys are optional —
anything unset just falls back to the anonymous provider set.

### Run `torrent` from anywhere on Windows

The repository includes `torrent.bat`, which launches `main.py` relative to the repo folder. Add the repo folder to your user `PATH`, then open a new terminal:

```powershell
# Run from the repository root in PowerShell
$repo = (Get-Location).Path
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ';') -notcontains $repo) {
    $newPath = @($userPath, $repo) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath.Trim(';'), "User")
}
```

After opening a new terminal, this works from any directory:

```bash
torrent
torrent -q "The Matrix" -t movie -y
```

If you do not add the repo folder to `PATH`, run `torrent.bat` or `python main.py` from the repository folder.

## Usage

### Interactive Mode

The easiest way to use the CLI is to run it interactively. The arrow-key driven UI will guide you through selecting a category, searching, filtering, and downloading.

```bash
# If the repo folder is on your PATH (Windows)
torrent

# From the repository folder
torrent.bat
python main.py
```

### Command Line Arguments

```bash
# Direct search (defaults to Movies)
torrent -q "The Matrix"

# Specify the search type (movie, game, software, anime, manga). `movie` covers both films and series.
torrent -q "Elden Ring" -t game

# Search desktop software (The Pirate Bay Applications + SolidTorrents)
torrent -q "Photoshop" -t software

# Search manga (Nyaa Literature English + Apibay Comics; Raw Nyaa available as a toggle)
torrent -q "Berserk" -t manga

# Apply custom filters (include "1080p", exclude "cam")
torrent -q "Dune" -t movie -f "1080p" -x "cam"

# Skip the network exposure warning at startup
torrent -y
```

You can also suppress the warning with the environment variable `TORRENT_SKIP_WARNING=1`, or permanently dismiss it from inside the panel itself (see below).

If you did not add the repo folder to `PATH`, replace `torrent` with `python main.py` in the examples above.

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

The application is structured into a modular, provider-based architecture:

- `main.py`: The main entry point and CLI argument parser.
- `torrent.bat`: Windows launcher. It calls `main.py` relative to the batch file location, so adding the repo folder to `PATH` makes `torrent` usable from any directory.
- `providers/`: Different search categories (Movies & Series, Games, Software, Anime, Manga). Each provider declares an immutable `slug` (used for persistence keys + CLI `-t` lookup), a display `name` (free to change), capability flags (`supports_subtitles`, `supports_episode_picker` — gate UI rows), its search engines, default filters, and toggleable presets. Nyaa-backed providers also set `nyaa_category` (the Nyaa `c` filter — e.g. `1_2` anime, `4_1` live-action, `3_1` manga).
- `ui/`: Interactive terminal prompts and rendering using `rich`. `prompts.py` (menus + `confirm_prompt` modal + `subtitle_source_prompt` + `download_dir_prompt`), `selector.py` (reusable arrow-key selector with windowing / marquee), `table.py` (paginated result table), `history.py` (search history browser), `stats.py` (usage stats page), `streaming.py` (themed Panel header + terminal-control primitives for the streaming flow), `tips.py` (categorized tip catalog), and `tips_page.py` (searchable tips browser).
- `filters.py`: Logic processing for including or excluding keywords.
- `torrent_session.py`: Post-torrent-pick state owner. Holds the picked magnet + user file selection + sub choice, and lazily resolves `files_meta` / `targets` / `stream_indexes` / `download_indexes` / `sub_paths`. Stream adapters consume the session directly; download adapters take `(magnet, indexes)` projections and stay session-unaware.
- `downloader.py`: Subprocess orchestration — `aria2c` / `webtorrent-cli` / `peerflix` execution, VLC launch + sub injection, quiet-mode plumbing, in-torrent sub batch fetch, and `v` / `n` / `b` hotkey handling. Stream adapters take a `TorrentSession`; download adapters keep an explicit `(magnet, indexes)` signature for reuse outside the menu loop.
- `subtitles.py`: Logic for searching and downloading subtitles using `subliminal`. Saves into the effective download folder via `constants.get_download_dir()`.
- `security.py`: Network exposure warning, public-IP/VPN detection via `ip-api.com`.
- `state.py`: Persists engine toggles, active presets, misc settings (dismissed-warning flag, quiet-mode flag, `download_dir`), and search history to `filter_state.json`. Backed by an in-memory cache: mutations mark dirty, disk write happens at `atexit` and at three destructive sites (`save_state`, `clear_history`, `reset_stats`). Includes a one-shot migration that rewrites legacy display-name keys (e.g. `"Movies & Series"`) to provider slugs.
- `stats.py`: Usage counter recorders and read helpers; stores under the `stats` subtree, keyed by provider slug. Same in-memory cache flow as `state.py`.
- `torrent_meta.py`: Fetches a torrent's file list from a magnet via `aria2c`. Helpers for episode-number extraction, video/subtitle classification, multi-episode detection (any torrent with ≥ 2 video files), sub-to-video matching (`match_subtitles_for`), and `--select-file` range formatting.
- `updates.py`: Lightweight git-clone update notice. It rate-limits remote checks in `filter_state.json` and reports when the local branch is behind `origin`.
- `constants.py`: Configuration constants, trackers, UI themes, and `get_download_dir()` (returns the user's chosen `download_dir` setting or falls back to `DOWNLOADS_DIR`).

## Security Notes

This tool does **not** make torrenting safe. Some things it cannot guarantee:

- Your real IP is visible to every peer and tracker in the swarm unless you are behind a VPN.
- Trackers in `constants.py` are plain UDP — there is no "tracker-over-HTTPS" that hides your IP, since trackers exist to exchange peer IPs.
- Seed counts, file names, and uploader tags are not safety signals. The "Trusted Uploaders" preset is a convenience filter based on community reputation, not a guarantee of clean content.
- The startup `ip-api.com` call travels over plain HTTP (free tier limitation). If that matters to you, use `-y` or `TORRENT_SKIP_WARNING=1`.

Use a VPN, verify content before running installers, and treat everything in a public swarm as untrusted.
