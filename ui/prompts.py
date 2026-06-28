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
from providers import PROVIDER_MENU, PROVIDERS, ProviderGroup
from ui.selector import SelectItem, arrow_select


# "Add another title" trigger for multi-line search entry. Ctrl+N on every
# platform: it's distinct from Enter everywhere, whereas Ctrl+J is LF ('\n') and
# would collide with Enter on POSIX — readchar leaves ICRNL set, so the Enter key
# arrives as '\n' there (see readchar's _posix_key.py: ENTER = LF).
_ADD_LINE_KEYS = {readchar.key.CTRL_N}
MULTI_ADD_KEY_LABEL = "Ctrl+N"


def get_query_with_shortcut(prompt_str: str, initial: str = "", history=None,
                            filters_shortcut: bool = False,
                            multi: bool = False) -> "str | tuple | list | None":
    """Read a search query with inline editing.

    With ``multi=True``, Ctrl+J commits the current line and starts another;
    Enter then returns the full ``list[str]`` of titles. Ctrl+F / Tab are
    suppressed once a title has been committed so the in-progress list isn't
    lost. Without ``multi`` the return is a single string, exactly as before.

    Returns the typed text, "GO_BACK" on Esc, or ``("ACTIONS", typed)`` when Tab
    is pressed — the caller opens the quick-actions menu and re-prompts with
    ``initial=typed`` so the in-progress query is preserved. With
    ``filters_shortcut=True``, Ctrl+F returns ``("FILTERS", typed)`` to jump
    straight to the filter menu. No single-letter shortcuts here: a search box
    must be able to start with any letter (Ctrl combos are safe — non-printable).

    ``history`` (this provider's past queries, newest first) enables shell-style
    recall: Up walks to older searches, Down back toward the in-progress line.
    """
    console.print(prompt_str, end="")
    buffer: list[str] = list(initial)
    pos = len(buffer)  # cursor index within buffer; physical cursor sits `pos` cols past the prompt
    if buffer:
        sys.stdout.write(''.join(buffer))
    sys.stdout.flush()

    def repaint(prev_col: int, prev_len: int) -> None:
        """Redraw the input after an edit, then park the cursor at `pos`.

        Uses only backspaces and spaces (no ANSI) so it behaves the same on
        every Windows console. `prev_col` is where the physical cursor was
        (always the old `pos`); `prev_len` is the old text length, so we know
        how many stale trailing chars to wipe when the text got shorter.
        """
        out = ['\b' * prev_col, ''.join(buffer)]
        extra = prev_len - len(buffer)
        if extra > 0:
            out.append(' ' * extra)      # paint over leftover chars
            out.append('\b' * extra)
        out.append('\b' * (len(buffer) - pos))  # back to the cursor
        sys.stdout.write(''.join(out))
        sys.stdout.flush()

    committed: list[str] = []  # multi mode: titles locked in with Ctrl+J

    hist = history or []
    hpos = -1   # -1 = editing the live line; 0.. = stepped into history (newest first)
    stash = ""  # the live line, stashed when first stepping into history

    def _recall(text: str) -> None:
        """Replace the whole buffer with `text`, cursor at end."""
        nonlocal pos
        prev_col, prev_len = pos, len(buffer)
        buffer[:] = list(text)
        pos = len(buffer)
        repaint(prev_col, prev_len)

    while True:
        key = readchar.readkey()

        if multi and key in _ADD_LINE_KEYS:
            # Add-another-title key (Ctrl+J on Windows / Ctrl+N anywhere): lock the
            # current title in and start a fresh line below.
            text = "".join(buffer).strip()
            if text:
                committed.append(text)
                print()
                console.print(prompt_str, end="")
                sys.stdout.flush()
                buffer[:] = []
                pos = 0
                hpos = -1
                stash = ""
            continue

        if key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
            print()
            if multi:
                text = "".join(buffer).strip()
                if text:
                    committed.append(text)
                return list(committed)
            return "".join(buffer)

        elif key == readchar.key.ESC:
            print()
            return "GO_BACK"

        elif key in (readchar.key.TAB, '\t'):
            if multi and committed:
                continue  # mid-multi-entry: don't lose the locked-in titles
            print()
            return ("ACTIONS", "".join(buffer))

        elif key == readchar.key.CTRL_F:
            # Quick filters jump. Always swallowed so the control char (\x06) is
            # never inserted into the query; only acts where it's enabled.
            if filters_shortcut:
                if multi and committed:
                    continue  # mid-multi-entry: keep the locked-in titles
                print()
                return ("FILTERS", "".join(buffer))

        elif key == readchar.key.LEFT:
            if pos > 0:
                pos -= 1
                sys.stdout.write('\b')
                sys.stdout.flush()

        elif key == readchar.key.RIGHT:
            if pos < len(buffer):
                sys.stdout.write(buffer[pos])  # reprint char to advance cursor
                pos += 1
                sys.stdout.flush()

        elif key == readchar.key.UP:
            # Walk to older searches (newest first). Stash the live line first.
            if hist and hpos < len(hist) - 1:
                if hpos == -1:
                    stash = "".join(buffer)
                hpos += 1
                _recall(hist[hpos])

        elif key == readchar.key.DOWN:
            # Walk back toward the live line; past the newest restores it.
            if hpos >= 0:
                hpos -= 1
                _recall(hist[hpos] if hpos >= 0 else stash)

        elif key == readchar.key.HOME or key == readchar.key.CTRL_A:
            if pos > 0:
                sys.stdout.write('\b' * pos)
                pos = 0
                sys.stdout.flush()

        elif key == readchar.key.END or key == readchar.key.CTRL_E:
            if pos < len(buffer):
                sys.stdout.write(''.join(buffer[pos:]))
                pos = len(buffer)
                sys.stdout.flush()

        elif key in (readchar.key.BACKSPACE, '\x08', '\x7f'):
            if pos > 0:
                prev_col, prev_len = pos, len(buffer)
                del buffer[pos - 1]
                pos -= 1
                repaint(prev_col, prev_len)

        elif key in (readchar.key.DELETE, readchar.key.SUPR):
            if pos < len(buffer):
                prev_col, prev_len = pos, len(buffer)
                del buffer[pos]
                repaint(prev_col, prev_len)

        elif key in (readchar.key.CTRL_C, '\x03'):
            raise KeyboardInterrupt

        elif key in (readchar.key.CTRL_D, '\x04'):
            raise EOFError

        elif len(key) == 1 and key >= ' ' and not key.startswith('\x1b') and not key.startswith('\x00') and not key.startswith('\xe0'):
            prev_col, prev_len = pos, len(buffer)
            buffer.insert(pos, key)
            pos += 1
            repaint(prev_col, prev_len)


def quick_actions_menu() -> "str | None":
    """Search-prompt quick actions, opened with Tab.

    Returns "filter", "history", "stats", "tips", or None if cancelled. The
    familiar F/H/S/T letters jump straight to each action; arrows + Enter also
    work. Lives behind Tab so it never clashes with typing a query.
    """
    items = [
        SelectItem(label="🔍 Filters & engines", value="filter", is_action=True, hint="F"),
        SelectItem(label="🕑 Search history", value="history", is_action=True, hint="H"),
        SelectItem(label="📊 Usage stats", value="stats", is_action=True, hint="S"),
        SelectItem(label="💡 Tips & shortcuts", value="tips", is_action=True, hint="T"),
        SelectItem(label="↩  Back", value=None, is_action=True),
    ]

    def _pick(index: int):
        return lambda cursor, items_list: index

    key_actions = {
        "F": _pick(0), "f": _pick(0),
        "H": _pick(1), "h": _pick(1),
        "S": _pick(2), "s": _pick(2),
        "T": _pick(3), "t": _pick(3),
    }
    idx = arrow_select(
        items,
        title="Quick actions",
        banner=_make_banner_panel(),
        footer="↑/↓ select  •  F / H / S / T jump  •  Esc back",
        key_actions=key_actions,
    )
    if idx is None:
        return None
    return items[idx].value


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
    from constants import get_download_dir

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

    # external — open file picker, listing recent subs from the effective
    # download dir (which may have been overridden by the user via the
    # "📁 Save to:" menu).
    dl_dir = get_download_dir()
    sub_files: list[tuple[str, str]] = []  # (label, abs_path)
    if os.path.isdir(dl_dir):
        try:
            entries = [
                (n, os.path.getmtime(os.path.join(dl_dir, n)))
                for n in os.listdir(dl_dir)
                if n.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"))
            ]
            entries.sort(key=lambda t: -t[1])
            for fname, _ in entries[:15]:
                sub_files.append((fname, os.path.join(dl_dir, fname)))
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


def download_dir_prompt() -> None:
    """Pick the default download directory. Persists via ``save_setting`` and
    returns to the caller — no return value. Applies to aria2, webtorrent /
    peerflix downloads, and subtitle saves (not streams or magnet handoff)."""
    import os
    from constants import DOWNLOADS_DIR
    from state import load_setting, save_setting

    home_downloads = os.path.expanduser("~/Downloads")
    current = load_setting("download_dir", None)

    items = [
        SelectItem(
            label=f"📂 Default ({os.path.basename(DOWNLOADS_DIR)}/)",
            value="__default__",
            description=f"Save into the project's downloads/ folder.\nPath: {DOWNLOADS_DIR}",
        ),
        SelectItem(
            label="🏠 ~/Downloads",
            value=home_downloads,
            description=f"Save into your user Downloads folder.\nPath: {home_downloads}",
        ),
        SelectItem(
            label="✍️  Type custom path…",
            value="__type__",
            is_action=True,
            description="Type or paste an absolute path. Will be created if it doesn't exist.",
        ),
        SelectItem(label="↩ Back", value="back", is_action=True),
    ]

    # Start cursor on the current selection when possible.
    start = 0
    if current == home_downloads:
        start = 1
    elif isinstance(current, str) and current.strip() and current != DOWNLOADS_DIR:
        start = 2

    result = arrow_select(
        items,
        title="Download Folder",
        banner=_make_banner_panel(),
        start_index=start,
    )

    if result is None:
        return
    chosen = items[result].value
    if chosen == "back":
        return

    if chosen == "__default__":
        save_setting("download_dir", None)
        return

    if chosen == "__type__":
        try:
            path = console.input("[info]Path to save downloads: [/info]").strip().strip('"').strip("'")
        except (EOFError, KeyboardInterrupt):
            return
        if not path:
            return
        path = os.path.abspath(os.path.expanduser(path))
    else:
        path = chosen

    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        console.print(f"[error] Could not create directory: {e}[/error]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return
    save_setting("download_dir", path)


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


def torrent_info_screen(result: dict) -> None:
    """Fetch and display origin details for a torrent in a scrollable view."""
    import textwrap
    from torrent_info import fetch_torrent_info

    with console.status("[bold cyan]Fetching torrent info…[/bold cyan]", spinner="dots"):
        info, err = fetch_torrent_info(result)

    if info is None:
        console.print(f"[warning]{err}[/warning]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return

    width = max(40, console.size.width - 12)
    rows: list[SelectItem] = []

    def add(text: str = "") -> None:
        rows.append(SelectItem(label=text, value="__line__", passive=True))

    def add_wrapped(text: str, indent: str = "    ") -> None:
        for para in text.splitlines() or [""]:
            for line in (textwrap.wrap(para, width) or [""]):
                add(indent + line)

    def field(lbl: str, val: str) -> None:
        if val:
            add(f"  {lbl}: {val}")

    field("Title", info.title)
    field("Category", info.category)
    field("Uploader", info.uploader)
    field("Date", info.date)
    if info.seeders or info.leechers:
        add(f"  Seeders / Leechers: {info.seeders or '?'} / {info.leechers or '?'}")
    field("Size", info.size)
    field("Info hash", info.info_hash)
    field("Embedded subs", info.embedded_subs)

    if info.description:
        add(); add("  ── Description ──")
        add_wrapped(info.description, indent="  ")

    if info.files:
        add(); add(f"  ── Files ({len(info.files)}) ──")
        for name, size in info.files:
            add(f"    {name}  ({size})" if size else f"    {name}")

    items = rows + [SelectItem(label="↩  Back", value="back", is_action=True)]
    arrow_select(
        items,
        title=f"ℹ Torrent info — {info.source}",
        banner=_make_banner_panel(),
        footer="↑/↓ scroll  •  Esc / Back to return",
    )


def download_method_prompt(
    magnet: str = "",
    show_subtitles: bool = True,
    show_episode_picker: bool = False,
    selected_indexes: list[int] | None = None,
    sub_choice: dict | None = None,
    show_streaming: bool = True,
    page_url: str | None = None,
    info_source: str | None = None,
) -> str | None:
    """
    Prompt the user to choose a download method.
    Returns 't', 'd', 'p', 'aria', 'stream_w', 'stream_p', 's', 'pick_episodes',
    'torrent_info', 'set_subs', 'back', 'cancel', or None (Esc). 'back' and Esc
    step back to the results table; 'cancel' (✕ Cancel) means "done with this
    torrent" → caller goes to what's next. 'l' (copy magnet) and 'open_page'
    (browser) are handled internally.
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

    # --- Torrent & files ---
    _info_available = info_source in ("Nyaa", "Apibay", "YTS")
    if show_episode_picker or _info_available:
        items.append(_section("Torrent & files"))
        if show_episode_picker:
            ep_label = (
                f"📂 Change selection ({n_sel} picked)"
                if has_selection
                else "📂 Browse torrent files… (Episode Selection, useful for animes/series)"
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
        if _info_available:
            items.append(SelectItem(
                label=f"ℹ  Torrent info (from {info_source})",
                value="torrent_info",
                is_action=True,
                description=(
                    "Fetch details from the source page: category, description, file "
                    "list, comments, and whether subtitles are embedded in the video."
                ),
            ))

    # --- Subtitle source (for streaming) ---
    if show_subtitles:
        import os as _os
        mode = (sub_choice or {}).get("mode", "auto")
        paths = (sub_choice or {}).get("paths")
        if not paths:
            _single = (sub_choice or {}).get("path")
            paths = [_single] if _single else []
        if mode == "auto":
            sub_label = "auto-detect from torrent"
        elif mode == "off":
            sub_label = "disabled"
        elif not paths:
            sub_label = "file: ?"
        elif len(paths) == 1:
            sub_label = f"file: {_os.path.basename(paths[0])}"
        else:
            sub_label = f"{len(paths)} tracks: {_os.path.basename(paths[0])} +{len(paths) - 1}"
        items.append(_section("Subtitles"))
        items.append(SelectItem(
            label=f"📝 Source: {sub_label}",
            value="set_subs",
            is_action=True,
            description=(
                "Choose how VLC gets subtitles when streaming: auto-detect inside "
                "the torrent, use an external .srt/.ass file, or disable subtitles."
            ),
        ))
        # Co-located with Source: searching downloads a .srt and auto-promotes it
        # to external source-mode, so the two subtitle rows belong together.
        items.append(SelectItem(
            label="📝 Search & download subtitles",
            value="s",
            description="Find a matching .srt via OpenSubtitles and save it next to the video",
        ))

    # --- Stream to VLC (hidden for non-video providers, e.g. Manga) ---
    if show_streaming:
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
    # "Open in client" leads the section and is the default-focused row (see
    # default_focus below): it's the only option that seeds and the natural
    # primary for non-streaming providers (games/software). The terminal
    # downloaders follow, aria2c first as the best of them.
    items.append(_section("Download"))
    default_focus = len(items)  # index of the row the cursor should start on
    items.append(SelectItem(
        label=f"🧲 Open in {client_name}",
        value="t",
        hint=("⚠  uncheck unwanted files in the client's dialog" if has_selection else ""),
        description="Hand magnet to your desktop client — use to seed or manage in a GUI",
    ))
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
            "⚠  --select is not strict; webtorrent-cli often downloads the whole torrent anyway. "
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
            "⚠  Does NOT honor file selection: peerflix always downloads the whole torrent. "
            "Use aria2c if you need strict file picking."
        ),
    ))

    # --- Other ---
    items.append(_section("Other"))
    items.append(SelectItem(
        label="📋 Copy magnet link",
        value="l",
        is_action=True,
        description="Copies the magnet URI to your clipboard",
    ))
    if page_url:
        from urllib.parse import urlparse as _urlparse
        _page_domain = _urlparse(page_url).netloc or page_url
        items.append(SelectItem(
            label="🌐 Open torrent page",
            value="open_page",
            is_action=True,
            hint=_page_domain,
            description=f"Open this torrent's page on its source site in your browser.\n{page_url}",
        ))

    # --- Settings (persistent across runs, unlike the one-shot actions above) ---
    items.append(_section("Settings"))

    # Persistent download-folder override. Applies to aria2/webtorrent/peerflix
    # downloads + subtitle saves (not streams, not magnet handoff).
    import os as _os_dir
    from constants import get_download_dir
    _dl_dir = get_download_dir()
    _dl_basename = _os_dir.path.basename(_dl_dir.rstrip(_os_dir.sep)) or _dl_dir
    items.append(SelectItem(
        label=f"📁 Save to: {_dl_basename}",
        value="set_download_dir",
        is_action=True,
        description=(
            f"Choose where non-magnet downloads + subtitles save to. "
            f"Default: the project's downloads/ folder.\nCurrent: {_dl_dir}"
        ),
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
    items.append(SelectItem(label="✕  Cancel", value="cancel", is_action=True))

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
                items[idx].hint = "⚠  Could not copy"
            return True  # Stay in menu
        if items[idx].value == "open_page" and page_url:
            try:
                import webbrowser
                webbrowser.open(page_url)
                items[idx].hint = "✅ Opened!"
            except Exception:
                items[idx].hint = "⚠  Could not open browser"
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
        start_index=default_focus,  # land on "Open in client" (the primary action)
    )

    if idx is None:
        return None

    return items[idx].value


def batch_download_menu(count: int, copyable: int) -> "str | None":
    """Reduced download menu for a multi-torrent selection.

    Only the actions that generalise across many *different* torrents: hand them
    all to the system client (it queues and downloads in parallel), or copy
    their magnets. Per-torrent actions (browse files, info, subtitles, stream)
    don't apply to a batch and are omitted — pick a single torrent for those.

    ``copyable`` is how many of the selected items actually have a magnet
    (Online-Fix has none); Copy is disabled when it's zero. Returns "open",
    "copy", "back", "cancel", or None (Esc — caller treats it as back).
    """
    from downloader import detect_torrent_client

    client = detect_torrent_client()
    copy_label = "📋 Copy all magnet links"
    if copyable != count:
        copy_label += f" ({copyable})"
    items = [
        SelectItem(
            label=f"🧲 Open all {count} in {client}",
            value="open",
            is_action=True,
            description=(
                "Hand every selected torrent to your desktop client at once — it "
                "queues and downloads them in parallel. Press Esc mid-run to stop."
            ),
        ),
        SelectItem(
            label=copy_label,
            value="copy",
            is_action=True,
            enabled=copyable > 0,
            hint=("" if copyable > 0 else "no magnet links in this selection"),
            description=(
                "Copy the magnets to your clipboard. Online-Fix entries have no "
                "magnet and are skipped; RuTracker links are resolved on demand."
            ),
        ),
        SelectItem(
            label="↩  Back to results",
            value="back",
            is_action=True,
            description="Return to the results list to change your selection.",
        ),
        SelectItem(label="✕  Cancel", value="cancel", is_action=True),
    ]

    idx = arrow_select(
        items,
        title=f"Batch download — {count} torrents",
        banner=_make_banner_panel(),
        start_index=0,
        footer="↑/↓ navigate  •  Enter select  •  Esc back to results",
    )
    if idx is None:
        return None
    return items[idx].value


# Credential metadata for the in-program manager. Each field is
# (env_var_name, prompt_label, is_secret); `category` groups them on the menu
# (entries are kept ordered by category so section headers fall in one place).
_CRED_PROVIDERS = [
    {
        "id": "opensubtitles",
        "category": "Subtitles",
        "icon": "🎬",
        "name": "OpenSubtitles.com",
        "fields": [
            ("OPENSUBTITLES_USERNAME", "Username", False),
            ("OPENSUBTITLES_PASSWORD", "Password", True),
            ("OPENSUBTITLES_APIKEY", "API key (optional, blank to skip)", True),
        ],
        "required": ["OPENSUBTITLES_USERNAME", "OPENSUBTITLES_PASSWORD"],
        "limit": "Free accounts have a small daily download limit; VIP raises it.",
    },
    {
        "id": "addic7ed",
        "category": "Subtitles",
        "icon": "📺",
        "name": "Addic7ed (TV series)",
        "fields": [
            ("ADDIC7ED_USERNAME", "Username", False),
            ("ADDIC7ED_PASSWORD", "Password", True),
        ],
        "required": ["ADDIC7ED_USERNAME", "ADDIC7ED_PASSWORD"],
        "limit": "Limits downloads per day (more with an account than anonymous).",
    },
    {
        "id": "jimaku",
        "category": "Subtitles",
        "icon": "🍙",
        "name": "Jimaku (anime)",
        "fields": [
            ("JIMAKU_API_KEY", "API key", True),
        ],
        "required": ["JIMAKU_API_KEY"],
        "limit": "",  # no notable daily limit
    },
    {
        "id": "rutracker",
        "category": "Search provider logins",
        "icon": "🧲",
        "name": "RuTracker",
        "fields": [
            ("RUTRACKER_USERNAME", "Username", False),
            ("RUTRACKER_PASSWORD", "Password", True),
        ],
        "required": ["RUTRACKER_USERNAME", "RUTRACKER_PASSWORD"],
        "limit": "Required — the RuTracker provider logs in to search and returns nothing without an account.",
    },
    {
        "id": "online_fix",
        "category": "Search provider logins",
        "icon": "🔧",
        "name": "Online-Fix",
        "fields": [
            ("ONLINE_FIX_USERNAME", "Username", False),
            ("ONLINE_FIX_PASSWORD", "Password", True),
        ],
        "required": ["ONLINE_FIX_USERNAME", "ONLINE_FIX_PASSWORD"],
        "limit": "Optional — Online-Fix search and download work without it; login is supported for completeness.",
    },
    {
        "id": "tmdb",
        "category": "Creator-search upgrades (optional)",
        "icon": "🎬",
        "name": "TMDB (Movies & Series — by director / studio)",
        "fields": [
            ("TMDB_API_KEY", "API key (v3)", True),
        ],
        "required": ["TMDB_API_KEY"],
        "limit": "Optional — Movies & Series 'by director / studio' works keyless via Wikidata; a free TMDB v3 API key upgrades it to richer results.",
        "howto": [
            "Create a free account at themoviedb.org",
            "Settings → API → Request an API key (choose Developer, accept the terms)",
            "Copy the “API Key (v3 auth)” and paste it below",
        ],
        "tip": "The form's Application URL can be anything valid — e.g. http://localhost",
    },
    {
        "id": "igdb",
        "category": "Creator-search upgrades (optional)",
        "icon": "🎮",
        "name": "IGDB (Games — by developer / publisher)",
        "fields": [
            ("IGDB_CLIENT_ID", "Twitch Client ID", False),
            ("IGDB_CLIENT_SECRET", "Twitch Client Secret", True),
        ],
        "required": ["IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET"],
        "limit": "Optional — Games 'by developer / publisher' works keyless via Wikidata; free Twitch/IGDB creds (dev.twitch.tv → register an app) upgrade it to richer results.",
        "howto": [
            "dev.twitch.tv/console → Applications → Register Your Application",
            "OAuth Redirect URL: http://localhost  •  Category: Application Integration",
            "Copy the Client ID, click New Secret, copy the Client Secret → paste below",
        ],
        "tip": "The Client Secret is shown only once — copy it before leaving the page",
    },
]


def _credentials_form(meta: dict, buffers: dict) -> dict | None:
    """Single-screen login form — edit every field inline, then Save.

    ``buffers`` maps env_key -> typed value and is mutated in place so values
    persist if the caller re-opens the form. Returns ``buffers`` on Save, or
    ``None`` on Esc / Cancel. Type to edit the focused field; Up/Down or Tab
    move between fields; Enter on a field jumps to the next; Enter on Save/Cancel
    finishes.
    """
    import credentials as C
    from rich.panel import Panel
    from rich.text import Text
    from ui.selector import _render

    fields = meta["fields"]
    n = len(fields)
    SAVE, CANCEL = n, n + 1
    focus = 0

    notes = []
    if meta["limit"]:
        notes.append(meta["limit"])
    if any(C.env_overrides(k) for k in meta["required"]):
        notes.append("Env var overrides the saved file")
    notes.append("Type to edit • ↑/↓ or Tab move • Enter on a field = next • Esc cancels")
    notes.append("Stored in plaintext in subtitle_credentials.json")
    footer = "  •  ".join(notes)

    def _field_text(env_key, label, secret, focused):
        buf = buffers.get(env_key, "")
        if focused:
            shown = ("*" * len(buf)) if secret else buf
            return f"{label}: {shown}█"  # block = text cursor (real cursor is hidden)
        if buf:
            return f"{label}: " + (("*" * len(buf)) if secret else buf)
        cur = C.get_credential(env_key)
        if cur:
            return f"{label}: " + (("*" * 8) if secret else cur) + "  (unchanged)"
        return f"{label}: not set"

    def _panel():
        body = Text()
        howto = meta.get("howto")
        if howto:
            body.append("  How to get this:\n", style="bold")
            for step_no, step in enumerate(howto, 1):
                body.append(f"   {step_no}. {step}\n", style="dim")
            tip = meta.get("tip")
            if tip:
                body.append(f"   💡 {tip}\n", style="yellow")
            body.append("  ─────────────────────────\n", style="dim")
        for i, (env_key, label, secret) in enumerate(fields):
            foc = focus == i
            sty = "bold cyan" if foc else "white"
            body.append("  ❯ " if foc else "    ", style=sty)
            body.append(_field_text(env_key, label, secret, foc), style=sty)
            body.append("\n")
        body.append("  ─────────────────────────\n", style="dim")
        for idx_btn, lbl in ((SAVE, "✅  Save"), (CANCEL, "↩  Cancel")):
            sty = "bold cyan" if focus == idx_btn else "white"
            body.append("  ❯ " if focus == idx_btn else "    ", style=sty)
            body.append(lbl, style=sty)
            body.append("\n")
        body.append("\n")
        body.append_text(Text.from_markup(f" {footer}", style="dim"))
        return Panel(
            body,
            title=f"[bold magenta]{meta['icon']} {meta['name']} — sign in[/bold magenta]",
            border_style="bright_blue",
            padding=(1, 2),
        )

    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")  # alt screen + hide cursor
    sys.stdout.flush()
    try:
        _render(_make_banner_panel(), _panel())
        while True:
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                return None
            if key == readchar.key.ESC:
                return None
            elif key == readchar.key.UP:
                focus = (focus - 1) % (n + 2)
            elif key in (readchar.key.DOWN, "\t"):
                focus = (focus + 1) % (n + 2)
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                if focus == CANCEL:
                    return None
                if focus == SAVE:
                    return buffers
                focus = (focus + 1) % (n + 2)  # field → jump to next row
            elif key in (readchar.key.BACKSPACE, "\x08", "\x7f"):
                if focus < n:
                    k = fields[focus][0]
                    if buffers.get(k):
                        buffers[k] = buffers[k][:-1]
            elif len(key) == 1 and not key.startswith(("\x1b", "\x00", "\xe0")):
                if focus < n:
                    k = fields[focus][0]
                    buffers[k] = buffers.get(k, "") + key
            _render(_make_banner_panel(), _panel())
    finally:
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")  # restore screen
        sys.stdout.flush()


def _inline_confirm(message: str, default: bool = False) -> bool:
    """Inline y/N confirmation printed in the current flow (no modal screen).

    The caller supplies its own answer hint in ``message``.
    """
    try:
        ans = console.input(f"[warning]{message}[/warning] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def _test_provider_credentials(provider_id: str, effective: dict) -> tuple[bool, str]:
    """Verify credentials against the live provider. Returns (ok, message)."""
    with console.status("[bold cyan]Verifying credentials…[/bold cyan]", spinner="dots"):
        if provider_id == "opensubtitles":
            from subtitles import test_opensubtitles
            return test_opensubtitles(
                effective["OPENSUBTITLES_USERNAME"],
                effective["OPENSUBTITLES_PASSWORD"],
                effective.get("OPENSUBTITLES_APIKEY"),
            )
        if provider_id == "addic7ed":
            from subtitles import test_addic7ed
            return test_addic7ed(
                effective["ADDIC7ED_USERNAME"], effective["ADDIC7ED_PASSWORD"]
            )
        if provider_id == "jimaku":
            from jimaku import validate_key
            return validate_key(effective["JIMAKU_API_KEY"])
        if provider_id == "rutracker":
            import rutracker
            return rutracker.test_credentials(
                effective["RUTRACKER_USERNAME"], effective["RUTRACKER_PASSWORD"]
            )
        if provider_id == "online_fix":
            import online_fix
            return online_fix.test_credentials(
                effective["ONLINE_FIX_USERNAME"], effective["ONLINE_FIX_PASSWORD"]
            )
        if provider_id == "tmdb":
            from resolvers import tmdb
            return tmdb.test_api_key(effective["TMDB_API_KEY"])
        if provider_id == "igdb":
            from resolvers import igdb
            return igdb.test_credentials(effective["IGDB_CLIENT_ID"], effective["IGDB_CLIENT_SECRET"])
    return False, "unknown provider"


def _finalize_credentials_save(meta: dict, entered: dict) -> bool:
    """Validate, verify, and save entered credentials.

    Returns True when the form is done (saved, or nothing to do), False to
    stay in the form (required field missing, or the user declined to save
    rejected credentials).
    """
    import credentials as C

    if not entered:
        # Nothing edited — don't verify (a blank form would fall back to the
        # env-shadowing values and report a misleading success).
        console.print("[dim]No changes entered — existing credentials kept, nothing saved.[/dim]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return True

    effective = {k: (entered.get(k) or C.get_credential(k)) for k, _, _ in meta["fields"]}
    missing = [k for k in meta["required"] if not effective.get(k)]
    if missing:
        labels = ", ".join(lbl for k, lbl, _ in meta["fields"] if k in missing)
        console.print(f"[warning]Required field(s) missing: {labels}.[/warning]")
        console.print("[dim]Press any key to continue...[/dim]")
        readchar.readkey()
        return False  # back to the form to fill them in

    ok, msg = _test_provider_credentials(meta["id"], effective)
    if ok is True:
        console.print(f"[success]✓ Verified: {msg}[/success]")
    elif ok is None:
        # Couldn't verify (rate limit / network / unverifiable provider).
        console.print(f"[warning]⚠  {msg}[/warning]")
    else:  # definitively rejected
        console.print(f"[error]✗ Verification failed: {msg}[/error]")
        if not _inline_confirm("Save these credentials anyway? — Y/Yes to save, anything else cancels:"):
            console.print("[warning]Not saved.[/warning]")
            console.print("[dim]Press any key to continue...[/dim]")
            readchar.readkey()
            return False  # back to the form

    C.save_credentials(entered)
    console.print(f"[success]Saved {meta['name']} credentials.[/success]")
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()
    return True


def _edit_provider_credentials(meta: dict) -> None:
    """Single-screen login form for one provider. Esc cancels and goes back."""
    buffers: dict = {}  # env_key -> typed value, kept across re-tries
    while True:
        result = _credentials_form(meta, buffers)
        if result is None:
            return  # Esc / Cancel
        entered = {k: v.strip() for k, v in result.items() if v.strip()}
        if _finalize_credentials_save(meta, entered):
            return
        # else: required field missing or save declined — reopen, values kept


def _view_field_label(env_key: str, label: str, secret: bool, revealed: bool) -> str:
    """Render one credential row for the view screen (plain text, no markup)."""
    import credentials as C
    val = C.get_credential(env_key)
    if not val:
        return f"{label}: not set"
    shown = val if (revealed or not secret) else "*" * 8
    src = {"env": "from environment", "file": "from file"}.get(C.credential_source(env_key), "")
    return f"{label}: {shown}" + (f"   [{src}]" if src else "")


def _view_provider_credentials(meta: dict) -> None:
    """Show a provider's current credentials, masking secrets with a reveal toggle."""
    fields = meta["fields"]
    state = {"revealed": False}

    def _toggle_label() -> str:
        return "🙈 Hide password / API key" if state["revealed"] else "👁  Show password / API key"

    items = [
        SelectItem(label=_view_field_label(k, lbl, sec, False), value=("field", k),
                   enabled=False, is_action=True)
        for k, lbl, sec in fields
    ]
    items.append(SelectItem(label="", value="__sep__", enabled=False, is_action=True))
    items.append(SelectItem(
        label=_toggle_label(), value="toggle", is_action=True,
        description="Reveal or hide the stored password / API key.",
    ))
    items.append(SelectItem(label="↩  Back", value="back", is_action=True))

    def on_action(idx, items_list):
        if items_list[idx].value == "toggle":
            state["revealed"] = not state["revealed"]
            for j, (k, lbl, sec) in enumerate(fields):
                items_list[j].label = _view_field_label(k, lbl, sec, state["revealed"])
            items_list[idx].label = _toggle_label()
            return True  # stay in menu — redraws in place
        return False

    arrow_select(
        items,
        title=f"{meta['icon']} {meta['name']} — stored credentials",
        banner=_make_banner_panel(),
        footer="Secrets are masked — pick Show password / API key to reveal.",
        on_action=on_action,
    )


def _manage_provider_credentials(meta: dict) -> None:
    """Per-provider sub-menu: view, enter/update, or clear stored credentials."""
    import credentials as C

    while True:
        # Offer Clear when credentials exist anywhere (file or environment), so
        # env-set users can clear the file and get told about the env override.
        has_creds = any(
            C.file_has(k) or C.env_overrides(k) for k, _, _ in meta["fields"]
        )
        sub_items = [
            SelectItem(label="👁  View credentials", value="view", is_action=True),
            SelectItem(label="✏  Enter / update credentials", value="edit", is_action=True),
        ]
        if has_creds:
            sub_items.append(SelectItem(label="🗑  Clear stored credentials", value="clear", is_action=True))
        sub_items.append(SelectItem(label="↩  Back", value="back", is_action=True))

        idx = arrow_select(sub_items, title=f"{meta['icon']} {meta['name']}", banner=_make_banner_panel())
        if idx is None:
            return
        action = sub_items[idx].value
        if action == "back":
            return
        if action == "view":
            _view_provider_credentials(meta)
        elif action == "edit":
            _edit_provider_credentials(meta)
        elif action == "clear":
            if confirm_prompt(f"Clear stored {meta['name']} credentials?"):
                C.save_credentials({k: None for k, _, _ in meta["fields"]})
                console.print(f"[success]Cleared {meta['name']} credentials from the file.[/success]")
                # Environment variables override the file and can't be removed
                # from here — tell the user exactly which still apply.
                shadow = [k for k, _, _ in meta["fields"] if C.env_overrides(k)]
                if shadow:
                    console.print(
                        "[warning]Still set via environment (overrides the file): "
                        + ", ".join(shadow) + ".[/warning]"
                    )
                    console.print("[dim]Unset those environment variables to fully remove them.[/dim]")
                console.print("[dim]Press any key to continue...[/dim]")
                readchar.readkey()
        # loop back to the sub-menu after any action


def credentials_menu() -> None:
    """Manage credentials, grouped by kind: subtitle providers, search-provider
    logins, and the optional TMDB/IGDB creator-search upgrades. Stored in the
    gitignored JSON."""
    import credentials as C

    while True:
        items = []
        last_cat = None
        for meta in _CRED_PROVIDERS:
            cat = meta.get("category", "Other")
            if cat != last_cat:
                items.append(SelectItem(
                    label=f"─── {cat} ───",
                    value="section_header",
                    enabled=False,
                    is_action=True,
                ))
                last_cat = cat
            configured = all(C.get_credential(k) for k in meta["required"])
            sources = {C.credential_source(k) for k in meta["required"]}
            if not configured:
                status = "not set"
            elif "env" in sources:
                status = "set via environment"
            else:
                status = "saved"
            # Labels/hints are rendered as literal text by the selector (no Rich
            # markup), so keep the status plain.
            items.append(SelectItem(
                label=f"{meta['icon']} {meta['name']}",
                value=meta,
                is_action=True,
                hint=status,
                description=(meta["limit"] or "No notable daily limit."),
            ))
        items.append(SelectItem(label="↩  Back", value="__back__", is_action=True))

        idx = arrow_select(
            items,
            title="Credentials",
            banner=_make_banner_panel(),
            footer="Stored in subtitle_credentials.json (gitignored, plaintext) — holds all of these. Env vars override the file.",
            start_index=1,  # land on the first entry, skipping the section header
        )
        if idx is None:
            return
        choice = items[idx].value
        if choice == "__back__":
            return
        _manage_provider_credentials(choice)


def _provider_group_menu(group) -> object | None:
    """Submenu for a provider group (e.g. Software → Desktop / Mobile / RuTracker).

    Returns the chosen child provider, or None to go back to the provider list.
    Mirrors the main screen: F opens a child's filter menu, Esc/Back returns None.
    """
    items = [
        SelectItem(label=p.label, value=p, description=getattr(p, "search_note", ""))
        for p in group.children
    ]
    items.append(SelectItem(label="↩  Back", value="__back__", is_action=True))

    _filter_request = {"target": None}

    def _handle_f(cursor, items_list):
        target = items_list[cursor].value
        if isinstance(target, str):
            return True  # the Back row — no filters
        _filter_request["target"] = target
        return cursor

    start = 0
    while True:
        _filter_request["target"] = None
        result = arrow_select(
            items,
            title=f"{group.icon} {group.name} — choose a source",
            footer=(
                "↑/↓ navigate  •  Enter select  •  "
                "[bold yellow]F[/bold yellow] filters  •  Esc back"
            ),
            banner=_make_banner_panel(),
            start_index=start,
            key_actions={"F": _handle_f, "f": _handle_f},
        )

        if result is None:
            return None

        if _filter_request["target"] is not None:
            filter_menu(_filter_request["target"])
            start = result
            continue

        chosen = items[result].value
        if chosen == "__back__":
            return None
        return chosen


def _provider_source_menu(provider, facets=None) -> "str | object | None":
    """Choose how to search a creator-capable provider.

    Shows normal keyword search up top, then one row per creator facet
    (director/studio/author/…) under a "By <labels>" section header. ``facets``
    is the already-credential-filtered list (falls back to all when omitted).
    Returns:
      - ``"search"`` for the normal keyword search,
      - a ``CreatorFacet`` to search by that facet,
      - ``None`` to go back to the provider list.
    """
    if facets is None:
        facets = list(getattr(provider, "creator_facets", []) or [])
    if not facets:
        return "search"

    items = [
        SelectItem(label="─── Search ───", value="section_header", enabled=False, is_action=True),
        SelectItem(
            label=f"{provider.icon} {provider.name} — keyword search",
            value="__search__",
            description="Type a query and search the enabled engines, as usual.",
        ),
    ]
    header = "By " + " / ".join(f.label for f in facets)
    items.append(SelectItem(label=f"─── {header} ───", value="section_header", enabled=False, is_action=True))
    for f in facets:
        items.append(SelectItem(
            label=f"{f.icon or '🎬'} By {f.label.lower()}",
            value=("facet", f),
            description=f.note,
        ))
    items.append(SelectItem(label="↩  Back", value="__back__", is_action=True))

    idx = arrow_select(
        items,
        title=f"{provider.icon} {provider.name} — choose how to search",
        banner=_make_banner_panel(),
        footer="↑/↓ navigate  •  Enter select  •  Esc back",
        start_index=1,  # land on the keyword-search row, skipping the header
    )
    if idx is None:
        return None
    val = items[idx].value
    if val == "__search__":
        return "search"
    if isinstance(val, tuple) and val and val[0] == "facet":
        return val[1]
    return None  # __back__


def provider_select_prompt(notice: str = "", open_group=None) -> object | None:
    """Prompt the user to select a torrent provider. Returns the provider object or None if cancelled.

    Press F on a highlighted provider to configure its filters without leaving the menu.
    Press H to browse search history.
    Press T to browse all tips and shortcuts.
    A "Network exposure info" action re-opens the security warning on demand.

    ``notice`` is an optional Rich-markup line (e.g. an "update available"
    banner) prepended to the footer; pass "" to show nothing.

    ``open_group`` (a ProviderGroup) jumps straight into that group's submenu —
    used by back-navigation from a group child so Esc returns to the source
    submenu (Esc in the submenu then falls through to the full provider list).

    Returns:
        - A provider object for normal selection.
        - A ``("history", entry)`` tuple when the user picks a history entry
          (the raw entry dict; main routes keyword vs creator).
        - ``None`` if cancelled.
    """
    if open_group is not None:
        chosen = _provider_group_menu(open_group)
        if chosen is not None:
            return chosen
        # backed out of the submenu → fall through to the full provider list

    provider_items = [
        SelectItem(label=p.label, value=p, description=getattr(p, "search_note", ""))
        for p in PROVIDER_MENU
    ]
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
    tips_item = SelectItem(
        label="💡 Tips & shortcuts",
        value="__tips__",
        is_action=True,
    )
    creds_item = SelectItem(
        label="🔑 Credentials — subtitles, provider logins, creator-search keys",
        value="__credentials__",
        is_action=True,
        description="Manage subtitle logins (OpenSubtitles / Addic7ed / Jimaku), search-provider logins (RuTracker / Online-Fix), and the optional TMDB / IGDB creator-search upgrades.",
    )
    items = provider_items + [separator, tips_item, info_item, creds_item]
    start = 0

    # Closure flag: set by key_action when F is pressed on a provider
    _filter_request = {"target": None}

    def _handle_f(cursor, items_list):
        target = items_list[cursor].value
        if isinstance(target, (str, ProviderGroup)):
            # Non-provider row (separator, network info) or a group (no filters
            # of its own — drill in with Enter instead) — silently ignore.
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
                (notice + "\n" if notice else "")
                + "↑/↓ navigate  •  Enter select  •  "
                "[bold yellow]F[/bold yellow] filters  •  "
                "[bold yellow]H[/bold yellow] history  •  "
                "[bold yellow]S[/bold yellow] stats  •  "
                "[bold yellow]T[/bold yellow] tips  •  Esc cancel\n\n"
                f"   {tip_line}"
            ),
            banner=_make_banner_panel(),
            start_index=start,
            hotkeys={
                "H": "history",
                "h": "history",
                "S": "stats",
                "s": "stats",
                "T": "tips",
                "t": "tips",
            },
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
                    return ("history", pick)  # entry dict — main routes keyword vs creator
                start = cursor
                continue
            if action == "stats":
                from ui.stats import stats_page
                stats_page()
                start = cursor
                continue
            if action == "tips":
                from ui.tips_page import tips_page
                tips_page()
                start = cursor
                continue

        if items[result].value == "__tips__":
            from ui.tips_page import tips_page
            tips_page()
            start = result
            continue

        if items[result].value == "__network_info__":
            from security import show_security_warning
            show_security_warning(force=True)
            start = result
            continue

        if items[result].value == "__credentials__":
            credentials_menu()
            start = result
            continue

        # A group row — drill into its submenu. Picking a child returns it to
        # the caller; backing out stays on the provider screen.
        if isinstance(items[result].value, ProviderGroup):
            chosen = _provider_group_menu(items[result].value)
            if chosen is None:
                start = result
                continue
            return chosen

        return items[result].value


def search_again_prompt() -> str | tuple | None:
    """Prompt the user for what to do next after a download.

    Returns:
        - ``'search'`` to search again with the same provider.
        - ``'provider'`` to change provider.
        - ``("history", entry)`` when the user picks a history entry (raw entry dict).
        - ``None`` (exit).
    """
    items = [
        SelectItem(label="🔍 Search Again", value="search"),
        SelectItem(label="🔄 Change Provider", value="provider"),
        SelectItem(label="📜 Search History", value="history"),
        SelectItem(label="📊 Usage Stats", value="stats"),
        SelectItem(label="💡 Tips & shortcuts", value="tips"),
        SelectItem(label="🔑 Credentials", value="credentials"),
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
                "↑/↓ navigate  •  Enter select  •  Esc cancel\n\n"
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
                return ("history", pick)  # entry dict — main routes keyword vs creator
            start = idx
            continue

        if selected == "stats":
            from ui.stats import stats_page
            stats_page()
            start = idx
            continue

        if selected == "tips":
            from ui.tips_page import tips_page
            tips_page()
            start = idx
            continue

        if selected == "credentials":
            credentials_menu()
            start = idx
            continue

        if selected == "exit":
            return None

        return selected
