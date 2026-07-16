"""Shared helpers for terminal-width-aware UI rendering."""

from rich.cells import cell_len, chop_cells


def ellipsize_cells(value: object, width: int) -> str:
    """Crop *value* to a terminal-cell width, appending an ellipsis."""
    text = str(value)
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    if width == 1:
        return "…"
    return chop_cells(text, width - 1)[0] + "…"


def marquee_cells(text: str, width: int, tick: int, sep: str = "   •   ") -> str:
    """Return a scrolling window bounded by terminal cells, not code points."""
    if width <= 0:
        return ""
    if cell_len(text) <= width:
        return text
    period = len(text) + len(sep)
    offset = tick % period
    repeated = text + sep + text + sep
    return chop_cells(repeated[offset:], width)[0]