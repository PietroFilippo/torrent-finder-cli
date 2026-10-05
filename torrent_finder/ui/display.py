"""The alternate screen and flicker-free frames, shared by every full-screen view.

**Frames overwrite in place.** ``paint`` homes the cursor and writes the new
frame over the old one: a line shorter than the window erases what is left of
the old line, and rows under the frame are erased. Clearing the whole screen
first showed a blank screen for a moment in large windows, where a frame is
a big write. A line that fills the width gets no erase: the cursor waits on
its last cell, and an erase there would take that cell (the Athanor frame's
right border). The frame is sent as one synchronized update, which terminals
that know mode 2026 draw at once and the others ignore.

**Views share one alternate screen.** A view opened over another (a
confirmation over a menu, the key list) must not hand the screen back to the
shell when it closes, or the view underneath goes on drawing on the main
screen, where each frame pushes a page into the scrollback. So
``enter_screen``/``leave_screen`` count: only the outermost view switches,
and leaving a nested view restores the cursor the view underneath wants.
"""

from __future__ import annotations

import re
import sys

from rich.cells import cell_len

_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_views: list[bool] = []  # per open view, outermost first: whether it shows the cursor

BEGIN_UPDATE, END_UPDATE = "\033[?2026h", "\033[?2026l"


def _cursor(shown: bool) -> str:
    return "\033[?25h" if shown else "\033[?25l"


def enter_screen(cursor: bool = False) -> None:
    """Open a full-screen view: the outermost one switches to the alternate screen."""
    outermost = not _views
    _views.append(cursor)
    sys.stdout.write(("\033[?1049h\033[2J\033[H" if outermost else "") + _cursor(cursor))
    sys.stdout.flush()


def leave_screen(clear: bool = False) -> None:
    """Close a view: the outermost one returns to the main screen (cleared when *clear*)."""
    if _views:
        _views.pop()
    if _views:
        sys.stdout.write(_cursor(_views[-1]))
    else:
        sys.stdout.write("\033[?25h\033[?1049l" + ("\033[2J\033[H" if clear else ""))
    sys.stdout.flush()


def depth() -> int:
    """How many full-screen views are open."""
    return len(_views)


def paint(content: str, width: int, height: int, after: str = "") -> str:
    """The escape codes that replace the screen's contents with *content* without blanking it.

    *after* (a cursor move, say) goes inside the same update.
    """
    rows = content.split("\n")
    lines = [row if cell_len(_ESCAPES.sub("", row)) >= width else row + "\033[K" for row in rows]
    out = BEGIN_UPDATE + "\033[H" + "\n".join(lines)
    if len(rows) < height:
        out += f"\033[{len(rows) + 1};1H\033[J"
    return out + after + END_UPDATE
