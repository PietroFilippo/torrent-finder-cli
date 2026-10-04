"""The search-in-progress screen, drawn in the Quiet layout on the alternate screen.

The screen names what is being searched, shows providers finished, results
ready, elapsed time and the providers still pending, and keeps the Enter
(show results so far) and Esc (cancel) keys in its key bar. Frames are
redrawn in place, line by line, so a spinner refresh never flickers.
"""

from __future__ import annotations

import io
import sys

from rich.cells import cell_len
from rich.console import Console, Group
from rich.spinner import SPINNERS
from rich.text import Text

from torrent_finder.constants import console, custom_theme
from torrent_finder.ui import theme

KEYS = "Enter view results so far  •  Esc cancel"
REDRAW_S = 0.1
_DOTS = SPINNERS["dots"]


def spinner_frame(elapsed: float) -> str:
    """The "dots" spinner frame for *elapsed* seconds, so every redraw advances it."""
    frames = _DOTS["frames"]
    return frames[int(elapsed * 1000 / _DOTS["interval"]) % len(frames)]


def progress_frame(title: str, intro: str, notes: list[str], progress, elapsed: float,
                   waiting_label: str, now: float | None = None):
    """One frame: header, what is searched, live counts, pending names, keys.

    The live status and the keys always fit: in a short window the spacing goes
    first, then the description of what is searched shortens (ending in "…"),
    then the pending names and the header's second line.
    """
    width, height = console.size.width, console.size.height
    seconds = int(elapsed)
    top: list[Text] = list(theme.header_lines(title, f"{seconds}s", width))
    info = theme.wrap_block(Text.from_markup(intro), width, console)
    for note in notes:
        info += theme.wrap_block(Text.from_markup(note, style=theme.MUTED), width, console)

    status = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    status.append(spinner_frame(elapsed), style=theme.ACCENT)
    status.append(" ")
    if progress is None:
        status.append(waiting_label, style="bold")
    else:
        status.append(f"{progress.completed}/{progress.total} providers finished · "
                      f"{progress.results} results ready · {seconds}s", style="bold")
    waiting: list[Text] = []
    if progress is not None and progress.waiting:
        pending = ", ".join(progress.waiting[:2])
        if len(progress.waiting) > 2:
            pending += f" +{len(progress.waiting) - 2} more"
        waiting = theme.wrap_block(Text(f"Waiting: {pending}", style=theme.MUTED), width, console)
    keys = theme.wrap_keys(theme.parse_footer(KEYS).keys, width)

    spaced = height >= 14 and len(top) + len(info) + 1 + len(waiting) + len(keys) + 3 <= height
    spacers = 3 if spaced else 0
    fixed = len(top) + 1 + len(waiting) + len(keys) + spacers
    if fixed + 1 > height and waiting:
        waiting, fixed = [], fixed - len(waiting)
    if fixed + 1 > height and len(top) > 1:
        fixed -= len(top) - 1
        top = [theme.header(title, f"{seconds}s", width)]
    room = max(0, height - fixed)
    if len(info) > room:
        info = info[:room]
        if info:
            last = info[-1]
            last.truncate(max(1, width - 1), overflow="ellipsis")
            if not last.plain.endswith("…"):
                last.truncate(max(1, cell_len(last.plain) - 1))
                last.append("…")

    blank = [Text("")] if spaced else []
    return Group(*top, *blank, *info, *blank, status, *waiting, *blank, *keys)


class ProgressScreen:
    """Owns the alternate screen while a search runs; restores the terminal on exit."""

    def __enter__(self) -> "ProgressScreen":
        sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
        sys.stdout.flush()
        self._last_size = None
        return self

    def draw(self, frame) -> None:
        size = console.size
        buffer = io.StringIO()
        Console(file=buffer, width=size.width, height=size.height, force_terminal=True,
                theme=custom_theme).print(frame)
        lines = buffer.getvalue().rstrip("\n").split("\n")[: size.height]
        # A resize needs a clean slate; otherwise overwrite in place.
        prefix = "\033[2J\033[H" if size != self._last_size else "\033[H"
        self._last_size = size
        sys.stdout.write(prefix + "\033[K\n".join(lines) + "\033[K\033[J")
        sys.stdout.flush()

    def __exit__(self, *_exc) -> None:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
