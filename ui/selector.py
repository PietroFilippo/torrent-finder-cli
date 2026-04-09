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


def _build_panel(
    items: list[SelectItem],
    cursor: int,
    title: str,
    multi: bool,
    footer: str = "",
) -> Panel:
    """Render the selector as a Rich Panel."""
    body = Text()
    has_actions = any(it.is_action for it in items)

    for i, item in enumerate(items):
        is_cursor = i == cursor

        # Insert separator before action buttons
        if multi and has_actions and item.is_action:
            prev = items[i - 1] if i > 0 else None
            if prev and not prev.is_action:
                body.append("  ─────────────────────────\n", style="dim")

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
            style = "dim strikethrough" if is_cursor else "dim"
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

    # Footer / help text
    if not footer:
        if multi:
            footer = "↑/↓ navigate  •  Enter toggle/select  •  Esc cancel"
        else:
            footer = "↑/↓ navigate  •  Enter select  •  Esc cancel"

    body.append("\n")
    body.append(f" {footer}", style="dim")

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
) -> int | list[int] | None:
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
