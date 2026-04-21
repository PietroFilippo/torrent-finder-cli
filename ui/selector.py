"""Reusable arrow-key interactive selector using readchar + Rich."""

import sys
import time
from dataclasses import dataclass
from typing import Callable

import readchar
from rich.panel import Panel
from rich.text import Text

from constants import console
from utils import marquee


# Marquee timing
_MARQUEE_DWELL_S = 1.0      # delay before scrolling starts
_MARQUEE_RATE = 6           # chars/sec scroll speed
_TICK_INTERVAL_S = 0.12     # how often the watcher wakes up


@dataclass
class SelectItem:
    """A single item in the selector list."""
    label: str
    value: object = None
    enabled: bool = True
    toggled: bool = False
    hint: str = ""        # Dim subtext shown next to the label
    is_action: bool = False  # Action buttons: Enter returns instead of toggling
    description: str = ""  # Dim context-help shown above the footer when cursor on this item
    marker: str = ""      # Inline marker (e.g. 📍 for range-select anchor)


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


def _label_avail_width(item: "SelectItem", multi: bool) -> int:
    """Approximate visible chars available for the label of one item."""
    # Panel: 1 border + 2 padding on each side = 6 chars chrome.
    inner = max(20, console.size.width - 6)
    if multi and not item.is_action:
        prefix_len = 8   # "  ❯ [✓] "
    else:
        prefix_len = 4   # "  ❯ " or "    "
    hint_len = (2 + len(item.hint)) if item.hint else 0
    marker_len = (len(item.marker) + 1) if item.marker else 0
    return max(10, inner - prefix_len - hint_len - marker_len)


def _cursor_overflows(items: list["SelectItem"], cursor: int, multi: bool) -> bool:
    if not (0 <= cursor < len(items)):
        return False
    it = items[cursor]
    if it.is_action and (isinstance(it.value, str) and it.value == "section_header"):
        return False
    return len(it.label) > _label_avail_width(it, multi)


def _build_panel(
    items: list[SelectItem],
    cursor: int,
    title: str,
    multi: bool,
    footer: str = "",
    tick: int = 0,
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
    # + description line (2) + action rows at top/bottom of the list.
    chrome = 14 + main_start + (n - main_end)
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

        # Optional inline marker (anchor pin, etc.) — rendered before label
        if item.marker:
            body.append(f"{item.marker} ", style="bold yellow")

        # Marquee the cursor item's label when it overflows the panel.
        label_text = item.label
        if is_cursor and not is_section_header:
            avail = _label_avail_width(item, multi)
            label_text = marquee(item.label, avail, tick)
        body.append(label_text, style=style)

        # Show hint if present
        if item.hint:
            body.append(f"  {item.hint}", style="dim yellow")

        body.append("\n")

        if in_main and i == win_end - 1 and win_end < main_end:
            body.append(f"    … {main_end - win_end} more below\n", style="dim italic")

    # Context-help for current cursor item. Always renders (even blank) so
    # the footer doesn't jump when moving between described/undescribed rows.
    cur_item = items[cursor] if 0 <= cursor < len(items) else None
    desc = cur_item.description if cur_item else ""
    body.append("\n")
    body.append_text(Text.from_markup(f" {desc}" if desc else " ", style="dim italic"))
    body.append("\n")

    # Footer / help text
    if not footer:
        if multi:
            footer = "↑/↓ navigate  •  Enter toggle/select  •  Esc cancel"
        else:
            footer = "↑/↓ navigate  •  Enter select  •  Esc cancel"

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
    """Redraw inside the alternate screen buffer.

    Clears the viewport first (cheap inside an alt-screen) so a previous
    render that overflowed and scrolled can't leave ghost borders behind.
    """
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

    # Home + clear entire screen + write content. The 2J clear avoids
    # ghost borders when a prior render overflowed and scrolled the
    # viewport (which was leaving leftover top borders visible).
    sys.stdout.write("\033[H\033[2J" + content)
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
    key_actions: dict[str, Callable[[int, list[SelectItem]], object]] | None = None,
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

    # Shared state for resize watcher + marquee ticker
    state = {
        "cursor": cursor,
        "tick": 0,
        "cursor_changed_at": time.monotonic(),
    }
    stop_event = threading.Event()

    def watcher():
        prev_size = console.size
        last_cursor = state["cursor"]
        last_rendered_tick = -1
        while not stop_event.is_set():
            if stop_event.wait(_TICK_INTERVAL_S):
                break

            cur_size = console.size
            size_changed = cur_size != prev_size
            prev_size = cur_size

            # Reset marquee on cursor move
            if state["cursor"] != last_cursor:
                last_cursor = state["cursor"]
                state["cursor_changed_at"] = time.monotonic()
                state["tick"] = 0
                last_rendered_tick = -1

            elapsed = time.monotonic() - state["cursor_changed_at"]
            overflows = _cursor_overflows(items, state["cursor"], multi)

            new_tick = 0
            if overflows and elapsed > _MARQUEE_DWELL_S:
                new_tick = int((elapsed - _MARQUEE_DWELL_S) * _MARQUEE_RATE)

            need_redraw = size_changed or (overflows and new_tick != last_rendered_tick)
            if need_redraw:
                state["tick"] = new_tick
                last_rendered_tick = new_tick
                _render(banner, _build_panel(items, state["cursor"], title, multi, footer, tick=new_tick))

    # Enter alternate screen buffer + hide cursor + clear it
    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()

    watcher_thread = threading.Thread(target=watcher, daemon=True)
    watcher_thread.start()

    try:
        # Initial render
        _render(banner, _build_panel(items, cursor, title, multi, footer, tick=0))

        while True:
            key = readchar.readkey()
            prev_cursor = cursor

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
            elif key_actions and key in key_actions:
                outcome = key_actions[key](cursor, items)
                # bool True = stay; int = return that index; "jump:N" = move cursor
                if isinstance(outcome, bool):
                    pass  # stay and redraw
                elif isinstance(outcome, int):
                    return outcome
                elif isinstance(outcome, tuple) and len(outcome) == 2 and outcome[0] == "jump":
                    new = outcome[1]
                    if 0 <= new < len(items) and items[new].enabled:
                        cursor = new
                # else: no-op (None/other) — still redraw

            # Reset marquee state on cursor move
            if cursor != prev_cursor:
                state["tick"] = 0
                state["cursor_changed_at"] = time.monotonic()

            state["cursor"] = cursor
            _render(banner, _build_panel(items, cursor, title, multi, footer, tick=state["tick"]))

    finally:
        stop_event.set()
        watcher_thread.join(timeout=1)
        # Show cursor + exit alt screen + clear main screen — all in one write
        # to prevent any flash of stale content
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")
        sys.stdout.flush()

    return None
