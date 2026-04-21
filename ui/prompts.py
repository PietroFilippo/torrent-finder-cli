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
    items.append(SelectItem(label="Clear filters", value="clear", is_action=True))
    items.append(SelectItem(label="✅ Confirm", value="confirm", is_action=True))
    items.append(SelectItem(label="↩ Go Back", value="back", is_action=True))

    def handle_filter_action(idx, items):
        if items[idx].value == "clear":
            # Clear preset toggles only — leave engine toggles alone
            for pi in preset_indices:
                items[pi].toggled = False
            return True  # Stay in menu
        return False  # Exit for Confirm / Go Back

    # Start cursor on first enabled item (skip header)
    start = 1 if has_engines else 0

    result_idx = arrow_select(
        items,
        title=f"Filters — {provider.label}",
        multi=True,
        banner=_make_banner_panel(),
        on_action=handle_filter_action,
        start_index=start,
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


def episode_select_prompt(files: list) -> list[int] | None:
    """Multi-select menu for picking episodes from a torrent's file list.

    Takes a list of TorrentFile. Returns a list of 1-based indexes selected,
    or None if cancelled or nothing was picked.
    """
    import os
    from torrent_meta import extract_episode_number, format_size

    if not files:
        console.print("[warning] No files in torrent.[/warning]")
        return None

    items: list[SelectItem] = []
    file_item_indexes: list[int] = []
    for f in files:
        ep = extract_episode_number(f.name)
        ep_label = f"Ep {ep.rjust(3, '0') if ep.isdigit() else ep}" if ep else "      "
        label = f"{ep_label}  {os.path.basename(f.name)}"
        items.append(SelectItem(
            label=label,
            value=("file", f),
            toggled=False,
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

    selected = [items[i].value[1].index for i in file_item_indexes if items[i].toggled]
    return selected or None


def _make_banner_panel() -> Panel:
    """Return the app banner as a Rich Panel renderable."""
    banner = Text()
    banner.append("Torrent Search CLI", style="bold magenta")
    return Panel(
        banner,
        border_style="bright_blue",
        padding=(1, 2),
    )


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
) -> str | None:
    """
    Prompt the user to choose a download method.
    Returns 't', 'd', 'p', 'aria', 'stream_w', 'stream_p', 's', 'pick_episodes',
    'back', or None. 'l' (copy magnet) is handled internally.
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
        items.append(_section("Episode selection"))
        ep_label = (
            f"📺 Change selection ({n_sel} picked)"
            if has_selection
            else "📺 Pick specific episodes…"
        )
        items.append(SelectItem(
            label=ep_label,
            value="pick_episodes",
            is_action=True,
            hint=("requires aria2c to fetch file list" if not aria_available else ""),
            enabled=aria_available,
            description="Pick files from the torrent — downstream downloads grab only those",
        ))

    # --- Stream to VLC ---
    items.append(_section("Stream to VLC"))
    items.append(SelectItem(
        label="▶  peerflix",
        value="stream_p",
        enabled=pf_available,
        hint=(
            "(not installed)" if not pf_available
            else f"plays {n_sel} episode(s) sequentially" if has_selection
            else "requires VLC installed"
        ),
        description="Watch while downloading via VLC (peerflix) — good streaming default",
    ))
    items.append(SelectItem(
        label="▶  webtorrent",
        value="stream_w",
        enabled=wt_available,
        hint=(
            "(not installed)" if not wt_available
            else f"plays {n_sel} episode(s) sequentially" if has_selection
            else "requires VLC installed"
        ),
        description="Stream via webtorrent — try if peerflix stalls or finds no peers",
    ))

    # --- Download ---
    items.append(_section("Download"))
    items.append(SelectItem(
        label="⬇  aria2c",
        value="aria",
        enabled=aria_available,
        hint=(
            "(not installed — https://aria2.github.io/)" if not aria_available
            else "fastest, multi-file in one process, won't seed"
        ),
        description="Best downloader — native multi-file, resumes, fastest for batches",
    ))
    items.append(SelectItem(
        label="⬇  peerflix",
        value="p",
        enabled=pf_available,
        hint=(
            "(not installed)" if not pf_available
            else f"{n_sel} sequential session(s), won't seed" if has_selection
            else "slower, won't seed"
        ),
        description="Plain download via peerflix — slower than aria2, no seeding",
    ))
    items.append(SelectItem(
        label="⬇  webtorrent",
        value="d",
        enabled=wt_available,
        hint=(
            "(not installed)" if not wt_available
            else f"{n_sel} sequential session(s), won't seed" if has_selection
            else "slower, won't seed"
        ),
        description="Plain download via webtorrent — one file per run, no seeding",
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
    A "Network exposure info" action re-opens the security warning on demand.
    """
    provider_items = [SelectItem(label=p.label, value=p) for p in PROVIDERS]
    info_item = SelectItem(
        label="🔒 Network exposure info",
        value="__network_info__",
        is_action=True,
    )
    items = provider_items + [info_item]
    start = 0

    while True:
        result = arrow_select(
            items,
            title="Select Provider",
            footer=(
                "↑/↓ navigate  •  Enter select  •  "
                "[bold yellow]F[/bold yellow] configure filters  •  Esc cancel\n"
                "   Tip: For the best results, search using the complete name."
            ),
            banner=_make_banner_panel(),
            start_index=start,
            hotkeys={"F": "filter", "f": "filter"},
        )

        if result is None:
            return None

        if isinstance(result, tuple) and result[0] == "hotkey":
            _, action, cursor = result
            if action == "filter":
                target = items[cursor].value
                # Skip filter hotkey for the network-info action item
                if target != "__network_info__":
                    filter_menu(target)
                start = cursor
                continue

        if items[result].value == "__network_info__":
            from security import show_security_warning
            show_security_warning(force=True)
            start = result
            continue

        return items[result].value


def search_again_prompt() -> str | None:
    """Prompt the user for what to do next after a download.

    Returns 'search', 'provider', or None (exit).
    """
    items = [
        SelectItem(label="🔍 Search Again", value="search"),
        SelectItem(label="🔄 Change Provider", value="provider"),
        SelectItem(label="👋 Exit", value="exit"),
    ]

    idx = arrow_select(
        items,
        title="What's Next?",
        banner=_make_banner_panel(),
    )

    if idx is None:
        return None

    return items[idx].value
