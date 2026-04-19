"""Reusable arrow-key interactive selector using readchar + Rich."""

import sys
from dataclasses import dataclass, field
from typing import Callable

import readchar
from rich.panel import Panel
from rich.text import Text

from constants import console


@dataclass
class SelectItem:
    """A single item in the selector list."""
    label: str
    value: object = None
    enabled: bool = True
    toggled: bool = False
    hint: str = ""        # Dim subtext shown next to the label
    is_action: bool = False  # Action buttons: Enter returns instead of toggling


def _compute_window(n: int, cursor: int, max_visible: int) -> tuple[int, int]:
    """Return [start, end) indexes for a window that fits max_visible rows.

    The window keeps the cursor in view; it never slides past the list ends.
    """
    if n <= max_visible:
        return 0, n
    half = max_visible // 2
    start = max(0, cursor - half)
    end = start + max_visible
    if end > n:
        end = n
        start = end - max_visible
    return start, end


def _build_panel(
    items: list[SelectItem],
    cursor: int,
    title: str,
    multi: bool,
    footer: str = "",
) -> Panel:
    """Render the selector as a Rich Panel.

    When the item list is too tall for the terminal, the main (non-action)
    section is windowed around the cursor. Action buttons (Confirm/Cancel/
    Select all, etc.) always render so they can't be scrolled out of reach.
    """
    body = Text()
    has_actions = any(it.is_action for it in items)

    # Partition into [leading actions … main items … trailing actions].
    # Leading section headers count as "actions" (always visible).
    # Only the main list gets windowed.
    n = len(items)
    main_start = 0
    while main_start < n and items[main_start].is_action:
        main_start += 1
    main_end = n
    while main_end > main_start and items[main_end - 1].is_action:
        main_end -= 1
    main_len = main_end - main_start

    # Reserve chrome: banner (~4) + panel borders (4) + padding (2) + footer (2)
    # + action rows at top/bottom of the list.
    chrome = 12 + main_start + (n - main_end)
    max_visible = max(6, console.size.height - chrome)

    win_start_rel, win_end_rel = _compute_window(main_len, cursor - main_start, max_visible)
    win_start = main_start + win_start_rel
    win_end = main_start + win_end_rel

    # If cursor is outside the main list (on an action button), clamp window
    # so we still show a sensible slice of the main list.
    if cursor < main_start or cursor >= main_end:
        win_start_rel, win_end_rel = _compute_window(main_len, 0, max_visible)
        win_start = main_start + win_start_rel
        win_end = main_start + win_end_rel

    for i, item in enumerate(items):
        in_main = main_start <= i < main_end
        # Interspersed action rows (section headers, mid-list actions) always
        # render — only regular list items get windowed out.
        if in_main and not item.is_action and (i < win_start or i >= win_end):
            continue

        if in_main and i == win_start and win_start > main_start:
            body.append(f"    … {win_start - main_start} more above\n", style="dim italic")

        is_cursor = i == cursor

        # Check if this is a section header (visual-only, non-interactive)
        is_section_header = (
            item.is_action and not item.enabled
            and isinstance(item.value, str) and item.value == "section_header"
        )

        # Insert separator before action buttons (but not section headers)
        if multi and has_actions and item.is_action and not is_section_header:
            prev = items[i - 1] if i > 0 else None
            if prev and not prev.is_action:
                body.append("  ─────────────────────────\n", style="dim")

        # Section headers render as dim labels
        if is_section_header:
            body.append(f"    {item.label}\n", style="dim bold")
            continue

        # Build the prefix
        if multi and not item.is_action:
            check = "✓" if item.toggled else " "
            if is_cursor:
                prefix = f"  ❯ [{check}] "
            else:
                prefix = f"    [{check}] "
        else:
            if is_cursor:
                prefix = "  ❯ "
            else:
                prefix = "    "

        # Determine style
        if not item.enabled:
            style = "dim"
        elif is_cursor:
            style = "bold cyan"
        else:
            style = "white"

        body.append(prefix, style=style)
        body.append(item.label, style=style)

        # Show hint if present
        if item.hint:
            body.append(f"  {item.hint}", style="dim yellow")

        body.append("\n")

        if in_main and i == win_end - 1 and win_end < main_end:
            body.append(f"    … {main_end - win_end} more below\n", style="dim italic")

    # Footer / help text
    if not footer:
        if multi:
            footer = "↑/↓ navigate  •  Enter toggle/select  •  Esc cancel"
        else:
            footer = "↑/↓ navigate  •  Enter select  •  Esc cancel"

    body.append("\n")
    body.append_text(Text.from_markup(f" {footer}", style="dim"))

    return Panel(
        body,
        title=f"[bold magenta]{title}[/bold magenta]",
        border_style="bright_blue",
        padding=(1, 2),
    )


def _next_enabled(items: list[SelectItem], current: int, direction: int) -> int:
    """Move to the next enabled item in the given direction, wrapping around."""
    n = len(items)
    pos = current
    for _ in range(n):
        pos = (pos + direction) % n
        if items[pos].enabled:
            return pos
    return current  # All disabled — stay put


def _render(banner: object, panel: Panel) -> None:
    """Redraw inside the alternate screen buffer — home, print, clear rest."""
    from io import StringIO
    from rich.console import Console as _Console

    # Pre-render all content into a string
    buf = StringIO()
    tmp = _Console(file=buf, width=console.size.width, force_terminal=True)
    if banner:
        tmp.print(banner)
        tmp.print()  # Blank line after banner
    tmp.print(panel)
    content = buf.getvalue()

    # Move to home, write content, clear anything below
    sys.stdout.write("\033[H" + content + "\033[J")
    sys.stdout.flush()


def arrow_select(
    items: list[SelectItem],
    title: str = "Select",
    multi: bool = False,
    footer: str = "",
    start_index: int = 0,
    banner: object = None,
    on_action: Callable[[int, list[SelectItem]], bool] | None = None,
    hotkeys: dict[str, str] | None = None,
) -> int | list[int] | tuple | None:
    """Interactive arrow-key selector.

    Uses the terminal's alternate screen buffer for a clean, flicker-free
    experience. The original screen content is restored when done.

    Args:
        items: List of SelectItem to display.
        title: Panel title.
        multi: If True, enables toggle mode with checkboxes.
               Enter on regular items toggles them.
               Enter on action items (is_action=True) returns that index.
               The caller reads items[i].toggled to see what was toggled.
               If False, Enter returns the index of the highlighted item.
        footer: Custom footer text (overrides default).
        start_index: Initial cursor position.
        banner: Optional Rich renderable displayed above the panel.
        on_action: Optional callback for action items. Called with
                   (index, items). Return True to stay in the menu,
                   False to exit and return the index.

    Returns:
        - Single-select mode: index of chosen item, or None if cancelled.
        - Multi-toggle mode: index of the action item that was selected,
          or None if cancelled. Read items[i].toggled for toggle state.
    """
    import threading

    if not items:
        return None

    # Ensure cursor starts on an enabled item
    cursor = start_index
    if not items[cursor].enabled:
        cursor = _next_enabled(items, cursor, 1)

    # Shared state for resize watcher
    state = {"cursor": cursor}
    stop_event = threading.Event()

    def resize_watcher():
        prev_size = console.size
        while not stop_event.is_set():
            stop_event.wait(0.25)
            cur_size = console.size
            if cur_size != prev_size:
                prev_size = cur_size
                _render(banner, _build_panel(items, state["cursor"], title, multi, footer))

    # Enter alternate screen buffer + hide cursor
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()

    watcher = threading.Thread(target=resize_watcher, daemon=True)
    watcher.start()

    try:
        # Initial render
        _render(banner, _build_panel(items, cursor, title, multi, footer))

        while True:
            key = readchar.readkey()

            if key == readchar.key.UP:
                cursor = _next_enabled(items, cursor, -1)
            elif key == readchar.key.DOWN:
                cursor = _next_enabled(items, cursor, 1)
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                if multi:
                    if items[cursor].is_action:
                        # Check if callback wants us to stay
                        if on_action and on_action(cursor, items):
                            pass  # Stay in the menu
                        else:
                            return cursor
                    else:
                        # Toggle the item
                        if items[cursor].enabled:
                            items[cursor].toggled = not items[cursor].toggled
                else:
                    if items[cursor].enabled:
                        # Check if callback wants us to stay
                        if items[cursor].is_action and on_action and on_action(cursor, items):
                            pass  # Stay in the menu
                        else:
                            return cursor
            elif key == readchar.key.ESC:
                return None
            elif key in (readchar.key.CTRL_C, "\x03"):
                return None
            elif hotkeys and key in hotkeys:
                return ("hotkey", hotkeys[key], cursor)

            state["cursor"] = cursor
            _render(banner, _build_panel(items, cursor, title, multi, footer))

    finally:
        stop_event.set()
        watcher.join(timeout=1)
        # Show cursor + exit alt screen + clear main screen — all in one write
        # to prevent any flash of stale content
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")
        sys.stdout.flush()

    return None
