#!/usr/bin/env python3
"""
Torrent Search CLI — Search for torrents and download via magnet link.

Usage:
    python main.py              # Interactive prompt
    python main.py -q "query"   # Direct search
"""
import argparse
import warnings

# Suppress requests dependency warnings (urllib3/chardet version mismatch)
warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from constants import console
import readchar
from downloader import download_with_webtorrent, open_magnet
from filters import FilterConfig
from providers import PROVIDERS, get_provider
from ui.prompts import clear_screen, download_method_prompt, filter_menu, get_query_with_shortcut, print_banner, provider_select_prompt, search_again_prompt
from ui.table import interactive_select
from utils import build_magnet


def main() -> None:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("-q", "--query", type=str, help="Search query (skip prompt)")
    parser.add_argument("-t", "--type", type=str, choices=["movie", "game", "anime"], help="Search type (default: movie if used with -q)")
    parser.add_argument("-f", "--filter", action="append", help="Include keyword in results")
    parser.add_argument("-x", "--exclude", action="append", help="Exclude keyword from results")
    args = parser.parse_args()

    query = args.query
    initial_provider = None

    if args.type:
        initial_provider = get_provider(args.type)
        if not initial_provider:
            console.print(f"[warning] Unknown provider type '{args.type}'. Falling back to Movies.[/warning]")
            initial_provider = PROVIDERS[0]
    elif query:
        # Backward compatibility: if -q is passed but no -t, default to Movies
        initial_provider = PROVIDERS[0]

    session_provider = initial_provider
    current_provider = session_provider
    
    cli_filters = None
    if args.filter or args.exclude:
        cli_filters = FilterConfig(
            include_keywords=args.filter or [],
            exclude_keywords=args.exclude or [],
        )

    # Clean the terminal for initial run if an interactive search is expected
    if not (args.type and args.query):
        console.clear()

    while True:
        if not current_provider:
            current_provider = provider_select_prompt()
            if not current_provider:
                console.print("\n[info]Goodbye![/info]")
                break
            clear_screen()

        provider = current_provider

        # 2. Get query
        if not query:
            active_names = [p.name for p in provider.active_presets]
            active_name = ", ".join(active_names) if active_names else "None"
            console.print(f"[dim]Active Filters: {active_name} | Press Shift+F to change | Esc to go back[/dim]")
            try:
                query = get_query_with_shortcut(f"[title] Search {provider.name}:[/title] ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n[info]Goodbye![/info]")
                break
                
            if query == "SPECIAL_FILTER":
                filter_menu(provider)
                clear_screen()
                query = None
                continue
            elif query == "GO_BACK":
                current_provider = None
                query = None
                continue

        if not query:
            console.print("[warning] Please enter a search term.[/warning]")
            query = None
            continue

        # Search using provider
        console.print(f"[info]Searching {provider.name} for:[/info] [highlight]{query}[/highlight]...")

        results = provider.search(query, cli_filters=cli_filters)
        if not results:
            console.print("[warning] No results found.[/warning]\n")
            query = None
            continue

        # Torrent selection + download loop (allows going back to results)
        while True:
            clear_screen()
            idx = interactive_select(results)
            if idx is None:
                query = None
                break

            selected = results[idx]
            name = selected.get("name", "Unknown")
            info_hash = selected.get("info_hash", "")

            # Download method selection
            magnet = build_magnet(info_hash, name)

            go_back_to_results = False
            while True:
                show_subs = hasattr(provider, "name") and provider.name in ("Movies", "Anime")
                method = download_method_prompt(magnet=magnet, show_subtitles=show_subs)

                if method == "t":
                    clear_screen()
                    console.print("[info]Opening magnet link with default torrent client...[/info]")
                    open_magnet(magnet)
                    console.print("[success] Magnet link sent to torrent client![/success]\n")
                    console.print("[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    break
                elif method == "d":
                    clear_screen()
                    download_with_webtorrent(magnet)
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    break
                elif method == "s":
                    from subtitles import download_subtitles
                    download_subtitles(name)
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    continue
                elif method == "back":
                    go_back_to_results = True
                    break
                else:
                    break

            if go_back_to_results:
                continue  # Back to torrent selection
            break  # Proceed to "what's next?"

        if idx is None:
            continue

        # What's next?
        choice = search_again_prompt()
        if choice == "search":
            clear_screen()
        elif choice == "provider":
            current_provider = None
        else:
            console.print("[info]Goodbye![/info]")
            break

        query = None

if __name__ == "__main__":
    main()
