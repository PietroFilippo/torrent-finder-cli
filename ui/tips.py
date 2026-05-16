"""Rotating tip pool shown on menu screens — reminds users about non-obvious
hotkeys, persisted behavior, and safety notes without stealing attention.

Tips are rendered as italic body text with a bold cyan "💡 Tip:" prefix —
loud enough to actually catch the eye, quiet enough to stay subordinate to
the menu it sits under.
"""

import random


TIPS: list[str] = [
    # — Search & navigation —
    "For best results, search using the complete release name.",
    "Press Shift+F at the search prompt to tweak engines or toggle filter presets.",
    "Press F on a highlighted provider to configure its filters without leaving this menu.",
    "Shift+H opens your search history — past queries re-run with one keypress.",
    "Shift+S shows usage stats: runtime, top queries, method completion rates.",
    "History entries remember the filter presets you had active at search time.",
    "Use -f and -x on the CLI to add ad-hoc include/exclude keywords.",

    # — Filters & menus —
    "Filter menu keybinds: a select all • i invert • c clear presets • w save.",
    "Episode/filter pickers share keybinds: v anchor, Shift+V toggles the range.",
    "Your engine + preset toggles persist across runs in filter_state.json.",
    "Results are deduped by info hash across engines, then sorted by seeders.",
    "Toggle 🔇 Quiet mode in the download menu to replace subprocess UIs with a minimal spinner.",

    # — Downloads —
    "aria2c is the only downloader that strictly honors your file selection — webtorrent/peerflix may pull the whole torrent.",
    "aria2c handles multi-file selection in a single process — fastest for batches.",
    "Browse torrent files (📂) before downloading to pick just the episodes/extras you actually want.",
    "The episode picker remembers your previous selection — re-open it to refine, not rebuild.",
    "Confirming the picker with nothing checked clears the selection; Esc keeps your prior picks.",

    # — Streaming —
    "webtorrent is the default streaming backend; peerflix is the fallback if it stalls.",
    "Press v while streaming to reopen VLC — it's a no-op if VLC is already running, so spamming it is safe.",
    "Multi-episode streams: press n for next, b for previous episode.",
    "Even without a picker selection, multi-episode torrents auto-enable n/b navigation in VLC.",
    "Pick non-video files (.srt/.nfo/.jpg) in the browser — downloads grab them, streams skip them.",

    # — Subtitles —
    "📝 Source: auto-detect pulls .srt/.ass files out of the torrent and attaches them to VLC for you.",
    "Need subs the torrent doesn't ship? 📝 Search & download subtitles auto-pins the result to the next stream.",
    "Switch 📝 Source to 'external' to pick any .srt/.ass from your downloads folder.",

    # — Safety —
    "Your public IP is visible to every peer — a VPN is the only real mitigation.",
    "The 'Trusted Uploaders' preset is a community reputation heuristic, not a safety guarantee.",
    "Re-open the network exposure panel anytime from the 🔒 row on the Select Provider screen.",
]


def random_tip() -> str:
    """Return a randomly-picked tip rendered as Rich markup.

    The prefix is bold cyan so it catches the eye; the body is italic at normal
    intensity so it's readable without competing with the menu above it. Safe
    to drop into an `arrow_select` footer.
    """
    text = random.choice(TIPS)
    return f"[bold cyan]💡 Tip:[/bold cyan] [italic]{text}[/italic]"
