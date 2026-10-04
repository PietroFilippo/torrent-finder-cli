"""Interactive table selection UI for torrent results."""

import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import readchar
from rich.cells import cell_len
from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from torrent_finder.constants import RESULTS_PER_PAGE, console
from torrent_finder.ui import theme
from torrent_finder.ui.layout import ellipsize_cells, marquee_cells
from torrent_finder.utils import format_size, leech_style, seed_style
from torrent_finder.result_view import SORT_ORDERS, result_indices, timestamp
from torrent_finder.ui.result_filters import refine_results
from torrent_finder.result_details import detail_lines


# Marquee timing for the selected-row name
_MARQUEE_DWELL_S = 1.0
_MARQUEE_RATE = 6           # chars/sec
_TICK_INTERVAL_S = 0.12


def _source_label(item: dict) -> str:
    source = str(item.get("source") or "Unknown")
    return f"{source}*" if item.get("apibay_cached_at") else source


@dataclass(frozen=True)
class _TableLayout:
    mode: str
    name_width: int
    source: bool
    from_work: bool
    size: bool
    seeds: bool
    leeches: bool
    provider: bool = False
    age: bool = False


# Borderless columns: widths in cells. Rich pads every cell by one, so
# neighbouring cells are two apart and the table edges carry one cell each:
# with the gutter's own space the left margin is two cells, and the right
# margin reserves two (the edge cell plus one).
_GUTTER_W, _SOURCE_W, _PROVIDER_W, _FROM_W = 3, 9, 14, 12
_SIZE_W, _SEEDS_W, _LEECHES_W, _AGE_W = 9, 6, 7, 4
_RIGHT_MARGIN = 3


def _fixed(*widths: int) -> int:
    """Cells used by the given fixed columns, the name's padding and the right margin."""
    return sum(widths) + 2 * len(widths) + _RIGHT_MARGIN


def _lead_width(digits: int) -> int:
    """The first column: a space, cursor bar, check mark, a space, the row number."""
    return _GUTTER_W + 1 + digits


def _index_digits(indexes) -> int:
    return len(str(max(indexes))) if indexes else 1


def _table_layout(width: int, show_from: bool, show_provider: bool = False,
                  show_age: bool = False, digits: int = 2) -> _TableLayout:
    """Choose progressively smaller result columns for the terminal width."""
    lead = _lead_width(digits)
    full = [lead, _SOURCE_W, _SIZE_W, _SEEDS_W, _LEECHES_W]
    if show_provider:
        full.append(_PROVIDER_W)
    if show_from:
        full.append(_FROM_W)
    if show_age:
        full.append(_AGE_W)
    if width - _fixed(*full) >= 36:
        return _TableLayout(
            "full", width - _fixed(*full), True, show_from, True, True, True, show_provider, show_age
        )
    medium = _fixed(lead, _SOURCE_W, _SIZE_W, _SEEDS_W)
    if width - medium >= 29:
        return _TableLayout("medium", width - medium, True, False, True, True, False)
    compact = _fixed(lead, _SEEDS_W)
    if width - compact >= 25:
        return _TableLayout("compact", width - compact, False, False, False, True, False)
    return _TableLayout(
        "minimal", max(8, width - _RIGHT_MARGIN - lead - 2), False, False, False, False, False
    )


def _page_layout(rows: list[dict], width: int, show_from: bool, indexes=()) -> _TableLayout:
    """The layout build_table draws for these rows; marquee and detail scrolling share it.

    *indexes* are the row numbers the page shows; they set the number column's width.
    """
    return _table_layout(width, show_from, any(r.get("provider_slug") for r in rows),
                         any(timestamp(r.get("uploaded_at")) for r in rows), _index_digits(indexes))


def _pack(parts: list[str], width: int) -> list[str]:
    """Join *parts* with " · " into lines of *width* cells; a part never splits."""
    lines: list[str] = []
    for part in parts:
        if lines and cell_len(lines[-1]) + 3 + cell_len(part) <= width:
            lines[-1] += " · " + part
        else:
            lines.append(part)
    return lines


def _age(uploaded: int, now: float | None = None) -> str:
    """Compact upload age: 5h, 3d, 2w, 7mo, 1y; empty when unknown."""
    if not uploaded:
        return ""
    seconds = max(0, (now if now is not None else time.time()) - uploaded)
    hours = seconds / 3600
    if hours < 24:
        return f"{max(1, int(hours))}h"
    days = hours / 24
    if days < 14:
        return f"{int(days)}d"
    if days < 60:
        return f"{int(days // 7)}w"
    if days < 730:
        return f"{int(days // 30)}mo"
    return f"{int(days // 365)}y"


def _selected_metadata(
    results: list[dict], selected_idx: int, layout: _TableLayout, show_from: bool
) -> Text:
    """Render metadata hidden by the active column layout for the selected row."""
    details = Text()
    if not (0 <= selected_idx < len(results)):
        return details

    item = results[selected_idx]
    room = theme.inner_width(console.size.width)
    parts: list[str] = []
    if item.get("provider_label"):
        for line in _pack([f"Provider: {item['provider_label']}", f"Source: {_source_label(item)}"], room):
            details.append(f"{theme.MARGIN}{line}\n", style=theme.MUTED)
    uploaded = timestamp(item.get("uploaded_at"))
    parts.append("Uploaded: " + (datetime.fromtimestamp(uploaded, timezone.utc).strftime("%Y-%m-%d") if uploaded else "unknown"))
    if not layout.source and not item.get("provider_label"):
        parts.append(f"Source: {_source_label(item)}")
    if item.get("source") == "Knaben" and item.get("knaben_tracker"):
        parts.append(f"Knaben tracker: {item.get('knaben_tracker')}")
    if show_from and not layout.from_work and item.get("from_work"):
        parts.append(f"From: {item.get('from_work')}")
    if not layout.size:
        parts.append(f"Size: {format_size(int(item.get('size', 0) or 0))}")
    if not layout.seeds:
        parts.append(f"Seeds: {int(item.get('seeders', 0) or 0)}")
    if not layout.leeches:
        parts.append(f"Leeches: {int(item.get('leechers', 0) or 0)}")
    for line in _pack(parts, room):
        details.append(theme.MARGIN + line + "\n", style=theme.MUTED)
    return details


def _wrapped_details(item, layout):
    width = max(8, console.size.width - 12) if layout.mode == "minimal" else layout.name_width
    return Text("\n".join(detail_lines(item))).wrap(console, width)


def _detail_count():
    # Leave a line for the compact search-notice banner, including bookmarks.
    return max(2, min(8, console.size.height // 4) - 1)


def _result_keys(total_pages: int, picked: "frozenset[int]", expanded: bool = False) -> str:
    """The results key bar as plain text (it contains "[/]"), most frequent keys first."""
    if expanded:
        return "i close • [/] scroll details • b bookmark • Esc back"
    enter = f"Enter download {len(picked)} selected" if picked else "Enter open"
    if console.size.width < 52:
        enter = f"Enter download {len(picked)}" if picked else "Enter open"
        keys = f"↑/↓ move • Space pick • {enter} • i details • b save • f refine"
    else:
        keys = f"↑/↓ navigate • Space select • {enter} • i details • f refine/sort • b bookmark"
    keys += " • a all • c clear"
    if total_pages > 1:
        keys += " • ←/→ page"
    return keys + " • Esc back"


def _table_caption(
    results: list[dict],
    selected_idx: int,
    layout: _TableLayout,
    show_from: bool,
    total_pages: int,
    picked: "frozenset[int]",
    expanded: bool = False,
) -> Text:
    """Details for the focused row, then the key bar, under the left margin."""
    width = console.size.width
    caption = Text(no_wrap=False, overflow="fold")
    if not expanded and 0 <= selected_idx < len(results):
        name = ellipsize_cells(str(results[selected_idx].get("name", "Unknown")),
                               theme.inner_width(width))
        caption.append("\n" + theme.MARGIN + name + "\n", style="bold")
        caption.append_text(_selected_metadata(results, selected_idx, layout, show_from))
    if not expanded and any(item.get("apibay_cached_at") for item in results):
        caption.append(theme.MARGIN + "Apibay* = cached last-known-good results\n", style=theme.WARN)
    if console.size.height >= 20:
        caption.append("\n")  # short windows keep the row for results
    caption.append_text(Text("\n").join(theme.wrap_keys(
        theme.parse_footer(Text(_result_keys(total_pages, picked, expanded))).keys, width)))
    return caption


def _note_preview(note: str) -> Text:
    """Keep partial-search notices from crowding results out of short windows."""
    count = len(note.splitlines())
    if console.size.height < 28 or count > 2:
        return Text(f"{theme.MARGIN}{count} search notice{'s' if count != 1 else ''} — n to read",
                    style=theme.WARN, no_wrap=True, overflow="ellipsis")
    preview = Text(style=theme.WARN, overflow="fold")
    for line in note.splitlines():
        preview.append(theme.MARGIN + line + "\n")
    preview.append(theme.MARGIN + "n: read search notices")
    return preview


def _show_search_notices(note: str) -> None:
    from rich.markup import escape
    from torrent_finder.ui.selector import SelectItem, arrow_select
    items = [SelectItem(line.split(":", 1)[0], description=escape(line), passive=True)
             for line in note.splitlines() if line.strip()]
    items.append(SelectItem("Back to results", is_action=True))
    arrow_select(items, title="Search notices", footer="↑/↓ read notices • Esc back to results")


def _note_line_count(note: str, width: int) -> int:
    if not note:
        return 0
    return max(1, len(_note_preview(note).wrap(console, max(8, width))))


_METADATA_LINES = {"full": 1, "medium": 1, "compact": 2, "minimal": 3}


def _visible_count(
    total: int, height: int, width: int, note: str, show_from: bool, show_provider: bool = False,
    heading: str = "",
) -> int:
    """Return rows that fit after the header, notices, details and key bar."""
    layout = _table_layout(width, show_from, show_provider)
    header = len(theme.header_lines(heading or "Results", "888–888 of 888 · page 88/88 · 888 picked", width))
    compact = height < 20
    keys = len(theme.wrap_keys(theme.parse_footer(
        Text(_result_keys(2, frozenset(range(100))))).keys, width))
    chrome = (
        header + (0 if compact else 1)       # header lines, spacer
        + 1 + _note_line_count(note, width)  # view status, notices
        + 1                                  # table header row
        + 1 + 1 + _METADATA_LINES[layout.mode] + (2 if show_provider else 0)  # spacer, name, metadata
        + 1 + (0 if compact else 1) + keys   # cached-results note, spacer, keys
    )
    available = max(1, height - chrome)
    return min(total, available)


def build_table(
    results: list[dict],
    selected_idx: int,
    scroll_offset: int,
    visible_count: int,
    total: int,
    current_page: int = 0,
    total_pages: int = 1,
    global_offset: int = 0,
    tick: int = 0,
    picked: "frozenset[int]" = frozenset(),
    show_from: bool = False,
    original_indices: list[int] | None = None,
    expanded: bool = False,
    detail_offset: int = 0,
) -> Table:
    """Build a borderless result table whose columns collapse by width."""
    width = console.size.width
    page_indexes = (original_indices if original_indices is not None
                    else range(global_offset, global_offset + max(total, 1)))
    digits = _index_digits(page_indexes)
    layout = _page_layout(results, width, show_from, page_indexes)
    end_idx = min(scroll_offset + visible_count, total)
    table = Table(
        box=None,
        show_edge=False,
        pad_edge=False,
        padding=(0, 1),
        header_style=f"bold {theme.MUTED}",
        show_lines=False,
        width=width - 1 if layout.mode == "minimal" else None,
        caption=_table_caption(
            results, selected_idx, layout, show_from, total_pages, picked, expanded
        ),
        caption_justify="left",
    )
    if not total:
        notice = Text(f"\n{theme.MARGIN}No matching results — f to refine\n", style=theme.WARN)
        notice.append_text(table.caption)
        table.caption = notice

    if layout.mode == "minimal":
        table.add_column("Result", no_wrap=not expanded, overflow="fold" if expanded else "ellipsis")
    else:
        table.add_column("#", justify="right", width=_lead_width(digits), no_wrap=True)
        if layout.source:
            table.add_column("Source", style=theme.MUTED, width=_SOURCE_W, no_wrap=True, overflow="ellipsis")
        if layout.provider:
            table.add_column("Provider", width=_PROVIDER_W, no_wrap=True, overflow="ellipsis")
        if layout.from_work:
            table.add_column("From", width=_FROM_W, no_wrap=True, overflow="ellipsis")
        table.add_column("Name", width=layout.name_width, no_wrap=not expanded)
        if layout.size:
            table.add_column("Size", justify="right", width=_SIZE_W, no_wrap=True)
        if layout.seeds:
            table.add_column("Seeds", justify="right", width=_SEEDS_W, no_wrap=True)
        if layout.leeches:
            table.add_column("Leeches", justify="right", width=_LEECHES_W, no_wrap=True)
        if layout.age:
            table.add_column("Age", justify="right", style=theme.MUTED, width=_AGE_W, no_wrap=True)

    now = time.time()
    for visible_idx, item in enumerate(results[scroll_offset:end_idx]):
        index = scroll_offset + visible_idx
        global_index = original_indices[index] if original_indices is not None else global_offset + index
        seeds = int(item.get("seeders", 0) or 0)
        leeches = int(item.get("leechers", 0) or 0)
        size = int(item.get("size", 0) or 0)
        name = str(item.get("name", "Unknown"))
        if item.get("provider_label") and not layout.provider:
            name = f"{item['provider_label']} · {name}"
        is_selected = index == selected_idx
        checked = global_index in picked

        display_name = (
            marquee_cells(name, layout.name_width, tick)
            if is_selected and cell_len(name) > layout.name_width
            else ellipsize_cells(name, layout.name_width)
        )
        lead = Text(" ")
        lead.append(theme.CURSOR if is_selected else " ", style=theme.ACCENT)
        lead.append(theme.CHECK if checked else " ", style=theme.GOOD)
        lead.append(f" {global_index:>{digits}}")

        name_cell = Text(display_name)
        if expanded and is_selected:
            lines = _wrapped_details(item, layout)
            count = _detail_count()
            offset = min(detail_offset, max(0, len(lines) - count))
            name_cell.append(f"\nDetails {offset + 1}-{min(len(lines), offset + count)}/{len(lines)} ([/])",
                             style=theme.ACCENT)
            for line in lines[offset:offset + count]:
                name_cell.append("\n")
                name_cell.append(line)
        row_style = theme.FOCUS if is_selected else ""
        seed_text = Text(str(seeds), style=seed_style(seeds))
        leech_text = Text(str(leeches), style=leech_style(leeches))

        if layout.mode == "minimal":
            result_cell = Text()
            result_cell.append_text(lead)
            result_cell.append("  ")
            result_cell.append_text(name_cell)
            table.add_row(result_cell, style=row_style)
            continue

        cells: list[object] = [lead]
        if layout.source:
            cells.append(Text(_source_label(item)))
        if layout.provider:
            cells.append(Text(str(item.get("provider_label", ""))))
        if layout.from_work:
            cells.append(Text(str(item.get("from_work", "") or "")))
        cells.append(name_cell)
        if layout.size:
            cells.append(format_size(size))
        if layout.seeds:
            cells.append(seed_text)
        if layout.leeches:
            cells.append(leech_text)
        if layout.age:
            cells.append(_age(timestamp(item.get("uploaded_at")), now))
        table.add_row(*cells, style=row_style)

    return table


def results_status(scroll_offset: int, visible_count: int, total: int, current_page: int,
                   total_pages: int, picked: "frozenset[int]") -> str:
    """Header status: visible rows, page and picks."""
    if not total:
        return "no matching results"
    end_idx = min(scroll_offset + visible_count, total)
    parts = [f"{scroll_offset + 1}–{end_idx} of {total}"]
    if total_pages > 1:
        parts.append(f"page {current_page + 1}/{total_pages}")
    if picked:
        parts.append(f"{len(picked)} picked")
    return " · ".join(parts)


def _pick_result(picked: set[int]) -> tuple:
    """Map the checkbox set to the selector's return shape.

    Exactly one checked collapses to the single-torrent path (so a lone pick
    keeps the full per-torrent download menu); two or more is a batch.
    """
    idxs = sorted(picked)
    return ("one", idxs[0]) if len(idxs) == 1 else ("many", idxs)


def interactive_select(results: list[dict], note: str = "", *, initial_order: str = "relevance",
                       search_summary: str = "", on_bookmark=None, heading: str = "") -> "tuple | None":
    """Interactive torrent results table with multi-select.

    Navigate with arrows; Left/Right switch pages; type a number to jump.
    Space toggles a row's checkbox; ``a`` selects every result, ``c`` clears.
    ``note`` is an optional line shown above the table (e.g. which multi-search
    titles returned nothing). Returns:
      - ``("one", global_idx)`` — Enter with nothing checked (open that row), or
        Enter/``d`` with exactly one checked;
      - ``("many", [global_idx, ...])`` — Enter/``d`` with two or more checked
        (batch hand-off);
      - ``None`` if cancelled (Esc).
    """
    view_query, view_mode, view_order = "", "contains", initial_order
    session = getattr(results, "session", None)
    if session is not None:
        # Reserve one compact line for diagnostics/actions even with zero rows.
        note = note or "Search diagnostics"
    view_indexes = result_indices(results, order=view_order)
    all_results = [results[i] for i in view_indexes]
    total_all = len(all_results)
    # Provenance "From" column: only when results came from more than one searched
    # title (multi-title search); redundant for a single query.
    show_from = len({r.get("from_work") for r in all_results if r.get("from_work")}) > 1
    show_provider = any(r.get("provider_slug") for r in all_results)
    total_pages = max(1, math.ceil(total_all / RESULTS_PER_PAGE))
    current_page = 0

    def page_results():
        start = current_page * RESULTS_PER_PAGE
        end = start + RESULTS_PER_PAGE
        return all_results[start:end]

    # Current selection index (local to the page)
    current = 0
    num_buffer = ""
    # Checkbox multi-select: global indexes the user has ticked. Persists across
    # page flips (it stores global indexes, not page-local ones).
    picked: set[int] = set()
    page_items = page_results()
    total = len(page_items)
    global_offset = current_page * RESULTS_PER_PAGE

    # Reserve room for the header, notices, details and key bar.
    visible_count = _visible_count(
        total, console.size.height, console.size.width, note, show_from, show_provider, heading=heading
    )

    scroll_offset = 0
    expanded, detail_offset, saved_scroll = False, 0, 0
    feedback = ""

    # Marquee state shared with the ticker thread
    marquee_state = {
        "tick": 0,
        "cursor_changed_at": time.monotonic(),
    }
    stop_event = threading.Event()

    def framed(tbl):
        """The whole results screen: header, view line, notices, table, details, keys."""
        status = results_status(current if expanded else scroll_offset, 1 if expanded else visible_count,
                                total, current_page, total_pages, frozenset(picked))
        parts: list[object] = list(theme.header_lines(heading or "Results", status, console.size.width))
        if console.size.height >= 20:
            parts.append(Text(""))
        order_label = SORT_ORDERS.get(view_order, view_order)
        if view_order != "relevance":
            order_label += " (overrides preferences)"
        view_status = Text(theme.MARGIN + f"Sort: {order_label} • {view_mode}: {view_query or 'all names'}"
                           + (f" • {search_summary}" if search_summary else ""),
                           style=theme.MUTED, no_wrap=True, overflow="ellipsis")
        if feedback:
            view_status = Text(theme.MARGIN + feedback, style=theme.WARN, no_wrap=True, overflow="ellipsis")
        if session is not None:
            failures = sum(d.retryable for d in session.diagnostics)
            retry_label = f"r retry ({failures})" if failures else "r retry"
            controls = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
            for i, segment in enumerate(theme.parse_footer(f"n diagnostics • {retry_label} • m more").keys):
                if i:
                    controls.append(theme.KEY_GAP)
                controls.append_text(segment)
            if not results and not feedback:
                view_status = Text(theme.MARGIN + "No results • n explains the search", style=theme.WARN,
                                   no_wrap=True, overflow="ellipsis")
            return Group(*parts, view_status, controls, tbl)
        if note:
            return Group(*parts, view_status, _note_preview(note), tbl)
        return Group(*parts, view_status, tbl)

    # screen=True renders into the terminal's alternate-screen buffer — a fixed
    # viewport that never scrolls. Without it, Live updates (e.g. the marquee on
    # a long selected name) redraw on the scrolling main buffer and the bottom
    # caption flickers in and out. The flicker-free menu selector uses the same
    # alternate-screen trick.
    with Live(
        framed(build_table(
            page_items, current, current if expanded else scroll_offset, 1 if expanded else visible_count, total,
            current_page, total_pages, global_offset, tick=0,
            picked=frozenset(picked), show_from=show_from,
            original_indices=view_indexes[global_offset:global_offset + total],
            expanded=expanded, detail_offset=detail_offset,
        )),
        console=console,
        refresh_per_second=15,
        transient=False,
        screen=True,
    ) as live:

        def ticker():
            nonlocal scroll_offset, visible_count
            last_tick = 0
            previous_size = console.size
            while not stop_event.is_set():
                if stop_event.wait(_TICK_INTERVAL_S):
                    break

                current_size = console.size
                size_changed = current_size != previous_size
                previous_size = current_size
                cur = current
                has_current = 0 <= cur < len(page_items)

                if size_changed:
                    visible_count = _visible_count(
                        total,
                        current_size.height,
                        current_size.width,
                        note,
                        show_from,
                        show_provider,
                        heading=heading,
                    )
                    if cur < scroll_offset:
                        scroll_offset = cur
                    elif cur >= scroll_offset + visible_count:
                        scroll_offset = max(0, cur - visible_count + 1)

                layout = _page_layout(page_items, current_size.width, show_from,
                                      view_indexes[global_offset:global_offset + total])
                name = str(page_items[cur].get("name", "")) if has_current else ""
                if has_current and show_provider and not layout.provider:
                    name = f"{page_items[cur].get('provider_label', '')} · {name}"
                tick_changed = False
                new_tick = 0
                if cell_len(name) > layout.name_width:
                    elapsed = time.monotonic() - marquee_state["cursor_changed_at"]
                    if elapsed > _MARQUEE_DWELL_S:
                        new_tick = int(
                            (elapsed - _MARQUEE_DWELL_S) * _MARQUEE_RATE
                        )
                    tick_changed = new_tick != last_tick
                elif last_tick:
                    tick_changed = True

                if not size_changed and not tick_changed:
                    continue
                last_tick = new_tick
                marquee_state["tick"] = new_tick
                live.update(
                    framed(build_table(
                        page_items, cur, cur if expanded else scroll_offset, 1 if expanded else visible_count, total,
                        current_page, total_pages, global_offset, tick=new_tick,
                        picked=frozenset(picked), show_from=show_from,
                        original_indices=view_indexes[global_offset:global_offset + total],
                        expanded=expanded, detail_offset=detail_offset,
                    ))
                )

        ticker_thread = threading.Thread(target=ticker, daemon=True)
        ticker_thread.start()

        try:
            while True:
                try:
                    key = readchar.readkey()
                except KeyboardInterrupt:
                    # Some terminals raise for Ctrl+C instead of returning
                    # the CTRL_C key code handled below.
                    return None
                prev_current = current
                prev_page = current_page

                if key == readchar.key.UP:
                    current = max(0, current - 1)
                    num_buffer = ""
                elif key == readchar.key.DOWN:
                    current = max(0, min(total - 1, current + 1))
                    num_buffer = ""
                elif key == readchar.key.LEFT:
                    if current_page > 0:
                        current_page -= 1
                        page_items = page_results()
                        total = len(page_items)
                        global_offset = current_page * RESULTS_PER_PAGE
                        current = 0
                        scroll_offset = 0
                        visible_count = _visible_count(
                            total,
                            console.size.height,
                            console.size.width,
                            note,
                            show_from,
                            show_provider,
                            heading=heading,
                        )
                    num_buffer = ""
                elif key == readchar.key.RIGHT:
                    if current_page < total_pages - 1:
                        current_page += 1
                        page_items = page_results()
                        total = len(page_items)
                        global_offset = current_page * RESULTS_PER_PAGE
                        current = 0
                        scroll_offset = 0
                        visible_count = _visible_count(
                            total,
                            console.size.height,
                            console.size.width,
                            note,
                            show_from,
                            show_provider,
                            heading=heading,
                        )
                    num_buffer = ""
                elif key == " ":
                    if not total:
                        continue
                    gi = view_indexes[global_offset + current]
                    if gi in picked:
                        picked.discard(gi)
                    else:
                        picked.add(gi)
                    num_buffer = ""
                elif key in ("a", "A"):
                    picked.update(view_indexes)
                    num_buffer = ""
                elif key in ("c", "C"):
                    picked.clear()
                    num_buffer = ""
                elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                    if picked:
                        return _pick_result(picked)
                    if total:
                        return ("one", view_indexes[global_offset + current])
                elif key in ("i", "I") and total:
                    expanded = not expanded
                    detail_offset = 0
                    if expanded:
                        saved_scroll = scroll_offset
                        scroll_offset = current
                    else:
                        scroll_offset = saved_scroll
                elif key in ("[", "]") and expanded:
                    layout = _page_layout(page_items, console.size.width, show_from,
                                          view_indexes[global_offset:global_offset + total])
                    limit = max(0, len(_wrapped_details(page_items[current], layout)) - _detail_count())
                    detail_offset = min(limit, max(0, min(limit, detail_offset) + (1 if key == "]" else -1)))
                elif key in ("b", "B") and on_bookmark and total:
                    ids = sorted(picked) if picked else [view_indexes[global_offset + current]]
                    try:
                        feedback = on_bookmark([results[i] for i in ids])
                    except (OSError, ValueError) as error:
                        feedback = "Bookmark not saved: " + str(error)
                elif key.lower() in ("n", "r", "m") and session is not None:
                    from torrent_finder.ui.search_diagnostics import diagnostics_menu, run_action
                    from torrent_finder.providers.combined_provider import result_identity
                    selected_id = result_identity(page_items[current]) if total else None
                    checked_ids = {result_identity(results[i]) for i in picked}
                    stop_event.set()
                    ticker_thread.join(timeout=1)
                    live.stop()
                    try:
                        action = diagnostics_menu(session) if key.lower() == "n" else "retry" if key.lower() == "r" else "more"
                        if action:
                            available = session.can_retry if action == "retry" else session.can_load_more
                            if available:
                                updated, error = run_action(session, action)
                                if updated is not None:
                                    old_count = len(results)
                                    results[:] = updated
                                    results.notices = updated.notices
                                    feedback = f"{len(results) - old_count} added • {len(results)} total • n: diagnostics"
                                if error:
                                    feedback = error
                            else:
                                feedback = "No failed sources to retry" if action == "retry" else "No more pages available • n: details"
                    except KeyboardInterrupt:
                        pass
                    view_indexes = result_indices(results, view_query, view_mode, view_order)
                    all_results = [results[i] for i in view_indexes]
                    picked = {i for i in view_indexes if result_identity(results[i]) in checked_ids}
                    total_all = len(all_results)
                    total_pages = max(1, math.ceil(total_all / RESULTS_PER_PAGE))
                    position = next((i for i, row in enumerate(all_results) if result_identity(row) == selected_id), 0)
                    current_page, current = divmod(position, RESULTS_PER_PAGE)
                    global_offset = current_page * RESULTS_PER_PAGE
                    page_items = page_results()
                    total = len(page_items)
                    show_from = len({r.get("from_work") for r in all_results if r.get("from_work")}) > 1
                    show_provider = any(r.get("provider_slug") for r in all_results)
                    visible_count = _visible_count(total, console.size.height, console.size.width, note, show_from, show_provider, heading=heading)
                    scroll_offset = min(scroll_offset, max(0, total - visible_count))
                    num_buffer = ""
                    # These are identity-preserving changes, not a user move.
                    prev_page, prev_current = current_page, current
                    live.start()
                    stop_event.clear()
                    ticker_thread = threading.Thread(target=ticker, daemon=True)
                    ticker_thread.start()
                elif key in ("n", "N") and note:
                    stop_event.set()
                    ticker_thread.join(timeout=1)
                    live.stop()
                    try:
                        _show_search_notices(note)
                    except KeyboardInterrupt:
                        pass
                    visible_count = _visible_count(total, console.size.height, console.size.width, note, show_from, show_provider, heading=heading)
                    live.start()
                    stop_event.clear()
                    ticker_thread = threading.Thread(target=ticker, daemon=True)
                    ticker_thread.start()
                elif key in ("f", "F"):
                    num_buffer = ""
                    # Stop background redraws while the modal owns the terminal.
                    stop_event.set()
                    ticker_thread.join(timeout=1)
                    live.stop()
                    try:
                        view_query, view_mode, view_order = refine_results(view_query, view_mode, view_order)
                    except KeyboardInterrupt:
                        pass
                    view_indexes = result_indices(results, view_query, view_mode, view_order)
                    all_results = [results[i] for i in view_indexes]
                    picked.intersection_update(view_indexes)
                    total_all = len(all_results)
                    total_pages = max(1, math.ceil(total_all / RESULTS_PER_PAGE))
                    current_page = current = scroll_offset = global_offset = 0
                    page_items = page_results()
                    total = len(page_items)
                    visible_count = _visible_count(total, console.size.height, console.size.width, note, show_from, show_provider, heading=heading)
                    marquee_state["tick"] = 0
                    marquee_state["cursor_changed_at"] = time.monotonic()
                    live.start()
                    stop_event.clear()
                    ticker_thread = threading.Thread(target=ticker, daemon=True)
                    ticker_thread.start()
                elif key in ("d", "D"):
                    if picked:
                        return _pick_result(picked)
                    num_buffer = ""
                elif key == readchar.key.ESC:
                    return None
                elif key in (readchar.key.CTRL_C,):
                    return None
                elif key.isdigit():
                    num_buffer += key
                    try:
                        if not any(str(i).startswith(num_buffer) for i in view_indexes):
                            num_buffer = key
                        original = int(num_buffer)
                        if original in view_indexes:
                            position = view_indexes.index(original)
                            current_page, current = divmod(position, RESULTS_PER_PAGE)
                            page_items = page_results()
                            total = len(page_items)
                            global_offset = current_page * RESULTS_PER_PAGE
                            visible_count = _visible_count(total, console.size.height, console.size.width, note, show_from, show_provider, heading=heading)
                            if current_page != prev_page:
                                scroll_offset = 0
                    except ValueError:
                        num_buffer = ""
                else:
                    num_buffer = ""

                # A refined, retried or extended view may have no current row:
                # details stay open only while there is a row to show them for.
                current = min(current, max(0, total - 1))
                if expanded and not total:
                    expanded, detail_offset, scroll_offset = False, 0, 0

                # Keep cursor visible: adjust scroll_offset to follow current
                if current < scroll_offset:
                    scroll_offset = current
                elif current >= scroll_offset + visible_count:
                    scroll_offset = current - visible_count + 1

                # Reset marquee on selection or page change
                if current != prev_current or current_page != prev_page:
                    detail_offset = 0
                    feedback = ""
                    marquee_state["tick"] = 0
                    marquee_state["cursor_changed_at"] = time.monotonic()

                live.update(
                    framed(build_table(
                        page_items, current, current if expanded else scroll_offset, 1 if expanded else visible_count, total,
                        current_page, total_pages, global_offset,
                        tick=marquee_state["tick"],
                        picked=frozenset(picked), show_from=show_from,
                        original_indices=view_indexes[global_offset:global_offset + total],
                        expanded=expanded, detail_offset=detail_offset,
                    ))
                )
        finally:
            stop_event.set()
            ticker_thread.join(timeout=1)

    return None
