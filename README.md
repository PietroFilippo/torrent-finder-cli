# Torrent Search CLI

An interactive command-line application for searching and downloading torrents directly from your terminal. Built with Python and `rich`.

## Features

- **Multi-Category Search:** Torrents across different providers (Movies & Series, Games, Anime), each with its own tailored search backends. The Movies & Series provider handles both films and TV shows — the episode-aware streaming flow kicks in automatically when a torrent contains multiple video files.
- **Multi-Engine Fan-Out:** Each provider queries several sources in parallel (e.g. Apibay + SolidTorrents + YTS for Movies & Series, Nyaa for Anime) and merges results, deduplicating by info hash and sorting by seeders.
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
  - **Persistent across runs:** engine toggles, active filter presets, search history, usage stats, the quiet-mode flag, and the dismissed-warning state all live in `filter_state.json` next to the script, so configuration sticks after you close the program.
- **Search History:** Press `Shift+H` at the search prompt (or `H` on the provider screen) to browse past searches. Filter by provider (`P`), date range (`D`, today/week/month), and sort order (`S`). Each entry shows the provider, relative timestamp, and the filter presets that were active at search time. Pick an entry to re-run the query; clear history with a confirmation modal.
- **Usage Stats:** Press `Shift+S` at the search prompt (or `S` on the provider screen) to open a scrollable stats page showing session count, total runtime, searches, top queries, torrents picked, method picks vs. completions (with success rate), avg seeders of picks, and preset usage counters. Reset all stats from the same screen, guarded by a confirmation modal.
- **Confirmation Modals:** Destructive actions (clear history, reset stats) share a unified red Y/N panel so you can't nuke state with a stray keypress.
- **Dynamic Contextual Tips:** Random hints (`💡 Tip: ...`) are displayed in the footers of the provider selector and post-download menus to remind you about hotkeys, quiet mode, episode picking, and UI shortcuts.
- **Quiet Mode:** Toggle **🔇 Quiet mode** from the Download Method menu to suppress the native progress UIs of `aria2c`, `webtorrent-cli`, and `peerflix` (full-screen progress bars, peer lists, speed graphs) and replace them with a single minimal spinner. The toggle redraws in place with no flicker and persists across runs (stored as `hide_stream_output` in `filter_state.json`). Episode info, VLC hotkey hints, and `Ctrl+C` all still work.
- **Flexible Downloading & Streaming:**
  - **System Client:** Automatically send generated magnet links to your default system torrent client (like qBittorrent, Transmission, etc.).
  - **Direct Terminal Download:** Use `aria2c`, `webtorrent-cli`, or `peerflix` integration to download files directly within the terminal, with native progress UIs.
  - **File Browser / Episode Picker (Anime + Movies & Series):** Open **📂 Browse torrent files…** from the download menu to list every file in the torrent (videos, subs, artwork, .nfo, samples) and pick any subset. Features vim-style visual range selection (`v` anchor, `Shift+V` range-toggle) and rapid hotkeys (`a`, `i`, `c`, `w`). **Selection persists across re-entries** — reopening the picker shows your existing checkboxes already ticked, so you can refine without rebuilding from scratch. Confirming with nothing checked clears the selection; `Esc` cancels and keeps the prior picks intact. Only `aria2c` honors strict file selection on download — `webtorrent` and `peerflix` ignore `--select` and pull the whole torrent (the menu warns you when a selection is active). **Streams auto-skip non-video picks** and warn about it, so you can still e.g. download the .srt + .nfo alongside the video without breaking playback. If a stream selection contains zero video files, the stream errors out instead of silently substituting another file.
  - **Stream to VLC:** Stream media directly to VLC Media Player using `webtorrent-cli` (default) or `peerflix` (fallback). Both stream and download menus list **webtorrent before peerflix** to match this preference. Press the `v` hotkey at any time during a streaming session to reopen VLC without losing your torrent download/buffering progress. The CLI checks active processes (`tasklist` on Windows, `pgrep -x` on Mac/Linux) and silently ignores the hotkey if VLC is already running, preventing accidental duplicate windows. When an episode is selected, streams that specific file.
  - **Subtitles for streams (auto + manual):** A `📝 Source: <mode>` row in the Download Method menu controls how VLC gets subtitles for the next stream:
    - `auto-detect from torrent` *(default)* — scans the torrent for `.srt/.ass/.ssa/.vtt/.sub` files paired with each video (matched by basename, language tag like `.en.srt`, or a sibling `Subs/` folder with episode-numbered files like `01.ass`). Matches are pre-downloaded via aria2c and attached to VLC via `--sub-file` before playback starts. English subs are prioritized as the primary track when available.
    - `external file` — pick a `.srt/.ass` from a list of recent files in your `downloads/` folder, or type a custom path. The same file is attached to every episode in the session.
    - `off` — stream with no subtitles.
    - After downloading subs via **📝 Search & download subtitles** (the existing subliminal flow), the saved file is auto-promoted to external mode so your next stream just picks it up.
  - **Auto Episode Navigation:** When streaming a multi-episode torrent (TV shows, anime batches, season packs) **without** pre-selecting anything, the CLI auto-detects the episode structure via `aria2c` metadata, queues every video file in episode order, and enables `n` (next) / `b` (previous) hotkeys so you can jump between episodes mid-session. Single-file movies still stream as-is — no forced picker, no extra wait. Detection accepts either: (1) ≥ 2 video files carrying explicit episode markers (`S01E01`, ` - 01`, `[01]`, `Episode 01`) regardless of size — robust for releases where finales/specials run 2-3× the average ep — or (2) ≥ 2 video files whose sizes are within an order of magnitude of each other.
  - **Subtitle Download:** Search and download the best matching subtitles directly from the terminal using `subliminal`.
  - **Clipboard Integration:** Easily copy magnet links directly to your OS clipboard (Windows/macOS/Linux).
  - **Seamless Error Recovery:** If a terminal download fails, lacks dependencies, or is manually forcefully aborted by you (`Ctrl+C`), the CLI intercepts the exit and safely drops you back into the download method selector without losing your active search context.
- **Network Exposure Warning:** At startup a red panel queries `ip-api.com` and shows your public IP, ISP, ASN, location, plus flags for `proxy` / `hosting` / `mobile`. Gives you a clear go/no-go decision before joining a public swarm.
- **Pagination & Navigation:** Navigate through large sets of search results cleanly, with the ability to safely go back to your previous search results after viewing download options.

## Prerequisites

- **Python 3.x**
- (Optional but recommended) **Node.js** & **npm** for installing `webtorrent-cli` or `peerflix`.
- (Optional) **VLC Media Player** — required for streaming.
- (Optional) **aria2** — required for the file browser / episode picker, the in-torrent subtitle auto-detect path, auto episode navigation on the peerflix backend, and single-process multi-file downloads. Install with `winget install aria2.aria2` (Windows), `brew install aria2` (macOS), or `apt install aria2` / `dnf install aria2` (Linux).

## Installation

1. Clone or download the repository.
2. Install the required Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. (Optional) Install `webtorrent-cli` and/or `peerflix` if you want to download or stream files directly within the terminal:

   ```bash
   npm install -g webtorrent-cli peerflix
   ```

## Usage

### Interactive Mode

The easiest way to use the CLI is to run it interactively. The arrow-key driven UI will guide you through selecting a category, searching, filtering, and downloading.

```bash
# On Windows, you can use the provided batch script
torrent.bat

# Or run the main Python script directly
python main.py
```

### Command Line Arguments

```bash
# Direct search (defaults to Movies)
python main.py -q "The Matrix"

# Specify the search type (movie, game, anime). `movie` covers both films and series.
python main.py -q "Elden Ring" -t game

# Apply custom filters (include "1080p", exclude "cam")
python main.py -q "Dune" -t movie -f "1080p" -x "cam"

# Skip the network exposure warning at startup
python main.py -y
```

You can also suppress the warning with the environment variable `TORRENT_SKIP_WARNING=1`, or permanently dismiss it from inside the panel itself (see below).

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
- **Configure filters during search**: Press `Shift+F` at the search prompt to open the filter menu for the current provider. The status line above the prompt shows the active engines / presets and the hotkey.
- **Filter menu keybinds**: `a` select all, `i` invert, `c` clear presets, `w` save & confirm, `v` drop anchor, `Shift+V` range toggle between anchor and cursor, `Space` toggle current. The "Clear filters" button clears preset toggles only — your engine selections are preserved.
- **Search history / stats from the search prompt**: `Shift+H` opens history, `Shift+S` opens usage stats. On the provider screen use `H` and `S`.
- **Cancel / Back**: Press `Esc` to safely cancel an action, close a menu, or go back to the previous screen.


## Project Architecture

The application is structured into a modular, provider-based architecture:

- `main.py`: The main entry point and CLI argument parser.
- `providers/`: Directory containing different search categories (Movies & Series, Games, Anime). Each provider declares its own search engines, default filters, and toggleable presets.
- `ui/`: Controls the interactive terminal prompts and rendering of tables using the `rich` library. Includes `prompts.py` (menus + `confirm_prompt` modal + `subtitle_source_prompt`), `selector.py` (reusable arrow-key selector with windowing / marquee), `table.py` (paginated result table), `history.py` (search history browser), `stats.py` (usage stats page), and `tips.py` (rotating contextual hints).
- `filters.py`: Logic processing for including or excluding keywords.
- `downloader.py`: Torrent-client detection, `aria2c` / `webtorrent-cli` / `peerflix` execution, VLC launch + sub injection, quiet-mode plumbing, and `v` / `n` / `b` hotkey handling.
- `subtitles.py`: Logic for searching and downloading subtitles using `subliminal`.
- `security.py`: Network exposure warning, public-IP/VPN detection via `ip-api.com`.
- `state.py`: Persists engine toggles, active presets, misc settings (dismissed-warning flag, quiet-mode flag), and search history to `filter_state.json`.
- `stats.py`: Usage counter recorders and read helpers; stores under the `stats` subtree of `filter_state.json`.
- `torrent_meta.py`: Fetches a torrent's file list from a magnet via `aria2c`. Helpers for episode-number extraction, video/subtitle classification, multi-episode detection, sub-to-video matching (`match_subtitles_for`), and `--select-file` range formatting.
- `constants.py`: Stores configuration constants, trackers, and UI themes.

## Security Notes

This tool does **not** make torrenting safe. Some things it cannot guarantee:

- Your real IP is visible to every peer and tracker in the swarm unless you are behind a VPN.
- Trackers in `constants.py` are plain UDP — there is no "tracker-over-HTTPS" that hides your IP, since trackers exist to exchange peer IPs.
- Seed counts, file names, and uploader tags are not safety signals. The "Trusted Uploaders" preset is a convenience filter based on community reputation, not a guarantee of clean content.
- The startup `ip-api.com` call travels over plain HTTP (free tier limitation). If that matters to you, use `-y` or `TORRENT_SKIP_WARNING=1`.

Use a VPN, verify content before running installers, and treat everything in a public swarm as untrusted.
