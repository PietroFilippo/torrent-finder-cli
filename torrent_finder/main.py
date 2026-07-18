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

from torrent_finder import __version__, acquisition
from torrent_finder.constants import console
import readchar
from torrent_finder.downloader import download_with_aria2, download_with_webtorrent, download_with_peerflix, has_aria2, open_magnet, stream_with_peerflix, stream_with_webtorrent
from torrent_finder.filters import FilterConfig
from torrent_finder.providers import (
    PROVIDERS,
    creator_facet_choices,
    get_provider,
    group_for,
    provider_cli_choices,
)
from torrent_finder.security import show_security_warning
from torrent_finder.state import history_queries, load_state
from torrent_finder.stats import (
    add_runtime_seconds,
    record_magnet_dispatch,
    record_method_complete,
    record_method_pick,
    record_search,
    record_session_start,
    record_torrent_picked,
)
from torrent_finder.torrent_session import TorrentSession
from torrent_finder.ui.prompts import (
    clear_screen,
    download_method_prompt,
    episode_select_prompt,
    filter_menu,
    get_query_with_shortcut,
    make_search_screen_renderer,
    print_banner,
    provider_select_prompt,
    search_again_prompt,
)
from torrent_finder.terminal_check import advise_limited_terminal
from torrent_finder.ui.table import interactive_select
from torrent_finder.updates import check_for_update, notice_line, run_update
from torrent_finder.utils import start_esc_listener

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
    from torrent_finder.constants import get_download_dir

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


def _magnet_for(result) -> str | None:
    """Magnet URI for a result, or None when its acquisition style has none.

    Thin delegate kept for the characterization tests; the per-source logic
    lives behind the acquisition seam (``acquisition.magnet_for``).
    """
    return acquisition.magnet_for(result)


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to the OS clipboard. Returns False if no clipboard tool exists."""
    import subprocess
    import platform
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run("clip", input=text.encode(), check=True)
        elif system == "Darwin":
            subprocess.run("pbcopy", input=text.encode(), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
        return True
    except Exception:
        return False


def _batch_handoff(provider, results: list, idxs: list[int]) -> None:
    """Hand every checkbox-selected torrent to the system client at once.

    A results list can mix acquisition styles (magnet, torrent-file handoff,
    direct download), so each item drives its own adapter's ``batch_item``;
    the outcomes aggregate into one summary. Esc stops the run between items
    (and mid-transfer for direct downloads).
    """
    from rich.panel import Panel
    from torrent_finder.constants import get_download_dir

    n = len(idxs)
    sent = 0
    saved_direct = 0
    failed: list[str] = []
    manual_urls: list[str] = []
    ofix_pw = None

    from rich.markup import escape

    cancel_event = threading.Event()
    stop_listener = start_esc_listener(cancel_event)
    # The status line names the item being handled ("(3/8) Title…") — and for a
    # Madokami file, a live MB counter — so a multi-minute batch isn't a blind
    # spinner. Titles are markup-escaped (manga names carry brackets).
    status = console.status("[bold cyan]Opening torrents…  (Esc to stop)[/bold cyan]", spinner="dots")
    try:
        with status:
            for k, gi in enumerate(idxs, 1):
                if cancel_event.is_set():
                    break
                if not (0 <= gi < len(results)):
                    continue
                r = results[gi]
                name = r.get("name", "Unknown")
                shown = escape(name[:40] + ("…" if len(name) > 40 else ""))
                status.update(f"[bold cyan]({k}/{n}) {shown}  (Esc to stop)[/bold cyan]")
                def _set_status(suffix, _k=k, _shown=shown):
                    status.update(
                        f"[bold cyan]({_k}/{n}) {_shown} — {suffix}  (Esc to stop)[/bold cyan]"
                    )

                outcome = None
                try:
                    outcome = acquisition.for_result(r).batch_item(
                        r, download_dir=get_download_dir(),
                        cancel_event=cancel_event, set_status=_set_status,
                    )
                except Exception:
                    outcome = None
                if outcome is not None and outcome.ok:
                    sent += 1
                    if outcome.saved_direct:
                        saved_direct += 1
                    if outcome.password:
                        ofix_pw = outcome.password
                    record_torrent_picked(provider.slug, int(r.get("seeders", 0) or 0))
                    if not outcome.saved_direct:  # a saved file isn't a magnet dispatch
                        record_magnet_dispatch()
                elif cancel_event.is_set():
                    break  # aborted mid-transfer — cancelled, not failed
                else:
                    if outcome is not None and outcome.manual_url:
                        manual_urls.append(outcome.manual_url)
                    failed.append(name)
    finally:
        stop_listener.set()

    if cancel_event.is_set():
        lines = [f"[warning] Stopped after {sent} of {n}.[/warning]"]
    elif saved_direct and saved_direct == sent:
        lines = [f"[success]✓ {sent} of {n} saved to your download folder.[/success]"]
    elif saved_direct:
        lines = [f"[success]✓ {sent} of {n} done — {sent - saved_direct} to your torrent client, "
                 f"{saved_direct} saved directly (Madokami).[/success]"]
    else:
        lines = [f"[success]✓ {sent} of {n} sent to your torrent client.[/success]"]
    if ofix_pw:
        lines.append(f"[cyan]Online-Fix archive password:[/cyan] {ofix_pw}")
    if failed:
        shown = ", ".join(failed[:6]) + (" …" if len(failed) > 6 else "")
        lines.append(f"[warning] Couldn't open {len(failed)}:[/warning] {shown}")
        for u in manual_urls[:6]:
            lines.append(f"[dim]Grab manually: {u}[/dim]")
    console.print(Panel(
        "\n".join(lines),
        title="🧲 Batch download", border_style="bright_blue", padding=(1, 2),
    ))
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()
    clear_screen()


def _batch_copy_magnets(provider, results: list, idxs: list[int]) -> None:
    """Copy the selection's magnet links to the clipboard.

    Online-Fix and Madokami entries have no magnet and are skipped; RuTracker
    and FitGirl magnets are resolved on demand (so this can take a moment).
    """
    magnets: list[str] = []
    skipped = 0
    with console.status("[bold cyan]Collecting magnet links…[/bold cyan]", spinner="dots"):
        for gi in idxs:
            if not (0 <= gi < len(results)):
                continue
            magnet = _magnet_for(results[gi])
            if magnet:
                magnets.append(magnet)
            else:
                skipped += 1

    if not magnets:
        console.print("[warning] No magnet links in this selection (e.g. all Online-Fix / Madokami).[/warning]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        clear_screen()
        return

    if _copy_to_clipboard("\n".join(magnets)):
        console.print(f"[success]✓ Copied {len(magnets)} magnet link(s) to the clipboard.[/success]")
    else:
        console.print(
            f"[warning] Couldn't access the clipboard — {len(magnets)} link(s) below:[/warning]\n"
            + "\n".join(magnets)
        )
    if skipped:
        console.print(f"[dim]{skipped} skipped (no magnet link).[/dim]")
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()
    clear_screen()


def _batch_aria2(provider, results: list, idxs: list[int]) -> None:
    """Download every selected torrent that has a magnet with one aria2c process.

    The client-free batch path (parallel, single process). Online-Fix and
    Madokami entries have no magnet and are skipped; RuTracker and FitGirl
    magnets are resolved on demand.
    """
    from torrent_finder.downloader import download_many_with_aria2

    magnets: list[str] = []
    picked: list[dict] = []
    skipped = 0
    with console.status("[bold cyan]Collecting magnet links…[/bold cyan]", spinner="dots"):
        for gi in idxs:
            if not (0 <= gi < len(results)):
                continue
            magnet = _magnet_for(results[gi])
            if magnet:
                magnets.append(magnet)
                picked.append(results[gi])
            else:
                skipped += 1

    if not magnets:
        console.print("[warning] Nothing to download via aria2c — no magnet links (e.g. all Online-Fix / Madokami).[/warning]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        clear_screen()
        return

    if skipped:
        console.print(
            f"[dim]{skipped} item(s) skipped — no magnet (e.g. Online-Fix / Madokami). "
            "Use “Open all in client” for those.[/dim]"
        )

    ok = download_many_with_aria2(magnets)
    if ok:
        record_method_complete("aria")
        for r in picked:
            record_torrent_picked(provider.slug, int(r.get("seeders", 0) or 0))
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()
    clear_screen()


def _batch_flow(provider, results: list, idxs: list[int]) -> str:
    """Drive the reduced batch-download menu for a multi-torrent selection.

    Loops the menu so Copy stays put; returns "next" when the user opened or
    cancelled (caller shows what's next), or "back" to re-show the results table
    (Back / Esc).
    """
    from torrent_finder.ui.prompts import batch_download_menu

    copyable = sum(
        1 for gi in idxs
        if 0 <= gi < len(results)
        and acquisition.for_result(results[gi]).has_magnet
    )
    while True:
        action = batch_download_menu(len(idxs), copyable)
        if action == "open":
            # Guard against an accidental flood (e.g. 'a' select-all then Enter):
            # a decline returns to the menu rather than dropping to what's next.
            if len(idxs) > 8:
                from torrent_finder.ui.prompts import confirm_prompt
                if not confirm_prompt(
                    f"Open {len(idxs)} torrents in your client at once?",
                    title="Batch download",
                ):
                    clear_screen()
                    continue
            _batch_handoff(provider, results, idxs)
            return "next"
        if action == "aria":
            _batch_aria2(provider, results, idxs)
            return "next"
        if action == "copy":
            _batch_copy_magnets(provider, results, idxs)
            continue
        if action == "cancel":
            clear_screen()
            return "next"
        # "back" or None (Esc) → step back to the results table
        clear_screen()
        return "back"


def browse_results(provider, results, note: str = "") -> str:
    """Show the torrent results table + download-method UI for ``results``.

    Returns ``"back"`` if the user Esc'd the results table (caller steps back a
    screen), or ``"next"`` if a download action completed (caller shows "what's
    next?"). On the download menu, Esc / "↩ Go back to results" step back to the
    results table; "✕ Cancel" means "done with this torrent" → returns ``"next"``
    (what's next), as do completed actions (magnet sent, download finished,
    Online-Fix handoff).
    """
    while True:
        clear_screen()
        choice = interactive_select(results, note=note)
        if choice is None:
            return "back"

        # Multi-select: two or more torrents checked → reduced batch menu. "back"
        # re-shows the results table (re-select); otherwise we go to "what's
        # next?". A single pick falls through to the full per-torrent download
        # menu below (unchanged).
        if choice[0] == "many":
            if _batch_flow(provider, results, choice[1]) == "back":
                continue
            return "next"

        idx = choice[1]
        selected = results[idx]
        record_torrent_picked(provider.slug, int(selected.get("seeders", 0) or 0))

        # Acquisition seam: magnet styles hand back a magnet and fall through
        # to the download-method menu; handoff / direct-download styles finish
        # (or abort) the whole acquisition inside ``pick``. "back" means
        # nothing happened — re-show the results table.
        outcome = acquisition.for_result(selected).pick(selected)
        if outcome.action == "back":
            clear_screen()
            continue
        if outcome.action == "next":
            clear_screen()
            return "next"

        session = TorrentSession(selected, outcome.magnet)

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
                from torrent_finder.ui.prompts import subtitle_source_prompt
                session.set_sub_choice(subtitle_source_prompt(session.sub_choice))
                clear_screen()
                continue

            if method == "set_download_dir":
                from torrent_finder.ui.prompts import download_dir_prompt
                download_dir_prompt()
                clear_screen()
                continue

            if method == "torrent_info":
                clear_screen()
                from torrent_finder.ui.prompts import torrent_info_screen
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
                return "next"
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
                    continue
                return "next"
            elif method == "p":
                clear_screen()
                ok = download_with_peerflix(session.magnet, session.download_indexes)
                if ok:
                    record_method_complete("peerflix_download")
                console.print("\n[dim]Press any key to continue...[/dim]")
                readchar.readkey()
                if not ok:
                    continue
                return "next"
            elif method == "d":
                clear_screen()
                ok = download_with_webtorrent(session.magnet, session.download_indexes)
                if ok:
                    record_method_complete("webtorrent_download")
                console.print("\n[dim]Press any key to continue...[/dim]")
                readchar.readkey()
                if not ok:
                    continue
                return "next"
            elif method == "s":
                import os as _os
                from torrent_finder.jimaku import is_subtitle_file
                sub_paths: list[str] = []
                # Anime: try Jimaku first (best anime coverage) when a key is
                # configured; it returns None to fall through to subliminal.
                if getattr(provider, "slug", "") == "anime":
                    from torrent_finder.jimaku import search_and_download
                    jp = search_and_download(session.name)
                    if jp:
                        sub_paths = [jp]
                if not sub_paths:
                    from torrent_finder.subtitles import download_subtitles
                    video_path = _locate_downloaded_video(session.name)
                    sub_paths = download_subtitles(session.name, video_path=video_path)
                record_method_complete("subtitles")
                # Attach only real subtitle files (skip e.g. a Jimaku .zip) to the
                # next stream as selectable VLC tracks (first = primary).
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
                    console.print(
                        f"[success]Saved[/success] "
                        f"[highlight]{_os.path.basename(sub_paths[0])}[/highlight]"
                        f"[success].[/success]"
                    )
                console.print("\n[dim]Press any key to continue...[/dim]")
                readchar.readkey()
                continue
            elif method == "cancel":  # ✕ Cancel → done with this torrent → what's next
                clear_screen()
                return "next"
            else:  # "back" (Go back to results) or Esc → step back to the results table
                go_back_to_results = True
                break

        if go_back_to_results:
            continue
        return "next"


def _available_facets(provider) -> list:
    """Creator facets whose required credential (if any) is configured.

    Credential-gated facets (e.g. movies/games via TMDB/IGDB) are hidden until
    their key is set, so the provider falls back to keyword-only search.
    """
    import torrent_finder.credentials as C
    out = []
    for f in getattr(provider, "creator_facets", []) or []:
        if not getattr(f, "requires_cred", "") or C.get_credential(f.requires_cred):
            out.append(f)
    return out


def _provider_entry(provider, cli_filters) -> str:
    """Entry screen for a freshly selected provider.

    Creator-capable providers show a source screen (keyword search vs. by
    director/studio/…) and drive the creator journey; others go straight to
    keyword search. Looping keeps Esc inside the creator flow returning to the
    source screen. Returns ``"keyword"`` (run the normal keyword search),
    ``"next"`` (a creator download completed → "what's next?"), or ``"provider"``
    (user backed out → return to the provider list).
    """
    facets = _available_facets(provider)
    if not facets:
        return "keyword"
    from torrent_finder.ui.prompts import _provider_source_menu
    from torrent_finder.ui.creator import creator_search_flow
    while True:
        choice = _provider_source_menu(provider, facets)
        if choice is None:
            return "provider"
        if choice == "search":
            # The source menu's alt-screen exit cleared the banner — redraw it so
            # the keyword prompt shows under the banner like every other provider.
            clear_screen()
            return "keyword"
        if creator_search_flow(provider, cli_filters, choice, browse_results) == "next":
            return "next"
        # "back" → re-show the source screen


def _history_pick(entry):
    """Resolve a history entry → (provider, facet_or_None, value).

    Creator entry → (provider, facet, name); keyword → (provider, None, query).
    ``provider`` is None when it no longer exists; ``facet`` is None when the
    stored facet is gone (caller then treats ``value`` as a keyword fallback).
    """
    prov = get_provider(entry.get("provider", "") or "")
    if entry.get("kind") == "creator":
        facet = None
        if prov:
            facet = next((f for f in getattr(prov, "creator_facets", []) if f.key == entry.get("facet")), None)
        return prov, facet, entry.get("name", "")
    return prov, None, entry.get("query", "")


def _handle_whats_next(current_provider):
    """Show the post-action "What's next?" menu.

    Returns ``(query, provider, facet, name)`` to keep looping, or ``"EXIT"`` to
    quit. ``facet`` is set only when a creator history entry was picked (caller
    seeds the by-creator one-shot); otherwise it's None and ``query`` drives a
    normal search.
    """
    choice = search_again_prompt()
    if isinstance(choice, tuple) and choice[0] == "history":
        clear_screen()
        prov, facet, val = _history_pick(choice[1])
        if prov is None:
            return (None, current_provider, None, None)  # provider gone → just re-prompt
        if facet:
            return (None, prov, facet, val)              # creator replay
        return (val, prov, None, None)                   # keyword replay
    if choice == "search":
        clear_screen()
        return (None, current_provider, None, None)
    if choice == "provider":
        return (None, None, None, None)
    return "EXIT"


def _run_update_flow(info: dict) -> None:
    """Run the install-appropriate update (git pull / pipx / open Releases)."""
    clear_screen()
    console.print("[info]Updating…[/info]\n")
    ok, msg = run_update(info)
    style = "success" if ok else "warning"
    console.print(f"\n[{style}]{msg}[/{style}]")
    console.print("\n[dim]Press any key to continue...[/dim]")
    readchar.readkey()
    clear_screen()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-q", "--query", type=str, help="Search query (skip prompt)")
    parser.add_argument(
        "-t", "--type", type=str, choices=provider_cli_choices(),
        help="Search provider (default: movie if used with -q)",
    )
    parser.add_argument("-f", "--filter", action="append", help="Include keyword in results")
    parser.add_argument("-x", "--exclude", action="append", help="Exclude keyword from results")
    parser.add_argument("-y", "--skip-warning", action="store_true", help="Skip network exposure warning")
    parser.add_argument(
        "--by", choices=creator_facet_choices(),
        help="Search by creator role (use with --name and -t), e.g. --by director",
    )
    parser.add_argument("--name", type=str, help='Creator name for --by, e.g. --name "Hayao Miyazaki"')
    return parser


def _main_loop() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    advise_limited_terminal()
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
    elif query or args.by:
        # If -q or --by is passed without -t, default to Movies.
        initial_provider = PROVIDERS[0]

    session_provider = initial_provider
    current_provider = session_provider

    cli_filters = None
    if args.filter or args.exclude:
        cli_filters = FilterConfig(
            include_keywords=args.filter or [],
            exclude_keywords=args.exclude or [],
        )

    # CLI creator search: -t <provider> --by <facet> --name "<name>" jumps
    # straight into the by-creator flow (then the normal loop takes over).
    cli_facet = None
    pending_creator_name = None
    if args.by:
        cli_facet = next(
            (f for f in getattr(current_provider, "creator_facets", []) if f.key == args.by),
            None,
        )
        if cli_facet is None:
            avail = ", ".join(f.key for f in getattr(current_provider, "creator_facets", [])) or "none"
            console.print(f"[warning] {current_provider.name} has no '--by {args.by}' option (available: {avail}).[/warning]")
        elif not args.name:
            console.print('[warning] --by requires --name "<creator>".[/warning]')
            cli_facet = None
        else:
            pending_creator_name = args.name

    # Clean the terminal for initial run if an interactive search is expected
    if not (args.type and args.query):
        console.clear()

    # One-shot, install-aware update check (git / pip-pipx / binary). Rate-limited
    # to once a day inside check_for_update. ``update_info`` also drives the
    # "Install update" entry in the Tab menu; ``update_msg`` is the footer line,
    # printed once here for direct -q/-t runs that skip the menu.
    update_info = check_for_update()
    update_msg = notice_line(update_info)
    if current_provider and update_msg:
        # highlight=False: the auto-highlighter would restyle the version
        # digits (bold → bright black) on the yellow banner.
        console.print(update_msg + "\n", highlight=False)

    # One-line status (e.g. "No results", "cancelled") carried to the next
    # prompt render so it shows on the freshly-cleared screen instead of
    # stacking another search header below the old one.
    notice_msg = None

    # In-progress query preserved across a Tab quick-action excursion, so popping
    # into Filters/Stats/Tips and back doesn't lose what was typed.
    pending_query = ""

    # When set, the next provider selection re-opens this group's submenu (so
    # backing out of a group child returns to its source list, not the top list).
    pending_open_group = None

    # When set, (re)show the provider's "choose how to search" source screen — on
    # fresh selection, and when stepping back from a creator-capable provider's
    # keyword prompt (so Esc there lands on the source screen, not the prov list).
    show_source = False

    while True:
        # One-shot CLI creator search (--by/--name): jump into the by-creator
        # flow, then fall into the normal what's-next / keyword loop.
        if cli_facet is not None and pending_creator_name is not None:
            from torrent_finder.ui.creator import creator_search_flow
            facet, nm = cli_facet, pending_creator_name
            cli_facet = pending_creator_name = None
            if creator_search_flow(current_provider, cli_filters, facet, browse_results, initial_name=nm) == "next":
                res = _handle_whats_next(current_provider)
                if res == "EXIT":
                    _goodbye()
                    break
                query, current_provider, _hf, _hn = res
                if _hf:
                    cli_facet, pending_creator_name = _hf, _hn
            else:
                query = None  # backed out → normal keyword prompt for this provider
            clear_screen()
            continue

        if not current_provider:
            result = provider_select_prompt(
                notice=update_msg,
                open_group=pending_open_group,
                update_available=bool(update_info),
            )
            pending_open_group = None
            if result is None:
                _goodbye()
                break
            if result == "__update__":
                _run_update_flow(update_info)
                update_info = None   # consumed → drop the notice + menu row
                update_msg = ""
                continue
            # History selection returns ("history", entry) — keyword or creator.
            if isinstance(result, tuple) and result[0] == "history":
                prov, facet, val = _history_pick(result[1])
                clear_screen()
                if prov is None:
                    continue
                current_provider = prov
                if facet:  # creator entry → run the by-creator one-shot at loop top
                    cli_facet, pending_creator_name = facet, val
                    continue
                query = val  # keyword entry → normal search
            else:
                current_provider = result
                clear_screen()
                show_source = True  # show its "choose how to search" screen below

        # Source screen ("choose how to search") for creator-capable providers — on
        # fresh selection and when stepping back from the keyword prompt. Plain
        # providers' _provider_entry returns "keyword" with no screen shown.
        if show_source:
            show_source = False
            nxt = _provider_entry(current_provider, cli_filters)
            if nxt == "provider":
                # Back out → the provider's group submenu if it came from one,
                # otherwise the top provider list.
                pending_open_group = group_for(current_provider)
                current_provider = None
                continue
            if nxt == "next":
                res = _handle_whats_next(current_provider)
                if res == "EXIT":
                    _goodbye()
                    break
                query, current_provider, _hf, _hn = res
                if _hf:
                    cli_facet, pending_creator_name = _hf, _hn
                continue
            # nxt == "keyword" → fall through to the keyword prompt

        provider = current_provider

        # 2. Get query
        if not query:
            # Build status line showing active engines and filters
            engine_names = [e.name for e in provider.engines if e.enabled] if hasattr(provider, 'engines') else []
            engine_str = ", ".join(engine_names) if engine_names else "None"
            active_names = [p.name for p in provider.active_presets]
            active_name = ", ".join(active_names) if active_names else "None"
            prov_history = history_queries(provider.slug)
            screen_renderer = make_search_screen_renderer(
                engine_str,
                active_name,
                has_history=bool(prov_history),
                notice=notice_msg or "",
            )
            notice_msg = None
            initial, pending_query = pending_query, ""
            try:
                query = get_query_with_shortcut(
                    f"[title] Search {provider.name}:[/title] ",
                    initial=initial, history=prov_history, filters_shortcut=True,
                    multi=True, screen_renderer=screen_renderer,
                )
            except (EOFError, KeyboardInterrupt):
                _goodbye()
                break

            if query == "GO_BACK":
                if _available_facets(provider):
                    # Creator-capable → step back to its "choose how to search"
                    # screen, not all the way to the provider list.
                    show_source = True
                    query = None
                    continue
                # Plain provider → its group submenu if any, else the top list.
                pending_open_group = group_for(provider)
                current_provider = None
                query = None
                continue

            # Ctrl+F → jump straight to the filter menu, keeping the typed query.
            if isinstance(query, tuple) and query and query[0] == "FILTERS":
                pending_query = query[1]
                filter_menu(provider)
                query = None
                clear_screen()
                continue

            # Tab opened the quick-actions menu. Loop it so finishing or
            # cancelling an action returns here (Esc inside an action goes back
            # to this menu); only Esc in the menu itself drops to the prompt.
            if isinstance(query, tuple) and query and query[0] == "ACTIONS":
                typed = query[1]
                from torrent_finder.ui.prompts import quick_actions_menu
                query = None
                while True:
                    action = quick_actions_menu(update_available=bool(update_info))
                    if action == "update":
                        _run_update_flow(update_info)
                        update_info = None   # consumed → drop the notice + entry
                        update_msg = ""
                    elif action == "filter":
                        filter_menu(provider)
                    elif action == "history":
                        from torrent_finder.ui.history import history_select_prompt
                        pick = history_select_prompt()
                        if pick:
                            prov, facet, val = _history_pick(pick)
                            if prov is not None:
                                current_provider = prov
                                if facet:  # creator entry → by-creator one-shot
                                    cli_facet, pending_creator_name = facet, val
                                else:
                                    query = val
                                break  # leave the menu and run it
                    elif action == "stats":
                        from torrent_finder.ui.stats import stats_page
                        stats_page()
                    elif action == "tips":
                        from torrent_finder.ui.tips_page import tips_page
                        tips_page()
                    else:  # Back / Esc in the menu → return to the search prompt
                        break
                if not query:
                    pending_query = typed
                clear_screen()
                continue

        # Normalize the prompt result to a list of query strings. Multi mode
        # (Ctrl+N = add another title) returns a list; single mode a string.
        if isinstance(query, list):
            queries = [q.strip() for q in query if q and q.strip()]
        else:
            queries = [query.strip()] if isinstance(query, str) and query.strip() else []

        if not queries:
            notice_msg = "[warning] Please enter a search term.[/warning]"
            clear_screen()
            query = None
            continue

        # Search the provider. Multiple titles fan out across the same engines
        # and merge (dedupe by hash, sort by seeders), reusing the by-creator
        # search path.
        shown = ", ".join(queries)
        console.print(f"[info]Searching {provider.name} for:[/info] [highlight]{shown}[/highlight]...")
        if getattr(provider, "search_note", ""):
            console.print(f"[dim]{provider.search_note}[/dim]")
        console.print("[dim]Press Esc to cancel and go back.[/dim]")

        # Run the search on a worker thread so Esc can abort the wait instead of
        # forcing the user to sit through the engine timeouts (or Ctrl+C).
        search_result: dict = {}
        cancel_event = threading.Event()

        def _run_search() -> None:
            try:
                if len(queries) == 1:
                    search_result["results"] = provider.search(queries[0], cli_filters=cli_filters)
                else:
                    from torrent_finder.resolvers.types import Work
                    from torrent_finder.creator_search import fan_out
                    search_result["results"] = fan_out(
                        provider, [Work(title=q) for q in queries], cli_filters,
                        cancel_event=cancel_event,
                    )
            except Exception:
                search_result["results"] = []
            finally:
                search_result["done"] = True

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

        # Record the successful search in history + stats — each title
        # individually so ↑/↓ recall offers them separately.
        from torrent_finder.state import add_history_entry
        active_preset_names = [pr.name for pr in getattr(provider, "active_presets", [])]
        for q in queries:
            add_history_entry(q, provider.slug, active_preset_names)
            record_search(provider.slug, q, active_preset_names)

        # Note any searched titles that returned nothing (multi-title only). It
        # rides above the results table (a pre-table print would be wiped by the
        # table's own screen clear).
        note = ""
        if len(queries) > 1:
            found = {r.get("from_work") for r in results}
            missing = [q for q in queries if q not in found]
            if missing:
                cap = 4
                more = f" +{len(missing) - cap} more" if len(missing) > cap else ""
                note = (f"⚠  No torrents for {len(missing)} of {len(queries)} titles: "
                        + ", ".join(missing[:cap]) + more)

        # Results + download (shared with the by-creator flow). Esc on the
        # results table steps back to the keyword prompt; a completed download
        # proceeds to "what's next?".
        if browse_results(provider, results, note=note) == "back":
            query = None
            clear_screen()
            continue

        res = _handle_whats_next(current_provider)
        if res == "EXIT":
            _goodbye()
            break
        query, current_provider, _hf, _hn = res
        if _hf:
            cli_facet, pending_creator_name = _hf, _hn
        continue

def main() -> None:
    record_session_start()
    t0 = time.monotonic()
    try:
        _main_loop()
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C / Ctrl+D from any menu (readchar raises these from readkey).
        # Caught here so every entry point — the console script, python -m,
        # and the frozen binary — exits cleanly instead of dumping a traceback.
        _goodbye()
    finally:
        add_runtime_seconds(time.monotonic() - t0)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        _goodbye()
