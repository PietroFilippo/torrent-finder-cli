"""Interactive table selection UI for torrent results."""

import math

import readchar
from rich.live import Live
from rich.table import Table

from constants import RESULTS_PER_PAGE, console
from utils import format_size, leech_style, seed_style


def build_table(
    results: list[dict],
    selected_idx: int,
    scroll_offset: int,
    visible_count: int,
    total: int,
    current_page: int = 0,
    total_pages: int = 1,
    global_offset: int = 0,
) -> Table:
    """Build a rich table showing only the visible window of rows."""
    # Scroll indicator in the title
    end_idx = min(scroll_offset + visible_count, total)
    scroll_info = f"[dim]({scroll_offset + 1}-{end_idx} of {total})[/dim]"

    # Page indicator (only show when there are multiple pages)
    page_info = ""
    if total_pages > 1:
        page_info = f"  [bold cyan]Page {current_page + 1}/{total_pages}[/bold cyan]"

    table = Table(
        title=f"Torrent Results {scroll_info}{page_info}",
        title_style="bold magenta",
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=False,
        padding=(0, 1),
        caption=(
            "[dim] Up/Down: navigate | Enter: select | Esc: cancel | Type number to jump"
            + (" | Left/Right: change page" if total_pages > 1 else "")
            + "[/dim]"
        ),
        caption_style="dim",
    )

    table.add_column("#", style="bold white", justify="right", width=4)
    table.add_column("Name", style="white", max_width=60, no_wrap=True)
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

        table.add_row(
            num_text,
            name,
            format_size(size),
            seed_text,
            leech_text,
            style=row_style,
        )

    return table


def interactive_select(results: list[dict]) -> int | None:
    """
    Display an interactive table where the user navigates with arrow keys.
    Results are split into pages of RESULTS_PER_PAGE. Left/Right arrows
    switch pages. Returns the global index of the selected result, or
    None if cancelled.
    """
    all_results = results
    total_all = len(all_results)
    total_pages = math.ceil(total_all / RESULTS_PER_PAGE)
    current_page = 0

    def page_results():
        start = current_page * RESULTS_PER_PAGE
        end = start + RESULTS_PER_PAGE
        return all_results[start:end]

    # Current selection index (local to the page)
    current = 0
    num_buffer = ""
    page_items = page_results()
    total = len(page_items)
    global_offset = current_page * RESULTS_PER_PAGE

    # Calculate how many rows fit: terminal height minus overhead
    # (title, header, caption, border lines, prompt above/below ~ 8 lines)
    term_height = console.size.height
    overhead = 8
    visible_count = max(3, term_height - overhead)
    visible_count = min(visible_count, total)  # Don't exceed result count

    scroll_offset = 0

    console.print()

    with Live(
        build_table(
            page_items, current, scroll_offset, visible_count, total,
            current_page, total_pages, global_offset,
        ),
        console=console,
        refresh_per_second=15,
        transient=False,
    ) as live:
        while True:
            key = readchar.readkey()

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
            elif key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                return global_offset + current
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

            live.update(
                build_table(
                    page_items, current, scroll_offset, visible_count, total,
                    current_page, total_pages, global_offset,
                )
            )

    return None
