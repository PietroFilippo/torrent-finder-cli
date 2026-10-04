"""The search-in-progress screen, drawn in the Quiet layout on the alternate screen.

The screen names what is being searched, shows providers finished, results
ready, elapsed time and the providers still pending, and keeps the Enter
(show results so far) and Esc (cancel) keys in its key bar. Frames are
redrawn in place, line by line, so a spinner refresh never flickers.
"""

from __future__ import annotations

import io
import sys
import time

from rich.console import Console, Group
from rich.spinner import Spinner
from rich.text import Text

from torrent_finder.constants import console, custom_theme
from torrent_finder.ui import theme

KEYS = "Enter view results so far  •  Esc cancel"
REDRAW_S = 0.1


def progress_frame(title: str, intro: str, notes: list[str], progress, elapsed: float,
                   waiting_label: str, now: float | None = None):
    """One frame: header, what is searched, live counts, pending names, keys."""
    width, height = console.size.width, console.size.height
    seconds = int(elapsed)
    lines: list[Text] = list(theme.header_lines(title, f"{seconds}s", width))
    if height >= 14:
        lines.append(Text(""))
    lines.extend(theme.wrap_block(Text.from_markup(intro), width, console))
    for note in notes:
        lines.extend(theme.wrap_block(Text.from_markup(note, style=theme.MUTED), width, console))
    lines.append(Text(""))

    status = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    spinner = Spinner("dots", style=theme.ACCENT).render(time.monotonic() if now is None else now)
    status.append_text(spinner if isinstance(spinner, Text) else Text(str(spinner)))
    status.append(" ")
    if progress is None:
        status.append(waiting_label, style="bold")
    else:
        status.append(f"{progress.completed}/{progress.total} providers finished · "
                      f"{progress.results} results ready · {seconds}s", style="bold")
    lines.append(status)
    if progress is not None and progress.waiting:
        pending = ", ".join(progress.waiting[:2])
        if len(progress.waiting) > 2:
            pending += f" +{len(progress.waiting) - 2} more"
        lines.extend(theme.wrap_block(Text(f"Waiting: {pending}", style=theme.MUTED), width, console))
    lines.append(Text(""))
    lines.extend(theme.wrap_keys(theme.parse_footer(KEYS).keys, width))
    return Group(*lines)


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
