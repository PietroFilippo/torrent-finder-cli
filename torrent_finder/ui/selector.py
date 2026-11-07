"""Reusable arrow-key interactive selector using readchar + Rich."""

# i18n: converted
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import readchar
from rich.cells import cell_len
from rich.console import Group
from rich.text import Text

from torrent_finder.constants import buffer_console, console
from torrent_finder.i18n import N_, t, current as current_language
from torrent_finder.ui import chrome as frames, display, theme
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
    # Lines for the inspector pane of wide windows, below the row's name, hint
    # and description; called the first time the row is focused, then kept.
    inspect: "Callable[[], list[str | Text]] | None" = None
    _details: "list | None" = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.toggle_states and self.toggle_state not in self.toggle_states:
            self.toggle_state = self.toggle_states[0]

    def details(self) -> list:
        """The inspector lines, computed once; a failing source shows none rather than stopping the menu."""
        if self.inspect is None:
            return []
        if self._details is None:
            try:
                self._details = list(self.inspect())
            except Exception:
                self._details = []
        return self._details

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
    # A shortcut letter reads as a key; a number (a count, a size) is a value, not a key.
    is_key = theme.is_key(item.hint) and not item.hint.strip().isdigit()
    return Text(item.hint, style=theme.KEY if is_key else theme.MUTED)


def _toggle_badge(item: "SelectItem") -> str:
    """The state shown before a multi-select label: a named state or a check mark."""
    if item.toggle_states:
        return _state_label(item.toggle_state, item.toggle_states)
    return theme.CHECK if item.toggled else theme.UNCHECKED


def _state_label(state: str, states: tuple[str, ...]) -> str:
    """Translate a badge with the shipped contexts; its stored state stays English."""
    if "On" in states or "Auto" in states:  # i18n: ignore — engine state identities
        return t(state, ctx="engine mode")
    return t(state, ctx="preset state")


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


def _section_window(items: list["SelectItem"], main_start: int, main_end: int, start: int, end: int,
                    cursor: int) -> tuple[int, int, "int | None"]:
    """Adjust a window of list rows so section headings keep their rows.

    A window never ends on a heading: the heading goes to the next page (the
    window moves up a row, or loses its last row at the top of the list). A
    window that starts inside a section repeats that section's heading as its
    first row, in place of a row at an end the cursor is not on. Returns
    ``(start, end, heading)``: *heading* is the index of the heading to repeat,
    or None.
    """
    rows = end - start
    if rows < 2 or rows >= main_end - main_start:  # the whole list shows, or there is no room to spare
        return start, end, None
    if _is_section_header(items[end - 1]) and end < main_end:
        if start > main_start:
            start, end = start - 1, end - 1
        else:
            end -= 1
    heading = None
    if rows >= 4 and not _is_section_header(items[start]):
        heading = next((i for i in range(start - 1, main_start - 1, -1) if _is_section_header(items[i])), None)
    if heading is not None:
        if cursor != end - 1:
            end -= 1
            if _is_section_header(items[end - 1]) and end < main_end:
                end -= 1  # the row before it was a heading: it goes to the next page too
        else:
            start += 1
            if _is_section_header(items[start]):
                heading = None  # the window now starts on its own heading
    return start, end, heading


# Rows below this height drop the spacer lines around the list.
_COMPACT_HEIGHT = 20
_GUTTER = 2  # cursor bar + space


# The width rows are laid out in: the window's, or the list column's when the
# inspector pane takes the right of a wide window. Set while a frame is built
# or measured, per thread: the marquee watcher measures while frames draw.
_layout = threading.local()


def _screen_width() -> int:
    return getattr(_layout, "width", None) or console.size.width


def _inner_width() -> int:
    """Usable content width inside the left and right margins."""
    return theme.inner_width(_screen_width())


def _inline_hint(item: "SelectItem") -> bool:
    """Keep a hint beside its label when it leaves useful label space, or when the whole row fits."""
    inner = _inner_width()
    hint = _plain(item.hint)
    if not hint:
        return False
    if _screen_width() >= 72 and cell_len(hint) + 2 <= inner // 2:
        return True
    marker = cell_len(item.marker) + 1 if item.marker else 0
    badge = 1 + max((cell_len(_state_label(state, item.toggle_states)) for state in item.toggle_states), default=-1)
    row = _GUTTER + badge + marker + cell_len(_plain(item.label)) + 2 + cell_len(hint)
    return row <= inner  # label and hint both whole


def _badge_width(items: list["SelectItem"]) -> int:
    """One width for every state badge in the list, so labels line up."""
    widths = [cell_len(_state_label(state, item.toggle_states)) for item in items for state in item.toggle_states]
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
    column set by unrelated rows further down the menu. Section headings
    inside a run do not break it, so hinted sections share one column.
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
        if _is_section_header(item):
            continue
        if _inline_hint(item):
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


# The work area, in cells with margins: a list column is as wide as its widest
# row within these bounds, and the inspector, when a window has room for one,
# sits right beside it. The rest of the window is left to the painting.
_LIST_MIN, _LIST_MAX = 48, 108
_PANE_MIN, _PANE_MAX = 40, 56
_PANE_SCREEN_MIN = 120  # narrower windows keep one column
_KEYS_MIN = 64          # a narrow list still gets a key bar this wide
_CONTEXT_CAP = 4        # rows kept for the focused row's help, so the key bar stays put
_PROSE_WIDTH = 100      # the intro and the tip may run this wide, past a narrow block


def _natural_width(items: list["SelectItem"], multi: bool) -> int:
    """Cells the widest row needs, label and hint on one line, margins included."""
    badge = _badge_width(items) if multi else 1
    widest = 0
    for item in items:
        if _is_section_header(item):
            cells = cell_len(theme.section_label(_plain(item.label)))
        else:
            cells = _prefix_width(item, multi, badge) + cell_len(" ".join(_plain(item.label).splitlines()))
            if _plain(item.hint):
                cells += 2 + cell_len(_plain(item.hint))
        widest = max(widest, cells)
    # Hints line up in one column when the list is wide enough: the longest label plus the longest hint.
    hinted = [item for item in items if not _is_section_header(item) and _plain(item.hint)]
    if len(hinted) >= 2:
        aligned = (max(_prefix_width(item, multi, badge) for item in hinted)
                   + max(cell_len(" ".join(_plain(item.label).splitlines())) for item in hinted)
                   + 2 + max(cell_len(_plain(item.hint)) for item in hinted))
        widest = max(widest, aligned)
    return widest + 2 * len(theme.MARGIN)


def pane_width(screen_width: int) -> int:
    """The inspector's width in a window this wide, when it shows one."""
    return min(_PANE_MAX, max(_PANE_MIN, round(screen_width * 0.3)))


def columns(items: list["SelectItem"], multi: bool, screen_width: int) -> tuple[int, int, int]:
    """(list column, inspector, work area) widths for *items* in a window *screen_width* wide.

    The key bar, help and notices span the work area: the list column plus,
    when shown, the inspector beside it.
    """
    natural = _natural_width(items, multi)
    listed = min(screen_width, max(_LIST_MIN, min(natural, _LIST_MAX)))
    if screen_width >= _PANE_SCREEN_MIN and any(_has_details(item) for item in items):
        pane = pane_width(screen_width)
        listed = min(listed, screen_width - pane - _PANE_GAP)
        if listed >= _LIST_MIN:
            return listed, pane, listed + _PANE_GAP + pane
    if screen_width < _PANE_SCREEN_MIN:  # little painting beside it: the list's help wraps less
        return screen_width, 0, screen_width
    listed = min(screen_width, max(listed, _KEYS_MIN))
    return listed, 0, listed


@dataclass
class _MeasuredLayout:
    size: object
    width: int
    pane_width: int
    geometry: _Geometry
    overflows: bool
    work: int = 0
    context_budget: int = 0
    # Rows the pane and detail lines have needed on this screen: kept, so moving
    # the focus does not move the key bar.
    seen: dict = field(default_factory=dict)


def _context_rows(item: "SelectItem", width: int) -> int:
    """Rows the focused-row help of *item* takes under a list *width* cells wide."""
    if _is_section_header(item):
        return 0
    blocks = []
    if _plain(item.hint) and not _inline_hint(item):
        blocks.append(_hint_text(item))
    if item.description:
        blocks.append(Text.from_markup(item.description))
    return sum(_wrapped_line_count(block, theme.inner_width(width)) for block in blocks)


def _context_budget(items: list["SelectItem"], width: int, work: int) -> int:
    """Rows to keep for the focused row's help: the longest any row needs, up to _CONTEXT_CAP."""
    if len(items) > 400:
        return 0
    previous_width = getattr(_layout, "width", None)
    _layout.width = width
    try:
        return min(_CONTEXT_CAP, max((_context_rows(entry, work) for entry in items), default=0))
    finally:
        _layout.width = previous_width


def _measure_layout(items: list["SelectItem"], cursor: int, multi: bool, size,
                    budget: "int | None" = None) -> _MeasuredLayout:
    """Measure the list once, in the same column used for drawing and marquee."""
    width, pane, work = columns(items, multi, size.width)
    previous_width = getattr(_layout, "width", None)
    _layout.width = width
    try:
        geometry = _geometry(items, multi)
        item = items[cursor] if 0 <= cursor < len(items) else None
        overflows = bool(item is not None and not _is_section_header(item) and
                         cell_len(_plain(item.label)) > _label_avail_width(item, multi, geometry))
        if budget is None:
            budget = 0 if pane else _context_budget(items, width, work)
        return _MeasuredLayout(size, width, pane, geometry, overflows, work, budget)
    finally:
        _layout.width = previous_width


def _first_seen(items: list["SelectItem"], measurement: "_MeasuredLayout") -> dict:
    """Rows the tallest pane or details on a short list need, so the first frame keeps them already.

    The keys then stay put from the first frame, not only after a taller row
    was visited. Longer lists fill the window, so their keys do not move.
    """
    if len(items) > 40:
        return {}
    previous = getattr(_layout, "width", None)
    _layout.width = measurement.width
    try:
        if measurement.pane_width:
            heights = [len(lines) for lines in (_pane(item, measurement.pane_width) for item in items)
                       if len(lines) > 1]
            return {"pane": max(heights, default=0)}
        tallest = max((len(item.details()) for item in items if not _is_section_header(item)), default=0)
        return {"details": tallest + 1 if tallest else 0}  # with the blank row above them
    finally:
        _layout.width = previous


class _LayoutCache:
    """One menu's measurements; in-place edits invalidate through actions/refresh."""

    def __init__(self):
        self.revision = 0
        self.key = None
        self.measurement = None
        self.seen_key = None
        self.seen: dict = {}

    def invalidate(self) -> None:
        self.revision += 1

    def get(self, items, cursor: int, multi: bool, size) -> _MeasuredLayout:
        key = (id(items), len(items), self.revision, size, cursor, multi,
               theme.current(), theme.FRAMED, current_language())
        if key != self.key:
            # The help budget does not depend on the focus: measured once per list and size.
            budget_key = key[:4] + key[5:]
            if budget_key != getattr(self, "budget_key", None):
                width, pane, work = columns(items, multi, size.width)
                self.budget_key, self.budget = budget_key, 0 if pane else _context_budget(items, width, work)
            self.measurement = _measure_layout(items, cursor, multi, size, self.budget)
            self.key = key
            seen_key = (id(items), size, multi, theme.current(), theme.FRAMED, current_language())
            if seen_key != self.seen_key:
                self.seen_key, self.seen = seen_key, _first_seen(items, self.measurement)
            self.measurement.seen = self.seen
        return self.measurement


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


def _small_window(width: int, height: int) -> bool:
    return theme.small_window(width, height)


budget_keys = theme.budget_keys


def _rows_for_choices(items: list["SelectItem"], start: int, end: int, cursor: int, wanted: int) -> int:
    """Rows that show *wanted* selectable rows around *cursor*, with the headings among them."""
    rows, seen, index = 0, 0, max(start, min(cursor, end - 1))
    above = int(index > start and _is_section_header(items[index - 1]))
    rows += above  # the focused row's section heading sits above it
    while index < end and seen < wanted:
        rows += 1
        seen += not _is_section_header(items[index])
        index += 1
    index = max(start, min(cursor, end - 1)) - 1 - above
    while index >= start and seen < wanted:
        rows += 1
        seen += not _is_section_header(items[index])
        index -= 1
    return max(1, rows)


def _default_footer(multi: bool) -> str:
    if multi:
        return t("↑/↓ navigate  •  Enter toggle/select  •  Esc cancel")
    return t("↑/↓ navigate  •  Enter select  •  Esc cancel")


def _position(start: int, end: int, total: int) -> str:
    """The same position template for drawing and the header's row budget."""
    return t("{start}–{end} of {total}", start=start, end=end, total=total)


def _row(item: "SelectItem", index: int, is_cursor: bool, multi: bool, geometry: _Geometry, tick: int) -> Text:
    """One selectable row: margin, cursor bar, state, marker, label, inline hint."""
    row = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    row.append(theme.CURSOR if is_cursor else " ", style=theme.ACCENT)
    row.append(" ")
    if multi and not item.is_action:
        badge = _toggle_badge(item)
        if item.toggle_states:
            badge_style = theme.state_style(item.toggle_state)
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
    item_label = item.label
    if "\n" in _plain(item_label):  # a saved query with line breaks still takes one row
        item_label = (Text(" ").join(item_label.split("\n")) if isinstance(item_label, Text)
                      else " ".join(item_label.splitlines()))
    plain_label = _plain(item_label)
    if is_cursor and cell_len(plain_label) > available:
        label = Text(marquee_cells(plain_label, available, tick), style=style)
    elif isinstance(item_label, Text):
        label = item_label.copy()
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
        end = max(cell_len(row.plain), _screen_width() - len(theme.MARGIN))
        row.append(" " * (end - cell_len(row.plain)))
        row.stylize(f"on {theme.FILL}", len(theme.MARGIN), len(row.plain))  # i18n: ignore — Rich style syntax
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
    intro: "str | Text | list[Text]" = "",
    help_key: bool = False,
    message: "str | Text" = "",
    tip: str = "",
    measurement: _MeasuredLayout | None = None,
) -> Group:
    """Render one complete selector frame: header, intro, windowed list, context, keys, alert, tip.

    *intro* is a short summary under the header (what the screen is about),
    one Text or several; *help_key* adds "? keys" to the key bar when it fits
    on the lines the keys already take. *alert* (the quit guard) is the line
    under the keys. *tip* sits on the bottom rows, in space the screen leaves
    empty, and steps aside when there is none. In the Athanor design the
    frame comes from ``chrome.compose`` (imported as ``frames``): the screen
    name moves into its top edge and *message*, an announcement, onto the
    message line above it.

    Every selectable row stays one physical line so the window is stable;
    descriptions, notices and the key bar wrap and are measured, and the list
    gets whatever height is left.

    In a wide window, when the rows carry help or details, an inspector pane
    takes the right of the frame: the focused row's name, hint, description
    and ``SelectItem.inspect`` lines, beside a list column laid out as if the
    window were that narrow.
    """
    size = measurement.size if measurement is not None else console.size
    screen_width, full_height = size.width, size.height
    if frames.too_small(screen_width, full_height):
        return Group(*frames.enlarge_notice(screen_width, full_height))
    cursor = min(cursor, len(items) - 1)  # a live list that shrank under the cursor keeps it on its last row
    measurement = measurement or _measure_layout(items, cursor, multi, size)
    pane_width, width = measurement.pane_width, measurement.width
    _layout.width = width
    try:
        return _panel(items, cursor, title, multi, footer, tick, status, alert, intro, help_key, message, tip,
                      screen_width, full_height, width, pane_width, measurement.geometry,
                      measurement.work or width, measurement.context_budget, measurement.seen)
    finally:
        _layout.width = None


# The pane's divider, the space after it and the right margin.
_PANE_GAP = 5


def _has_details(item: "SelectItem") -> bool:
    return not _is_section_header(item) and bool(item.description or item.inspect)


def _fit(line: "str | Text", width: int) -> Text:
    """One detail entry on one row of *width* cells: line breaks become spaces, the end an ellipsis."""
    text = line.copy() if isinstance(line, Text) else Text.from_markup(line)
    if "\n" in text.plain:  # one entry, one row: line breaks in saved text become spaces
        text = Text(" ").join(text.split("\n"))
    text.no_wrap, text.overflow, text.justify = True, "ellipsis", "left"
    if cell_len(text.plain) > width:
        text.truncate(width, overflow="ellipsis")
    return text


def _pane(item: "SelectItem | None", width: int) -> list[Text]:
    """The inspector: the focused row's name, hint and help, then its detail lines, fitted to *width*."""
    if item is None or _is_section_header(item):
        return []

    def prose(text: Text) -> list[Text]:
        return list(text.wrap(console, max(1, width), overflow="fold"))

    lines = [_fit(Text(_plain(item.label), style=theme.FOCUS), width)]
    if _plain(item.hint) and not _inline_hint(item):  # a hint the row shows in full is not repeated
        lines += prose(_hint_text(item))
    if item.description:
        lines += [Text("")] + prose(Text.from_markup(item.description))
    details = item.details()
    if details:
        lines.append(Text(""))
        lines += [_fit(line, width) for line in details]
    return lines


def _beside(left: "Text | None", right: "Text | None", width: int, divider: bool = True) -> Text:
    """A list-column line padded to *width*, the pane's divider, then the pane's line.

    Without *divider* (rows below the pane's last line) the cells stay blank.

    The left part is appended, not copied: a section heading's whole-line
    style must not spill onto the pane's text.
    """
    line = Text(no_wrap=True, overflow="crop")
    if left is not None:
        line.append_text(left)
    if cell_len(line.plain) > width:
        line.truncate(width)
    if not divider and right is None:
        return line
    line.append(" " * (width - cell_len(line.plain)))
    line.append("│", style=theme.RULE_STYLE)
    line.append("  ")
    if right is not None:
        line.append_text(right)
    return line


def _panel(items, cursor, title, multi, footer, tick, status, alert, intro, help_key, message, tip,
           screen_width: int, full_height: int, width: int, pane_width: int, geometry: _Geometry,
           work: int = 0, context_budget: int = 0, seen: "dict | None" = None) -> Group:
    """One frame laid out as a work block: intro, list (and inspector), help, notices, keys, tip.

    Every screen starts on the first row, where the search field and the
    results start too, so moving between screens never shifts the eye. A
    short screen keeps its block together and leaves the rest of the window
    to the painting; a long list fills the window and its keys end up on the
    last rows. *width* is the list column, *work* the
    block (the list column and the inspector beside it).
    """
    work = work or width
    seen = seen if seen is not None else {}
    height = theme.view_height(full_height, screen_width)  # the chrome's rows come off first
    framed = theme.framed(screen_width, full_height)
    inner_work = theme.inner_width(work)
    compact = not theme.roomy(height, _COMPACT_HEIGHT)
    has_actions = any(item.is_action for item in items)

    parsed = theme.parse_footer(footer or _default_footer(multi))
    keys = parsed.keys or theme.parse_footer(_default_footer(multi)).keys

    current_item = items[cursor] if 0 <= cursor < len(items) else None
    item_blocks: list[Text] = []
    if pane_width:
        pass  # the inspector pane shows the focused row's hint and description
    elif current_item and _plain(current_item.hint) and not _inline_hint(current_item):
        hint = _hint_text(current_item)
        hint.overflow = "fold"
        item_blocks.append(hint)
    if current_item and current_item.description and not pane_width:
        description = Text.from_markup(current_item.description)
        description.overflow = "fold"
        item_blocks.append(description)
    item_lines = sum(_wrapped_line_count(block, inner_work) for block in item_blocks)
    notice_lines = sum(_wrapped_line_count(block, inner_work) for block in parsed.context)
    # A transient message (the quit guard) is the line under the key bar;
    # announcements take the Athanor message line when the window shows one.
    bar_message = message if theme.bars(screen_width, full_height) else ""
    alert_lines = theme.wrap_block(Text.from_markup(alert), work, console) if alert else []
    if message and not bar_message and theme.FRAMED:
        # No message line in this window (compact, or short): the announcement goes under the keys.
        alert_lines += theme.wrap_block(theme._as_text(message), work, console)
    # Simple has no message line: the announcement is a notice above the key bar.
    notice = [frames.notice_line(message, work)] if message and not theme.FRAMED else []
    # The summary over the list (a torrent's name and facts) may run wider than the block, like the tip.
    intro_width = min(screen_width, max(work, _PROSE_WIDTH))
    intro_lines = []
    for block in (intro if isinstance(intro, list) else [intro]):
        text = (block.copy() if isinstance(block, Text) else Text.from_markup(block)) if block else Text()
        if text.plain.strip():
            intro_lines += theme.wrap_block(text, intro_width, console)
    # Rows kept for the longest help on this screen, so the keys do not move with the focus.
    pad_lines = 0 if compact else max(0, min(context_budget, 2 if _small_window(screen_width, full_height) else context_budget) - item_lines)

    # Partition into leading actions, a windowed main list, and trailing actions.
    n = len(items)
    main_start = 0
    # A heading that opens the list scrolls with its rows instead of being pinned above them.
    while main_start < n and items[main_start].is_action and not _is_section_header(items[main_start]):
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
        spacing = 1 + (0 if compact or framed else 1)  # below the list; below the header
        if (context_lines or pad_lines) and not compact:
            spacing += 1  # between the context and the keys
        return (header_count + spacing + len(intro_lines) + always_visible_rows + separators
                + context_lines + pad_lines + len(notice) + len(theme.wrap_keys(key_segments, work))
                + len(alert_lines))

    small = _small_window(screen_width, full_height)

    def with_help(segments: list[Text]) -> list[Text]:
        if not help_key:
            return segments
        if small:  # two rows of keys, ? among them; the help lists the rest
            if not theme.has_key(segments, "?"):
                segments = segments + [theme.key_segment("?", t("keys", ctx="key bar"))]
            return budget_keys(segments, work)
        return theme.with_help(segments, work)

    def windowed_keys() -> list[Text]:
        if theme.has_key(keys, "PgUp/PgDn"):
            return keys
        return keys + [theme.key_segment("PgUp/PgDn", t("page", ctx="key bar"))]

    def plan() -> tuple[list[Text], int]:
        """Keys and chrome height for the current pinning, paging included."""
        nonlocal header_count
        header_count = len(theme.frame_header(title, header_status(""), screen_width, full_height))
        segments = with_help(keys)
        total = chrome_for(segments, item_lines + notice_lines)
        if main_len > height - total:
            segments = with_help(windowed_keys())
            # Measure the header with a position as wide as the real one will be.
            widest_position = _position(main_len, main_len, main_len)
            header_count = len(theme.frame_header(title, header_status(widest_position), screen_width,
                                                  full_height))
            total = chrome_for(segments, item_lines + notice_lines)
        return segments, total

    shown_keys, chrome = plan()
    if pad_lines and main_len > height - chrome:
        # A list that scrolls keeps its rows: the kept help rows go first.
        pad_lines = 0
        shown_keys, chrome = plan()
    if always_visible_rows and chrome >= height:
        # Long help and many pinned actions can leave no room for a selectable
        # row, once paging has added its keys and position. Let the actions
        # scroll with the list in that case.
        main_start, main_end, main_len = 0, n, n
        always_visible_rows = 0
        shown_keys, chrome = plan()
    # A small window: shorten the focused row's help (e.g. a long folder path)
    # so three selectable rows (or every row, when fewer) and the key bar still fit.
    want = _rows_for_choices(items, main_start, main_end, cursor, 3)
    missing = chrome + want - height
    if missing > 0 and item_lines > 1:
        keep = max(1, item_lines - missing)
        item_blocks = [_clip_lines(item_blocks, keep, inner_work)]
        chrome -= item_lines - keep
        item_lines = keep
    # Still too tall: footer prose (notices, a long search text) shortens too.
    missing = chrome + want - height
    context = parsed.context
    if missing > 0 and notice_lines > 1:
        keep = max(1, notice_lines - missing)
        context = [_clip_lines(parsed.context, keep, inner_work)]
        chrome -= notice_lines - keep
        notice_lines = keep
    # Then the intro under the header, down to nothing in a tiny window: the choices come first.
    missing = chrome + want - height
    if missing > 0 and intro_lines:
        keep = max(0, len(intro_lines) - missing)
        chrome -= len(intro_lines) - keep
        intro_lines = intro_lines[:keep]
        if intro_lines:
            last = intro_lines[-1]
            last.truncate(max(1, min(cell_len(last.plain), intro_width - len(theme.MARGIN)) - 1))
            last.append("…")
    if main_len <= height - chrome and theme.has_key(shown_keys, "PgUp/PgDn") and not theme.has_key(keys, "PgUp/PgDn"):
        shown_keys, chrome = plan()  # the shortened prose made room: the whole list shows, no paging keys
    max_visible = max(1, height - chrome)

    # A tall window with no room beside the list shows the inspector's detail
    # lines under the focused row's help instead, in rows the list leaves empty.
    detail_lines: list[Text] = []
    spare = max_visible - main_len - 1  # one row stays between the list and the footer
    if not pane_width and not compact and current_item is not None and spare > 2:
        details = [] if _is_section_header(current_item) else current_item.details()
        room = spare - 1  # the blank row above them
        if details:
            detail_lines = [Text(theme.MARGIN) + _fit(line, inner_work) for line in details[:room]]
            if len(details) > room:
                detail_lines[-1] = Text(theme.MARGIN + "…", style=theme.MUTED)
            detail_lines.insert(0, Text(""))
        # Rows another focused row needed stay, so the keys do not jump.
        kept = min(seen.get("details", 0), room + 1)
        seen["details"] = max(seen.get("details", 0), len(detail_lines))
        detail_lines += [Text("")] * max(0, kept - len(detail_lines))
        chrome += len(detail_lines)
        max_visible = max(1, height - chrome)

    win_start_rel, win_end_rel = _compute_window(
        main_len, cursor - main_start, max_visible
    )
    if cursor < main_start or cursor >= main_end:
        win_start_rel, win_end_rel = _compute_window(main_len, 0, max_visible)
    win_start, win_end, repeated = _section_window(items, main_start, main_end, main_start + win_start_rel,
                                                   main_start + win_end_rel, cursor)
    win_start_rel, win_end_rel = win_start - main_start, win_end - main_start

    position = (
        _position(win_start_rel + 1, win_end_rel, main_len) if main_len > max_visible else ""
    )
    head: list[Text] = theme.frame_header(title, header_status(position), screen_width, full_height)
    if not compact:
        head += theme.frame_rule(screen_width, full_height)

    def heading(item: SelectItem) -> Text:
        label = theme.section_label(item.label)
        return Text(theme.MARGIN + ellipsize_cells(label, inner_width), style=theme.SECTION)

    inner_width = _inner_width()
    listed: list[Text] = []
    for i, item in enumerate(items):
        in_main = main_start <= i < main_end
        if in_main and (i < win_start or i >= win_end):
            continue
        if i == win_start and repeated is not None:
            listed.append(heading(items[repeated]))  # the section this page starts inside
        if multi and has_actions and item.is_action and not _is_section_header(item):
            previous = items[i - 1] if i > 0 else None
            if previous and not previous.is_action:
                listed.append(Text(""))
        if _is_section_header(item):
            listed.append(heading(item))
            continue
        listed.append(_row(item, i, i == cursor, multi, geometry, tick))

    # Under the list: the focused row's help and details, the screen's notices,
    # then the keys. The line above the key bar is a rule in roomy windows.
    # Rows kept for help count as help: the rule then stays where it is with or without it.
    has_context = bool(item_lines or notice_lines or notice or pad_lines)
    below: list[Text] = [theme.rule(work) if not compact and not has_context else Text("")]
    for block in item_blocks:
        below.extend(theme.wrap_block(block, work, console))
    below.extend([Text("")] * pad_lines)
    below.extend(detail_lines)
    for block in context:
        below.extend(theme.wrap_block(block, work, console))
    below.extend(notice)
    if has_context and not compact:
        below.append(theme.rule(work))
    below.extend(theme.wrap_keys(shown_keys, work))
    below.extend(alert_lines)

    if pane_width:
        # The inspector beside the list, as tall as the list or its own lines;
        # its divider ends with them.
        room = max(len(listed), height - len(head) - len(intro_lines) - len(below))
        pane = _pane(current_item, pane_width)
        if len(pane) <= 1:
            pane = []  # the row's name alone says nothing the row does not: no pane, no divider
        rows = max(len(listed), min(len(pane), room), min(seen.get("pane", 0), room))
        seen["pane"] = max(seen.get("pane", 0), min(len(pane), room))
        if len(pane) > rows:
            pane = pane[:max(0, rows - 1)] + [Text("…", style=theme.MUTED)]
        # The divider runs as far as the pane's lines; the list column keeps its width below them.
        listed = [_beside(listed[i] if i < len(listed) else None, pane[i] if i < len(pane) else None, width,
                          divider=i < len(pane))
                  for i in range(rows)]
    block = intro_lines + listed + below

    # A short tip under the keys, when the window leaves room for it.
    _layout.width = None
    tip_width = min(screen_width, max(work, _PROSE_WIDTH))
    tip_lines = theme.wrap_block(Text.from_markup(tip), tip_width, console) if tip else []
    free = height - len(head) - len(block)
    if tip_lines and len(tip_lines) <= 2 and free >= len(tip_lines) + 1:
        block += [Text("")] + tip_lines
        free -= len(tip_lines) + 1
    lines = (head + block)[:height]  # a window too small keeps its top
    return Group(*frames.compose(lines, title, header_status(position), screen_width, full_height, bar_message))


# Keys every selector understands, listed by show_keys after the screen's own.
_STANDARD_KEYS = (("↑/↓", N_("move", ctx="key bar")), ("PgUp/PgDn", N_("page", ctx="key bar")),
                  ("Home/End", N_("first / last", ctx="key bar")), ("Esc", N_("back", ctx="key bar")),
                  ("Ctrl+C", N_("back", ctx="key bar")))
_SELECT = N_("Select")


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
    if extra is _STANDARD_KEYS:
        extra = [(key, t(action)) for key, action in extra]
    pairs = key_pairs(footer, extra)
    width = max((cell_len(key) for key, _ in pairs), default=1)
    items = []
    for key, action in pairs:
        label = Text(key + " " * (width - cell_len(key)), style=theme.KEY)
        label.append("  " + action, style="")
        items.append(SelectItem(label, value="__key__", passive=True))
    items.append(SelectItem(t("Back"), value=None, is_action=True))
    screen = title.plain if isinstance(title, Text) else Text.from_markup(title).plain
    arrow_select(items, title=Text(t("Keys") + theme.CRUMB + screen), footer=t("↑/↓ scroll • Esc back"), help=False)


def _next_enabled(items: list[SelectItem], current: int, direction: int) -> int:
    """Move to the next enabled item in the given direction, wrapping around."""
    n = len(items)
    pos = current
    for _ in range(n):
        pos = (pos + direction) % n
        if items[pos].enabled:
            return pos
    return current  # All disabled — stay put


_focus: dict = {"value": None}


def focused() -> object:
    """The value of the row the selector being drawn has focused: a footer callable may follow it."""
    return _focus["value"]


def _focused_value(items: list[SelectItem], cursor: int):
    """The focused row's value when it names that row alone, so a live list can keep the focus on it."""
    if not 0 <= cursor < len(items):
        return None
    value = items[cursor].value
    if not isinstance(value, str) or sum(item.value == value for item in items) != 1:
        return None
    return value


def _follow(items: list[SelectItem], value, cursor: int) -> int:
    """The cursor after a live list changed: on the same row when it is still there, else near where it was."""
    if value is not None:
        for index, item in enumerate(items):
            if item.value == value and item.enabled:
                return index
    return _valid_cursor(items, cursor)


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
    """Redraw inside the alternate screen buffer, over the previous frame.

    ``display.paint`` rewrites every row in place and erases the rest, so a
    render that overflowed and scrolled leaves no ghost rows, and the screen
    is never blank between frames. The frame carries its own header line, so
    *banner* is accepted for older callers and ignored.
    """
    from io import StringIO

    # Pre-render all content into a string
    buf = StringIO()
    buffer_console(buf, width if width is not None else console.size.width).print(panel)
    # A final newline scrolls a frame that exactly fills the viewport, hiding
    # its heading in short terminals. The next redraw already homes the cursor.
    content = buf.getvalue().rstrip("\n")

    if expected_size is not None and console.size != expected_size:
        return False
    size = console.size
    sys.stdout.write(display.paint(content, width if width is not None else size.width, size.height))
    sys.stdout.flush()
    return True


def _resolve(val):
    """If *val* is callable, call it; otherwise return it unchanged."""
    return val() if callable(val) else val


def arrow_select(
    items: list[SelectItem],
    title: str = _SELECT,
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
    tip: str = "",
    refresh: Callable[[], bool] | None = None,
    help_footer: "str | Text | Callable[[], str | Text]" = "",
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
        help_footer: Complete key bar for ``?`` when footer uses compact labels
                     or omits keys. May be a callable, like footer.
        start_index: Initial cursor position.
        banner: Accepted for older callers; every frame draws its own header.
        status: Optional right-aligned header text (str or callable).
        alert: Optional transient Rich-markup message drawn as the last line,
               under the key bar (e.g. "press again to quit"); str or callable.
        intro: Optional summary under the header (str, Text or callable).
        help: ``?`` opens the list of this screen's keys unless the caller
              binds ``?`` itself.
        tip: Optional Rich-markup tip for the bottom rows, shown when the
             screen leaves them empty.
        on_action: Optional callback for action items. Called with
                   (index, items). Return True to stay in the menu,
                   False to exit and return the index.
        refresh: Optional non-blocking poll for background content; True requests
                 a redraw. It may rebuild *items* in place: the focus stays on the
                 row with the same string value when exactly one row has it.

    Returns:
        - Single-select mode: index of chosen item, or None if cancelled.
        - Multi-toggle mode: index of the action item that was selected,
          or None if cancelled. Read items[i].toggled for toggle state.
    """
    import threading

    if title is _SELECT:
        title = lambda: t(_SELECT)
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
        "holding": False,  # a key is being handled: the live list stays as that key saw it
    }
    help_enabled = help and "?" not in (hotkeys or {}) and "?" not in (key_actions or {})
    layout_cache = _LayoutCache()  # shared only while render_lock is held

    def aside(callback, *args):
        """Run a callback that may open another view, with this screen's redraws paused."""
        with render_lock:  # a frame being drawn finishes first
            state["paused"] = True
        try:
            return callback(*args)
        finally:
            with render_lock:
                layout_cache.invalidate()  # callbacks may edit labels, hints or markers in place
                state["paused"] = False
    # Background downloads: a finished one announces itself before the first
    # frame, and the figure on the status line (and this screen's rows, when
    # it shows them) follow the jobs while the screen waits for a key.
    from torrent_finder.ui import downloads as downloads_ui
    watched = downloads_ui.watch()
    # The message line's text while this screen is open. A window too small for any
    # screen shows none: the message stays queued and the first usable frame takes it.
    owed = frames.too_small(console.size.width, console.size.height)
    announcement = "" if owed else frames.take_message()
    stop_event = threading.Event()
    render_lock = threading.Lock()
    resize = _ResizeRedraw(console.size)

    def refresh_content() -> bool:
        nonlocal announcement, owed
        focused = _focused_value(items, state["cursor"]) if refresh is not None else None
        changed = refresh is not None and refresh()
        if changed and items:
            state["cursor"] = _follow(items, focused, state["cursor"])
        if downloads_ui.poll(watched):
            changed = True
        if changed or owed:
            owed = frames.too_small(console.size.width, console.size.height)
            taken = "" if owed else frames.take_message()
            if taken:
                announcement, changed = taken, True
        if changed:
            layout_cache.invalidate()
        return changed

    def draw(tick: int) -> bool:
        """Write a complete frame only when it matches the current viewport."""
        with render_lock:
            if state["paused"] or state["holding"]:
                return False  # another view owns the screen, or a key is acting on the list as it was
            refresh_content()
            cursor_now = state["cursor"]
            _focus["value"] = items[cursor_now].value if 0 <= cursor_now < len(items) else None
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
                    message=announcement,
                    tip=tip,
                    measurement=layout_cache.get(items, state["cursor"], multi, frame_size),
                )
                if stop_event.is_set():
                    return False  # the menu closed while this frame was built: never paint over what follows
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
        last_rendered_tick = state["tick"]
        while not stop_event.is_set():
            if stop_event.wait(_TICK_INTERVAL_S):
                break
            if state["paused"] or state["holding"]:
                continue

            with render_lock:
                if state["paused"] or state["holding"]:
                    continue
                content_changed = refresh_content()
                size = console.size
                size_changed = resize.observe(size)
                previous = layout_cache.measurement
                measurement = layout_cache.get(items, state["cursor"], multi, size)
                layout_changed = previous is not None and previous is not measurement

                # Input already reset the dwell and painted tick zero on a cursor move.
                if state["cursor"] != last_cursor:
                    last_cursor = state["cursor"]
                    last_rendered_tick = 0

                new_tick = 0
                if measurement.overflows:
                    elapsed = time.monotonic() - state["cursor_changed_at"]
                    if elapsed > _MARQUEE_DWELL_S:
                        new_tick = int((elapsed - _MARQUEE_DWELL_S) * _MARQUEE_RATE)

                need_redraw = content_changed or size_changed or layout_changed or (
                    measurement.overflows and new_tick != last_rendered_tick
                )
                if need_redraw:
                    state["tick"] = new_tick
                    last_rendered_tick = new_tick
            if need_redraw:
                draw(new_tick)

    display.enter_screen()

    watcher_thread = threading.Thread(target=watcher, daemon=True)
    watcher_thread.start()

    try:
        # Initial render
        draw(0)

        while True:
            try:
                key = readchar.readkey()
                frames.turn()
            except KeyboardInterrupt:
                # Some terminals raise for Ctrl+C instead of returning \x03.
                # Treat both forms exactly like Esc at the active selector.
                return None
            if refresh is not None:
                # A key acts on the list as it is now (a live list may have moved the focused
                # row), and the list holds still until the key is handled.
                with render_lock:
                    refresh_content()
                    cursor = state["cursor"]
                    state["holding"] = True
                if not items:
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
                        if on_action and aside(on_action, cursor, items):
                            pass  # Stay in the menu
                        else:
                            return cursor
                    else:
                        # Toggle/cycle the item
                        if items[cursor].enabled:
                            with render_lock:
                                items[cursor].cycle_toggle()
                                layout_cache.invalidate()
                else:
                    if items[cursor].enabled:
                        if items[cursor].passive:
                            pass  # Passive row: Enter is a no-op (scroll-view read-only)
                        elif items[cursor].is_action and on_action and aside(on_action, cursor, items):
                            pass  # Stay in the menu
                        else:
                            return cursor
            elif key == readchar.key.ESC:
                return None
            elif key in (readchar.key.CTRL_C, "\x03"):
                return None
            elif key == "?" and help_enabled:
                try:
                    aside(show_keys, _resolve(title), _resolve(help_footer) or _resolve(footer) or _default_footer(multi))
                except KeyboardInterrupt:
                    pass
            elif hotkeys and key in hotkeys:
                return ("hotkey", hotkeys[key], cursor)
            elif key_actions and key in key_actions:
                outcome = aside(key_actions[key], cursor, items)
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
            with render_lock:
                if cursor != prev_cursor:
                    state["tick"] = 0
                    state["cursor_changed_at"] = time.monotonic()
                state["cursor"] = cursor
                state["holding"] = False
            draw(state["tick"])

    finally:
        stop_event.set()
        watcher_thread.join(timeout=1)
        display.leave_screen(clear=True)  # a view underneath keeps the alternate screen

    return None
