#!/usr/bin/env python3
"""
Torrent Search CLI — Search for torrents and download via magnet link.

Usage:
    python torrent_search.py              # Interactive prompt
    python torrent_search.py -q "query"   # Direct search
"""

import argparse
import os
import platform
import subprocess
import sys

import readchar
import requests
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Theme & Console
custom_theme = Theme(
    {
        "title": "bold magenta",
        "info": "dim cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "highlight": "bold white",
    }
)

console = Console(theme=custom_theme)

# Constants
API_URL = "https://apibay.org/q.php"
MAX_RESULTS = 20

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969",
    "udp://open.demonii.com:1337/announce",
]


# Utilities
def format_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    if size_bytes <= 0:
        return "N/A"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    size = float(size_bytes)
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {units[idx]}"


def seed_style(seeds: int) -> str:
    """Return a rich color tag based on seed count."""
    if seeds >= 50:
        return "bold green"
    elif seeds >= 10:
        return "green"
    elif seeds >= 1:
        return "yellow"
    return "red"


def leech_style(leeches: int) -> str:
    """Return a rich color tag based on leech count."""
    if leeches <= 5:
        return "dim white"
    elif leeches <= 50:
        return "yellow"
    return "red"


def build_magnet(info_hash: str, name: str) -> str:
    """Build a magnet URI from an info hash."""
    trackers = "&".join(f"tr={t}" for t in TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={name}&{trackers}"


def open_magnet(magnet_link: str) -> None:
    """Open a magnet link with the system default handler (qBittorrent, etc.)."""
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(magnet_link)
        elif system == "Darwin":
            subprocess.Popen(["open", magnet_link])
        else:
            subprocess.Popen(["xdg-open", magnet_link])
    except Exception as e:
        console.print(f"[error] Failed to open magnet link: {e}[/error]")
        console.print(f"[info]Magnet link:[/info] {magnet_link}")


# API


def search_torrents(query: str) -> list[dict]:
    """Search apibay.org and return a list of torrent dicts."""
    try:
        response = requests.get(API_URL, params={"q": query}, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        console.print(f"[error] API request failed: {e}[/error]")
        return []
    except ValueError:
        console.print("[error] Invalid response from API.[/error]")
        return []

    # apibay returns [{"id": "0", "name": "No results ..."}] when nothing is found
    if not data or (len(data) == 1 and data[0].get("id") == "0"):
        return []

    return data[:MAX_RESULTS]


# Interactive Table Selection
def build_table(
    results: list[dict],
    selected_idx: int,
    scroll_offset: int,
    visible_count: int,
    total: int,
) -> Table:
    """Build a rich table showing only the visible window of rows."""
    # Scroll indicator in the title
    end_idx = min(scroll_offset + visible_count, total)
    scroll_info = f"[dim]({scroll_offset + 1}-{end_idx} of {total})[/dim]"

    table = Table(
        title=f"Torrent Results {scroll_info}",
        title_style="bold magenta",
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=False,
        padding=(0, 1),
        caption="[dim] Up/Down: navigate | Enter: select | Esc: cancel | Type number to jump[/dim]",
        caption_style="dim",
    )

    table.add_column("#", style="bold white", justify="right", width=4)
    table.add_column("Name", style="white", max_width=60, no_wrap=True)
    table.add_column("Size", style="cyan", justify="right", width=10)
    table.add_column("Seeds", justify="right", width=7)
    table.add_column("Leeches", justify="right", width=9)

    # Only render the visible slice
    visible_slice = results[scroll_offset:end_idx]

    for vi, item in enumerate(visible_slice):
        i = scroll_offset + vi  # Real index
        seeds = int(item.get("seeders", 0))
        leeches = int(item.get("leechers", 0))
        size = int(item.get("size", 0))
        name = item.get("name", "Unknown")

        is_selected = i == selected_idx

        if is_selected:
            row_style = "bold reverse"
            num_text = f">> {i}"
            seed_text = str(seeds)
            leech_text = str(leeches)
        else:
            row_style = "" if i % 2 == 0 else "dim"
            num_text = str(i)
            seed_text = f"[{seed_style(seeds)}]{seeds}[/{seed_style(seeds)}]"
            leech_text = f"[{leech_style(leeches)}]{leeches}[/{leech_style(leeches)}]"

        table.add_row(
            num_text,
            name,
            format_size(size),
            seed_text,
            leech_text,
            style=row_style,
        )

    return table


def interactive_select(results: list[dict]) -> int | None:
    """
    Display an interactive table where the user navigates with arrow keys.
    Only shows rows that fit the terminal height (scrolling window).
    Returns the index of the selected result, or None if cancelled.
    """
    current = 0
    num_buffer = ""
    total = len(results)

    # Calculate how many rows fit: terminal height minus overhead
    # (title, header, caption, border lines, prompt above/below ~ 8 lines)
    term_height = console.size.height
    overhead = 8
    visible_count = max(3, term_height - overhead)
    visible_count = min(visible_count, total)  # Don't exceed result count

    scroll_offset = 0

    console.print()

    with Live(
        build_table(results, current, scroll_offset, visible_count, total),
        console=console,
        refresh_per_second=15,
        transient=False,
    ) as live:
        while True:
            key = readchar.readkey()

            if key == readchar.key.UP:
                current = max(0, current - 1)
                num_buffer = ""
            elif key == readchar.key.DOWN:
                current = min(total - 1, current + 1)
                num_buffer = ""
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                return current
            elif key == readchar.key.ESC:
                return None
            elif key in (readchar.key.CTRL_C,):
                return None
            elif key.isdigit():
                num_buffer += key
                try:
                    idx = int(num_buffer)
                    if 0 <= idx < total:
                        current = idx
                    if idx >= total and idx * 10 > total * 10:
                        num_buffer = key
                        idx = int(key)
                        if 0 <= idx < total:
                            current = idx
                except ValueError:
                    num_buffer = ""
            else:
                num_buffer = ""

            # Keep cursor visible: adjust scroll_offset to follow current
            if current < scroll_offset:
                scroll_offset = current
            elif current >= scroll_offset + visible_count:
                scroll_offset = current - visible_count + 1

            live.update(
                build_table(results, current, scroll_offset, visible_count, total)
            )

    return None


# Main Loop
def print_banner() -> None:
    banner = Text()
    banner.append("Torrent Search CLI", style="bold magenta")
    console.print(
        Panel(
            banner,
            border_style="bright_blue",
            padding=(1, 2),
        )
    )
    console.print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("-q", "--query", type=str, help="Search query (skip prompt)")
    args = parser.parse_args()

    print_banner()

    query = args.query

    while True:
        # Get query
        if not query:
            try:
                query = console.input("[title] Search torrent:[/title] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[info]Goodbye![/info]")
                break

        if not query:
            console.print("[warning] Please enter a search term.[/warning]")
            query = None
            continue

        # Search
        console.print(f"[info]Searching for:[/info] [highlight]{query}[/highlight]...")

        results = search_torrents(query)
        if not results:
            console.print("[warning] No results found.[/warning]\n")
            query = None
            continue

        # Interactive table selection (single unified view)
        idx = interactive_select(results)
        if idx is None:
            console.print("[info]Selection cancelled.[/info]\n")
            query = None
            continue

        selected = results[idx]
        name = selected.get("name", "Unknown")
        info_hash = selected.get("info_hash", "")

        console.print(f"\n[success] Selected:[/success] [highlight]{name}[/highlight]")

        # Download
        magnet = build_magnet(info_hash, name)
        console.print("[info]Opening magnet link with default torrent client...[/info]")
        open_magnet(magnet)
        console.print("[success] Magnet link sent to torrent client![/success]\n")

        # Continue?
        try:
            again = console.input("[info]Search again? (Y/n):[/info] ").strip().lower()
            if again in ("n", "no"):
                console.print("[info]Goodbye![/info]")
                break
        except (EOFError, KeyboardInterrupt):
            console.print("\n[info]Goodbye![/info]")
            break

        query = None


if __name__ == "__main__":
    main()
