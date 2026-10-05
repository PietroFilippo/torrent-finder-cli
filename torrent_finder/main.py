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

from rich.markup import escape as markup_escape  # _main_loop imports `escape` locally further down

from torrent_finder import __version__, acquisition, store
from torrent_finder.ui import theme
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
    provider_for_result,
)
from torrent_finder.security import show_security_warning
from torrent_finder.state import history_notes, history_queries, load_state
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
    download_complete_prompt,
    download_method_prompt,
    episode_select_prompt,
    filter_menu,
    get_query_with_shortcut,
    PROMPT,
    input_screen,
    make_search_screen_renderer,
    print_banner,
    provider_select_prompt,
    search_again_prompt,
)
from torrent_finder.terminal_check import advise_limited_terminal
from torrent_finder.ui.search_progress import REDRAW_S as SEARCH_REDRAW_S, ProgressScreen, progress_frame
from torrent_finder.ui.table import interactive_select
from torrent_finder.ui.update_progress import UpdateDisplay, preview_update
from torrent_finder.updates import (
    check_for_update, consume_update_report, needs_exit_before_update,
    notice_line, run_update, status_label,
)
from torrent_finder.utils import start_esc_listener

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


def _saved_data_action(action):
    """Keep a local read/write failure inside its UI flow, preserving stored data."""
    try:
        return action()
    except (OSError, ValueError) as error:
        from rich.markup import escape
        from torrent_finder.ui.selector import SelectItem, arrow_select
        arrow_select([SelectItem("Back", description=escape(str(error)))],
                     title="Saved data could not be updated", footer="Enter / Esc back")
        return None


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


def _batch_handoff(provider, results: list, idxs: list[int]) -> str:
    """Hand every checkbox-selected torrent to the system client at once.

    A results list can mix acquisition styles (magnet, torrent-file handoff,
    direct download), so each item drives its own adapter's ``batch_item``;
    the outcomes aggregate into one summary. Esc stops the run between items
    (and mid-transfer for direct downloads).
    """
    from torrent_finder.constants import get_download_dir
    from torrent_finder.ui.prompts import download_dir_ready

    # Direct downloads and Online-Fix .torrent files are saved to the folder.
    saves_files = any(not acquisition.for_result(results[gi]).has_magnet
                      for gi in idxs if 0 <= gi < len(results))
    if saves_files and not download_dir_ready():
        clear_screen()
        return "back"
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
    status = console.status("[accent]Opening torrents…  (Esc to stop)[/accent]", spinner=theme.SPINNER)
    selection = [results[gi] for gi in idxs if 0 <= gi < len(results)]
    notes: list[str] = []
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
                status.update(f"[accent]({k}/{n}) {shown}  (Esc to stop)[/accent]")
                def _set_status(suffix, _k=k, _shown=shown):
                    status.update(
                        f"[accent]({_k}/{n}) {_shown} — {suffix}  (Esc to stop)[/accent]"
                    )

                outcome = None
                try:
                    outcome = acquisition.for_result(r).batch_item(
                        r, download_dir=acquisition.batch_download_dir(r, selection, get_download_dir()),
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
                    if outcome.note:
                        notes.append(outcome.note)
                    record_torrent_picked(provider_for_result(r, provider).slug, int(r.get("seeders", 0) or 0))
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
        lines = [f"[success]✓ {sent} of {n} done — {sent - saved_direct} handed to your torrent client, "
                 f"{saved_direct} saved directly.[/success]"]
    else:
        lines = [f"[success]✓ {sent} of {n} handed to your torrent client.[/success]"]
    if ofix_pw:
        lines.append(f"[muted]Online-Fix archive password:[/muted] {escape(ofix_pw)}")
    lines += [f"[warning]{escape(note)}[/warning]" for note in notes[:4]]
    if failed:
        shown = ", ".join(failed[:6]) + (" …" if len(failed) > 6 else "")
        lines.append(f"[warning] Couldn't open {len(failed)}:[/warning] {escape(shown)}")
        for u in manual_urls[:6]:
            lines.append(f"[dim]Grab manually: {escape(u)}[/dim]")
    return download_complete_prompt("Batch handoff finished", summary="\n".join(lines))


def _batch_copy_magnets(provider, results: list, idxs: list[int]) -> None:
    """Copy the selection's magnet links to the clipboard.

    Online-Fix and Madokami entries have no magnet and are skipped; RuTracker
    and FitGirl magnets are resolved on demand (so this can take a moment).
    """
    magnets: list[str] = []
    skipped = 0
    with console.status("[accent]Collecting magnet links…[/accent]", spinner=theme.SPINNER):
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
        console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
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
    console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
    readchar.readkey()
    clear_screen()


def _batch_aria2(provider, results: list, idxs: list[int]) -> str:
    """Download every selected torrent that has a magnet with one aria2c process.

    The client-free batch path (parallel, single process). Online-Fix and
    Madokami entries have no magnet and are skipped; RuTracker and FitGirl
    magnets are resolved on demand.
    """
    from torrent_finder.downloader import download_many_with_aria2
    from torrent_finder.ui.prompts import download_dir_ready

    if not download_dir_ready():
        clear_screen()
        return "back"
    magnets: list[str] = []
    picked: list[dict] = []
    skipped = 0
    with console.status("[accent]Collecting magnet links…[/accent]", spinner=theme.SPINNER):
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
        console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
        readchar.readkey()
        clear_screen()
        return "back"

    if skipped:
        console.print(
            f"[dim]{skipped} item(s) skipped — no magnet (e.g. Online-Fix / Madokami). "
            "Use “Open all in client” for those.[/dim]"
        )

    ok = download_many_with_aria2(magnets)
    if ok:
        record_method_complete("aria")
        for r in picked:
            record_torrent_picked(provider_for_result(r, provider).slug, int(r.get("seeders", 0) or 0))
    if not ok:
        console.print("[muted]Press [key]any key[/key] to return to download options…[/muted]")
        readchar.readkey()
        return "back"
    from torrent_finder import unpack
    from torrent_finder.constants import get_download_dir
    summary = f"{len(picked)} torrent(s) downloaded; {skipped} skipped (no magnet)."
    if unpack.enabled():
        paths = [path for magnet in magnets for path in unpack.torrent_files(get_download_dir(), magnet=magnet)]
        summary = "\n".join(filter(None, (summary, _unpack_downloaded(paths))))
    return download_complete_prompt("Batch download finished", summary=summary)


def _batch_flow(provider, results: list, idxs: list[int]) -> str:
    """Drive the reduced batch-download menu for a multi-torrent selection.

    Copy and Back after a completed action retain this selection. Returns
    "next" when the user continues or cancels (caller shows what's next), or
    "back" to re-show the results table (Back / Esc in the download menu).
    """
    from torrent_finder.ui.prompts import batch_download_menu

    copyable = sum(
        1 for gi in idxs
        if 0 <= gi < len(results)
        and acquisition.for_result(results[gi]).has_magnet
    )
    while True:
        action = batch_download_menu(len(idxs), copyable)
        if action == "qbittorrent":
            from torrent_finder.ui.qbittorrent import send_results
            if (send_results([results[i] for i in idxs if 0 <= i < len(results)])
                    and download_complete_prompt("qBittorrent handoff finished") == "next"):
                return "next"
            continue
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
            if _batch_handoff(provider, results, idxs) == "next":
                return "next"
            continue
        if action == "aria":
            if _batch_aria2(provider, results, idxs) == "next":
                return "next"
            continue
        if action == "copy":
            _batch_copy_magnets(provider, results, idxs)
            continue
        if action == "cancel":
            clear_screen()
            return "next"
        # "back" or None (Esc) → step back to the results table
        clear_screen()
        return "back"


def _unpack_downloaded(paths) -> str:
    """Unpack the page archives among a finished download's files (callers
    check the setting); summary text for the finished prompt ("" when none)."""
    from torrent_finder import unpack
    from rich.markup import escape

    if not any(unpack.is_archive(path) for path in paths):
        return ""
    with console.status("[accent]Unpacking…[/accent]", spinner=theme.SPINNER) as status:
        report = unpack.unpack_all(paths, status=lambda text: status.update(f"[accent]{escape(text)}[/accent]"))
    return "\n".join(unpack.summary_lines(report))


def _unpack_torrent(session) -> str:
    """``_unpack_downloaded`` for the torrent just downloaded in the app."""
    from torrent_finder import unpack
    from torrent_finder.constants import get_download_dir

    if not unpack.enabled():
        return ""
    return _unpack_downloaded(unpack.torrent_files(get_download_dir(), session.files_meta,
                                                   session.download_indexes, session.magnet))


def _fetch_session_files(session) -> tuple[bool, object]:
    """Fetch the torrent's file list with Esc / Ctrl+C cancellation.

    Returns ``(cancelled, metadata)``; metadata is None when cancelled or when
    no file list could be found (timeout, no metadata peers).
    """
    console.print("[info]Looking for online peers that can share the torrent's file list…[/info]")
    console.print("[dim]This may take a minute or time out. Listed seed counts can be stale; even a torrent showing seeders may have no reachable metadata peers right now.[/dim]")
    console.print("[dim]Press Esc or Ctrl+C to cancel and go back.[/dim]\n")
    cancel_event = threading.Event()
    stop_listener = start_esc_listener(cancel_event)
    try:
        try:
            with console.status("[accent]Fetching file list...[/accent]", spinner=theme.SPINNER):
                metadata = session.fetch_files_meta(cancel_event=cancel_event)
        except KeyboardInterrupt:
            # Deeper flows cancel locally. Only the idle provider /
            # search screens participate in the double-press quit guard.
            cancel_event.set()
            metadata = None
    finally:
        stop_listener.set()
    return cancel_event.is_set(), metadata


def browse_results(provider, results, note: str = "") -> str:
    """Run the results/download flow with Ctrl+C scoped as local Back.

    Individual operations handle cancellation more precisely when they own a
    child process or cancel event. This boundary catches any remaining nested
    menu/status interrupt so it can never fall through to ``main()`` and exit.
    """
    while True:
        try:
            return _browse_results(provider, results, note=note)
        except KeyboardInterrupt:
            clear_screen()


def _browse_results(provider, results, note: str = "") -> str:
    """Show the torrent results table + download-method UI for ``results``.

    Returns ``"back"`` if the user Esc'd the results table (caller steps back a
    screen), or ``"next"`` if a download action completed (caller shows "what's
    next?"). On the download menu, Esc / "↩ Go back to results" step back to the
    results table; "✕ Cancel" means "done with this torrent" → returns ``"next"``
    (what's next). Completed download-menu actions offer Continue or Back to
    the same session; standalone acquisitions handle their own completion.
    """
    while True:
        clear_screen()
        from torrent_finder.bookmarks import save_results
        queries = getattr(getattr(results, "session", None), "queries", None) or []
        from rich.markup import escape
        # Headers are Rich markup; queries are user text and may hold brackets.
        crumbs = [escape(getattr(provider, "name", "") or "Results"), escape(", ".join(queries))]
        from torrent_finder.result_view import ranking_notes
        choice = interactive_select(results, note=note, initial_order=provider.result_sort,
                                    search_summary=provider.filter_summary(),
                                    on_bookmark=lambda rows: save_results(provider, rows),
                                    heading=" › ".join(part for part in crumbs if part),
                                    describe=ranking_notes(provider, queries))
        if choice is None:
            return "back"

        # Multi-select: two or more torrents checked → reduced batch menu. "back"
        # re-shows the results table (re-select); otherwise we go to "what's
        # next?". A single pick falls through to the full per-torrent download
        # menu below (unchanged).
        if choice[0] == "many":
            try:
                batch_outcome = _batch_flow(provider, results, choice[1])
            except KeyboardInterrupt:
                # A batch status screen is still a nested operation: Ctrl+C
                # cancels back to the results rather than exiting the app.
                clear_screen()
                continue
            if batch_outcome == "back":
                continue
            return "next"

        idx = choice[1]
        selected = results[idx]
        selected_provider = provider_for_result(selected, provider)
        record_torrent_picked(selected_provider.slug, int(selected.get("seeders", 0) or 0))

        from torrent_finder.qbittorrent import configured
        if configured() and acquisition.for_result(selected).style == "torrent-file-handoff":
            from torrent_finder.ui.selector import SelectItem, arrow_select
            options = [SelectItem("Send to qBittorrent WebUI", "qbittorrent"),
                       SelectItem("Open with default client", "default"), SelectItem("Back", None)]
            while True:
                picked = arrow_select(options, title="Torrent client", footer="Enter select • Esc back")
                if picked is None or options[picked].value != "qbittorrent":
                    break
                from torrent_finder.ui.qbittorrent import send_results
                if (send_results([selected])
                        and download_complete_prompt("qBittorrent handoff finished") == "next"):
                    return "next"
            if picked is None or options[picked].value is None:
                continue

        # Acquisition seam: magnet styles hand back a magnet and fall through
        # to the download-method menu; handoff / direct-download styles finish
        # (or abort) the whole acquisition inside ``pick``. "back" means
        # nothing happened — re-show the results table.
        try:
            outcome = acquisition.for_result(selected).pick(selected)
        except KeyboardInterrupt:
            # Magnet resolution / direct handoff is nested below the results
            # screen, so Ctrl+C behaves like Back here.
            clear_screen()
            continue
        if outcome.action == "back":
            clear_screen()
            continue
        if outcome.action == "next":
            clear_screen()
            return "next"

        session = TorrentSession(selected, outcome.magnet)

        go_back_to_results = False
        last_method = None  # coming back to the options keeps the cursor here
        while True:
            show_subs = getattr(selected_provider, "supports_subtitles", False)
            show_picker = getattr(selected_provider, "supports_episode_picker", False)
            show_stream = getattr(selected_provider, "supports_streaming", True)
            method = download_method_prompt(
                magnet=session.magnet,
                show_subtitles=show_subs,
                show_episode_picker=show_picker,
                selected_indexes=session.selected_files,
                sub_choice=session.sub_choice,
                show_streaming=show_stream,
                page_url=session.result.get("page_url") or None,
                info_source=session.result.get("source") or None,
                focus=last_method,
                torrent=session.result,
                file_count=len(meta.files) if (meta := getattr(session, "files_meta", None)) else None,
            )
            last_method = method

            if method in _METHOD_TRACK:
                record_method_pick(_METHOD_TRACK[method])

            if method == "qbittorrent":
                from torrent_finder.ui.qbittorrent import send_results
                if (send_results([selected], magnet=session.magnet)
                        and download_complete_prompt("qBittorrent handoff finished") == "next"):
                    return "next"
                continue

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
                    console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
                    readchar.readkey()
                    continue
                cancelled, metadata = _fetch_session_files(session)
                if cancelled:
                    clear_screen()
                    continue
                if not metadata or not metadata.files:
                    console.print("[error] Could not fetch file list (timeout or no metadata peers).[/error]")
                    console.print("[dim]Choose Browse torrent files again to retry.[/dim]\n")
                    console.print("[muted]Press [key]any key[/key] to continue…[/muted]")
                    readchar.readkey()
                    continue
                picked = episode_select_prompt(metadata.files, preselected=session.selected_files)
                if picked is not None:
                    session.set_selected_files(picked or None)
                clear_screen()
                continue

            if method in ("aria", "p", "d"):
                from torrent_finder.ui.prompts import download_dir_ready
                if not download_dir_ready():
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
                try:
                    open_magnet(session.magnet)
                except OSError as error:
                    from rich.markup import escape
                    console.print(f"[error] Couldn't open the magnet link: {escape(error.strerror or str(error))}[/error]")
                    console.print("[dim]Is a torrent client set to open magnet links? You can also use "
                                  "Copy magnet link and add it in your client.[/dim]\n")
                    console.print("[muted]Press [key]any key[/key] to return to download options…[/muted]")
                    readchar.readkey()
                    continue
                record_magnet_dispatch()
                console.print("[success] Magnet link handed to your torrent client.[/success]\n")
                summary = (
                    "[warning]File selection must be set in your torrent client.[/warning]\n"
                    "Uncheck unwanted files in its Add torrent dialog or Content/Files tab."
                ) if session.selected_files else ""
                if download_complete_prompt("Magnet link handed to torrent client", summary=summary) == "next":
                    return "next"
                continue
            elif method in ("stream_p", "stream_w"):
                clear_screen()
                # The file list picks the episode, its stream URL and in-torrent
                # subtitles. Fetch it once, cancellably: Esc / Ctrl+C returns to
                # these options without starting anything.
                if session.files_meta_status == "unknown" and has_aria2():
                    cancelled, metadata = _fetch_session_files(session)
                    if cancelled:
                        clear_screen()
                        continue
                    if metadata is None:
                        console.print("[warning] File list unavailable — streaming the backend's default file.[/warning]")
                stream = stream_with_peerflix if method == "stream_p" else stream_with_webtorrent
                stream(session)
                console.print("\n[muted]Press [key]any key[/key] to continue…[/muted]")
                readchar.readkey()
                continue
            elif method == "aria":
                clear_screen()
                ok = download_with_aria2(session.magnet, session.download_indexes)
                if ok:
                    record_method_complete("aria")
                if not ok:
                    console.print("\n[muted]Press [key]any key[/key] to return to download options…[/muted]")
                    readchar.readkey()
                    continue
                if download_complete_prompt("Download finished", summary=_unpack_torrent(session)) == "next":
                    return "next"
                continue
            elif method == "p":
                clear_screen()
                ok = download_with_peerflix(session.magnet, session.download_indexes)
                if ok:
                    record_method_complete("peerflix_download")
                if not ok:
                    console.print("\n[muted]Press [key]any key[/key] to return to download options…[/muted]")
                    readchar.readkey()
                    continue
                if download_complete_prompt("Download finished", summary=_unpack_torrent(session)) == "next":
                    return "next"
                continue
            elif method == "d":
                clear_screen()
                ok = download_with_webtorrent(session.magnet, session.download_indexes)
                if ok:
                    record_method_complete("webtorrent_download")
                if not ok:
                    console.print("\n[muted]Press [key]any key[/key] to return to download options…[/muted]")
                    readchar.readkey()
                    continue
                if download_complete_prompt("Download finished", summary=_unpack_torrent(session)) == "next":
                    return "next"
                continue
            elif method == "s":
                import os as _os
                from torrent_finder.jimaku import is_subtitle_file
                sub_paths: list[str] = []
                # Anime: try Jimaku first (best anime coverage) when a key is
                # configured; it returns None to fall through to subliminal.
                if getattr(selected_provider, "slug", "") == "anime":
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
                            f"[highlight]{escape(primary)}[/highlight] "
                            f"[success]as primary, plus {extra} more track(s).[/success]"
                        )
                    else:
                        console.print(
                            f"[success]Saved. Next stream will use[/success] "
                            f"[highlight]{escape(primary)}[/highlight] "
                            f"[success]as the subtitle source.[/success]"
                        )
                elif sub_paths:
                    console.print(
                        f"[success]Saved[/success] "
                        f"[highlight]{escape(_os.path.basename(sub_paths[0]))}[/highlight]"
                        f"[success].[/success]"
                    )
                console.print("\n[muted]Press [key]any key[/key] to continue…[/muted]")
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
        try:
            if choice == "titles":
                from torrent_finder.ui.titles import title_search_flow
                creator_outcome = title_search_flow(provider, cli_filters, browse_results)
            elif choice == "discover":
                from torrent_finder.ui.discovery import discovery_flow
                creator_outcome = discovery_flow(provider, cli_filters, browse_results)
            else:
                creator_outcome = creator_search_flow(
                    provider, cli_filters, choice, browse_results
                )
        except KeyboardInterrupt:
            creator_outcome = "back"
        if creator_outcome == "next":
            return "next"
        # "back" → re-show the source screen


def _history_pick(entry):
    """Resolve a history entry → (provider, facet_or_None, value).

    Creator entry → (provider, facet, name); keyword → (provider, None, query).
    ``provider`` is None when it no longer exists; ``facet`` is None when the
    stored facet is gone (caller then treats ``value`` as a keyword fallback).
    """
    prov = get_provider(entry.get("provider", "") or "")
    if getattr(prov, "is_combined", False) and isinstance(entry.get("search_profile"), dict):
        prov.restore_history(entry["search_profile"])
    if entry.get("kind") == "creator":
        facet = None
        if prov:
            facet = next((f for f in getattr(prov, "creator_facets", []) if f.key == entry.get("facet")), None)
        return prov, facet, entry.get("name", "")
    aliases = entry.get("queries")
    return prov, None, (aliases if isinstance(aliases, list) and aliases and
                       all(isinstance(q, str) and q.strip() for q in aliases) else entry.get("query", ""))


def _bookmarks_flow(cli_filters=None):
    """One bookmark journey shared by the main, next and provider menus."""
    from torrent_finder import bookmarks
    from torrent_finder.ui.bookmarks import bookmark_menu
    from torrent_finder.ui.creator import _run_cancellable, _notice
    from torrent_finder.search_session import search_many
    from torrent_finder.search_errors import SearchError
    while True:
        chosen = _saved_data_action(bookmark_menu)
        if not chosen:
            return
        operation, entry = chosen
        if operation == "compare":
            from torrent_finder.providers.combined_provider import CombinedProvider
            provider = CombinedProvider(get_provider("all").templates)
            provider.filter_summary = lambda: "Saved bookmarks; metadata may be stale"
            browse_results(provider, [dict(e["result"], fetched_at=e["fetched_at"]) for e in entry])
            continue
        provider = _saved_data_action(lambda: bookmarks.search_provider(entry))
        if provider is None:
            continue
        if operation == "open" and entry["kind"] == "result":
            browse_results(provider, [dict(entry["result"], fetched_at=entry["fetched_at"])],
                           note="Saved listing; current availability is unverified. i: metadata details")
            continue
        cancel = threading.Event()
        cancelled, results = _run_cancellable(
            lambda: search_many(provider, entry["queries"], cli_filters, cancel_event=cancel),
            "Searching saved names…", cancel=cancel)
        if cancelled:
            continue
        if results is None or isinstance(results, SearchError):
            _notice("Saved search failed. Try again later.")
            continue
        provider.last_queries = entry["queries"]
        if operation == "refresh":
            _saved_data_action(lambda: bookmarks.refresh(entry["id"], results))
        from torrent_finder.state import add_history_entry
        presets = [p.name for p in provider.active_presets]
        extra = {"search_profile": provider.snapshot()} if getattr(provider, "is_combined", False) else {}
        for query in entry["queries"]:
            add_history_entry(query, provider.slug, presets, **extra)
            record_search(provider.slug, query, presets)
        browse_results(provider, results)


def _quick_actions_flow(provider=None, cli_filters=None, typed="", on_update=None):
    """Provider-bound actions stay scoped; global actions choose their scope."""
    from torrent_finder.ui.prompts import quick_actions_menu, action_provider_prompt
    while True:
        action = quick_actions_menu(update_available=bool(on_update), provider=provider)
        scope = provider
        if action in {"filter", "titles", "discover", "save_search"} and scope is None:
            scope = action_provider_prompt({"filter": "Filters", "titles": "Alternate titles",
                                           "discover": "Topic discovery", "save_search": "Save search"}[action])
            if scope is None:
                continue
        if action == "update" and on_update:
            on_update()
            on_update = None
        elif action == "filter":
            filter_menu(scope)
        elif action in {"titles", "discover"}:
            if action == "titles":
                from torrent_finder.ui.titles import title_search_flow
                outcome = title_search_flow(scope, cli_filters, browse_results, initial=typed)
            else:
                from torrent_finder.ui.discovery import discovery_flow
                outcome = discovery_flow(scope, cli_filters, browse_results, initial=typed)
            if outcome == "next":
                return _handle_whats_next(scope, cli_filters, on_update)
        elif action == "save_search":
            from torrent_finder.bookmarks import save_search
            from torrent_finder.ui.creator import _notice
            value = typed.strip() or get_query_with_shortcut(
                PROMPT, screen_renderer=input_screen(
                    "Bookmark current search", "Saves this query with the provider's current settings.",
                    keys="Enter save  •  Esc cancel"))
            if isinstance(value, str) and value and value != "GO_BACK":
                if _saved_data_action(lambda: save_search(scope, value)):
                    _notice("Search bookmarked.")
        elif action == "bookmarks":
            _bookmarks_flow(cli_filters)
        elif action == "qbittorrent":
            from torrent_finder.ui.qbittorrent import client_menu
            client_menu()
        elif action == "backup":
            from torrent_finder.ui.backup import backup_menu
            if backup_menu():
                from torrent_finder.state import reload_state
                from torrent_finder.search_profiles import ProfileLibrary
                reload_state(PROVIDERS)
                current_profile = ProfileLibrary.load().current
                get_provider("all").use_profile(current_profile)
                if provider is not None:
                    if getattr(provider, "is_combined", False):
                        provider.use_profile(current_profile)
                    else:
                        reload_state([provider])
        elif action == "history":
            from torrent_finder.ui.history import history_select_prompt
            pick = history_select_prompt()
            if pick:
                prov, facet, val = _history_pick(pick)
                if prov is not None:
                    return (None, prov, facet, val) if facet else (val, prov, None, None)
        elif action == "stats":
            from torrent_finder.ui.stats import stats_page
            stats_page()
        elif action == "tips":
            from torrent_finder.ui.tips_page import tips_page
            tips_page()
        else:
            return None


def _handle_whats_next(current_provider, cli_filters=None, on_update=None):
    """Show the post-action "What's next?" menu.

    Returns ``(query, provider, facet, name)`` to keep looping, or ``"EXIT"`` to
    quit. ``facet`` is set only when a creator history entry was picked (caller
    seeds the by-creator one-shot); otherwise it's None and ``query`` drives a
    normal search.
    """
    from torrent_finder.ui.prompts import confirm_prompt

    while True:
        choice = search_again_prompt()
        if choice in (None, "exit"):
            if confirm_prompt("Quit torrent-finder?", title="Quit"):
                return "EXIT"
            clear_screen()
            continue
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
        if choice in {"provider", "main"}:
            return (None, None, None, None)
        if choice == "actions":
            outcome = _quick_actions_flow(cli_filters=cli_filters, on_update=on_update)
            if outcome is not None:
                return outcome


def _run_update_flow(info: dict) -> None:
    """Run the install-appropriate update (git pull / pipx / open Releases)."""
    clear_screen()
    try:
        with UpdateDisplay(console, current=info.get("current", ""), latest=info.get("latest", "")) as display:
            ok, msg = run_update(info, on_progress=display.update)
            stage = "failed"
            if ok:
                if needs_exit_before_update(info):
                    stage = "waiting"
                elif info.get("kind") == "binary":
                    stage = "opened"
                else:
                    stage = "succeeded"
            display.update(stage, msg)
    except KeyboardInterrupt:
        console.print("\n[warning]Update cancelled.[/warning]")
        clear_screen()
        return
    if ok and needs_exit_before_update(info):
        console.print("[muted]Press [key]any key[/key] to close and let the update finish.[/muted]")
        try:
            readchar.readkey()
        except KeyboardInterrupt:
            pass
        raise SystemExit(0)
    console.print("\n[muted]Press [key]any key[/key] to continue…[/muted]")
    try:
        readchar.readkey()
    except KeyboardInterrupt:
        pass
    clear_screen()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search and download torrents.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--preview-update", nargs="?", const="success", choices=("success", "failure"),
                        help="Preview the update display without installing anything")
    parser.add_argument("--providers", nargs="+", metavar="PROVIDER", choices=[p for p in provider_cli_choices() if p != "all"],
                        help="Providers for -t all (for example: --providers anime manga)")
    parser.add_argument("--profile", metavar="NAME", help="Use a named search profile (implies -t all)")
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
    from torrent_finder.ui.theme import THEMES
    parser.add_argument("--theme", choices=tuple(THEMES), type=str.lower,
                        help="Colour theme for this run (saved choice: Settings › Appearance)")
    return parser


def _apply_appearance(args) -> str:
    """Apply the theme before the first frame; returns a notice for the main menu."""
    from torrent_finder.ui.appearance import apply_startup
    return apply_startup(getattr(args, "theme", None))


def _main_loop(args=None) -> None:
    parser = _build_parser()
    args = args or parser.parse_args()
    theme_notice = _apply_appearance(args)
    if args.preview_update:
        preview_update(args.preview_update)
        return
    if store.problem() is not None:
        from torrent_finder.ui.storage import storage_problem_prompt
        storage_problem_prompt()
    load_state(PROVIDERS)
    if args.profile:
        if args.type not in (None, "all"):
            parser.error("--profile requires -t all (or omit -t)")
        args.type = "all"
        from torrent_finder.search_profiles import ProfileLibrary
        try:
            library = ProfileLibrary.load()
        except ValueError as error:
            parser.error(str(error))
        profile_entry = library.find(args.profile)
        if profile_entry is None:
            parser.error(f"Unknown search profile {args.profile!r}. Available: " + ", ".join(p["name"] for p in library.entries))
    if args.providers and args.type != "all":
        parser.error("--providers requires -t all")
    advise_limited_terminal()
    if not args.skip_warning:
        if not show_security_warning():
            console.print("[info]Aborted.[/info]")
            return
    from torrent_finder.security import exposure
    from torrent_finder.ui import chrome as frames
    if exposure() == "exposed":
        frames.announce("You feel watched: every peer can see your real IP.")
    elif exposure() == "vpn":
        frames.announce("A cloak of VPN hides your address from the swarm.")

    query = args.query
    initial_provider = None

    if args.type:
        initial_provider = get_provider(args.type)
        if not initial_provider:
            console.print(f"[warning] Unknown provider type '{markup_escape(args.type)}'. Falling back to Movies.[/warning]")
            initial_provider = PROVIDERS[0]
    elif query or args.by:
        # If -q or --by is passed without -t, default to Movies.
        initial_provider = PROVIDERS[0]

    session_provider = initial_provider
    current_provider = session_provider
    if args.profile:
        current_provider.use_profile(profile_entry)
    if args.providers:
        profile = current_provider.snapshot()
        profile["selected"] = [get_provider(name).slug for name in args.providers]
        current_provider.restore(profile)

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
            console.print(f"[warning] {markup_escape(current_provider.name)} has no '--by {markup_escape(args.by)}' "
                          f"option (available: {markup_escape(avail)}).[/warning]")
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
    if theme_notice:
        update_msg = "\n".join(filter(None, (update_msg, f"[warning]{markup_escape(theme_notice)}[/warning]")))
    from rich.markup import escape
    update_report = consume_update_report()
    if update_report:
        update_msg = "\n".join(filter(None, (update_msg, escape(update_report))))
    # In the Athanor design these are messages on the message line instead of a banner.
    if update_info:
        frames.announce(f"A raven arrives: {escape(status_label(update_info))}. U installs it.")
    if update_report:
        frames.announce(escape(update_report.splitlines()[0]))
    if theme_notice:
        frames.announce(f"[warn]{markup_escape(theme_notice)}[/warn]")
    if current_provider and update_msg:
        # highlight=False: the auto-highlighter would restyle the version
        # digits (bold → bright black) on the yellow banner.
        console.print(update_msg + "\n", highlight=False)

    def run_pending_update():
        nonlocal update_info, update_msg
        if update_info:
            _run_update_flow(update_info)
        update_info, update_msg = None, ""

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

    # Double-press quit guard: the first Esc/Ctrl+C on the provider menu or
    # search prompt re-opens the menu with a "press again to quit" hint; the
    # next Esc/Ctrl+C there quits, any other selection disarms. Deeper flows
    # keep instant Ctrl+C (it means "abort this operation", not idle exit).
    exit_armed = False

    while True:
        # One-shot CLI creator search (--by/--name): jump into the by-creator
        # flow, then fall into the normal what's-next / keyword loop.
        if cli_facet is not None and pending_creator_name is not None:
            from torrent_finder.ui.creator import creator_search_flow
            facet, nm = cli_facet, pending_creator_name
            cli_facet = pending_creator_name = None
            try:
                creator_outcome = creator_search_flow(
                    current_provider, cli_filters, facet, browse_results,
                    initial_name=nm,
                )
            except KeyboardInterrupt:
                creator_outcome = "back"
            if creator_outcome == "next":
                res = _handle_whats_next(current_provider, cli_filters, run_pending_update if update_info else None)
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
            exit_hint = (
                "[alert]Press Esc or Ctrl+C again to quit[/alert]"
                if exit_armed else ""
            )
            try:
                result = provider_select_prompt(
                    notice="" if theme.FRAMED else update_msg or "",  # Athanor: the message line says it
                    alert=exit_hint,  # the last line of the frame, under the keys
                    open_group=pending_open_group,
                    update_available=bool(update_info),
                    update_status=status_label(update_info),
                )
            except (KeyboardInterrupt, EOFError):
                result = None  # Ctrl+C/Ctrl+D arm the same quit guard as Esc
            pending_open_group = None
            if result is None:
                if exit_armed:
                    _goodbye()
                    break
                exit_armed = True
                continue
            exit_armed = False
            if result == "__update__":
                _run_update_flow(update_info)
                update_info = None   # consumed → drop the notice + menu row
                update_msg = ""
                continue
            if result == "__actions__":
                outcome = _quick_actions_flow(cli_filters=cli_filters, on_update=run_pending_update if update_info else None)
                if outcome == "EXIT":
                    _goodbye()
                    return
                if outcome is not None:
                    query, current_provider, cli_facet, pending_creator_name = outcome
                continue
            # The CONTINUE row of a plain keyword search opens the search
            # field with that query, ready to run or edit.
            if isinstance(result, tuple) and result[0] == "continue":
                continued = get_provider(result[1].get("provider", "") or "")
                if continued is None:
                    continue
                current_provider = continued
                pending_query = str(result[1].get("query", ""))
                query = None
                clear_screen()
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
                res = _handle_whats_next(current_provider, cli_filters, run_pending_update if update_info else None)
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
            engine_names = [e.name for e in provider.effective_engines]
            engine_str = ", ".join(engine_names) if engine_names else "None"
            active_name = provider.filter_summary()
            if getattr(provider, "is_combined", False):
                engine_str, active_name = provider.summary()
            prov_history = history_queries(provider.slug)
            screen_renderer = make_search_screen_renderer(
                engine_str,
                active_name,
                has_history=bool(prov_history),
                notice=notice_msg or "",
                scope_label="Providers" if getattr(provider, "is_combined", False) else "Engines",
                title=provider.name,
                provider=provider,
                recent_hints=history_notes(provider.slug),
            )
            notice_msg = None
            initial, pending_query = pending_query, ""
            try:
                query = get_query_with_shortcut(
                    PROMPT,
                    initial=initial, history=prov_history, filters_shortcut=True,
                    multi=True, screen_renderer=screen_renderer, propagate_interrupt=True,
                )
            except (EOFError, KeyboardInterrupt):
                # Ctrl+C at the search prompt: route to the provider menu with
                # the quit guard armed instead of exiting outright — the next
                # Esc/Ctrl+C there quits.
                exit_armed = True
                current_provider = None
                query = None
                show_source = False
                clear_screen()
                continue

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
                query = None
                outcome = _quick_actions_flow(provider, cli_filters, typed, run_pending_update if update_info else None)
                if outcome == "EXIT":
                    _goodbye()
                    return
                if outcome is not None:
                    query, current_provider, _hf, _hn = outcome
                    if _hf:
                        cli_facet, pending_creator_name = _hf, _hn
                else:
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
        # and merge (dedupe by hash, ranked like a single search), reusing the
        # by-creator search path.
        shown = ", ".join(queries)
        combined = getattr(provider, "is_combined", False)
        if combined:
            # CLI -q can reach this screen before the lazy profile is loaded.
            count = sum(p.slug in provider.selected_slugs for p in provider.children)
            intro = (f"Searching {count} provider{'s' if count != 1 else ''} for: "
                     f"[highlight]{escape(shown)}[/highlight]")
            notes = ["Results appear when the search finishes or after 30 seconds."]
        else:
            intro = f"Searching {escape(provider.name)} for: [highlight]{escape(shown)}[/highlight]"
            notes = [escape(provider.search_note)] if getattr(provider, "search_note", "") else []
            notes.append("30 s search limit; Enter shows the results received so far.")

        # Run the search on a worker thread so Esc can abort the wait instead of
        # forcing the user to sit through the engine timeouts (or Ctrl+C).
        search_result: dict = {}
        cancel_event = threading.Event()
        finish_event = threading.Event()

        def report_progress(progress, target=search_result):
            target["progress"] = progress

        def _run_search(provider=provider, queries=queries, cli_filters=cli_filters,
                        cancel_event=cancel_event, finish_event=finish_event,
                        search_result=search_result, report_progress=report_progress) -> None:
            try:
                from torrent_finder.search_session import search_many
                search_result["results"] = search_many(
                    provider, queries, cli_filters, cancel_event=cancel_event,
                    finish_event=finish_event, on_progress=report_progress,
                )
            except Exception as error:
                from torrent_finder.search_errors import SearchError
                search_result["results"] = []
                if isinstance(error, SearchError):
                    search_result["error"] = str(error)
                else:
                    search_result["error"] = "Search could not be completed. Please try again."
            finally:
                search_result["done"] = True

        worker = threading.Thread(target=_run_search, daemon=True)
        worker.start()
        stop_listener = start_esc_listener(cancel_event, finish_event=finish_event)
        started = time.monotonic()
        waiting_label = "Contacting selected providers…" if combined else f"Searching {provider.name}…"
        title = f"{escape(provider.name)} › {escape(shown)}"
        try:
            with ProgressScreen() as screen:
                drawn_at = 0.0
                while True:
                    now = time.monotonic()
                    if now - drawn_at >= SEARCH_REDRAW_S:
                        screen.draw(progress_frame(title, intro, notes, search_result.get("progress"),
                                                   now - started, waiting_label, now))
                        drawn_at = now
                    if search_result.get("done") or cancel_event.is_set():
                        break
                    time.sleep(0.05)
        except KeyboardInterrupt:
            cancel_event.set()
        finally:
            stop_listener.set()

        if cancel_event.is_set():
            notice_msg = "[warning] Search cancelled — returning to the prompt.[/warning]\n"
            clear_screen()
            query = None
            continue

        raw_results = search_result.get("results")
        notices = list(getattr(raw_results, "notices", ()))
        results = raw_results if raw_results is not None else []
        provider.last_queries = queries
        if not results and getattr(results, "session", None) is None:
            from rich.markup import escape
            message = search_result.get("error") or "\n".join(["No results found.", *notices])
            notice_msg = f"[warning] {escape(message)}[/warning]\n"
            clear_screen()
            query = None
            continue

        # Record the successful search in history + stats — each title
        # individually so ↑/↓ recall offers them separately.
        from torrent_finder.state import add_history_entry
        active_preset_names = [pr.name for pr in getattr(provider, "active_presets", [])]
        for q in queries:
            extra = {"search_profile": provider.snapshot()} if getattr(provider, "is_combined", False) else {}
            add_history_entry(q, provider.slug, active_preset_names, **extra)
            record_search(provider.slug, q, active_preset_names)

        # Note any searched titles that returned nothing (multi-title only). It
        # rides above the results table (a pre-table print would be wiped by the
        # table's own screen clear).
        note = ""
        if len(queries) > 1:
            found = {q for r in results for q in r.get("matched_queries", [r.get("from_work")])}
            missing = [q for q in queries if q not in found]
            if missing:
                cap = 4
                more = f" +{len(missing) - cap} more" if len(missing) > cap else ""
                note = (f"No torrents for {len(missing)} of {len(queries)} titles: "
                        + ", ".join(missing[:cap]) + more)
        if notices:
            note = "\n".join(filter(None, [note, *notices]))

        # Results + download (shared with the by-creator flow). Esc on the
        # results table steps back to the keyword prompt; a completed download
        # proceeds to "what's next?".
        frames.clear_messages()
        frames.announce(f"You find {len(results)} result{'s' if len(results) != 1 else ''} "
                        f"for {escape(', '.join(queries))}.")
        if browse_results(provider, results, note=note) == "back":
            query = None
            clear_screen()
            continue

        res = _handle_whats_next(current_provider, cli_filters, run_pending_update if update_info else None)
        if res == "EXIT":
            _goodbye()
            break
        query, current_provider, _hf, _hn = res
        if _hf:
            cli_facet, pending_creator_name = _hf, _hn
        continue

def main() -> None:
    from torrent_finder.search_profiles import ProfileError
    args = _build_parser().parse_args()
    if args.preview_update:
        _apply_appearance(args)
        try:
            preview_update(args.preview_update)
        except (KeyboardInterrupt, EOFError):
            pass
        return
    record_session_start()
    t0 = time.monotonic()
    try:
        _main_loop(args)
    except ProfileError as error:
        from rich.markup import escape
        console.print(f"[warning]{escape(str(error))}[/warning]")
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
