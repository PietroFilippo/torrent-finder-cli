"""Interactive table selection UI for torrent results."""

import math
import threading
import time

import readchar
from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from constants import RESULTS_PER_PAGE, console
from utils import format_size, leech_style, marquee, seed_style


# Marquee timing for the selected-row name
_NAME_COL_WIDTH = 46
_MARQUEE_DWELL_S = 1.0
_MARQUEE_RATE = 6           # chars/sec
_TICK_INTERVAL_S = 0.12


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
    """Build a rich table showing only the visible window of rows.

    ``picked`` is the set of *global* indexes the user has checkbox-selected
    (multi-select); their rows show a ✓ and the count surfaces in the title.
    ``show_from`` adds a "From" column with each row's ``from_work`` provenance
    (which searched title found it) — used for multi-title searches.
    """
    # Scroll indicator in the title
    end_idx = min(scroll_offset + visible_count, total)
    scroll_info = f"[dim]({scroll_offset + 1}-{end_idx} of {total})[/dim]"

    # Page indicator (only show when there are multiple pages)
    page_info = ""
    if total_pages > 1:
        page_info = f"  [bold cyan]Page {current_page + 1}/{total_pages}[/bold cyan]"

    sel_info = f"  [bold green]✓ {len(picked)} selected[/bold green]" if picked else ""

    table = Table(
        title=f"Torrent Results {scroll_info}{page_info}{sel_info}",
        title_style="bold magenta",
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=False,
        padding=(0, 1),
        caption=(
            "[dim] ↑/↓ navigate  |  Space select  |  a all  |  c clear"
            + ("  |  ←/→ page" if total_pages > 1 else "")
            + (f"  |  Enter download {len(picked)} selected" if picked else "  |  Enter open")
            + "  |  Esc back[/dim]"
        ),
        caption_style="dim",
    )

    table.add_column("Sel", justify="center", width=5)
    table.add_column("#", style="bold white", justify="right", width=7)
    table.add_column("Source", style="magenta", width=9)
    if show_from:
        table.add_column("From", style="green", width=12, no_wrap=True, overflow="ellipsis")
    table.add_column("Name", style="white", max_width=_NAME_COL_WIDTH, no_wrap=True)
    table.add_column("Size", style="cyan", justify="right", width=10)
    table.add_column("Seeds", justify="right", width=7)
    table.add_column("Leeches", justify="right", width=9)

    # Only render the visible slice
    visible_slice = results[scroll_offset:end_idx]

    for vi, item in enumerate(visible_slice):
        i = scroll_offset + vi  # Local index within the page
        global_i = global_offset + i  # Global index across all results
        seeds = int(item.get("seeders", 0))
        leeches = int(item.get("leechers", 0))
        size = int(item.get("size", 0))
        name = item.get("name", "Unknown")

        is_selected = i == selected_idx

        # Marquee the selected row's name when it overflows the column
        display_name = name
        if is_selected and len(name) > _NAME_COL_WIDTH:
            display_name = marquee(name, _NAME_COL_WIDTH, tick)

        if is_selected:
            row_style = "bold reverse"
            num_text = f">> {global_i}"
            seed_text = str(seeds)
            leech_text = str(leeches)
        else:
            row_style = "" if i % 2 == 0 else "dim"
            num_text = str(global_i)
            seed_text = f"[{seed_style(seeds)}]{seeds}[/{seed_style(seeds)}]"
            leech_text = f"[{leech_style(leeches)}]{leeches}[/{leech_style(leeches)}]"

        source_val = item.get("source", "Apibay")
        check_text = "[green][✓][/green]" if global_i in picked else "[dim][ ][/dim]"

        row_cells = [check_text, num_text, source_val]
        if show_from:
            row_cells.append(item.get("from_work", "") or "")
        row_cells += [display_name, format_size(size), seed_text, leech_text]
        table.add_row(*row_cells, style=row_style)

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

    # Rows that fit in the alternate-screen viewport (see screen=True below):
    # terminal height minus the banner (5) + its spacer (1), the table's chrome
    # (title, borders, header, caption ≈ 7) and a 1-line margin so the caption is
    # never on the last row.
    term_height = console.size.height
    overhead = 14 + (1 if note else 0)  # the note line (if any) takes one row
    visible_count = max(3, term_height - overhead)
    visible_count = min(visible_count, total)  # Don't exceed result count

    scroll_offset = 0

    # Marquee state shared with the ticker thread
    marquee_state = {
        "tick": 0,
        "cursor_changed_at": time.monotonic(),
    }
    stop_event = threading.Event()

    # Render the app banner inside the alt-screen frame, with a 1-line spacer
    # between it and the table (lazy import avoids a circular import).
    from ui.prompts import _make_banner_panel
    banner = _make_banner_panel()

    def framed(tbl):
        if note:
            note_line = Text(note, style="yellow", no_wrap=True, overflow="ellipsis")
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
            last_tick = -1
            while not stop_event.is_set():
                if stop_event.wait(_TICK_INTERVAL_S):
                    break
                # Snapshot mutable state
                cur = current
                if not (0 <= cur < len(page_items)):
                    continue
                name = page_items[cur].get("name", "")
                if len(name) <= _NAME_COL_WIDTH:
                    continue
                elapsed = time.monotonic() - marquee_state["cursor_changed_at"]
                if elapsed <= _MARQUEE_DWELL_S:
                    continue
                new_tick = int((elapsed - _MARQUEE_DWELL_S) * _MARQUEE_RATE)
                if new_tick == last_tick:
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
                        visible_count = min(max(3, term_height - overhead), total)
                    num_buffer = ""
                elif key == readchar.key.RIGHT:
                    if current_page < total_pages - 1:
                        current_page += 1
                        page_items = page_results()
                        total = len(page_items)
                        global_offset = current_page * RESULTS_PER_PAGE
                        current = 0
                        scroll_offset = 0
                        visible_count = min(max(3, term_height - overhead), total)
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
