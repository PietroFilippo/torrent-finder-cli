"""Reusable arrow-key interactive selector using readchar + Rich."""

import sys
import time
from dataclasses import dataclass
from typing import Callable

import readchar
from rich.cells import cell_len
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.ui.layout import ellipsize_cells, marquee_cells


# Marquee timing
_MARQUEE_DWELL_S = 1.0      # delay before scrolling starts
_MARQUEE_RATE = 6           # chars/sec scroll speed
_TICK_INTERVAL_S = 0.05     # how often the watcher wakes up


@dataclass
class _ResizeRedraw:
    """Track viewport changes that require an immediate coherent redraw."""

    size: object

    def observe(self, size: object) -> bool:
        if size == self.size:
            return False
        self.size = size
        return True


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
    passive: bool = False  # Navigable but Enter is a no-op (for read-only rows in a scroll view)
    # Named states are appended to preserve the positional constructor order
    # used by older SelectItem call sites.
    toggle_states: tuple[str, ...] = ()
    toggle_state: str = ""

    def __post_init__(self) -> None:
        if self.toggle_states and self.toggle_state not in self.toggle_states:
            self.toggle_state = self.toggle_states[0]

    def cycle_toggle(self) -> None:
        """Cycle a named state, or flip the legacy boolean checkbox."""
        if not self.toggle_states:
            self.toggled = not self.toggled
            return
        current = self.toggle_states.index(self.toggle_state)
        self.toggle_state = self.toggle_states[
            (current + 1) % len(self.toggle_states)
        ]


def _toggle_badge(item: "SelectItem") -> str:
    if item.toggle_states:
        return f"[{item.toggle_state}]"
    return f"[{'✓' if item.toggled else ' '}]"


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


def _inner_width() -> int:
    """Return usable selector content width after panel border and padding."""
    return max(8, console.size.width - 6)


def _inline_hint(item: "SelectItem") -> bool:
    """Keep short hints inline only when they leave useful label space."""
    inner = _inner_width()
    return (
        bool(item.hint)
        and console.size.width >= 72
        and cell_len(item.hint) + 2 <= inner // 2
    )


def _label_avail_width(item: "SelectItem", multi: bool) -> int:
    """Return terminal cells available for an item's one-line label."""
    if multi and not item.is_action:
        prefix_len = cell_len(f"  ❯ {_toggle_badge(item)} ")
    else:
        prefix_len = cell_len("  ❯ ")
    hint_len = cell_len(f"  {item.hint}") if _inline_hint(item) else 0
    marker_len = cell_len(f"{item.marker} ") if item.marker else 0
    return max(4, _inner_width() - prefix_len - hint_len - marker_len)


def _cursor_overflows(items: list["SelectItem"], cursor: int, multi: bool) -> bool:
    if not (0 <= cursor < len(items)):
        return False
    item = items[cursor]
    if isinstance(item.value, str) and item.value == "section_header":
        return False
    return cell_len(item.label) > _label_avail_width(item, multi)


def _wrapped_line_count(text: Text, width: int) -> int:
    """Count lines Rich will need for a wrapping text block."""
    return max(1, len(text.wrap(console, max(1, width), overflow="fold")))


def _build_panel(
    items: list[SelectItem],
    cursor: int,
    title: str,
    multi: bool,
    footer: str = "",
    tick: int = 0,
) -> Panel:
    """Render a height-windowed selector with responsive context text."""
    body = Text(no_wrap=True, overflow="ellipsis")
    has_actions = any(item.is_action for item in items)
    inner_width = _inner_width()

    if not footer:
        if multi:
            footer = "↑/↓ navigate  •  Enter toggle/select  •  Esc cancel"
        else:
            footer = "↑/↓ navigate  •  Enter select  •  Esc cancel"

    current_item = items[cursor] if 0 <= cursor < len(items) else None
    context_blocks: list[Text] = []
    if current_item and current_item.hint and not _inline_hint(current_item):
        context_blocks.append(
            Text(f" {current_item.hint}", style="dim yellow", overflow="fold")
        )
    if current_item and current_item.description:
        description = Text.from_markup(
            f" {current_item.description}", style="dim italic"
        )
        description.overflow = "fold"
        context_blocks.append(description)
    if not context_blocks:
        context_blocks.append(Text(" "))

    footer_text = Text.from_markup(f" {footer}", style="dim")
    footer_text.overflow = "fold"
    context_lines = sum(
        _wrapped_line_count(block, inner_width) for block in context_blocks
    )
    footer_lines = _wrapped_line_count(footer_text, inner_width)

    # Partition into leading actions, a windowed main list, and trailing actions.
    n = len(items)
    main_start = 0
    while main_start < n and items[main_start].is_action:
        main_start += 1
    main_end = n
    while main_end > main_start and items[main_end - 1].is_action:
        main_end -= 1
    main_len = main_end - main_start

    # Banner, panel borders/padding, indicators, context separator, and margin.
    always_visible_rows = main_start + (n - main_end)
    chrome = 11 + always_visible_rows + context_lines + footer_lines
    max_visible = max(1, console.size.height - chrome)

    win_start_rel, win_end_rel = _compute_window(
        main_len, cursor - main_start, max_visible
    )
    win_start = main_start + win_start_rel
    win_end = main_start + win_end_rel
    if cursor < main_start or cursor >= main_end:
        win_start_rel, win_end_rel = _compute_window(main_len, 0, max_visible)
        win_start = main_start + win_start_rel
        win_end = main_start + win_end_rel

    for i, item in enumerate(items):
        in_main = main_start <= i < main_end
        if in_main and not item.is_action and (i < win_start or i >= win_end):
            continue

        if in_main and i == win_start and win_start > main_start:
            body.append(
                f"    … {win_start - main_start} more above\n", style="dim italic"
            )

        is_cursor = i == cursor
        is_section_header = (
            not item.enabled
            and isinstance(item.value, str)
            and item.value == "section_header"
        )

        if multi and has_actions and item.is_action and not is_section_header:
            previous = items[i - 1] if i > 0 else None
            if previous and not previous.is_action:
                body.append(
                    "  " + "─" * max(1, inner_width - 2) + "\n", style="dim"
                )

        if is_section_header:
            body.append(
                "    " + ellipsize_cells(item.label, inner_width - 4) + "\n",
                style="dim bold",
            )
            continue

        if multi and not item.is_action:
            badge = _toggle_badge(item)
            prefix = f"  ❯ {badge} " if is_cursor else f"    {badge} "
        else:
            prefix = "  ❯ " if is_cursor else "    "

        if not item.enabled:
            style = "dim"
        elif is_cursor:
            style = "bold cyan"
        else:
            style = "white"

        body.append(prefix, style=style)
        if item.marker:
            body.append(f"{item.marker} ", style="bold yellow")

        available = _label_avail_width(item, multi)
        label = (
            marquee_cells(item.label, available, tick)
            if is_cursor
            else ellipsize_cells(item.label, available)
        )
        body.append(label, style=style)

        if _inline_hint(item):
            body.append(f"  {item.hint}", style="dim yellow")
        body.append("\n")

        if in_main and i == win_end - 1 and win_end < main_end:
            body.append(
                f"    … {main_end - win_end} more below\n", style="dim italic"
            )

    return Panel(
        Group(body, Text(""), *context_blocks, footer_text),
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


def _render(
    banner: object,
    panel: Panel,
    width: int | None = None,
    expected_size: object | None = None,
) -> bool:
    """Redraw inside the alternate screen buffer.

    Clears the viewport first (cheap inside an alt-screen) so a previous
    render that overflowed and scrolled can't leave ghost borders behind.
    """
    from io import StringIO
    from rich.console import Console as _Console

    # Pre-render all content into a string
    buf = StringIO()
    tmp = _Console(
        file=buf,
        width=width if width is not None else console.size.width,
        force_terminal=True,
    )
    if banner:
        tmp.print(banner)
        tmp.print()  # Blank line after banner
    tmp.print(panel)
    content = buf.getvalue()

    # Home + clear entire screen + write content. The 2J clear avoids
    # ghost borders when a prior render overflowed and scrolled the
    # viewport (which was leaving leftover top borders visible).
    if expected_size is not None and console.size != expected_size:
        return False
    sys.stdout.write("\033[H\033[2J" + content)
    sys.stdout.flush()
    return True


def _resolve(val):
    """If *val* is callable, call it; otherwise return it unchanged."""
    return val() if callable(val) else val


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

    *title* and *footer* may be strings **or callables** returning a string.
    Callables are re-evaluated on every render, allowing dynamic content
    (e.g. filter labels) without leaving the alt-screen.

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
    render_lock = threading.Lock()
    resize = _ResizeRedraw(console.size)

    def draw(tick: int) -> bool:
        """Write a complete frame only when it matches the current viewport."""
        with render_lock:
            for _ in range(3):
                frame_size = console.size
                panel = _build_panel(
                    items,
                    state["cursor"],
                    _resolve(title),
                    multi,
                    _resolve(footer),
                    tick=tick,
                )
                if _render(
                    banner,
                    panel,
                    width=frame_size.width,
                    expected_size=frame_size,
                ):
                    return True
            return False

    def watcher():
        last_cursor = state["cursor"]
        last_rendered_tick = -1
        while not stop_event.is_set():
            if stop_event.wait(_TICK_INTERVAL_S):
                break

            now = time.monotonic()
            size_changed = resize.observe(console.size)

            # Reset marquee on cursor move
            if state["cursor"] != last_cursor:
                last_cursor = state["cursor"]
                state["cursor_changed_at"] = now
                state["tick"] = 0
                last_rendered_tick = -1

            elapsed = now - state["cursor_changed_at"]
            overflows = _cursor_overflows(items, state["cursor"], multi)
            new_tick = 0
            if overflows and elapsed > _MARQUEE_DWELL_S:
                new_tick = int((elapsed - _MARQUEE_DWELL_S) * _MARQUEE_RATE)

            need_redraw = size_changed or (
                overflows and new_tick != last_rendered_tick
            )
            if need_redraw:
                state["tick"] = new_tick
                last_rendered_tick = new_tick
                draw(new_tick)

    # Enter alternate screen buffer + hide cursor + clear it
    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()

    watcher_thread = threading.Thread(target=watcher, daemon=True)
    watcher_thread.start()

    try:
        # Initial render
        draw(0)

        while True:
            try:
                key = readchar.readkey()
            except KeyboardInterrupt:
                # Some terminals raise for Ctrl+C instead of returning \x03.
                # Treat both forms exactly like Esc at the active selector.
                return None
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
                        # Toggle/cycle the item
                        if items[cursor].enabled:
                            items[cursor].cycle_toggle()
                else:
                    if items[cursor].enabled:
                        if items[cursor].passive:
                            pass  # Passive row: Enter is a no-op (scroll-view read-only)
                        elif items[cursor].is_action and on_action and on_action(cursor, items):
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
            draw(state["tick"])

    finally:
        stop_event.set()
        watcher_thread.join(timeout=1)
        # Show cursor + exit alt screen + clear main screen — all in one write
        # to prevent any flash of stale content
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")
        sys.stdout.flush()

    return None
