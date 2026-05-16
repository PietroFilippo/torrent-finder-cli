"""User-facing prompts: banner, download method selection."""

import sys

import readchar
from rich.panel import Panel
from rich.text import Text

from constants import console
from downloader import (
    detect_torrent_client,
    download_with_webtorrent,
    has_aria2,
    has_webtorrent,
    has_peerflix,
    open_magnet,
)
from providers import PROVIDERS
from ui.selector import SelectItem, arrow_select


def get_query_with_shortcut(prompt_str: str) -> str | None:
    """Get input from user manually, returning 'SPECIAL_FILTER' instantly if they press Shift+F as first char."""
    console.print(prompt_str, end="")
    sys.stdout.flush()
    
    buffer = []
    while True:
        key = readchar.readkey()
        
        if not buffer and key == "F":
            print()
            return "SPECIAL_FILTER"

        if not buffer and key == "H":
            print()
            return "SPECIAL_HISTORY"

        if not buffer and key == "S":
            print()
            return "SPECIAL_STATS"
            
        if key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
            print()
            return "".join(buffer)
            
        elif key == readchar.key.ESC:
            print()
            return "GO_BACK"
            
        elif key in (readchar.key.BACKSPACE, '\x08', '\x7f'):
            if buffer:
                buffer.pop()
                sys.stdout.write('\b \b')
                sys.stdout.flush()
                
        elif key in (readchar.key.CTRL_C, '\x03'):
            raise KeyboardInterrupt
            
        elif key in (readchar.key.CTRL_D, '\x04'):
            raise EOFError
            
        elif len(key) == 1 and not key.startswith('\x1b') and not key.startswith('\x00') and not key.startswith('\xe0'):
            buffer.append(key)
            sys.stdout.write(key)
            sys.stdout.flush()


def filter_menu(provider) -> None:
    """Show engine toggles and filter presets in a single menu."""
    has_engines = hasattr(provider, 'engines') and provider.engines
    has_presets = bool(provider.presets)

    if not has_engines and not has_presets:
        console.print("[warning] No filters available for this provider.[/warning]")
        return

    items = []

    # --- Section 1: Search Engines ---
    engine_indices = []
    if has_engines:
        items.append(SelectItem(
            label="─── Search Engines ───",
            value="section_header",
            enabled=False,
            is_action=True,
        ))
        for engine in provider.engines:
            items.append(SelectItem(
                label=f"{engine.icon} {engine.name}",
                value=("engine", engine),
                toggled=engine.enabled,
            ))
            engine_indices.append(len(items) - 1)

    # --- Section 2: Filter Presets ---
    preset_indices = []
    if has_presets:
        items.append(SelectItem(
            label="─── Filter Presets ───",
            value="section_header",
            enabled=False,
            is_action=True,
        ))
        for p in provider.presets:
            items.append(SelectItem(
                label=p.name,
                value=("preset", p),
                toggled=p in provider.active_presets,
            ))
            preset_indices.append(len(items) - 1)

    # --- Action buttons ---
    items.append(SelectItem(label="Clear filters  [c]", value="clear", is_action=True))
    items.append(SelectItem(label="✅ Confirm  [w]", value="confirm", is_action=True))
    items.append(SelectItem(label="↩ Go Back", value="back", is_action=True))

    # Index of Confirm action — returned when `w` is pressed
    confirm_idx = len(items) - 2

    # All toggleable rows (engines + presets)
    toggle_indexes = engine_indices + preset_indices

    # Anchor state for range-toggle (v/V)
    anchor = {"idx": None}

    def _toggle_set() -> set[int]:
        return set(toggle_indexes)

    def _select_all(cursor, items_list):
        for i in toggle_indexes:
            if items_list[i].enabled:
                items_list[i].toggled = True
        return True

    def _invert(cursor, items_list):
        for i in toggle_indexes:
            if items_list[i].enabled:
                items_list[i].toggled = not items_list[i].toggled
        return True

    def _clear(cursor, items_list):
        # Clear preset toggles only — leave engine toggles alone
        for pi in preset_indices:
            items_list[pi].toggled = False
        return True

    def _confirm_now(cursor, items_list):
        return confirm_idx

    def _set_anchor(cursor, items_list):
        t_set = _toggle_set()
        if cursor not in t_set:
            return True
        if anchor["idx"] is not None and 0 <= anchor["idx"] < len(items_list):
            items_list[anchor["idx"]].marker = ""
        anchor["idx"] = cursor
        items_list[cursor].marker = "📍"
        return True

    def _range_toggle(cursor, items_list):
        if anchor["idx"] is None:
            return _set_anchor(cursor, items_list)
        t_set = _toggle_set()
        lo, hi = sorted([anchor["idx"], cursor])
        anchor_now = items_list[anchor["idx"]].toggled
        target = not anchor_now
        for i in range(lo, hi + 1):
            if i in t_set and items_list[i].enabled:
                items_list[i].toggled = target
        items_list[anchor["idx"]].marker = ""
        anchor["idx"] = None
        return True

    def _toggle_current(cursor, items_list):
        if cursor in _toggle_set() and items_list[cursor].enabled:
            items_list[cursor].toggled = not items_list[cursor].toggled
        return True

    def handle_filter_action(idx, items):
        if items[idx].value == "clear":
            return _clear(idx, items)
        return False  # Exit for Confirm / Go Back

    key_actions = {
        "a": _select_all,
        "A": _select_all,
        "i": _invert,
        "I": _invert,
        "c": _clear,
        "C": _clear,
        "w": _confirm_now,
        "W": _confirm_now,
        "v": _set_anchor,
        "V": _range_toggle,
        " ": _toggle_current,
    }

    # Start cursor on first enabled item (skip header)
    start = 1 if has_engines else 0

    result_idx = arrow_select(
        items,
        title=f"Filters — {provider.label}",
        multi=True,
        banner=_make_banner_panel(),
        on_action=handle_filter_action,
        start_index=start,
        key_actions=key_actions,
        footer=(
            "↑/↓ nav  •  Space/Enter toggle  •  "
            "[bold yellow]v[/bold yellow] anchor  •  [bold yellow]shift + v or V[/bold yellow] range  •  "
            "[bold yellow]a[/bold yellow]ll/[bold yellow]i[/bold yellow]nvert/[bold yellow]c[/bold yellow]lear  •  "
            "[bold green]w[/bold green] save  •  Esc cancel"
        ),
    )

    if result_idx is None:
        return

    action = items[result_idx].value

    if action == "confirm":
        # Apply engine toggles
        for idx in engine_indices:
            item = items[idx]
            _type, engine = item.value
            engine.enabled = item.toggled

        # Apply preset toggles
        provider.active_presets.clear()
        for idx in preset_indices:
            item = items[idx]
            if item.toggled:
                _type, preset = item.value
                provider.active_presets.append(preset)

        from state import save_state
        save_state(PROVIDERS)
    # "back" — just return


def episode_select_prompt(files: list, preselected: list[int] | None = None) -> list[int] | None:
    """Multi-select menu for picking episodes from a torrent's file list.

    Takes a list of TorrentFile. ``preselected`` is a list of 1-based file
    indexes to pre-toggle (so re-entering the picker shows current selection).

    Returns:
        - ``None`` if cancelled (Esc / Cancel button) — caller keeps prior selection.
        - ``list[int]`` (possibly empty) on Confirm — caller replaces prior selection.
          Empty list means "clear selection".
    """
    import os
    from torrent_meta import extract_episode_number, format_size
    from stats import record_episode_picker_used

    if not files:
        console.print("[warning] No files in torrent.[/warning]")
        return None

    record_episode_picker_used()

    pre_set = set(preselected or [])

    items: list[SelectItem] = []
    file_item_indexes: list[int] = []
    for f in files:
        ep = extract_episode_number(f.name)
        ep_label = f"Ep {ep.rjust(3, '0') if ep.isdigit() else ep}" if ep else "      "
        label = f"{ep_label}  {os.path.basename(f.name)}"
        items.append(SelectItem(
            label=label,
            value=("file", f),
            toggled=(f.index in pre_set),
            hint=format_size(f.size_bytes),
        ))
        file_item_indexes.append(len(items) - 1)

    items.append(SelectItem(label="Select all  [a]", value="all", is_action=True))
    items.append(SelectItem(label="Invert selection  [i]", value="invert", is_action=True))
    items.append(SelectItem(label="Clear  [c]", value="clear", is_action=True))
    items.append(SelectItem(label="✅ Confirm  [w]", value="confirm", is_action=True))
    items.append(SelectItem(label="↩ Cancel", value="cancel", is_action=True))

    # Index of the Confirm action — returned when `w` is pressed
    confirm_idx = len(items) - 2

    # Anchor state for range-toggle (v/V)
    anchor = {"idx": None}

    def _file_item_set() -> set[int]:
        return set(file_item_indexes)

    def _select_all(cursor, items):
        for i in file_item_indexes:
            if items[i].enabled:
                items[i].toggled = True
        return True

    def _invert(cursor, items):
        for i in file_item_indexes:
            if items[i].enabled:
                items[i].toggled = not items[i].toggled
        return True

    def _clear(cursor, items):
        for i in file_item_indexes:
            items[i].toggled = False
        return True

    def _confirm_now(cursor, items):
        return confirm_idx

    def _set_anchor(cursor, items):
        file_set = _file_item_set()
        if cursor not in file_set:
            return True  # ignore on non-file rows
        # Clear any previous anchor marker
        if anchor["idx"] is not None and 0 <= anchor["idx"] < len(items):
            items[anchor["idx"]].marker = ""
        anchor["idx"] = cursor
        items[cursor].marker = "📍"
        return True

    def _range_toggle(cursor, items):
        if anchor["idx"] is None:
            # No anchor yet — treat as anchor set
            return _set_anchor(cursor, items)
        file_set = _file_item_set()
        lo, hi = sorted([anchor["idx"], cursor])
        # Derive target toggle state from anchor row (flip it for the whole range)
        anchor_now = items[anchor["idx"]].toggled
        target = not anchor_now
        for i in range(lo, hi + 1):
            if i in file_set and items[i].enabled:
                items[i].toggled = target
        # Clear anchor after range apply
        items[anchor["idx"]].marker = ""
        anchor["idx"] = None
        return True

    def _toggle_current(cursor, items):
        if cursor in _file_item_set() and items[cursor].enabled:
            items[cursor].toggled = not items[cursor].toggled
        return True

    def on_action(idx, items):
        val = items[idx].value
        if val == "all":
            return _select_all(idx, items)
        if val == "invert":
            return _invert(idx, items)
        if val == "clear":
            return _clear(idx, items)
        return False

    key_actions = {
        "a": _select_all,
        "A": _select_all,
        "i": _invert,
        "I": _invert,
        "c": _clear,
        "C": _clear,
        "w": _confirm_now,
        "W": _confirm_now,
        "v": _set_anchor,
        "V": _range_toggle,
        " ": _toggle_current,
    }

    result = arrow_select(
        items,
        title=f"Select Episodes — {len(files)} files",
        multi=True,
        banner=_make_banner_panel(),
        on_action=on_action,
        key_actions=key_actions,
        footer=(
            "↑/↓ nav  •  Space/Enter toggle  •  "
            "[bold yellow]v[/bold yellow] anchor  •  [bold yellow]shift + v or V[/bold yellow] range  •  "
            "[bold yellow]a[/bold yellow]ll/[bold yellow]i[/bold yellow]nvert/[bold yellow]c[/bold yellow]lear  •  "
            "[bold green]w[/bold green] save  •  Esc cancel"
        ),
    )

    if result is None:
        return None
    action = items[result].value
    if action != "confirm":
        return None

    return [items[i].value[1].index for i in file_item_indexes if items[i].toggled]


def _make_banner_panel() -> Panel:
    """Return the app banner as a Rich Panel renderable."""
    banner = Text()
    banner.append("Torrent Search CLI", style="bold magenta")
    return Panel(
        banner,
        border_style="bright_blue",
        padding=(1, 2),
    )


def subtitle_source_prompt(current: dict | None = None) -> dict:
    """Pick the subtitle source for the next stream.

    Returns a dict ``{"mode": "auto"|"off"|"external", "path": str | None}``.
    Falls back to *current* (or auto-detect) when cancelled.
    """
    import os
    from constants import DOWNLOADS_DIR

    current = current or {"mode": "auto", "path": None}

    items = [
        SelectItem(
            label="🔍 Auto-detect from torrent",
            value="auto",
            description="Scan the torrent for .srt/.ass files alongside each video and attach them automatically.",
        ),
        SelectItem(
            label="📁 Use external subtitle file…",
            value="external",
            description="Pick a .srt/.ass file from your downloads folder or type a custom path.",
            is_action=True,
        ),
        SelectItem(
            label="🚫 No subtitles",
            value="off",
            description="Stream without attaching any subtitles.",
        ),
        SelectItem(label="↩ Back", value="back", is_action=True),
    ]

    mode_to_index = {"auto": 0, "external": 1, "off": 2}
    start = mode_to_index.get(current.get("mode", "auto"), 0)

    result = arrow_select(
        items,
        title="Subtitle Source",
        banner=_make_banner_panel(),
        start_index=start,
    )

    if result is None:
        return current
    val = items[result].value
    if val == "back":
        return current
    if val in ("auto", "off"):
        return {"mode": val, "path": None}

    # external — open file picker
    sub_files: list[tuple[str, str]] = []  # (label, abs_path)
    if os.path.isdir(DOWNLOADS_DIR):
        try:
            entries = [
                (n, os.path.getmtime(os.path.join(DOWNLOADS_DIR, n)))
                for n in os.listdir(DOWNLOADS_DIR)
                if n.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"))
            ]
            entries.sort(key=lambda t: -t[1])
            for fname, _ in entries[:15]:
                sub_files.append((fname, os.path.join(DOWNLOADS_DIR, fname)))
        except OSError:
            pass

    picker_items: list[SelectItem] = []
    for label, path in sub_files:
        picker_items.append(SelectItem(label=f"📄 {label}", value=path))
    if not sub_files:
        picker_items.append(SelectItem(
            label="[no .srt/.ass files found in downloads folder]",
            value="__none__",
            enabled=False,
            is_action=True,
        ))
    picker_items.append(SelectItem(
        label="✍️  Type custom path…",
        value="__type__",
        is_action=True,
        description="Type or paste the absolute path to a subtitle file.",
    ))
    picker_items.append(SelectItem(label="↩ Back", value="back", is_action=True))

    pick = arrow_select(
        picker_items,
        title="External Subtitle File",
        banner=_make_banner_panel(),
    )

    if pick is None:
        return current
    chosen = picker_items[pick].value
    if chosen == "back" or chosen == "__none__":
        return current
    if chosen == "__type__":
        try:
            path = console.input("[info]Path to subtitle file: [/info]").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            return current
        if not path:
            return current
        if not os.path.exists(path):
            console.print(f"[warning] File not found: {path}[/warning]")
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return current
        return {"mode": "external", "path": os.path.abspath(path)}
    return {"mode": "external", "path": chosen}


def confirm_prompt(message: str, title: str = "Confirm") -> bool:
    """Show a Y/N confirmation modal in the alt-screen. Returns True on Y."""
    panel = Panel(
        Text.from_markup(
            f"{message}\n\n"
            "[bold yellow]Y[/bold yellow] confirm  •  any other key cancel"
        ),
        title=f"[bold red]{title}[/bold red]",
        border_style="red",
        padding=(1, 2),
    )
    sys.stdout.write("\033[?1049h\033[?25l\033[H\033[2J")
    sys.stdout.flush()
    try:
        console.print(panel)
        key = readchar.readkey()
        return key.lower() == "y"
    finally:
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")
        sys.stdout.flush()


def print_banner() -> None:
    """Display the app banner."""
    console.print(_make_banner_panel())
    console.print()


import os

def clear_screen() -> None:
    """Clear the console and reprint the banner to reduce visual pollution."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print_banner()


def download_method_prompt(
    magnet: str = "",
    show_subtitles: bool = True,
    show_episode_picker: bool = False,
    selected_indexes: list[int] | None = None,
    sub_choice: dict | None = None,
) -> str | None:
    """
    Prompt the user to choose a download method.
    Returns 't', 'd', 'p', 'aria', 'stream_w', 'stream_p', 's', 'pick_episodes',
    'set_subs', 'back', or None. 'l' (copy magnet) is handled internally.
    """
    wt_available = has_webtorrent()
    pf_available = has_peerflix()
    aria_available = has_aria2()
    client_name = detect_torrent_client()
    has_selection = bool(selected_indexes)
    n_sel = len(selected_indexes) if selected_indexes else 0

    def _section(label: str) -> SelectItem:
        return SelectItem(
            label=f"─── {label} ───",
            value="section_header",
            enabled=False,
            is_action=True,
        )

    items: list[SelectItem] = []

    # --- Episode selection (only for providers that support it) ---
    if show_episode_picker:
        items.append(_section("File selection"))
        ep_label = (
            f"📂 Change selection ({n_sel} picked)"
            if has_selection
            else "📂 Browse torrent files… (Episode Selection for animes/series)"
        )
        items.append(SelectItem(
            label=ep_label,
            value="pick_episodes",
            is_action=True,
            hint=("requires aria2c to fetch file list" if not aria_available else ""),
            enabled=aria_available,
            description=(
                "Browse every file in the torrent and pick any subset. "
                "Downloads grab exactly what you pick; streams auto-skip non-video files."
            ),
        ))

    # --- Subtitle source (for streaming) ---
    if show_subtitles:
        import os as _os
        mode = (sub_choice or {}).get("mode", "auto")
        path = (sub_choice or {}).get("path")
        if mode == "auto":
            sub_label = "auto-detect from torrent"
        elif mode == "off":
            sub_label = "disabled"
        else:
            sub_label = f"file: {_os.path.basename(path) if path else '?'}"
        items.append(_section("Subtitles (for streaming)"))
        items.append(SelectItem(
            label=f"📝 Source: {sub_label}",
            value="set_subs",
            is_action=True,
            description=(
                "Choose how VLC gets subtitles: auto-detect inside the torrent, "
                "use an external .srt/.ass file, or disable subtitles."
            ),
        ))

    # --- Stream to VLC ---
    items.append(_section("Stream to VLC"))
    items.append(SelectItem(
        label="▶  webtorrent",
        value="stream_w",
        enabled=wt_available,
        hint=(
            "(not installed)" if not wt_available
            else f"plays {n_sel} episode(s) sequentially" if has_selection
            else "requires VLC installed"
        ),
        description="Stream via webtorrent — good streaming default",
    ))
    items.append(SelectItem(
        label="▶  peerflix",
        value="stream_p",
        enabled=pf_available,
        hint=(
            "(not installed)" if not pf_available
            else f"plays {n_sel} episode(s) sequentially" if has_selection
            else "requires VLC installed"
        ),
        description="Watch while downloading via VLC (peerflix) — try if webtorrent stalls or finds no peers",
    ))

    # --- Download ---
    items.append(_section("Download"))
    items.append(SelectItem(
        label="⬇  aria2c",
        value="aria",
        enabled=aria_available,
        hint=(
            "(not installed — https://aria2.github.io/)" if not aria_available
            else "fastest, multi-file in one process, won't seed - downloads only selected files"
        ),
        description="Best downloader — native multi-file, resumes, fastest for batches",
    ))
    items.append(SelectItem(
        label="⬇  webtorrent",
        value="d",
        enabled=wt_available,
        hint=(
            "(not installed)" if not wt_available
            else f"⚠  may ignore selection ({n_sel} picked) — can pull full torrent" if has_selection
            else "slower, won't seed"
        ),
        description=(
            "Plain download via webtorrent — one file per run, no seeding. "
            "⚠ --select is not strict; webtorrent-cli often downloads the whole torrent anyway. "
            "Use aria2c if you need strict file picking."
        ),
    ))
    items.append(SelectItem(
        label="⬇  peerflix",
        value="p",
        enabled=pf_available,
        hint=(
            "(not installed)" if not pf_available
            else f"⚠  ignores file selection ({n_sel} picked) — downloads full torrent" if has_selection
            else "slower, won't seed"
        ),
        description=(
            "Plain download via peerflix — slower than aria2, no seeding. "
            "⚠ Does NOT honor file selection: peerflix always downloads the whole torrent. "
            "Use aria2c if you need strict file picking."
        ),
    ))

    # --- Other ---
    items.append(_section("Other"))
    items.append(SelectItem(
        label=f"🧲 Open in {client_name}",
        value="t",
        hint=("⚠  uncheck unwanted files in the client's dialog" if has_selection else ""),
        description="Hand magnet to your desktop client — use to seed or manage in a GUI",
    ))
    items.append(SelectItem(
        label="📋 Copy magnet link",
        value="l",
        is_action=True,
        description="Copies the magnet URI to your clipboard",
    ))
    if show_subtitles:
        items.append(SelectItem(
            label="📝 Search & download subtitles",
            value="s",
            description="Find a matching .srt via OpenSubtitles and save it next to the video",
        ))

    # Persistent toggle: suppress subprocess UI (progress bars, peer lists) and
    # replace it with a single spinner line. Applies to all stream + download
    # paths on the next launch.
    from state import load_setting
    quiet_on = bool(load_setting("hide_stream_output", False))

    def _quiet_label(on: bool) -> str:
        return f"🔇 Quiet mode: [{'✓' if on else ' '}] {'ON' if on else 'OFF'}"

    items.append(SelectItem(
        label=_quiet_label(quiet_on),
        value="toggle_quiet",
        is_action=True,
        description=(
            "Hide the native progress UI of webtorrent/peerflix/aria2 and show "
            "a minimal spinner instead. Persists across runs."
        ),
    ))

    # --- Trailing actions ---
    items.append(SelectItem(
        label="↩  Go back to results",
        value="back",
        is_action=True,
        description="Return to the search results list",
    ))
    items.append(SelectItem(label="✕  Cancel", value=None, is_action=True))

    def handle_download_action(idx, items):
        if items[idx].value == "l" and magnet:
            try:
                import subprocess, platform
                if platform.system() == "Windows":
                    subprocess.run("clip", input=magnet.encode(), check=True)
                elif platform.system() == "Darwin":
                    subprocess.run("pbcopy", input=magnet.encode(), check=True)
                else:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=magnet.encode(), check=True)
                items[idx].hint = "✅ Copied!"
            except Exception:
                items[idx].hint = "⚠ Could not copy"
            return True  # Stay in menu
        if items[idx].value == "toggle_quiet":
            from state import load_setting, save_setting
            new_state = not bool(load_setting("hide_stream_output", False))
            save_setting("hide_stream_output", new_state)
            items[idx].label = _quiet_label(new_state)
            return True  # Stay in menu — arrow_select redraws in place, no flicker
        return False

    title = "Download Method"
    if has_selection:
        from torrent_meta import compact_ranges
        title = f"Download Method — {n_sel} episode(s) selected [{compact_ranges(selected_indexes)}]"

    idx = arrow_select(
        items,
        title=title,
        banner=_make_banner_panel(),
        on_action=handle_download_action,
    )

    if idx is None:
        return None

    return items[idx].value


def provider_select_prompt() -> object | None:
    """Prompt the user to select a torrent provider. Returns the provider object or None if cancelled.

    Press F on a highlighted provider to configure its filters without leaving the menu.
    Press H to browse search history.
    A "Network exposure info" action re-opens the security warning on demand.

    Returns:
        - A provider object for normal selection.
        - A ``("history", query, provider_obj)`` tuple when the user picks a history entry.
        - ``None`` if cancelled.
    """
    provider_items = [SelectItem(label=p.label, value=p) for p in PROVIDERS]
    separator = SelectItem(
        label="───────────────────",
        value="section_header",
        enabled=False,
        is_action=True,
    )
    info_item = SelectItem(
        label="🔒 Network exposure info",
        value="__network_info__",
        is_action=True,
    )
    items = provider_items + [separator, info_item]
    start = 0

    # Closure flag: set by key_action when F is pressed on a provider
    _filter_request = {"target": None}

    def _handle_f(cursor, items_list):
        target = items_list[cursor].value
        if isinstance(target, str):
            # Non-provider row (separator, network info) — silently ignore
            return True  # stay in menu, no flicker
        _filter_request["target"] = target
        return cursor  # exit menu to open filter_menu outside

    from ui.tips import random_tip

    while True:
        _filter_request["target"] = None

        # Fresh tip each time we enter the selector — but NOT on every render
        # (that would re-roll on every keypress and make the footer jitter).
        tip_line = random_tip()

        result = arrow_select(
            items,
            title="Select Provider",
            footer=(
                "↑/↓ navigate  •  Enter select  •  "
                "[bold yellow]F[/bold yellow] filters  •  "
                "[bold yellow]H[/bold yellow] history  •  "
                "[bold yellow]S[/bold yellow] stats  •  Esc cancel\n"
                f"   {tip_line}"
            ),
            banner=_make_banner_panel(),
            start_index=start,
            hotkeys={"H": "history", "h": "history", "S": "stats", "s": "stats"},
            key_actions={"F": _handle_f, "f": _handle_f},
        )

        if result is None:
            return None

        # F key pressed on a provider — open its filter menu
        if _filter_request["target"] is not None:
            filter_menu(_filter_request["target"])
            start = result  # result is the cursor index returned by key_action
            continue

        # H/S hotkeys — open history / stats
        if isinstance(result, tuple) and result[0] == "hotkey":
            _, action, cursor = result
            if action == "history":
                from ui.history import history_select_prompt
                pick = history_select_prompt()
                if pick:
                    query, prov_name = pick
                    from providers import get_provider
                    prov = get_provider(prov_name)
                    if prov:
                        return ("history", query, prov)
                start = cursor
                continue
            if action == "stats":
                from ui.stats import stats_page
                stats_page()
                start = cursor
                continue

        if items[result].value == "__network_info__":
            from security import show_security_warning
            show_security_warning(force=True)
            start = result
            continue

        return items[result].value


def search_again_prompt() -> str | tuple | None:
    """Prompt the user for what to do next after a download.

    Returns:
        - ``'search'`` to search again with the same provider.
        - ``'provider'`` to change provider.
        - ``("history", query, provider_obj)`` when the user picks a history entry.
        - ``None`` (exit).
    """
    items = [
        SelectItem(label="🔍 Search Again", value="search"),
        SelectItem(label="🔄 Change Provider", value="provider"),
        SelectItem(label="📜 Search History", value="history"),
        SelectItem(label="👋 Exit", value="exit"),
    ]

    from ui.tips import random_tip

    start = 0
    while True:
        # Fresh tip per menu entry, fixed across the render loop.
        tip_line = random_tip()
        idx = arrow_select(
            items,
            title="What's Next?",
            banner=_make_banner_panel(),
            start_index=start,
            footer=(
                "↑/↓ navigate  •  Enter select  •  Esc cancel\n"
                f"   {tip_line}"
            ),
        )

        if idx is None:
            return None

        selected = items[idx].value

        if selected == "history":
            from ui.history import history_select_prompt
            pick = history_select_prompt()
            if pick:
                query, prov_name = pick
                from providers import get_provider
                prov = get_provider(prov_name)
                if prov:
                    return ("history", query, prov)
            start = idx
            continue

        if selected == "exit":
            return None

        return selected
