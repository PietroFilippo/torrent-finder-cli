"""The search-in-progress screen, drawn in the Quiet layout on the alternate screen.

The screen names what is being searched, then one line per provider: a state
mark, its engines with what each is doing, and how many results it has found.
A live status line counts providers finished and results ready, and the key
bar keeps Enter (show results so far) and Esc (cancel). Frames are redrawn in
place, line by line, so a spinner refresh never flickers.
"""

from __future__ import annotations

import io
import sys

from rich.cells import cell_len
from rich.console import Group
from rich.spinner import SPINNERS
from rich.text import Text

from torrent_finder.constants import buffer_console, console
from torrent_finder.ui import theme
from torrent_finder.ui.layout import ellipsize_cells

KEYS = "Enter view results so far  •  Esc cancel"
REDRAW_S = 0.1
_LABEL_MAX = 20

# What an engine's status reads as, here and on the diagnostics screen.
STATUS_WORDS = {
    "searching": "searching", "pending": "not finished", "auto": "auto, if needed", "skipped": "not needed",
    "results": "results", "empty": "none", "filtered": "filtered out", "off": "off",
    "timeout": "timed out", "interrupted": "stopped", "error": "failed", "blocked": "blocked",
    "missing_login": "login needed", "rejected_login": "login rejected", "login_error": "login failed",
}
_STATUS_WORDS = STATUS_WORDS
_WARN_STATUSES = {"timeout", "interrupted", "missing_login", "rejected_login", "login_error"}
_BAD_STATUSES = {"blocked", "error"}


def status_style(status: str) -> str:
    """Green for rows, yellow for failures worth retrying or a login to fix, red for blocks and errors."""
    if status == "results":
        return theme.GOOD
    if status in _WARN_STATUSES:
        return theme.WARN
    if status in _BAD_STATUSES:
        return theme.BAD
    return theme.MUTED


def spinner_frame(elapsed: float) -> str:
    """The design's spinner frame for *elapsed* seconds, so every redraw advances it."""
    spinner = SPINNERS[theme.SPINNER]
    frames = spinner["frames"]
    return frames[int(elapsed * 1000 / spinner["interval"]) % len(frames)]


def _engine_part(engine) -> Text:
    """``Apibay 20``, ``Nyaa searching``, ``Knaben timed out``: the name in steel, the state in its colour."""
    part = Text(engine.name + " ", style=theme.MUTED)
    if engine.status == "results":
        part.append(str(engine.kept), style="default")
    elif engine.status in _WARN_STATUSES:
        part.append(_STATUS_WORDS[engine.status], style=theme.WARN)
    elif engine.status in _BAD_STATUSES:
        part.append(_STATUS_WORDS[engine.status], style=theme.BAD)
    elif engine.status == "searching":
        part.append("searching", style="default")
    else:
        part.append(_STATUS_WORDS.get(engine.status, engine.status.replace("_", " ")), style=theme.MUTED)
    return part


def provider_line(line, label_width: int, width: int, elapsed: float) -> Text:
    """One provider: mark, label, its engines (cut to fit) and a right-aligned result count."""
    if line.state == "running":
        mark, mark_style = spinner_frame(elapsed), theme.ACCENT
    elif line.state == "failed":
        mark, mark_style = "×", theme.BAD
    elif line.results:
        mark, mark_style = theme.CHECK, theme.GOOD
    else:
        mark, mark_style = "–", theme.MUTED
    if line.results:
        right = Text(f"{line.results} result{'s' if line.results != 1 else ''}")
    elif line.state == "running":
        right = Text("waiting", style=theme.MUTED)
    else:
        right = Text("failed" if line.state == "failed" else "no results", style=theme.MUTED)
    row = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    row.append(mark, style=mark_style)
    row.append(" ")
    label = ellipsize_cells(line.label, label_width)
    row.append(label + " " * (label_width - cell_len(label)))
    engines = Text()
    for index, engine in enumerate(e for e in line.engines if e.status != "off"):
        if index:
            engines.append(" · ", style=theme.MUTED)
        engines.append_text(_engine_part(engine))
    room = width - len(theme.MARGIN) - cell_len(row.plain) - cell_len(right.plain) - 4
    if room >= 8 and engines.plain:
        row.append("  ")
        if cell_len(engines.plain) > room:
            engines.truncate(room, overflow="ellipsis")
        row.append_text(engines)
    row.append(" " * max(2, width - len(theme.MARGIN) - cell_len(row.plain) - cell_len(right.plain)))
    row.append_text(right)
    return row


def _provider_lines(progress, width: int, elapsed: float) -> list[Text]:
    lines = tuple(getattr(progress, "providers", ()) or ()) if progress is not None else ()
    if not lines:
        return []
    label_width = min(_LABEL_MAX, max(cell_len(line.label) for line in lines))
    label_width = min(label_width, max(6, (width - 2 * len(theme.MARGIN)) // 3))
    return [provider_line(line, label_width, width, elapsed) for line in lines]


def _cut(rows: list[Text], room: int, progress) -> list[Text]:
    """The provider lines that fit in *room* rows, the rest summed up on the last one."""
    if room >= len(rows):
        return rows
    if room <= 0:
        return []
    keep = room - 1
    rest = progress.providers[keep:]
    running = sum(line.state == "running" for line in rest)
    summary = f"+{len(rest)} more provider{'s' if len(rest) != 1 else ''}"
    if running:
        summary += f" · {running} searching"
    return rows[:keep] + [Text(theme.MARGIN + summary, style=theme.MUTED, no_wrap=True, overflow="ellipsis")]


def progress_frame(title: str, intro: str, notes: list[str], progress, elapsed: float,
                   waiting_label: str, now: float | None = None):
    """One frame: header, what is searched, a line per provider, live counts, keys.

    The live status and the keys always fit: in a short window the spacing goes
    first, then the notes, then provider lines (the rest summed up on one
    line), the pending names and the header's second line; the description
    of what is searched shortens last (ending in "…").
    """
    width, height = console.size.width, console.size.height
    seconds = int(elapsed)
    top: list[Text] = list(theme.header_lines(title, f"{seconds}s", width))
    intro_lines = theme.wrap_block(Text.from_markup(intro), width, console)
    note_lines = [line for note in notes
                  for line in theme.wrap_block(Text.from_markup(note, style=theme.MUTED), width, console)]

    status = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    status.append(spinner_frame(elapsed), style=theme.ACCENT)
    status.append(" ")
    if progress is None:
        status.append(waiting_label, style="bold")
    else:
        status.append(f"{progress.completed}/{progress.total} providers finished · "
                      f"{progress.results} results ready · {seconds}s", style="bold")
    rows = _provider_lines(progress, width, elapsed)
    waiting: list[Text] = []
    if not rows and progress is not None and progress.waiting:
        pending = ", ".join(progress.waiting[:2])
        if len(progress.waiting) > 2:
            pending += f" +{len(progress.waiting) - 2} more"
        waiting = theme.wrap_block(Text(f"Waiting: {pending}", style=theme.MUTED), width, console)
    keys = theme.wrap_keys(theme.parse_footer(KEYS).keys, width)
    spaced = theme.roomy(height, 14)

    def assemble() -> list[Text]:
        blank = [Text("")] if spaced else []
        rule = [theme.rule(width)] if spaced else []
        middle = rows + blank if rows else []
        return [*top, *rule, *intro_lines, *note_lines, *blank, *middle, status, *waiting, *rule, *keys]

    if len(assemble()) > height:
        spaced = False
    if len(assemble()) > height:
        note_lines = []
    if len(assemble()) > height and rows:
        rows = _cut(rows, height - (len(assemble()) - len(rows)), progress)
    if len(assemble()) > height:
        waiting = []
    if len(assemble()) > height and len(top) > 1:
        top = [theme.header(title, f"{seconds}s", width)]
    if len(assemble()) > height:
        room = max(0, height - (len(assemble()) - len(intro_lines)))
        cut = len(intro_lines) > room
        intro_lines = intro_lines[:room]
        if cut and intro_lines:
            last = intro_lines[-1]
            last.truncate(max(1, min(cell_len(last.plain), width - 1) - 1))
            last.append("…")
    return Group(*assemble())


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
        buffer_console(buffer, size.width, size.height).print(frame)
        lines = buffer.getvalue().rstrip("\n").split("\n")[: size.height]
        # A resize needs a clean slate; otherwise overwrite in place.
        prefix = "\033[2J\033[H" if size != self._last_size else "\033[H"
        self._last_size = size
        sys.stdout.write(prefix + "\033[K\n".join(lines) + "\033[K\033[J")
        sys.stdout.flush()

    def __exit__(self, *_exc) -> None:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
