"""Reusable arrow-key interactive selector using readchar + Rich."""

import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import readchar
from rich.cells import cell_len
from rich.console import Group
from rich.text import Text

from torrent_finder.constants import buffer_console, console
from torrent_finder.ui import theme
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
    """A single item in the selector list.

    *label* and *hint* are plain strings, or ``Text`` when parts of them carry
    their own colours (a state word, a bar, a matched prefix).
    """
    label: "str | Text"
    value: object = None
    enabled: bool = True
    toggled: bool = False
    hint: "str | Text" = ""  # Subtext beside the label (steel, or key-styled for shortcut letters)
    is_action: bool = False  # Action buttons: Enter returns instead of toggling
    description: str = ""  # Context help shown above the footer when the cursor is on this item
    marker: str = ""      # Inline marker (e.g. theme.MARKER for a range-select anchor)
    passive: bool = False  # Navigable but Enter is a no-op (for read-only rows in a scroll view)
    # Named states are appended to preserve the positional constructor order
    # used by older SelectItem call sites.
    toggle_states: tuple[str, ...] = ()
    toggle_state: str = ""
    marker_style: str = ""  # the marker's colour; the accent when empty

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


def _plain(value: "str | Text") -> str:
    return value.plain if isinstance(value, Text) else str(value)


def _hint_text(item: "SelectItem") -> Text:
    """The hint as drawn: its own colours, else key-styled for shortcut letters, else steel."""
    if isinstance(item.hint, Text):
        hint = item.hint.copy()
        hint.stylize_before(theme.MUTED)
        return hint
    return Text(item.hint, style=theme.KEY if theme.is_key(item.hint) else theme.MUTED)


def _toggle_badge(item: "SelectItem") -> str:
    """The state shown before a multi-select label: a named state or a check mark."""
    if item.toggle_states:
        return item.toggle_state
    return theme.CHECK if item.toggled else theme.UNCHECKED


def _is_section_header(item: "SelectItem") -> bool:
    return not item.enabled and isinstance(item.value, str) and item.value == "section_header"


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


# Rows below this height drop the spacer lines around the list.
_COMPACT_HEIGHT = 20
_GUTTER = 2  # cursor bar + space


def _inner_width() -> int:
    """Usable content width inside the left and right margins."""
    return theme.inner_width(console.size.width)


def _inline_hint(item: "SelectItem") -> bool:
    """Keep short hints inline only when they leave useful label space."""
    inner = _inner_width()
    hint = _plain(item.hint)
    return (
        bool(hint)
        and console.size.width >= 72
        and cell_len(hint) + 2 <= inner // 2
    )


def _badge_width(items: list["SelectItem"]) -> int:
    """One width for every state badge in the list, so labels line up."""
    widths = [cell_len(state) for item in items for state in item.toggle_states]
    return max(widths, default=1)


def _prefix_width(item: "SelectItem", multi: bool, badge_width: int) -> int:
    width = _GUTTER
    if multi and not item.is_action:
        width += badge_width + 1
    if item.marker:
        width += cell_len(item.marker) + 1
    return width


@dataclass(frozen=True)
class _Geometry:
    badge_width: int
    # Item index -> cell where the label area ends, for rows whose inline hints line up.
    hint_columns: dict = field(default_factory=dict)


def _geometry(items: list["SelectItem"], multi: bool) -> _Geometry:
    """Line hints up within each run of consecutive rows that show one inline.

    A lone hinted row keeps its hint beside the label instead of joining a
    column set by unrelated rows further down the menu.
    """
    badge_width = _badge_width(items) if multi else 1
    columns: dict[int, int] = {}
    run: list[int] = []

    def close_run() -> None:
        if len(run) >= 2:
            hinted = [items[i] for i in run]
            label_width = max(cell_len(_plain(item.label)) for item in hinted)
            hint_width = max(cell_len(_plain(item.hint)) for item in hinted)
            prefix = max(_prefix_width(item, multi, badge_width) for item in hinted)
            if prefix + label_width + 2 + hint_width <= _inner_width():
                # An absolute column, so a row with a marker still lines up.
                columns.update((i, prefix + label_width) for i in run)
        run.clear()

    for index, item in enumerate(items):
        if _inline_hint(item) and not _is_section_header(item):
            run.append(index)
        else:
            close_run()
    close_run()
    return _Geometry(badge_width, columns)


def _label_avail_width(item: "SelectItem", multi: bool, geometry: _Geometry | None = None) -> int:
    """Return terminal cells available for an item's one-line label."""
    geometry = geometry or _Geometry(1)
    available = _inner_width() - _prefix_width(item, multi, geometry.badge_width)
    if _inline_hint(item):
        available -= cell_len(_plain(item.hint)) + 2
    return max(4, available)


def _cursor_overflows(items: list["SelectItem"], cursor: int, multi: bool) -> bool:
    if not (0 <= cursor < len(items)):
        return False
    item = items[cursor]
    if _is_section_header(item):
        return False
    return cell_len(_plain(item.label)) > _label_avail_width(item, multi, _geometry(items, multi))


def _wrapped_line_count(text: Text, width: int) -> int:
    """Count lines Rich will need for a wrapping text block."""
    return max(1, len(text.wrap(console, max(1, width), overflow="fold")))


def _clip_lines(blocks: list[Text], limit: int, width: int) -> Text:
    """The first *limit* wrapped lines of *blocks*, ending in "…" when cut."""
    lines = [line for block in blocks for line in block.wrap(console, max(1, width), overflow="fold")]
    kept = lines[:limit]
    if len(lines) > limit and kept:
        kept[-1].truncate(max(1, width - 1))
        kept[-1].append("…")
    return Text("\n").join(kept)


def _default_footer(multi: bool) -> str:
    if multi:
        return "↑/↓ navigate  •  Enter toggle/select  •  Esc cancel"
    return "↑/↓ navigate  •  Enter select  •  Esc cancel"


def _row(item: "SelectItem", index: int, is_cursor: bool, multi: bool, geometry: _Geometry, tick: int) -> Text:
    """One selectable row: margin, cursor bar, state, marker, label, inline hint."""
    row = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    row.append(theme.CURSOR if is_cursor else " ", style=theme.ACCENT)
    row.append(" ")
    if multi and not item.is_action:
        badge = _toggle_badge(item)
        if item.toggle_states:
            badge_style = theme.state_style(badge)
        else:
            badge_style = theme.GOOD if item.toggled else theme.MUTED
        row.append(badge, style=badge_style if item.enabled else theme.MUTED)
        row.append(" " * (geometry.badge_width - cell_len(badge) + 1))
    if item.marker:
        row.append(f"{item.marker} ", style=item.marker_style or theme.ACCENT)

    if not item.enabled:
        style = theme.MUTED
    elif is_cursor:
        style = theme.FOCUS
    else:
        style = ""
    available = _label_avail_width(item, multi, geometry)
    plain_label = _plain(item.label)
    if is_cursor and cell_len(plain_label) > available:
        label = Text(marquee_cells(plain_label, available, tick), style=style)
    elif isinstance(item.label, Text):
        label = item.label.copy()
        label.stylize_before(style)  # the label's own colours win over the row's
        if cell_len(label.plain) > available:
            label.truncate(available, overflow="ellipsis")
    else:
        label = Text(ellipsize_cells(plain_label, available), style=style)
    row.append_text(label)
    if _inline_hint(item):
        column = geometry.hint_columns.get(index)
        if column is not None:
            prefix = _prefix_width(item, multi, geometry.badge_width)
            row.append(" " * max(0, min(column, prefix + available) - prefix - cell_len(label.plain)))
        row.append("  ")
        row.append_text(_hint_text(item))  # its own colours, keys as keys, else steel
    if is_cursor and theme.FILL_FOCUS and item.enabled:
        # Filled-row focus: tint from the cursor bar to the right margin.
        end = max(cell_len(row.plain), console.size.width - len(theme.MARGIN))
        row.append(" " * (end - cell_len(row.plain)))
        row.stylize(f"on {theme.FILL}", len(theme.MARGIN), len(row.plain))
    return row


def _build_panel(
    items: list[SelectItem],
    cursor: int,
    title: str,
    multi: bool,
    footer: str = "",
    tick: int = 0,
    status: str = "",
    alert: str = "",
    intro: "str | Text" = "",
    help_key: bool = False,
) -> Group:
    """Render one complete selector frame: header, intro, windowed list, context, keys, alert.

    *intro* is a short summary under the header (what the screen is about);
    *help_key* adds "? keys" to the key bar when it fits on the lines the
    keys already take.

    Every selectable row stays one physical line so the window is stable;
    descriptions, notices and the key bar wrap and are measured, and the list
    gets whatever height is left.
    """
    width = console.size.width
    height = console.size.height
    inner_width = _inner_width()
    compact = not theme.roomy(height, _COMPACT_HEIGHT)
    has_actions = any(item.is_action for item in items)
    geometry = _geometry(items, multi)

    parsed = theme.parse_footer(footer or _default_footer(multi))
    keys = parsed.keys or theme.parse_footer(_default_footer(multi)).keys

    current_item = items[cursor] if 0 <= cursor < len(items) else None
    item_blocks: list[Text] = []
    if current_item and _plain(current_item.hint) and not _inline_hint(current_item):
        hint = _hint_text(current_item)
        hint.overflow = "fold"
        item_blocks.append(hint)
    if current_item and current_item.description:
        description = Text.from_markup(current_item.description)
        description.overflow = "fold"
        item_blocks.append(description)
    item_lines = sum(_wrapped_line_count(block, inner_width) for block in item_blocks)
    notice_lines = sum(_wrapped_line_count(block, inner_width) for block in parsed.context)
    # A transient message (the quit guard) is the last line, under the key bar.
    alert_lines = theme.wrap_block(Text.from_markup(alert), width, console) if alert else []
    intro_text = (intro.copy() if isinstance(intro, Text) else Text.from_markup(intro)) if intro else Text()
    intro_lines = theme.wrap_block(intro_text, width, console) if intro_text.plain.strip() else []

    # Partition into leading actions, a windowed main list, and trailing actions.
    n = len(items)
    main_start = 0
    while main_start < n and items[main_start].is_action:
        main_start += 1
    main_end = n
    while main_end > main_start and items[main_end - 1].is_action:
        main_end -= 1
    main_len = main_end - main_start

    always_visible_rows = main_start + (n - main_end)
    if not main_len or always_visible_rows > max(3, height // 3):
        # Action-only menus (credentials, provider picker) need scrolling too.
        main_start, main_end, main_len = 0, n, n
        always_visible_rows = 0
    separators = sum(
        item.is_action and not _is_section_header(item) and not items[i - 1].is_action
        for i, item in enumerate(items) if i > 0
    ) if multi and has_actions else 0

    def header_status(position: str) -> str:
        # Position first: it is what a cut-down status should still show.
        return " · ".join(part for part in (position, status) if part)

    header_count = 1

    def chrome_for(key_segments: list[Text], context_lines: int) -> int:
        spacing = 1 + (0 if compact else 1)  # below the list; below the header
        if context_lines and not compact:
            spacing += 1  # between the context and the keys
        return (header_count + spacing + len(intro_lines) + always_visible_rows + separators
                + context_lines + len(theme.wrap_keys(key_segments, width)) + len(alert_lines))

    def with_help(segments: list[Text]) -> list[Text]:
        if not help_key or theme.has_key(segments, "?"):
            return segments
        candidate = segments + [theme.key_segment("?", "keys")]
        if len(theme.wrap_keys(candidate, width)) == len(theme.wrap_keys(segments, width)):
            return candidate
        return segments

    def windowed_keys() -> list[Text]:
        if theme.has_key(keys, "PgUp/PgDn"):
            return keys
        return keys + [theme.key_segment("PgUp/PgDn", "page")]

    def plan() -> tuple[list[Text], int]:
        """Keys and chrome height for the current pinning, paging included."""
        nonlocal header_count
        header_count = len(theme.header_lines(title, header_status(""), width))
        segments = with_help(keys)
        total = chrome_for(segments, item_lines + notice_lines)
        if main_len > height - total:
            segments = with_help(windowed_keys())
            # Measure the header with a position as wide as the real one will be.
            widest_position = f"{main_len}–{main_len} of {main_len}"
            header_count = len(theme.header_lines(title, header_status(widest_position), width))
            total = chrome_for(segments, item_lines + notice_lines)
        return segments, total

    shown_keys, chrome = plan()
    if always_visible_rows and chrome >= height:
        # Long help and many pinned actions can leave no room for a selectable
        # row, once paging has added its keys and position. Let the actions
        # scroll with the list in that case.
        main_start, main_end, main_len = 0, n, n
        always_visible_rows = 0
        shown_keys, chrome = plan()
    # A small window: shorten the focused row's help (e.g. a long folder path)
    # so a selectable row and the key bar still fit on screen.
    missing = chrome + 1 - height
    if missing > 0 and item_lines > 1:
        keep = max(1, item_lines - missing)
        item_blocks = [_clip_lines(item_blocks, keep, inner_width)]
        chrome -= item_lines - keep
        item_lines = keep
    # Still too tall: footer prose (notices, a long search text) shortens too.
    missing = chrome + 1 - height
    context = parsed.context
    if missing > 0 and notice_lines > 1:
        keep = max(1, notice_lines - missing)
        context = [_clip_lines(parsed.context, keep, inner_width)]
        chrome -= notice_lines - keep
        notice_lines = keep
    # Then the intro under the header, down to nothing in a tiny window.
    missing = chrome + 1 - height
    if missing > 0 and intro_lines:
        keep = max(0, len(intro_lines) - missing)
        chrome -= len(intro_lines) - keep
        intro_lines = intro_lines[:keep]
        if intro_lines:
            last = intro_lines[-1]
            last.truncate(max(1, min(cell_len(last.plain), width - len(theme.MARGIN)) - 1))
            last.append("…")
    max_visible = max(1, height - chrome)

    win_start_rel, win_end_rel = _compute_window(
        main_len, cursor - main_start, max_visible
    )
    if cursor < main_start or cursor >= main_end:
        win_start_rel, win_end_rel = _compute_window(main_len, 0, max_visible)
    win_start = main_start + win_start_rel
    win_end = main_start + win_end_rel

    position = (
        f"{win_start_rel + 1}–{win_end_rel} of {main_len}" if main_len > max_visible else ""
    )
    lines: list[Text] = theme.header_lines(title, header_status(position), width)
    if not compact:
        lines.append(theme.rule(width))
    lines.extend(intro_lines)

    for i, item in enumerate(items):
        in_main = main_start <= i < main_end
        if in_main and (i < win_start or i >= win_end):
            continue
        if multi and has_actions and item.is_action and not _is_section_header(item):
            previous = items[i - 1] if i > 0 else None
            if previous and not previous.is_action:
                lines.append(Text(""))
        if _is_section_header(item):
            label = theme.section_label(item.label)
            lines.append(Text(theme.MARGIN + ellipsize_cells(label, inner_width), style=theme.SECTION))
            continue
        lines.append(_row(item, i, i == cursor, multi, geometry, tick))

    # The line above the key bar is a rule in roomy windows; spacing stays the same.
    has_context = bool(item_lines or notice_lines)
    lines.append(theme.rule(width) if not compact and not has_context else Text(""))
    for block in item_blocks + context:
        lines.extend(theme.wrap_block(block, width, console))
    if has_context and not compact:
        lines.append(theme.rule(width))
    lines.extend(theme.wrap_keys(shown_keys, width))
    lines.extend(alert_lines)
    return Group(*lines)


# Keys every selector understands, listed by show_keys after the screen's own.
_STANDARD_KEYS = (("↑/↓", "move"), ("PgUp/PgDn", "page"), ("Home/End", "first / last"),
                  ("Esc", "back"))


def key_pairs(footer: "str | Text", extra=()) -> list[tuple[str, str]]:
    """(key, action) pairs from a footer's key segments, then *extra* keys it does not name."""
    pairs = []
    for segment in theme.parse_footer(footer).keys:
        key, _, action = segment.plain.partition(" ")
        pairs.append((key, action))
    named = {part for key, _ in pairs for part in key.split("/")}
    for key, action in extra:
        if not set(key.split("/")) & named:
            pairs.append((key, action))
    return pairs


def show_keys(title: "str | Text", footer: "str | Text", extra=_STANDARD_KEYS) -> None:
    """Every key of a screen in one list, including those a narrow key bar leaves out."""
    pairs = key_pairs(footer, extra)
    width = max((cell_len(key) for key, _ in pairs), default=1)
    items = []
    for key, action in pairs:
        label = Text(key.ljust(width), style=theme.KEY)
        label.append("  " + action, style="")
        items.append(SelectItem(label, value="__key__", passive=True))
    items.append(SelectItem("Back", value=None, is_action=True))
    screen = title.plain if isinstance(title, Text) else Text.from_markup(title).plain
    arrow_select(items, title=Text("Keys" + theme.CRUMB + screen), footer="↑/↓ scroll • Esc back", help=False)


def _next_enabled(items: list[SelectItem], current: int, direction: int) -> int:
    """Move to the next enabled item in the given direction, wrapping around."""
    n = len(items)
    pos = current
    for _ in range(n):
        pos = (pos + direction) % n
        if items[pos].enabled:
            return pos
    return current  # All disabled — stay put


def _valid_cursor(items: list[SelectItem], cursor: int) -> int:
    """Keep the cursor on an existing enabled row, e.g. after an action rebuilt *items*."""
    direction = 1
    if cursor >= len(items):
        cursor, direction = len(items) - 1, -1  # the list shrank: stay near its end
    if items[cursor].enabled:
        return cursor
    return _next_enabled(items, cursor, direction)


def _render(
    banner: object,
    panel: object,
    width: int | None = None,
    expected_size: object | None = None,
) -> bool:
    """Redraw inside the alternate screen buffer.

    Clears the viewport first (cheap inside an alt-screen) so a previous
    render that overflowed and scrolled can't leave ghost rows behind. The
    frame carries its own header line, so *banner* is accepted for older
    callers and ignored.
    """
    from io import StringIO

    # Pre-render all content into a string
    buf = StringIO()
    buffer_console(buf, width if width is not None else console.size.width).print(panel)
    # A final newline scrolls a frame that exactly fills the viewport, hiding
    # its heading in short terminals. The next redraw already homes the cursor.
    content = buf.getvalue().rstrip("\n")

    # Home + clear entire screen + write content. The 2J clear avoids
    # ghost rows when a prior render overflowed and scrolled the viewport.
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
    status: str | Callable[[], str] = "",
    alert: str | Callable[[], str] = "",
    intro: "str | Text | Callable[[], str | Text]" = "",
    help: bool = True,
) -> int | list[int] | tuple | None:
    """Interactive arrow-key selector.

    Uses the terminal's alternate screen buffer for a clean, flicker-free
    experience. The original screen content is restored when done.

    *title* and *footer* may be strings **or callables** returning a string.
    Callables are re-evaluated on every render, allowing dynamic content
    (e.g. filter labels) without leaving the alt-screen.

    Args:
        items: List of SelectItem to display.
        title: Screen name shown in the header line after the app name.
        multi: If True, enables toggle mode with checkboxes.
               Enter on regular items toggles them.
               Enter on action items (is_action=True) returns that index.
               The caller reads items[i].toggled to see what was toggled.
               If False, Enter returns the index of the highlighted item.
        footer: Custom footer text (overrides default).
        start_index: Initial cursor position.
        banner: Accepted for older callers; every frame draws its own header.
        status: Optional right-aligned header text (str or callable).
        alert: Optional transient Rich-markup message drawn as the last line,
               under the key bar (e.g. "press again to quit"); str or callable.
        intro: Optional summary under the header (str, Text or callable).
        help: ``?`` opens the list of this screen's keys unless the caller
              binds ``?`` itself.
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
    cursor = _valid_cursor(items, start_index)

    # Shared state for resize watcher + marquee ticker
    state = {
        "cursor": cursor,
        "tick": 0,
        "cursor_changed_at": time.monotonic(),
        "paused": False,  # another screen (the key list) owns the terminal
    }
    help_enabled = help and "?" not in (hotkeys or {}) and "?" not in (key_actions or {})
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
                    status=_resolve(status),
                    alert=_resolve(alert),
                    intro=_resolve(intro),
                    help_key=help_enabled,
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
            if state["paused"]:
                continue

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
            elif key in (readchar.key.PAGE_UP, readchar.key.PAGE_DOWN, readchar.key.HOME, readchar.key.END):
                enabled = [i for i, item in enumerate(items) if item.enabled] or [cursor]
                position = enabled.index(cursor) if cursor in enabled else 0
                step = max(1, console.size.height - 10)
                if key == readchar.key.HOME:
                    position = 0
                elif key == readchar.key.END:
                    position = len(enabled) - 1
                else:
                    position = max(0, min(len(enabled) - 1, position + (step if key == readchar.key.PAGE_DOWN else -step)))
                cursor = enabled[position]
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
            elif key == "?" and help_enabled:
                state["paused"] = True
                try:
                    show_keys(_resolve(title), _resolve(footer) or _default_footer(multi))
                except KeyboardInterrupt:
                    pass
                finally:
                    # The key list left the alternate screen; take it back.
                    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
                    sys.stdout.flush()
                    state["paused"] = False
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

            # Callbacks may have rebuilt the list (e.g. Clear history shrinking it).
            if not items:
                return None
            cursor = _valid_cursor(items, cursor)

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
