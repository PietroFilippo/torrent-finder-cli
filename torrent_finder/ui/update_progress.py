"""Update display and a read-only viewer for the detached Windows updater."""

import argparse
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import sys
import time

import readchar
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.padding import Padding
from rich.progress_bar import ProgressBar
from rich.text import Text


@dataclass(frozen=True)
class UpdateView:
    stage: str = "preparing"
    detail: str = "Preparing the updater."
    current: str = ""
    latest: str = ""


_HEADINGS = {
    "preparing": "Preparing update",
    "waiting": "Waiting for Torrent Finder to close",
    "installing": "Installing update",
    "opening": "Opening release page",
    "opened": "Release page opened",
    "succeeded": "Update complete",
    "failed": "Update did not complete",
}
_FINISHED = {"succeeded", "failed", "opened"}


def update_panel(view: UpdateView, elapsed: float, width: int = 72):
    """One shared renderer for real updates, terminal previews, and visual QA."""
    done = view.stage in _FINISHED
    color = "green" if view.stage == "succeeded" else "red" if view.stage == "failed" else "cyan"
    parts = []
    if view.current or view.latest:
        versions = f"{view.current or 'Installed version'} → {view.latest or 'Latest version'}"
        parts.extend([Text(versions, style="dim"), Text("")])
    parts.extend([
        Text(_HEADINGS.get(view.stage, "Updating"), style=f"bold {color}"),
        Text(""),
        Padding(ProgressBar(total=100 if done else None, completed=100 if view.stage == "succeeded" else 0,
                    pulse=not done, animation_time=elapsed, style="bright_black",
                    pulse_style="cyan", finished_style="green"), (0, 0)),
        Text(f"Elapsed {int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}", style="dim"),
        Text(""),
        Text(view.detail),
    ])
    return Panel(Group(*parts), title="Torrent Finder · Update", title_align="left",
                 border_style=color, padding=(1, 2), width=max(24, width))


class UpdateDisplay:
    def __init__(self, console=None, *, current="", latest="", preview=False):
        self.console = console or Console()
        self.view = UpdateView(current=current, latest=latest)
        self.started = time.monotonic()
        self.finished_at = None
        self.preview = preview
        self.live = Live(console=self.console, get_renderable=self.render,
                         refresh_per_second=10, transient=False)

    def render(self):
        elapsed = (self.finished_at or time.monotonic()) - self.started
        panel = update_panel(self.view, elapsed, min(72, self.console.size.width))
        if self.preview:
            return Group(Text("PREVIEW · No update will be installed", style="bold yellow"), panel)
        return panel

    def update(self, stage, detail=""):
        self.view = replace(self.view, stage=stage, detail=detail)
        if stage in _FINISHED and self.finished_at is None:
            self.finished_at = time.monotonic()
        self.live.refresh()

    def __enter__(self):
        self.live.start(refresh=True)
        return self

    def __exit__(self, *_args):
        self.live.stop()


def completion_detail(reopen=None, seconds=0):
    message = "The update was installed successfully.\n"
    if reopen == "waiting":
        if seconds > 0:
            return message + f"Reopening Torrent Finder in {seconds} second{'s' if seconds != 1 else ''}..."
        return message + "Reopening Torrent Finder..."
    if reopen == "started":
        return message + "Starting Torrent Finder..."
    if reopen == "failed":
        return message + "Could not reopen automatically. Open Torrent Finder manually."
    return message + "You can reopen Torrent Finder now."


def preview_view(elapsed, outcome="success"):
    if elapsed < 1:
        return UpdateView("preparing", "Preparing the updater.")
    if elapsed < 2:
        return UpdateView("waiting", "Return to the main app and press any key to begin.")
    if elapsed < 7:
        return UpdateView("installing", "Downloading and installing the latest version.\nLeave Torrent Finder closed until this finishes.")
    if outcome == "failure":
        return UpdateView("failed", "The update could not be completed.\nCheck update.log, then retry the update.")
    return UpdateView("succeeded", completion_detail(
        "waiting" if elapsed < 10 else "started", max(0, math.ceil(10 - elapsed))))


def preview_update(outcome="success", *, console=None, pause=True):
    """Exercise the actual display without invoking installers or status files."""
    with UpdateDisplay(console, preview=True) as display:
        stages = (0, 1, 2, 7, 8, 9, 10) if outcome == "success" else (0, 1, 2, 7)
        for index, stage_time in enumerate(stages):
            view = preview_view(stage_time, outcome)
            display.update(view.stage, view.detail)
            if index + 1 < len(stages):
                time.sleep(stages[index + 1] - stage_time)
        if pause:
            display.console.print("Press any key to close the preview.")
            try:
                readchar.readkey()
            except (KeyboardInterrupt, EOFError):
                pass


def read_job(status: Path, job_id: str):
    # Startup may already have archived a completed report for its own notice.
    for path in (status, status.with_name("last-update-status.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("job_id") == job_id:
                return data
        except (OSError, ValueError):
            continue
    return None


def watch_update(status: Path, job_id: str, *, console=None, pause=True):
    """Observe a job; closing this viewer cannot cancel the hidden installer."""
    with UpdateDisplay(console) as display:
        while True:
            data = read_job(status, job_id)
            if data:
                if data.get("reopen") == "waiting" and time.time() > data.get("reopen_at", 0) + 10:
                    data = {**data, "reopen": "failed"}
                state = data.get("state")
                stage = data.get("phase", "waiting") if state == "pending" else state
                detail = {
                    "waiting": "Return to the main app and press any key to begin.",
                    "installing": "Downloading and installing the latest version.\nLeave Torrent Finder closed until this finishes.",
                    "succeeded": completion_detail(data.get("reopen"), max(0, math.ceil(data.get("reopen_at", 0) - time.time()))),
                    "failed": f"Check the update log, then retry.\n{data.get('log', status.with_name('update.log'))}",
                }.get(stage, "Waiting for the updater to report its status.")
                display.view = replace(display.view, current=str(data.get("current", "")), latest=str(data.get("latest", "")))
                display.update(stage, detail)
                if stage == "succeeded" and data.get("reopen") == "started":
                    return  # The app owns a new console; close the updater window.
                if stage in _FINISHED and data.get("reopen") != "waiting":
                    break
            if time.monotonic() - display.started > 1900:
                display.update("failed", "The updater did not report completion. Check update.log before trying again.")
                break
            time.sleep(0.15)
        if pause:
            display.console.print("Press any key to close this window.")
            try:
                readchar.readkey()
            except (KeyboardInterrupt, EOFError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", type=Path)
    parser.add_argument("--job-id")
    parser.add_argument("--preview", choices=("success", "failure"), default="success")
    args = parser.parse_args()
    if args.watch:
        if not args.job_id:
            parser.error("--watch requires --job-id")
        if sys.platform == "win32":
            # The viewer owns a new console, separate from the closing app.
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = sys.stdout
            sys.stdin = open("CONIN$", "r", encoding="utf-8")
        action = lambda: watch_update(args.watch, args.job_id)
    else:
        action = lambda: preview_update(args.preview)
    try:
        action()
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()
