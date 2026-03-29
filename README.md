# Torrent Search CLI

A interactive command-line application for searching and downloading torrents directly from your terminal. Built with Python and `rich`.

## Features

- **Multi-Category Search:** Torrents across different providers (Movies, Games, Anime).
- **Interactive UI:** Single unified view using custom terminal UI elements for seamless navigation.
- **Advanced Filtering:** 
  - Toggle built-in presets (e.g., preferred resolutions, known uploaders/repackers).
  - Add custom include/exclude keywords to quickly find the exact release you want.
- **Flexible Downloading:**
  - **System Client:** Automatically send generated magnet links to your default system torrent client (like qBittorrent, Transmission, etc.).
  - **Direct Terminal Download:** Use `webtorrent-cli` integration to download files directly within the terminal, featuring native interactive progress bars.
- **Pagination:** Navigate through large sets of search results cleanly without cluttering the screen.

## Prerequisites

- **Python 3.x**
- (Optional but recommended) **Node.js** & **npm** for installing `webtorrent-cli`.

## Installation

1. Clone or download the repository.
2. Install the required Python dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. (Optional) Install `webtorrent-cli` if you want to download files directly within the terminal:

   ```bash
   npm install -g webtorrent-cli
   ```

## Usage

### Interactive Mode

The easiest way to use the CLI is to run it interactively. It will guide you through selecting a category, searching, filtering, and downloading.

```bash
# On Windows, you can use the provided batch script
torrent.bat

# Or run the main Python script directly
python main.py
```

### Command Line Arguments

You can bypass the initial interactive prompts and search directly using arguments:

```bash
# Direct search (defaults to Movies)
python main.py -q "The Matrix"

# Specify the search type (movie, game, anime)
python main.py -q "Elden Ring" -t game

# Apply custom filters (include "1080p", exclude "cam")
python main.py -q "Dune" -t movie -f "1080p" -x "cam"
```

### Shortcuts in Interactive Mode

- Use `Up/Down` arrows to navigate lists and tables.
- Press `Enter` to select an item.
- Press `Shift+F` on the search prompt to open the interactive filter menu for the current provider.
- Press `Esc` to go back or cancel a selection.

## Project Architecture

The application is structured into a modular, provider-based architecture:

- `main.py`: The main entry point and CLI argument parser.
- `providers/`: Directory containing different search categories (Movies, Games, Anime) with their specific default filter presets.
- `ui/`: Controls the interactive terminal prompts and rendering of tables using the `rich` library.
- `filters.py`: Logic processing for including or excluding keywords.
- `downloader.py`: Logic handling torrent client detection and `webtorrent-cli` execution.
- `constants.py`: Stores configuration constants, trackers, and UI themes.
