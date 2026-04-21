# Torrent Search CLI

An interactive command-line application for searching and downloading torrents directly from your terminal. Built with Python and `rich`.

## Features

- **Multi-Category Search:** Torrents across different providers (Movies, Games, Anime), each with its own tailored search backends.
- **Multi-Engine Fan-Out:** Each provider queries several sources in parallel (e.g. Apibay + SolidTorrents + YTS for Movies, Nyaa for Anime) and merges results, deduplicating by info hash and sorting by seeders.
- **Arrow-Key Driven UI:** Fully interactive, flicker-free terminal interface.
  - Utilizes an alternate screen buffer so your scrollback history remains flawlessly clean.
  - **Dynamic Viewport Windowing:** Capable of rendering massive 500+ item checklists (like huge anime seasons) by automatically windowing the active selection while pinning crucial action buttons tightly to the top and bottom of your screen to prevent terminal overflow.
  - **Marquee Scrolling:** Automatically scrolls long torrent names and checklist items that exceed the physical terminal width when hovered over.
  - **Contextual Footers:** Displays dynamic helper text explaining the trade-offs, speeds, and seeding behaviors of different download options as you highlight them.
- **Advanced Filtering:**
  - Toggle built-in presets (preferred resolutions, known uploaders/repackers, trusted release groups) using an interactive checklist.
  - Toggle individual search engines on and off per provider from the same menu.
  - Add custom include/exclude keywords to quickly find the exact release you want.
  - **Persistent across runs:** your engine toggles and active filter presets are saved to `filter_state.json` next to the script, so configuration sticks after you close the program.
- **Flexible Downloading & Streaming:**
  - **System Client:** Automatically send generated magnet links to your default system torrent client (like qBittorrent, Transmission, etc.).
  - **Direct Terminal Download:** Use `aria2c`, `webtorrent-cli`, or `peerflix` integration to download files directly within the terminal, with native progress UIs.
  - **Episode Picker (Anime):** For multi-file torrents (batches, seasons, complete collections), fetch the torrent's file list via `aria2c` and pick any subset of episodes. Features ultra-fast vim-style visual range selection (`v` to set an anchor, `shift+v` to toggle the block) and rapid hotkeys (`a`, `i`, `c`, `w`). Works natively with `aria2c` (`--select-file=1,3,5-7`) in a single process; falls back to sequential `webtorrent`/`peerflix` sessions per episode.
  - **Stream to VLC:** Stream media directly to VLC Media Player using `webtorrent-cli` or `peerflix`. Press the `v` hotkey at any time during a streaming session to reopen VLC without losing your torrent download/buffering progress. When an episode is selected, streams that specific file.
  - **Subtitle Download:** Search and download the best matching subtitles directly from the terminal using `subliminal`.
  - **Clipboard Integration:** Easily copy magnet links directly to your OS clipboard (Windows/macOS/Linux).
  - **Seamless Error Recovery:** If a terminal download fails, lacks dependencies, or is manually forcefully aborted by you (`Ctrl+C`), the CLI intercepts the exit and safely drops you back into the download method selector without losing your active search context.
- **Network Exposure Warning:** At startup a red panel queries `ip-api.com` and shows your public IP, ISP, ASN, location, plus flags for `proxy` / `hosting` / `mobile`. Gives you a clear go/no-go decision before joining a public swarm.
- **Pagination & Navigation:** Navigate through large sets of search results cleanly, with the ability to safely go back to your previous search results after viewing download options.

## Prerequisites

- **Python 3.x**
- (Optional but recommended) **Node.js** & **npm** for installing `webtorrent-cli` or `peerflix`.
- (Optional) **VLC Media Player** — required for streaming.
- (Optional) **aria2** — required for the anime episode picker and for single-process multi-file downloads. Install with `winget install aria2.aria2` (Windows), `brew install aria2` (macOS), or `apt install aria2` / `dnf install aria2` (Linux).

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

# Specify the search type (movie, game, anime)
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
- **Clear filters**: The "Clear filters" button in the filter menu only clears preset toggles — your engine selections are preserved.
- **Cancel / Back**: Press `Esc` to safely cancel an action, close a menu, or go back to the previous screen.


## Project Architecture

The application is structured into a modular, provider-based architecture:

- `main.py`: The main entry point and CLI argument parser.
- `providers/`: Directory containing different search categories (Movies, Games, Anime). Each provider declares its own search engines, default filters, and toggleable presets.
- `ui/`: Controls the interactive terminal prompts and rendering of tables using the `rich` library.
- `filters.py`: Logic processing for including or excluding keywords.
- `downloader.py`: Logic handling torrent client detection and `webtorrent-cli` / `peerflix` execution.
- `subtitles.py`: Logic for searching and downloading subtitles using `subliminal`.
- `security.py`: Network exposure warning, public-IP/VPN detection via `ip-api.com`.
- `state.py`: Persists engine toggles, active presets, and the dismissed-warning flag to `filter_state.json`.
- `torrent_meta.py`: Fetches a torrent's file list from a magnet via `aria2c`; helpers for episode-number extraction and `--select-file` range formatting.
- `constants.py`: Stores configuration constants, trackers, and UI themes.

## Security Notes

This tool does **not** make torrenting safe. Some things it cannot guarantee:

- Your real IP is visible to every peer and tracker in the swarm unless you are behind a VPN.
- Trackers in `constants.py` are plain UDP — there is no "tracker-over-HTTPS" that hides your IP, since trackers exist to exchange peer IPs.
- Seed counts, file names, and uploader tags are not safety signals. The "Trusted Uploaders" preset is a convenience filter based on community reputation, not a guarantee of clean content.
- The startup `ip-api.com` call travels over plain HTTP (free tier limitation). If that matters to you, use `-y` or `TORRENT_SKIP_WARNING=1`.

Use a VPN, verify content before running installers, and treat everything in a public swarm as untrusted.
