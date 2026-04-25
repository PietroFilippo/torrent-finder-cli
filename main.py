#!/usr/bin/env python3
"""
Torrent Search CLI — Search for torrents and download via magnet link.

Usage:
    python main.py              # Interactive prompt
    python main.py -q "query"   # Direct search
"""
import argparse
import time
import warnings

# Suppress requests dependency warnings (urllib3/chardet version mismatch)
warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from constants import console
import readchar
from downloader import download_with_aria2, download_with_webtorrent, download_with_peerflix, has_aria2, open_magnet, stream_with_peerflix, stream_with_webtorrent
from filters import FilterConfig
from providers import PROVIDERS, get_provider
from security import show_security_warning
from state import load_state
from stats import (
    add_runtime_seconds,
    record_magnet_dispatch,
    record_method_complete,
    record_method_pick,
    record_search,
    record_session_start,
    record_torrent_picked,
)
from torrent_meta import fetch_file_list
from ui.prompts import clear_screen, download_method_prompt, episode_select_prompt, filter_menu, get_query_with_shortcut, print_banner, provider_select_prompt, search_again_prompt
from ui.table import interactive_select
from utils import build_magnet

load_state(PROVIDERS)


# Maps download-method values returned by download_method_prompt to the
# stable method names stored in stats.
_METHOD_TRACK = {
    "t": "open_magnet",
    "stream_p": "stream_peerflix",
    "stream_w": "stream_webtorrent",
    "aria": "aria",
    "p": "peerflix_download",
    "d": "webtorrent_download",
    "s": "subtitles",
}


def _main_loop() -> None:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("-q", "--query", type=str, help="Search query (skip prompt)")
    parser.add_argument("-t", "--type", type=str, choices=["movie", "game", "anime"], help="Search type (default: movie if used with -q)")
    parser.add_argument("-f", "--filter", action="append", help="Include keyword in results")
    parser.add_argument("-x", "--exclude", action="append", help="Exclude keyword from results")
    parser.add_argument("-y", "--skip-warning", action="store_true", help="Skip network exposure warning")
    args = parser.parse_args()

    if not args.skip_warning:
        if not show_security_warning():
            console.print("[info]Aborted.[/info]")
            return

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
            result = provider_select_prompt()
            if result is None:
                console.print("\n[info]Goodbye![/info]")
                break
            # History selection returns ("history", query, provider)
            if isinstance(result, tuple) and result[0] == "history":
                _, query, current_provider = result
            else:
                current_provider = result
            clear_screen()

        provider = current_provider

        # 2. Get query
        if not query:
            # Build status line showing active engines and filters
            engine_names = [e.name for e in provider.engines if e.enabled] if hasattr(provider, 'engines') else []
            engine_str = ", ".join(engine_names) if engine_names else "None"
            active_names = [p.name for p in provider.active_presets]
            active_name = ", ".join(active_names) if active_names else "None"
            console.print(f"[dim]Engines:[/dim] [cyan]{engine_str}[/cyan]   [dim]Filters:[/dim] [cyan]{active_name}[/cyan]")
            console.print(
                "[bold yellow on grey23] Shift+F [/bold yellow on grey23] "
                "[white]engines & filters[/white]   "
                "[bold yellow on grey23] Shift+H [/bold yellow on grey23] "
                "[white]history[/white]   "
                "[bold yellow on grey23] Shift+S [/bold yellow on grey23] "
                "[white]stats[/white]   "
                "[bold]Esc[/bold] [dim]go back[/dim]"
            )
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
            elif query == "SPECIAL_HISTORY":
                from ui.history import history_select_prompt
                pick = history_select_prompt()
                if pick:
                    query, prov_name = pick
                    from providers import get_provider
                    hist_prov = get_provider(prov_name)
                    if hist_prov:
                        current_provider = hist_prov
                else:
                    query = None
                clear_screen()
                continue
            elif query == "SPECIAL_STATS":
                from ui.stats import stats_page
                stats_page()
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

        with console.status(f"[bold cyan]Searching {provider.name}...[/bold cyan]", spinner="dots"):
            results = provider.search(query, cli_filters=cli_filters)
        
        if not results:
            console.print("[warning] No results found.[/warning]\n")
            query = None
            continue

        # Record successful search in history + stats
        from state import add_history_entry
        active_preset_names = [pr.name for pr in getattr(provider, "active_presets", [])]
        add_history_entry(query, provider.name, active_preset_names)
        record_search(provider.name, query, active_preset_names)

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
            record_torrent_picked(provider.name, int(selected.get("seeders", 0) or 0))

            # Download method selection
            magnet = build_magnet(info_hash, name)

            go_back_to_results = False
            selected_files: list[int] | None = None
            files_meta = None
            while True:
                show_subs = hasattr(provider, "name") and provider.name in ("Movies & Series", "Anime")
                show_picker = hasattr(provider, "name") and provider.name in ("Movies & Series", "Anime")
                method = download_method_prompt(
                    magnet=magnet,
                    show_subtitles=show_subs,
                    show_episode_picker=show_picker,
                    selected_indexes=selected_files,
                )

                if method in _METHOD_TRACK:
                    record_method_pick(_METHOD_TRACK[method])

                if method == "pick_episodes":
                    clear_screen()
                    if not has_aria2():
                        console.print("[error]aria2c required to list files. Install from https://aria2.github.io/[/error]\n")
                        console.print("[dim]Press any key to continue...[/dim]")
                        readchar.readkey()
                        continue
                    console.print("[info]Fetching torrent metadata via DHT (this can take 30–60s)...[/info]\n")
                    with console.status("[bold cyan]Fetching file list...[/bold cyan]", spinner="dots"):
                        metadata = fetch_file_list(magnet)
                    if not metadata or not metadata.files:
                        console.print("[error] Could not fetch file list (timeout or no metadata peers).[/error]\n")
                        console.print("[dim]Press any key to continue...[/dim]")
                        readchar.readkey()
                        continue
                    if len(metadata.files) == 1:
                        console.print("[warning] Torrent contains a single file — nothing to pick.[/warning]\n")
                        console.print("[dim]Press any key to continue...[/dim]")
                        readchar.readkey()
                        continue
                    picked = episode_select_prompt(metadata.files, preselected=selected_files)
                    if picked is not None:
                        # Confirm pressed — replace selection (empty list clears it)
                        selected_files = picked or None
                        files_meta = metadata if picked else None
                    clear_screen()
                    continue

                if method == "t":
                    clear_screen()
                    console.print("[info]Opening magnet link with default torrent client...[/info]")
                    if selected_files:
                        console.print(
                            "[warning] External torrent clients cannot be pre-filtered from here.[/warning]\n"
                            "[dim]When the client's 'Add new torrent' dialog appears, uncheck the files you don't want.[/dim]\n"
                            "[dim]If your client skipped the dialog, pause the torrent and deselect unwanted files in its Content/Files tab.[/dim]"
                        )
                    open_magnet(magnet)
                    record_magnet_dispatch()
                    console.print("[success] Magnet link sent to torrent client![/success]\n")
                    console.print("[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    break
                elif method == "stream_p":
                    clear_screen()
                    stream_with_peerflix(magnet, select_indexes=selected_files, files=files_meta)
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    continue
                elif method == "stream_w":
                    clear_screen()
                    stream_with_webtorrent(magnet, select_indexes=selected_files, files=files_meta)
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    continue
                elif method == "aria":
                    clear_screen()
                    ok = download_with_aria2(magnet, select_indexes=selected_files)
                    if ok:
                        record_method_complete("aria")
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    if not ok:
                        continue  # back to download-method menu
                    break
                elif method == "p":
                    clear_screen()
                    ok = download_with_peerflix(magnet, select_indexes=selected_files)
                    if ok:
                        record_method_complete("peerflix_download")
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    if not ok:
                        continue
                    break
                elif method == "d":
                    clear_screen()
                    ok = download_with_webtorrent(magnet, select_indexes=selected_files)
                    if ok:
                        record_method_complete("webtorrent_download")
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    if not ok:
                        continue
                    break
                elif method == "s":
                    from subtitles import download_subtitles
                    download_subtitles(name)
                    record_method_complete("subtitles")
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
        if isinstance(choice, tuple) and choice[0] == "history":
            _, query, current_provider = choice
            clear_screen()
        elif choice == "search":
            clear_screen()
            query = None
        elif choice == "provider":
            current_provider = None
            query = None
        else:
            console.print("[info]Goodbye![/info]")
            break

def main() -> None:
    record_session_start()
    t0 = time.monotonic()
    try:
        _main_loop()
    finally:
        add_runtime_seconds(time.monotonic() - t0)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[info]Goodbye![/info]")
