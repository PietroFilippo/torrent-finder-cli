"""The update screen: one renderer for real updates, the terminal preview and visual QA."""

from dataclasses import dataclass, replace
import time

import readchar
from rich.console import Console, Group
from rich.filesize import decimal
from rich.live import Live
from rich.padding import Padding
from rich.progress_bar import ProgressBar
from rich.text import Text

from torrent_finder.ui import theme


@dataclass(frozen=True)
class UpdateView:
    stage: str = "preparing"
    detail: str = "Getting ready to update."
    current: str = ""
    latest: str = ""
    done: "int | None" = None   # bytes downloaded, while pip reports them
    total: "int | None" = None


_HEADINGS = {
    "preparing": "Preparing update",
    "downloading": "Downloading update",
    "installing": "Installing update",
    "finishing": "Finishing update",
    "opening": "Opening release page",
    "opened": "Release page opened",
    "succeeded": "Update complete",
    "failed": "Update did not complete",
}
_FINISHED = {"succeeded", "failed", "opened"}
INTERRUPT_NOTE = "Ctrl+C cannot stop an update halfway. It finishes in a moment."


def _spread(left: Text, right: Text, width: int) -> Text:
    """*left* at the margin and *right* ending where the bar ends."""
    line = Text(theme.MARGIN, overflow="fold")
    line.append_text(left)
    if right.plain:
        line.append(" " * max(2, theme.inner_width(width) - left.cell_len - right.cell_len))
        line.append_text(right)
    return line


def update_panel(view: UpdateView, elapsed: float, width: int = 72, notice: str = ""):
    """The header with the version change, the stage, a bar and the detail text.

    The bar fills with the download percentage while pip reports bytes, pulses
    while a step's length is unknown, and is full only when the update succeeded.
    """
    width = max(24, width)
    finished = view.stage in _FINISHED
    color = theme.GOOD if view.stage == "succeeded" else theme.BAD if view.stage == "failed" else theme.ACCENT
    measured = not finished and bool(view.total) and view.done is not None
    versions = ""
    if view.current or view.latest:
        versions = f"{view.current or 'Installed version'} → {view.latest or 'Latest version'}"
    heading = Text(_HEADINGS.get(view.stage, "Updating"), style=f"bold {color}")
    percent = Text(f"{min(100, view.done * 100 // view.total)}%", style=f"bold {color}") if measured else Text()
    if measured:
        bar = ProgressBar(total=view.total, completed=min(view.done, view.total), width=theme.inner_width(width),
                          style=theme.MUTED, complete_style=theme.ACCENT, finished_style=theme.ACCENT)
    else:
        bar = ProgressBar(total=100 if finished else None, completed=100 if view.stage == "succeeded" else 0,
                          width=theme.inner_width(width), pulse=not finished, animation_time=elapsed,
                          style=theme.MUTED, pulse_style=theme.ACCENT, finished_style=theme.GOOD)
    size = Text(f"{decimal(view.done)} of {decimal(view.total)}", style=theme.MUTED) if measured else Text()
    clock = Text(f"Elapsed {int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}", style=theme.MUTED)
    parts: list = list(theme.header_lines("Update", Text(versions), width))
    parts.extend([
        theme.rule(width),
        _spread(heading, percent, width),
        Text(""),
        Padding(bar, (0, 0, 0, len(theme.MARGIN))),
        _spread(size, clock, width) if measured else _spread(clock, Text(), width),
        Text(""),
    ])
    for line in view.detail.splitlines() or [""]:
        parts.append(Text(theme.MARGIN + line, overflow="fold"))
    if notice and not finished:
        parts.extend([Text(""), Text(theme.MARGIN + notice, style=theme.WARN, overflow="fold")])
    return Group(*parts)


class UpdateDisplay:
    def __init__(self, console=None, *, current="", latest="", preview=False):
        self.console = console or Console()
        self.view = UpdateView(current=current, latest=latest)
        self.notice = ""
        self.started = time.monotonic()
        self.finished_at = None
        self.preview = preview
        self.live = Live(console=self.console, get_renderable=self.render,
                         refresh_per_second=10, transient=False)

    def render(self):
        elapsed = (self.finished_at or time.monotonic()) - self.started
        panel = update_panel(self.view, elapsed, min(72, self.console.size.width), self.notice)
        if self.preview:
            return Group(Text(theme.MARGIN + "PREVIEW · No update will be installed", style=f"bold {theme.WARN}"),
                         panel)
        return panel

    def update(self, stage, detail="", *, done=None, total=None, latest=None):
        self.view = replace(self.view, stage=stage, detail=detail, done=done, total=total,
                            latest=latest or self.view.latest)
        if stage in _FINISHED and self.finished_at is None:
            self.finished_at = time.monotonic()
        self.live.refresh()

    def interrupted(self):
        """Ctrl+C while installing: say why it is ignored. Safe from a signal handler (no drawing)."""
        self.notice = INTERRUPT_NOTE

    def __enter__(self):
        self.live.start(refresh=True)
        return self

    def __exit__(self, *_args):
        self.live.stop()


_PREVIEW_BYTES = 719_511  # the size of a recent release's wheel
PREVIEW_SECONDS = {"success": 7.0, "failure": 6.0}


def preview_view(elapsed, outcome="success"):
    """The real flow's stages on a fixed timeline; nothing is downloaded or installed."""
    if elapsed < 1:
        return UpdateView("preparing", "Getting ready to update.")
    if elapsed < 1.5:
        return UpdateView("downloading", "Looking for the latest version on PyPI.")
    if elapsed < 4:
        done = int(_PREVIEW_BYTES * min(1.0, (elapsed - 1.5) / 2.4))
        return UpdateView("downloading", "Downloading the newest torrent-finder-cli package.",
                          done=done, total=_PREVIEW_BYTES)
    if elapsed < 6:
        return UpdateView("installing", "Installing torrent-finder-cli.")
    if outcome == "failure":
        return UpdateView("failed", "The installer stopped with an error.\nDetails: update.log\n"
                                    "Or close Torrent Finder and run: pipx upgrade torrent-finder-cli")
    if elapsed < 7:
        return UpdateView("finishing", "Updating pipx's copy of the torrent-finder command.")
    return UpdateView("succeeded", "Torrent Finder is installed.")


def preview_update(outcome="success", *, console=None, pause=True):
    """Exercise the actual display without invoking installers or writing files."""
    end = PREVIEW_SECONDS[outcome]
    with UpdateDisplay(console, preview=True) as display:
        for tick in range(int(end * 10) + 1):
            view = preview_view(tick / 10, outcome)
            display.update(view.stage, view.detail, done=view.done, total=view.total)
            if view.stage in _FINISHED:
                break
            time.sleep(0.1)
    if pause:
        if outcome == "success":
            display.console.print(Text(theme.MARGIN + "A real update now restarts Torrent Finder in this window "
                                       "after a key press.", style=theme.MUTED, overflow="fold"))
        display.console.print(Text(theme.MARGIN + "Press any key to close the preview.", style=theme.MUTED))
        try:
            readchar.readkey()
        except (KeyboardInterrupt, EOFError):
            pass
