#!/usr/bin/env python3
"""
Torrent Search CLI — Search for torrents and download via magnet link.

Usage:
    python main.py              # Interactive prompt
    python main.py -q "query"   # Direct search
"""
import argparse
import threading
import time
import warnings

# Suppress requests dependency warnings (urllib3/chardet version mismatch)
warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from constants import console
import readchar
from downloader import download_with_aria2, download_with_webtorrent, download_with_peerflix, has_aria2, open_magnet, open_torrent_file, stream_with_peerflix, stream_with_webtorrent
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
from torrent_session import TorrentSession
from ui.prompts import clear_screen, download_method_prompt, episode_select_prompt, filter_menu, get_query_with_shortcut, print_banner, provider_select_prompt, search_again_prompt
from ui.table import interactive_select
from updates import update_notice
from utils import build_magnet, start_esc_listener

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


def _goodbye() -> None:
    """Clear the leftover UI (results table / search prompt) and sign off.

    Without the clear, whatever was last rendered stays on screen above the
    exit message, leaving stray output before "Goodbye!". Cleared raw (no
    banner reprint) so the exit screen shows only the farewell.
    """
    import os
    os.system('cls' if os.name == 'nt' else 'clear')
    console.print("[info]Goodbye![/info]")


def _locate_downloaded_video(torrent_name: str) -> str | None:
    """Best-effort: find an already-downloaded video file for this torrent.

    Lets the subtitle search hash-match the real file for accurate sync.
    Returns None when nothing in the download folder plausibly matches, so the
    caller falls back to name-only matching.
    """
    import os
    import re
    from constants import get_download_dir

    exts = (".mkv", ".mp4", ".avi", ".m4v", ".mov")

    def toks(s: str) -> set:
        return set(re.findall(r"[a-z0-9]+", s.lower()))

    want = toks(torrent_name)
    best, best_score = None, 0
    try:
        for root, _dirs, files in os.walk(get_download_dir()):
            for fn in files:
                if fn.lower().endswith(exts):
                    score = len(want & toks(fn))
                    if score > best_score:
                        best, best_score = os.path.join(root, fn), score
    except Exception:
        return None
    # Need a couple of shared tokens to avoid grabbing an unrelated video.
    return best if best_score >= 2 else None


def _online_fix_pick(selected: dict) -> None:
    """Handle a picked Online-Fix result: fetch its ``.torrent`` and hand it to
    the system torrent client.

    Online-Fix has no public magnet (games are distributed as .torrent files), so
    it can't use the magnet download menu. The post page is public and the file
    host is referer-gated (no login), so we download the .torrent into the user's
    download folder and open it in their client. On failure we show the page URL
    so they can grab it manually.
    """
    import online_fix
    from constants import get_download_dir
    from rich.panel import Panel

    name = selected.get("name", "Unknown")
    page_url = selected.get("page_url") or selected.get("of_post_url") or ""
    with console.status("[bold cyan]Fetching .torrent from online-fix.me…[/bold cyan]", spinner="dots"):
        path = online_fix.fetch_torrent_for(page_url, get_download_dir())

    if not path:
        console.print(Panel(
            f"[bold]{name}[/bold]\n\n"
            "[warning]Couldn't fetch the .torrent automatically[/warning] "
            "(post layout changed or host blocked).\n"
            f"[cyan]Open the page and grab it manually:[/cyan]\n{page_url}",
            title="🔧 Online-Fix", border_style="yellow", padding=(1, 2),
        ))
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return

    opened = open_torrent_file(path)
    handoff = ("[success]✓ opened in your torrent client[/success]" if opened
               else "[warning]saved, but couldn't auto-open — add it to your client manually[/warning]")
    console.print(Panel(
        f"[bold]{name}[/bold]\n\n"
        f"[cyan].torrent saved:[/cyan]   {path}\n"
        f"[cyan]Handed to client:[/cyan] {handoff}\n"
        f"[cyan]Archive password:[/cyan] {online_fix.ARCHIVE_PASSWORD}\n\n"
        "[dim]Your client downloads the game from online-fix's tracker; unpack the "
        "archives with the password above.[/dim]",
        title="🔧 Online-Fix", border_style="bright_blue", padding=(1, 2),
    ))
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()


def _main_loop() -> None:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("-q", "--query", type=str, help="Search query (skip prompt)")
    parser.add_argument("-t", "--type", type=str, choices=["movie", "game", "online-fix", "software", "mobile", "rutracker", "anime", "manga"], help="Search type (default: movie if used with -q)")
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

    # One-shot update check (git-clone installs). Empty string when up to date
    # or not checkable. Shown in the provider menu footer (interactive) and
    # printed once here for direct -q/-t runs that skip the menu.
    update_msg = update_notice()
    if current_provider and update_msg:
        console.print(update_msg + "\n")

    # One-line status (e.g. "No results", "cancelled") carried to the next
    # prompt render so it shows on the freshly-cleared screen instead of
    # stacking another search header below the old one.
    notice_msg = None

    # In-progress query preserved across a Tab quick-action excursion, so popping
    # into Filters/Stats/Tips and back doesn't lose what was typed.
    pending_query = ""

    # Results produced by the "search by creator" flow (Tab → Search by creator).
    # When set, the search section below uses them directly instead of running a
    # plain-text provider search; `query` carries a display label for the header.
    creator_results = None

    while True:
        if not current_provider:
            result = provider_select_prompt(notice=update_msg)
            if result is None:
                _goodbye()
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
            _actions_hint = "filters, history, stats, tips"
            if getattr(provider, "creator_facets", []):
                _actions_hint = "filters, history, creator, stats, tips"
            console.print(
                "[dim]Type to search  •  [/dim][bold]Tab[/bold] [dim]actions "
                f"({_actions_hint})  •  [/dim][bold]Esc[/bold] [dim]back[/dim]"
            )
            if notice_msg:
                console.print(notice_msg)
                notice_msg = None
            initial, pending_query = pending_query, ""
            try:
                query = get_query_with_shortcut(f"[title] Search {provider.name}:[/title] ", initial=initial)
            except (EOFError, KeyboardInterrupt):
                _goodbye()
                break

            if query == "GO_BACK":
                current_provider = None
                query = None
                continue

            # Tab opened the quick-actions menu. Loop it so finishing or
            # cancelling an action returns here (Esc inside an action goes back
            # to this menu); only Esc in the menu itself drops to the prompt.
            if isinstance(query, tuple) and query and query[0] == "ACTIONS":
                typed = query[1]
                from ui.prompts import quick_actions_menu
                query = None
                while True:
                    action = quick_actions_menu(
                        show_creator=bool(getattr(provider, "creator_facets", []))
                    )
                    if action == "filter":
                        filter_menu(provider)
                    elif action == "history":
                        from ui.history import history_select_prompt
                        pick = history_select_prompt()
                        if pick:
                            query, prov_name = pick
                            from providers import get_provider
                            hist_prov = get_provider(prov_name)
                            if hist_prov:
                                current_provider = hist_prov
                            break  # past search chosen → leave the menu and run it
                    elif action == "creator":
                        from ui.creator import creator_search_flow
                        outcome = creator_search_flow(provider, cli_filters)
                        if outcome is not None:
                            query, creator_results = outcome
                            break  # creator results ready → leave the menu and show them
                    elif action == "stats":
                        from ui.stats import stats_page
                        stats_page()
                    elif action == "tips":
                        from ui.tips_page import tips_page
                        tips_page()
                    else:  # Back / Esc in the menu → return to the search prompt
                        break
                if not query:
                    pending_query = typed
                clear_screen()
                continue

        if not query:
            notice_msg = "[warning] Please enter a search term.[/warning]"
            clear_screen()
            query = None
            continue

        # Search using provider — unless the by-creator flow already produced
        # results (in which case `query` is a display label, not a search term).
        if creator_results is not None:
            results = creator_results
            creator_results = None
            if not results:
                notice_msg = "[warning] No results found for that creator.[/warning]\n"
                clear_screen()
                query = None
                continue
            # A creator label isn't a replayable plain-text query, so record the
            # stat (keeps the session search count honest) but skip history.
            record_search(provider.slug, query, [pr.name for pr in getattr(provider, "active_presets", [])])
        else:
            console.print(f"[info]Searching {provider.name} for:[/info] [highlight]{query}[/highlight]...")
            if getattr(provider, "search_note", ""):
                console.print(f"[dim]{provider.search_note}[/dim]")
            console.print("[dim]Press Esc to cancel and go back.[/dim]")

            # Run the search on a worker thread so Esc can abort the wait instead
            # of forcing the user to sit through the engine timeouts (or Ctrl+C).
            search_result: dict = {}

            def _run_search() -> None:
                try:
                    search_result["results"] = provider.search(query, cli_filters=cli_filters)
                except Exception:
                    search_result["results"] = []
                finally:
                    search_result["done"] = True

            cancel_event = threading.Event()
            worker = threading.Thread(target=_run_search, daemon=True)
            worker.start()
            stop_listener = start_esc_listener(cancel_event)
            try:
                with console.status(f"[bold cyan]Searching {provider.name}...[/bold cyan]", spinner="dots"):
                    while not search_result.get("done") and not cancel_event.is_set():
                        time.sleep(0.05)
            finally:
                stop_listener.set()

            if cancel_event.is_set():
                notice_msg = "[warning] Search cancelled — returning to the prompt.[/warning]\n"
                clear_screen()
                query = None
                continue

            results = search_result.get("results") or []

            if not results:
                notice_msg = "[warning] No results found.[/warning]\n"
                clear_screen()
                query = None
                continue

            # Record successful search in history + stats
            from state import add_history_entry
            active_preset_names = [pr.name for pr in getattr(provider, "active_presets", [])]
            add_history_entry(query, provider.slug, active_preset_names)
            record_search(provider.slug, query, active_preset_names)

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
            record_torrent_picked(provider.slug, int(selected.get("seeders", 0) or 0))

            # Online-Fix has no public magnet — games are distributed as .torrent
            # files (public page, referer-gated host). Fetch the .torrent and hand
            # it to the system client instead of the magnet menu, then proceed to
            # the "What's next?" screen (break with idx set, so the results loop
            # exits past the `idx is None` guard below).
            if selected.get("source") == "Online-Fix":
                _online_fix_pick(selected)
                clear_screen()
                break

            # RuTracker results carry the topic id as a placeholder hash — the
            # real magnet lives on the topic page, so resolve it on demand here.
            if selected.get("source") == "RuTracker":
                import rutracker
                with console.status("[bold cyan]Fetching magnet from RuTracker…[/bold cyan]", spinner="dots"):
                    real_hash = rutracker.resolve_info_hash(selected.get("rt_topic_id") or info_hash)
                if not real_hash:
                    console.print("[error] Couldn't get the magnet from RuTracker (login expired or topic unavailable).[/error]")
                    console.print("[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    clear_screen()
                    continue
                info_hash = real_hash
                selected["info_hash"] = real_hash

            # Download method selection
            magnet = build_magnet(info_hash, name)
            session = TorrentSession(selected, magnet)

            go_back_to_results = False
            while True:
                show_subs = getattr(provider, "supports_subtitles", False)
                show_picker = getattr(provider, "supports_episode_picker", False)
                show_stream = getattr(provider, "supports_streaming", True)
                method = download_method_prompt(
                    magnet=session.magnet,
                    show_subtitles=show_subs,
                    show_episode_picker=show_picker,
                    selected_indexes=session.selected_files,
                    sub_choice=session.sub_choice,
                    show_streaming=show_stream,
                    page_url=session.result.get("page_url") or None,
                    info_source=session.result.get("source") or None,
                )

                if method in _METHOD_TRACK:
                    record_method_pick(_METHOD_TRACK[method])

                if method == "set_subs":
                    from ui.prompts import subtitle_source_prompt
                    session.set_sub_choice(subtitle_source_prompt(session.sub_choice))
                    clear_screen()
                    continue

                if method == "set_download_dir":
                    from ui.prompts import download_dir_prompt
                    download_dir_prompt()
                    clear_screen()
                    continue

                if method == "torrent_info":
                    clear_screen()
                    from ui.prompts import torrent_info_screen
                    torrent_info_screen(session.result)
                    clear_screen()
                    continue

                if method == "pick_episodes":
                    clear_screen()
                    if not has_aria2():
                        console.print("[error]aria2c required to list files. Install from https://aria2.github.io/[/error]\n")
                        console.print("[dim]Press any key to continue...[/dim]")
                        readchar.readkey()
                        continue
                    console.print("[info]Fetching torrent metadata via DHT (this can take 30–60s).[/info]")
                    console.print("[dim]Needs peers — if the torrent has no seeders, this won't work.[/dim]")
                    console.print("[dim]Press Esc to cancel and go back.[/dim]\n")
                    cancel_event = threading.Event()
                    stop_listener = start_esc_listener(cancel_event)
                    try:
                        with console.status("[bold cyan]Fetching file list...[/bold cyan]", spinner="dots"):
                            metadata = session.fetch_files_meta(cancel_event=cancel_event)
                    finally:
                        stop_listener.set()
                    if cancel_event.is_set():
                        console.print("[warning] Cancelled — returning to the menu.[/warning]")
                        clear_screen()
                        continue
                    if not metadata or not metadata.files:
                        console.print("[error] Could not fetch file list (timeout or no metadata peers).[/error]\n")
                        console.print("[dim]Press any key to continue...[/dim]")
                        readchar.readkey()
                        continue
                    picked = episode_select_prompt(metadata.files, preselected=session.selected_files)
                    if picked is not None:
                        # Confirm pressed — replace selection (empty list clears it)
                        session.set_selected_files(picked or None)
                    clear_screen()
                    continue

                if method == "t":
                    clear_screen()
                    console.print("[info]Opening magnet link with default torrent client...[/info]")
                    if session.selected_files:
                        console.print(
                            "[warning] External torrent clients cannot be pre-filtered from here.[/warning]\n"
                            "[dim]When the client's 'Add new torrent' dialog appears, uncheck the files you don't want.[/dim]\n"
                            "[dim]If your client skipped the dialog, pause the torrent and deselect unwanted files in its Content/Files tab.[/dim]"
                        )
                    open_magnet(session.magnet)
                    record_magnet_dispatch()
                    console.print("[success] Magnet link sent to torrent client![/success]\n")
                    console.print("[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    break
                elif method == "stream_p":
                    clear_screen()
                    stream_with_peerflix(session)
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    continue
                elif method == "stream_w":
                    clear_screen()
                    stream_with_webtorrent(session)
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    continue
                elif method == "aria":
                    clear_screen()
                    ok = download_with_aria2(session.magnet, session.download_indexes)
                    if ok:
                        record_method_complete("aria")
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    if not ok:
                        continue  # back to download-method menu
                    break
                elif method == "p":
                    clear_screen()
                    ok = download_with_peerflix(session.magnet, session.download_indexes)
                    if ok:
                        record_method_complete("peerflix_download")
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    if not ok:
                        continue
                    break
                elif method == "d":
                    clear_screen()
                    ok = download_with_webtorrent(session.magnet, session.download_indexes)
                    if ok:
                        record_method_complete("webtorrent_download")
                    console.print("\n[dim]Press any key to continue...[/dim]")
                    readchar.readkey()
                    if not ok:
                        continue
                    break
                elif method == "s":
                    import os as _os
                    from jimaku import is_subtitle_file
                    sub_paths: list[str] = []
                    # Anime: try Jimaku first (best anime coverage) when a key is
                    # configured; it returns None to fall through to subliminal.
                    if getattr(provider, "slug", "") == "anime":
                        from jimaku import search_and_download
                        jp = search_and_download(session.name)
                        if jp:
                            sub_paths = [jp]
                    if not sub_paths:
                        from subtitles import download_subtitles
                        video_path = _locate_downloaded_video(session.name)
                        sub_paths = download_subtitles(session.name, video_path=video_path)
                    record_method_complete("subtitles")
                    # Attach only real subtitle files (skip e.g. a Jimaku .zip) to
                    # the next stream as selectable VLC tracks (first = primary).
                    attachable = [
                        _os.path.abspath(p) for p in (sub_paths or [])
                        if p and _os.path.exists(p) and is_subtitle_file(p)
                    ]
                    if attachable:
                        session.set_sub_choice({"mode": "external", "paths": attachable})
                        primary = _os.path.basename(attachable[0])
                        extra = len(attachable) - 1
                        if extra > 0:
                            console.print(
                                f"[success]Saved. Next stream will use[/success] "
                                f"[highlight]{primary}[/highlight] "
                                f"[success]as primary, plus {extra} more track(s).[/success]"
                            )
                        else:
                            console.print(
                                f"[success]Saved. Next stream will use[/success] "
                                f"[highlight]{primary}[/highlight] "
                                f"[success]as the subtitle source.[/success]"
                            )
                    elif sub_paths:
                        # Downloaded but not directly attachable (e.g. a .zip).
                        console.print(
                            f"[success]Saved[/success] "
                            f"[highlight]{_os.path.basename(sub_paths[0])}[/highlight]"
                            f"[success].[/success]"
                        )
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
            clear_screen()
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
            _goodbye()
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
        _goodbye()
