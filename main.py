#!/usr/bin/env python3
"""
Torrent Search CLI — Search for torrents and download via magnet link.

Usage:
    python main.py              # Interactive prompt
    python main.py -q "query"   # Direct search
"""
import argparse

from constants import console
from downloader import download_with_webtorrent, open_magnet
from providers import PROVIDERS
from ui.prompts import download_method_prompt, print_banner
from ui.table import interactive_select
from utils import build_magnet


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("-q", "--query", type=str, help="Search query (skip prompt)")
    args = parser.parse_args()

    print_banner()

    # Default provider (Movies)
    provider = PROVIDERS[0]

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

        # Search using provider
        console.print(f"[info]Searching for:[/info] [highlight]{query}[/highlight]...")

        results = provider.search(query)
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

        console.print(f"\n[success] Selected:[/success] [highlight]{name}[/highlight]\n")

        # Download method selection
        magnet = build_magnet(info_hash, name)
        method = download_method_prompt()

        if method == "t":
            console.print("[info]Opening magnet link with default torrent client...[/info]")
            open_magnet(magnet)
            console.print("[success] Magnet link sent to torrent client![/success]\n")
        elif method == "d":
            download_with_webtorrent(magnet)
        else:
            console.print("[info]Download cancelled.[/info]\n")
            query = None
            continue

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
