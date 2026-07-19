"""Interactive table selection UI for torrent results."""

import math
import threading
import time
from dataclasses import dataclass

import readchar
from rich.cells import cell_len
from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from torrent_finder.constants import RESULTS_PER_PAGE, console
from torrent_finder.ui.layout import ellipsize_cells, marquee_cells
from torrent_finder.utils import format_size, leech_style, seed_style


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


def _table_layout(width: int, show_from: bool) -> _TableLayout:
    """Choose progressively smaller result columns for the terminal width."""
    full_min = 128 if show_from else 112
    if width >= full_min:
        fixed = 84 if show_from else 69
        return _TableLayout(
            "full", max(18, min(46, width - fixed)), True, show_from, True, True, True
        )
    if width >= 80:
        return _TableLayout(
            "medium", max(12, min(46, width - 57)), True, False, True, True, False
        )
    if width >= 52:
        return _TableLayout(
            "compact", max(10, width - 32), False, False, False, True, False
        )
    return _TableLayout(
        "minimal", max(8, width - 6), False, False, False, False, False
    )


def _selected_metadata(
    results: list[dict], selected_idx: int, layout: _TableLayout, show_from: bool
) -> Text:
    """Render metadata hidden by the active column layout for the selected row."""
    details = Text()
    if not (0 <= selected_idx < len(results)):
        return details

    item = results[selected_idx]
    parts: list[str] = []
    if not layout.source:
        parts.append(f"Source: {_source_label(item)}")
    if item.get("source") == "Knaben" and item.get("knaben_tracker"):
        parts.append(f"Origin: {item.get('knaben_tracker')}")
    if show_from and not layout.from_work and item.get("from_work"):
        parts.append(f"From: {item.get('from_work')}")
    if not layout.size:
        parts.append(f"Size: {format_size(int(item.get('size', 0) or 0))}")
    if not layout.seeds:
        parts.append(f"Seeds: {int(item.get('seeders', 0) or 0)}")
    if not layout.leeches:
        parts.append(f"Leeches: {int(item.get('leechers', 0) or 0)}")
    if parts:
        details.append("  " + "  |  ".join(parts) + "\n", style="dim")
    return details


def _table_caption(
    results: list[dict],
    selected_idx: int,
    layout: _TableLayout,
    show_from: bool,
    total_pages: int,
    picked: "frozenset[int]",
) -> Text:
    caption = _selected_metadata(results, selected_idx, layout, show_from)
    if any(item.get("apibay_cached_at") for item in results):
        caption.append(
            "  Apibay* = cached last-known-good results\n",
            style="yellow",
        )
    controls = " ↑/↓ navigate  |  Space select  |  a all  |  c clear"
    if total_pages > 1:
        controls += "  |  ←/→ page"
    controls += (
        f"  |  Enter download {len(picked)} selected"
        if picked
        else "  |  Enter open"
    )
    controls += "  |  Esc back"
    caption.append(controls, style="dim")
    caption.overflow = "fold"
    return caption


def _note_line_count(note: str, width: int) -> int:
    if not note:
        return 0
    return max(1, len(Text(note).wrap(console, max(8, width), overflow="fold")))


def _visible_count(
    total: int, height: int, width: int, note: str, show_from: bool
) -> int:
    """Return rows that fit after responsive caption and metadata lines."""
    layout = _table_layout(width, show_from)
    extra = {"full": 0, "medium": 1, "compact": 2, "minimal": 4}[layout.mode]
    available = max(1, height - 14 - _note_line_count(note, width) - extra)
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
) -> Table:
    """Build a result table whose columns progressively collapse by width."""
    width = console.size.width
    layout = _table_layout(width, show_from)
    end_idx = min(scroll_offset + visible_count, total)
    scroll_info = f"[dim]({scroll_offset + 1}-{end_idx} of {total})[/dim]"
    page_info = (
        f"  [bold cyan]Page {current_page + 1}/{total_pages}[/bold cyan]"
        if total_pages > 1
        else ""
    )
    selected_info = (
        f"  [bold green]✓ {len(picked)} selected[/bold green]" if picked else ""
    )

    table = Table(
        title=f"Torrent Results {scroll_info}{page_info}{selected_info}",
        title_style="bold magenta",
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=False,
        padding=(0, 1),
        caption=_table_caption(
            results, selected_idx, layout, show_from, total_pages, picked
        ),
        caption_style="dim",
    )

    if layout.mode == "minimal":
        table.add_column("Result", style="white", no_wrap=True, overflow="ellipsis")
    else:
        table.add_column("Sel", justify="center", width=5)
        table.add_column("#", style="bold white", justify="right", width=7)
        if layout.source:
            table.add_column("Source", style="magenta", width=9)
        if layout.from_work:
            table.add_column(
                "From", style="green", width=12, no_wrap=True, overflow="ellipsis"
            )
        table.add_column(
            "Name", style="white", width=layout.name_width, no_wrap=True
        )
        if layout.size:
            table.add_column("Size", style="cyan", justify="right", width=10)
        if layout.seeds:
            table.add_column("Seeds", justify="right", width=7)
        if layout.leeches:
            table.add_column("Leeches", justify="right", width=9)

    for visible_idx, item in enumerate(results[scroll_offset:end_idx]):
        index = scroll_offset + visible_idx
        global_index = global_offset + index
        seeds = int(item.get("seeders", 0) or 0)
        leeches = int(item.get("leechers", 0) or 0)
        size = int(item.get("size", 0) or 0)
        name = str(item.get("name", "Unknown"))
        is_selected = index == selected_idx

        display_name = (
            marquee_cells(name, layout.name_width, tick)
            if is_selected and cell_len(name) > layout.name_width
            else ellipsize_cells(name, layout.name_width)
        )

        if is_selected:
            row_style = "bold reverse"
            number = f">> {global_index}"
            seed_text = str(seeds)
            leech_text = str(leeches)
        else:
            row_style = "" if index % 2 == 0 else "dim"
            number = str(global_index)
            seed_text = f"[{seed_style(seeds)}]{seeds}[/{seed_style(seeds)}]"
            leech_text = f"[{leech_style(leeches)}]{leeches}[/{leech_style(leeches)}]"

        checked = global_index in picked
        if layout.mode == "minimal":
            result_cell = Text()
            result_cell.append("[✓]" if checked else "[ ]", style="green" if checked else "dim")
            result_cell.append(f"  {number}  ")
            result_cell.append(display_name)
            table.add_row(result_cell, style=row_style)
            continue

        check_text = "[green][✓][/green]" if checked else "[dim][ ][/dim]"
        cells: list[object] = [check_text, number]
        if layout.source:
            cells.append(Text(_source_label(item)))
        if layout.from_work:
            cells.append(Text(str(item.get("from_work", "") or "")))
        cells.append(Text(display_name))
        if layout.size:
            cells.append(format_size(size))
        if layout.seeds:
            cells.append(seed_text)
        if layout.leeches:
            cells.append(leech_text)
        table.add_row(*cells, style=row_style)

    return table


def _pick_result(picked: set[int]) -> tuple:
    """Map the checkbox set to the selector's return shape.

    Exactly one checked collapses to the single-torrent path (so a lone pick
    keeps the full per-torrent download menu); two or more is a batch.
    """
    idxs = sorted(picked)
    return ("one", idxs[0]) if len(idxs) == 1 else ("many", idxs)


def interactive_select(results: list[dict], note: str = "") -> "tuple | None":
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
    all_results = results
    total_all = len(all_results)
    # Provenance "From" column: only when results came from more than one searched
    # title (multi-title search); redundant for a single query.
    show_from = len({r.get("from_work") for r in all_results if r.get("from_work")}) > 1
    total_pages = math.ceil(total_all / RESULTS_PER_PAGE)
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

    # Reserve room for the banner, wrapping caption, and hidden metadata line.
    visible_count = _visible_count(
        total, console.size.height, console.size.width, note, show_from
    )

    scroll_offset = 0

    # Marquee state shared with the ticker thread
    marquee_state = {
        "tick": 0,
        "cursor_changed_at": time.monotonic(),
    }
    stop_event = threading.Event()

    # Render the app banner inside the alt-screen frame, with a 1-line spacer
    # between it and the table (lazy import avoids a circular import).
    from torrent_finder.ui.prompts import _make_banner_panel
    banner = _make_banner_panel()

    def framed(tbl):
        if note:
            note_line = Text(note, style="yellow", overflow="fold")
            return Group(banner, Text(""), note_line, tbl)
        return Group(banner, Text(""), tbl)

    # screen=True renders into the terminal's alternate-screen buffer — a fixed
    # viewport that never scrolls. Without it, Live updates (e.g. the marquee on
    # a long selected name) redraw on the scrolling main buffer and the bottom
    # caption flickers in and out. The flicker-free menu selector uses the same
    # alternate-screen trick.
    with Live(
        framed(build_table(
            page_items, current, scroll_offset, visible_count, total,
            current_page, total_pages, global_offset, tick=0,
            picked=frozenset(picked), show_from=show_from,
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
                if not (0 <= cur < len(page_items)):
                    continue

                if size_changed:
                    visible_count = _visible_count(
                        total,
                        current_size.height,
                        current_size.width,
                        note,
                        show_from,
                    )
                    if cur < scroll_offset:
                        scroll_offset = cur
                    elif cur >= scroll_offset + visible_count:
                        scroll_offset = max(0, cur - visible_count + 1)

                layout = _table_layout(current_size.width, show_from)
                name = str(page_items[cur].get("name", ""))
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
                        page_items, cur, scroll_offset, visible_count, total,
                        current_page, total_pages, global_offset, tick=new_tick,
                        picked=frozenset(picked), show_from=show_from,
                    ))
                )

        ticker_thread = threading.Thread(target=ticker, daemon=True)
        ticker_thread.start()

        try:
            while True:
                key = readchar.readkey()
                prev_current = current
                prev_page = current_page

                if key == readchar.key.UP:
                    current = max(0, current - 1)
                    num_buffer = ""
                elif key == readchar.key.DOWN:
                    current = min(total - 1, current + 1)
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
                        )
                    num_buffer = ""
                elif key == " ":
                    gi = global_offset + current
                    if gi in picked:
                        picked.discard(gi)
                    else:
                        picked.add(gi)
                    num_buffer = ""
                elif key in ("a", "A"):
                    picked.update(range(total_all))
                    num_buffer = ""
                elif key in ("c", "C"):
                    picked.clear()
                    num_buffer = ""
                elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                    if picked:
                        return _pick_result(picked)
                    return ("one", global_offset + current)
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
                        idx = int(num_buffer)
                        if 0 <= idx < total:
                            current = idx
                        if idx >= total and idx * 10 > total * 10:
                            num_buffer = key
                            idx = int(key)
                            if 0 <= idx < total:
                                current = idx
                    except ValueError:
                        num_buffer = ""
                else:
                    num_buffer = ""

                # Keep cursor visible: adjust scroll_offset to follow current
                if current < scroll_offset:
                    scroll_offset = current
                elif current >= scroll_offset + visible_count:
                    scroll_offset = current - visible_count + 1

                # Reset marquee on selection or page change
                if current != prev_current or current_page != prev_page:
                    marquee_state["tick"] = 0
                    marquee_state["cursor_changed_at"] = time.monotonic()

                live.update(
                    framed(build_table(
                        page_items, current, scroll_offset, visible_count, total,
                        current_page, total_pages, global_offset,
                        tick=marquee_state["tick"],
                        picked=frozenset(picked), show_from=show_from,
                    ))
                )
        finally:
            stop_event.set()
            ticker_thread.join(timeout=1)

    return None
