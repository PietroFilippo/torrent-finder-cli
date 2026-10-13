"""Background downloads on screen: the status figure, the Downloads screen and its prompts.

The engine (``torrent_finder.downloads``) owns the jobs; this module only
reads its snapshots and asks it to stop, remove or re-enqueue one. Every
menu polls it while it waits for a key (``watch`` and ``poll``, called by
``selector.arrow_select``), so the Athanor status line, Simple's header
badge, the main menu's Downloads row and the rows of the Downloads screen
follow the jobs, and a download that finished announces itself on the
message line once. Nothing here starts the engine: ``current`` is None
until the first job is enqueued. See docs/adr/0029-background-downloads.md.
"""

from __future__ import annotations

# i18n: converted
import os
import platform
import subprocess
import time

from rich.markup import escape
from rich.text import Text

from torrent_finder import downloads
from torrent_finder.constants import console
from torrent_finder.i18n import N_, t, tn
from torrent_finder.ui import chrome as frames, theme
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.utils import format_size

SETTING = "background_downloads"  # settings.background_downloads: True runs aria2c jobs in the background
_RUNNING = frozenset({"metadata", "running", "paused", "unpacking"})
_LOG_LINES = 40
_INSPECT_LINES = 6  # the main menu's inspector lists this many jobs


# --- reading the engine --------------------------------------------------------------------

def current():
    """The session's job manager, or None while no background download was started."""
    return downloads.current()


def enabled() -> bool:
    """The saved setting: True when aria2c downloads run in the background."""
    from torrent_finder.state import load_setting
    return bool(load_setting(SETTING, False))


def revision() -> int:
    manager = current()
    return manager.revision if manager is not None else -1


def _jobs() -> tuple:
    manager = current()
    return manager.snapshot() if manager is not None else ()


def _counts(jobs) -> tuple[int, int, int]:
    """(running, queued, finished): running counts metadata, paused and unpacking jobs too."""
    running = sum(job.state in _RUNNING for job in jobs)
    queued = sum(job.state == "queued" for job in jobs)
    finished = sum(job.state in downloads.FINISHED_STATES for job in jobs)
    return running, queued, finished


# --- live polling, done by every menu --------------------------------------------------------

_announced: set[str] = set()


def _announce_finished(jobs) -> None:
    """Queue one message per download that ended since the last look: done, failed or interrupted."""
    for job in jobs:
        if job.state not in ("done", "failed", "interrupted") or job.id in _announced:
            continue
        _announced.add(job.id)
        title = escape(job.title)
        if job.state == "done":
            frames.announce(t("[good]✓[/good] {title} finished · {size} · D opens Downloads",
                              title=title, size=format_size(job.total_bytes or job.done_bytes)))
        elif job.state == "failed":
            frames.announce(t("[bad]✗[/bad] {title} failed · D opens Downloads", title=title))
        else:
            frames.announce(t("[bad]✗[/bad] {title} interrupted · D opens Downloads", title=title))


def watch() -> dict:
    """A screen's view of the jobs, taken when it opens; finished downloads are announced now."""
    manager = current()
    if manager is None:
        return {"revision": -1}
    _announce_finished(manager.snapshot())
    return {"revision": manager.revision}


def poll(watched: dict) -> bool:
    """True when the jobs changed since *watched* last looked; finished downloads are announced."""
    manager = current()
    if manager is None:
        return False
    now = manager.revision
    if now == watched.get("revision"):
        return False
    watched["revision"] = now
    _announce_finished(manager.snapshot())
    return True


# --- the status figure and Simple's badge ----------------------------------------------------

def _rate(bps: int) -> str:
    return t("{size}/s", size=format_size(bps))


def _percent_of(progress: "float | None") -> str:
    """``43%``; a download short of complete never reads 100%."""
    if progress is None:
        return ""
    percent = int(progress * 100 + 0.5)
    return f"{min(percent, 99) if progress < 1 else 100}%"


def _figure_parts() -> "tuple[list[str], int]":
    """(the running figure's words, unseen completions): ``["2", "43%", "3.1 MB/s"]``.

    The count is the downloads under way (fetching metadata, downloading,
    unpacking), what the Downloads row calls running; a queued one waits
    for a slot and is not counted. The percentage is the furthest along.
    """
    manager = current()
    if manager is None:
        return [], 0
    jobs = manager.snapshot()
    running = [job for job in jobs if job.state in _RUNNING]
    unseen = manager.summary().unseen_completions
    if not running:
        return [], unseen
    parts = [str(len(running))]
    progress = [job.progress for job in running if job.progress is not None]
    if progress:
        parts.append(_percent_of(max(progress)))
    speed = sum(job.speed_bps for job in running)
    if speed:
        parts.append(_rate(speed))
    return parts, unseen


def figure() -> "Text | None":
    """``2 · 43% · 3.1 MB/s`` while jobs run, ``✓1 new`` after an unseen completion, else None."""
    parts, unseen = _figure_parts()
    text_style = theme.TEXT or ""
    if parts:
        text = Text(parts[0], style=text_style)
        for part in parts[1:]:
            text.append(" · ", style=theme.MUTED)
            text.append(part, style=text_style)
        return text
    if unseen:
        text = Text("✓", style=theme.GOOD)
        text.append(tn("{n} new", "{n} new", unseen), style=text_style)
        return text
    return None


def badge() -> str:
    """The figure as markup for Simple's header: ``↓ 2 · 43% · 3.1 MB/s``; empty when there is none."""
    parts, unseen = _figure_parts()
    if parts:
        return "↓ " + " · ".join(parts)
    if unseen:
        return "↓ [good]✓[/good]" + tn("{n} new", "{n} new", unseen)
    return ""


# --- the main menu's row ---------------------------------------------------------------------

def menu_hint() -> Text:
    """``2 running · 1 queued  D``: what the main menu's Downloads row says beside its name."""
    jobs = _jobs()
    running, queued, finished = _counts(jobs)
    manager = current()
    unseen = manager.summary().unseen_completions if manager is not None else 0
    hint = Text()
    if running:
        hint.append(tn("{n} running", "{n} running", running))
        if queued:
            hint.append(" · ", style=theme.MUTED)
            hint.append(tn("{n} queued", "{n} queued", queued))
    elif queued:
        hint.append(tn("{n} queued", "{n} queued", queued))
    elif unseen:
        hint.append("✓ ", style=theme.GOOD)
        hint.append(tn("{n} new", "{n} new", unseen))
    elif finished:
        hint.append(tn("{n} finished", "{n} finished", finished))
    else:
        hint.append(t("none running"))
    hint.append("  D", style=theme.KEY)
    return hint


def menu_inspect() -> list[Text]:
    """The inspector's lines for the main menu's row: each active job, then the unseen completions."""
    manager = current()
    if manager is None:
        return []
    jobs = manager.snapshot()
    lines = [Text.assemble((job.title, ""), ("  ", ""), _state_hint(job)) for job in jobs
             if job.state in downloads.ACTIVE_STATES]
    for job in jobs:
        if job.state == "done":
            lines.append(Text.assemble(("✓ ", theme.GOOD), (job.title, ""),
                                       ("  " + format_size(job.total_bytes or job.done_bytes), theme.MUTED)))
    if len(lines) > _INSPECT_LINES:
        lines = lines[:_INSPECT_LINES - 1] + [Text("…", style=theme.MUTED)]
    return lines


def menu_row() -> "SelectItem | None":
    """The main menu's Downloads row, once a background download was started this session."""
    if current() is None:
        return None
    return SelectItem(t("Downloads"), value="__downloads__", hint=menu_hint(),
                      description=t("Downloads running in the background: follow them, stop one or open its folder."),
                      inspect=menu_inspect)


def update_menu_row(item: SelectItem) -> None:
    """Refresh a row from ``menu_row`` in place: the live hint and the inspector's lines."""
    item.hint = menu_hint()
    item._details = None


# --- rows of the Downloads screen -----------------------------------------------------------

def _clock(moment: "float | None") -> str:
    return time.strftime("%H:%M", time.localtime(moment)) if moment else ""


def _span(seconds: float) -> str:
    """``9 min``, ``40 s``, ``1 h 05 min``."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return t("{n} s", n=seconds)
    minutes = seconds // 60
    if minutes < 60:
        return t("{n} min", n=minutes)
    return t("{hours} h {minutes:02d} min", hours=minutes // 60, minutes=minutes % 60)


def _percent(job) -> str:
    return _percent_of(job.progress)


def _state_hint(job) -> Text:
    """The hint beside a row, with its own colours: progress, a state word, or the result."""
    muted = theme.MUTED
    if job.state == "running":
        percent = _percent(job)
        if not percent:
            return Text(job.state_label, style=muted)
        hint = Text(percent)
        if job.speed_bps:
            hint.append(" · ", style=muted)
            hint.append(_rate(job.speed_bps), style=muted)
        if job.eta_s is not None:
            hint.append(" · ", style=muted)
            hint.append(_span(job.eta_s), style=muted)
        return hint
    if job.state == "done":
        return Text.assemble(("✓", theme.GOOD), (" " + format_size(job.total_bytes or job.done_bytes), ""))
    if job.state in ("failed", "interrupted"):
        return Text(job.state_label, style=theme.BAD)
    if job.state == "stopped":
        hint = Text(job.state_label, style=theme.WARN)
        percent = _percent(job)
        if percent:
            hint.append(" · ", style=muted)
            hint.append(percent, style=muted)
        return hint
    return Text(job.state_label, style=muted)  # queued, fetching metadata, paused, unpacking


_LOG_PREFIX = N_("aria2c log: ")  # the engine's note, written in the language of the moment it failed


def _log_prefixes() -> tuple[str, ...]:
    return tuple(dict.fromkeys((t(_LOG_PREFIX), _LOG_PREFIX)))


def _log_note(job) -> str:
    """The aria2c log lines the engine kept with a failed job, if any."""
    for note in job.notes:
        for prefix in _log_prefixes():
            if note.startswith(prefix):
                return note[len(prefix):]
    return ""


def _description(job) -> str:
    """The lines under the list (or in the inspector) for the focused row, as markup."""
    folder = escape(job.target_dir)
    if job.state in ("running", "paused", "unpacking"):
        swarm = tn("{n} peer", "{n} peers", job.peers) + " · " + tn("{n} seed", "{n} seeds", job.seeds)
        sizes = (t("{done} of {total}", done=format_size(job.done_bytes), total=format_size(job.total_bytes))
                 if job.total_bytes else job.state_label)
        return t("Saving to {folder}", folder=folder) + "\n" + sizes + " · " + swarm
    if job.state == "metadata":
        return t("Saving to {folder}", folder=folder) + "\n" + t("Waiting for the swarm to describe the files.")
    if job.state == "queued":
        return t("Saving to {folder}", folder=folder) + "\n" + t("Starts when a running download finishes.")
    if job.state == "done":
        when = t("finished {time}", time=_clock(job.finished_at))
        took = (" · " + t("took {span}", span=_span(job.finished_at - job.started_at))
                if job.started_at and job.finished_at else "")
        return t("Saved to {folder}", folder=folder) + "\n" + when + took
    if job.state in ("failed", "interrupted"):
        tail = _log_note(job).splitlines()
        return escape(job.error or job.state_label) + ("\n" + escape(" ".join(tail[-2:])) if tail else "")
    percent = _percent(job)
    stopped = (t("Stopped at {percent}", percent=percent) if percent else t("Stopped")) + " · "
    return stopped + t("the partial files stay in {folder}", folder=folder) + "\n" + t("Enter resumes it.")


def _pair(label: str, value: str) -> Text:
    line = Text(label + "  ", style=theme.MUTED)
    line.append(value)
    return line


def _inspect(job) -> list[Text]:
    """The inspector's detail lines: files, times, speed, notes and the log's path."""
    lines: list[Text] = []
    if job.files:
        count = tn("{n} file", "{n} files", len(job.files))
        if len(job.files) == 1:
            count += " · " + os.path.basename(job.files[0])
        lines.append(_pair(t("Files"), count))
    elif job.select:
        lines.append(_pair(t("Files"), tn("{n} picked", "{n} picked", len(job.select))))
    if job.state in downloads.ACTIVE_STATES and job.started_at:
        when = _clock(job.started_at)
        if job.eta_s is not None:
            when += " · " + t("{span} left", span=_span(job.eta_s))
        lines.append(_pair(t("Started"), when))
    elif job.state == "queued":
        lines.append(_pair(t("Queued"), _clock(job.created_at)))
    if job.state == "done" and job.started_at and job.finished_at:
        took = _span(job.finished_at - job.started_at)
        seconds = job.finished_at - job.started_at
        if job.total_bytes and seconds >= 1:
            took += " · " + t("{rate} on average", rate=_rate(int(job.total_bytes / seconds)))
        lines.append(_pair(t("Took"), took))
    if job.state in ("failed", "interrupted") and job.started_at:
        tried = _clock(job.started_at)
        if job.finished_at:
            tried += " · " + _span(job.finished_at - job.started_at)
        lines.append(_pair(t("Tried"), tried))
    if job.state == "stopped" and job.finished_at:
        lines.append(_pair(t("Stopped"), _clock(job.finished_at)))
    for note in job.notes:
        prefix = next((p for p in _log_prefixes() if note.startswith(p)), None)
        if prefix is not None:
            lines += [Text(line, style=theme.MUTED) for line in note[len(prefix):].splitlines()]
        else:
            lines.append(Text(note))
    if job.log_path:
        lines.append(_pair(t("Log"), job.log_path))
    return lines


def _row(job) -> SelectItem:
    return SelectItem(job.title, value=job.id, hint=_state_hint(job), description=_description(job),
                      inspect=lambda job=job: _inspect(job))


def _section(label: str) -> SelectItem:
    return SelectItem(label=label, value="section_header", enabled=False)


def _rows(jobs) -> list[SelectItem]:
    """ACTIVE then FINISHED, each heading only when it has rows; Back last."""
    active = [job for job in jobs if job.state in downloads.ACTIVE_STATES]
    finished = [job for job in jobs if job.state in downloads.FINISHED_STATES]
    items: list[SelectItem] = []
    if active:
        items.append(_section(t("Active")))
        items += [_row(job) for job in active]
    if finished:
        items.append(_section(t("Finished")))
        items += [_row(job) for job in finished]
    items.append(SelectItem(t("Back"), None, is_action=True))
    return items


def _status(jobs) -> str:
    running, queued, finished = _counts(jobs)
    parts = []
    if running:
        parts.append(tn("{n} running", "{n} running", running))
    if queued:
        parts.append(tn("{n} queued", "{n} queued", queued))
    if finished and not parts:
        parts.append(tn("{n} finished", "{n} finished", finished))
    return " · ".join(parts)


def _flavour(jobs) -> str:
    """The Athanor line under the frame's edge: the furnace, in the main menu's voice."""
    running, queued, finished = _counts(jobs)
    if running:
        line = tn("One retort bubbles over the fire", "{n} retorts bubble over the fire", running)
        if queued:
            line += "; " + tn("one more waits its turn", "{n} more wait their turn", queued)
        return line + "."
    if finished:
        return tn("The fire is out; one vessel has cooled.", "The fire is out; {n} vessels have cooled.", finished)
    return t("The furnace is cold; nothing is downloading.")


# --- the Downloads screen -------------------------------------------------------------------

_FOOTER = N_("↑/↓ navigate  •  Enter actions  •  X stop  •  O open folder  •  C clear finished  •  Esc back")


def _open_folder(path: str) -> bool:
    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def _folder_of(job) -> str:
    """The folder to open: the downloaded files' common folder once known, else the target."""
    if job.files:
        try:
            common = os.path.commonpath(job.files)
        except ValueError:
            return job.target_dir
        return common if len(job.files) > 1 and os.path.isdir(common) else os.path.dirname(common)
    return job.target_dir


def _say(message: str) -> None:
    frames.announce(message)


def _open(job) -> None:
    folder = _folder_of(job)
    if not _open_folder(folder):
        _say(t("[warn]Could not open {folder}[/warn]", folder=escape(folder)))


def _stop(manager, job) -> None:
    try:
        manager.stop(job.id)
    except Exception as error:
        _say(t("[warn]Could not stop {title}: {error}[/warn]", title=escape(job.title), error=escape(str(error))))


def _again(manager, job) -> None:
    """Retry a failed download or resume a stopped one: the same magnet, folder and files."""
    try:
        manager.enqueue_aria2(job.title, job.magnet, job.select, source=job.source,
                              provider_slug=job.provider_slug, method=job.method)
    except downloads.DuplicateDownloadError as error:
        _say(f"[warn]{escape(str(error))}[/warn]")
        return
    except Exception as error:
        _say(t("[warn]Could not start the download again: {error}[/warn]", error=escape(str(error))))
        return
    try:
        manager.remove(job.id)
    except Exception:
        pass  # the finished row stays beside the new one; harmless


def _show_log(job) -> None:
    from torrent_finder.downloader import _log_tail
    tail = _log_tail(job.log_path, _LOG_LINES) if job.log_path else ""
    lines = tail.splitlines() or [t("The log is empty.")]
    items = [SelectItem(line, value="__line__", passive=True) for line in lines]
    items.append(SelectItem(t("Back"), None, is_action=True))
    arrow_select(items, title=t("Downloads › Log"), intro=Text(job.log_path, style=theme.MUTED),
                 footer=t("↑/↓ scroll • Esc back"), start_index=len(items) - 1)


def _actions(manager, job) -> None:
    """Enter on a row: what can be done with this download, by its state."""
    items: list[SelectItem] = []
    if job.state in downloads.ACTIVE_STATES:
        items.append(SelectItem(t("Stop"), "stop", description=t("aria2c keeps the partial files; Resume picks them up later.")))
    elif job.state == "stopped":
        items.append(SelectItem(t("Resume"), "again", description=t("Downloads the same files to the same folder; aria2c continues from the partial files.")))
    else:
        items.append(SelectItem(t("Retry"), "again", description=t("Starts the download again with the same files and folder.")))
    items.append(SelectItem(t("Open folder"), "open", hint=_folder_of(job)))
    if job.state in downloads.FINISHED_STATES:
        items.append(SelectItem(t("Remove from the list"), "remove", description=t("Forgets this row; the files stay where they are.")))
    if job.log_path:
        items.append(SelectItem(t("Show log"), "log", description=t("The last lines aria2c wrote.")))
    items.append(SelectItem(t("Back"), None, is_action=True))
    index = arrow_select(items, title=t("Downloads › {title}", title=escape(job.title)),
                         intro=Text.assemble((job.state_label, theme.MUTED)),
                         footer=t("↑/↓ navigate  •  Enter select  •  Esc back"))
    choice = items[index].value if index is not None else None
    if choice == "stop":
        _stop(manager, job)
    elif choice == "again":
        _again(manager, job)
    elif choice == "open":
        _open(job)
    elif choice == "remove":
        try:
            manager.remove(job.id)
        except Exception as error:
            _say(f"[warn]{escape(str(error))}[/warn]")
    elif choice == "log":
        _show_log(job)


def downloads_screen(focus: "str | None" = None) -> None:
    """Every background download, live: ACTIVE and FINISHED rows, the focused one's details, keys to act.

    *focus* is a job id to start on; otherwise the first row.
    """
    manager = current()
    if manager is not None:
        manager.mark_seen()
    start = 1 if manager is not None and manager.snapshot() else 0
    if focus is not None:
        start = next((i for i, item in enumerate(_rows(_jobs())) if item.value == focus), start)
    while True:
        jobs = list(_jobs())
        items = _rows(jobs)
        seen = {"revision": revision()}

        def refresh(jobs=jobs, items=items, seen=seen) -> bool:
            now = revision()
            if now == seen["revision"]:
                return False
            seen["revision"] = now
            jobs[:] = _jobs()
            items[:] = _rows(jobs)
            return True

        def find(cursor: int, items_now: list):
            value = items_now[cursor].value if 0 <= cursor < len(items_now) else None
            return next((job for job in jobs if job.id == value), None) if isinstance(value, str) else None

        def stop_focused(cursor: int, items_now: list) -> bool:
            job = find(cursor, items_now)
            if job is not None and job.state in downloads.ACTIVE_STATES and manager is not None:
                _stop(manager, job)
                refresh()
            return True

        def open_focused(cursor: int, items_now: list) -> bool:
            job = find(cursor, items_now)
            if job is not None:
                _open(job)
            return True

        def clear_finished(cursor: int, items_now: list) -> bool:
            if manager is not None:
                manager.clear_finished()
                refresh()
            return True

        def intro():
            if not jobs:
                lines = [Text(t("Nothing is downloading in the background."))]
                if not enabled():
                    lines.append(Text(t("Turn on \"Downloads run: in background\" under Settings in a torrent's "
                                        "download menu; aria2c downloads then keep going while you search."),
                                      style=theme.MUTED))
                return lines
            if not theme.FRAMED or theme.view_height(console.size.height, console.size.width) < 30:
                return ""
            return Text(_flavour(jobs), style=theme.MUTED)

        def footer() -> str:
            return t(_FOOTER) if jobs else t("Esc back")

        index = arrow_select(
            items, title=t("Downloads"), status=lambda: _status(jobs), intro=intro,
            footer=footer, start_index=min(start, len(items) - 1), refresh=refresh,
            key_actions={"X": stop_focused, "x": stop_focused, "O": open_focused, "o": open_focused,
                         "C": clear_finished, "c": clear_finished},
        )
        if index is None or items[index].value is None:
            return
        job = find(index, items)
        if job is not None and manager is not None:
            _actions(manager, job)
        start = index


# --- after queuing a download: the confirmation ----------------------------------------------

def _ahead_line(size_bytes: int, ahead: int, folder: str, extra: list[str] = ()) -> Text:
    parts = [format_size(size_bytes)] if size_bytes else []
    parts += list(extra)
    parts.append(tn("queued behind {n} running", "queued behind {n} running", ahead) if ahead >= 2
                 else t("starting now"))
    parts.append(t("saves to {folder}", folder=folder))
    return Text(" · ".join(parts), style=theme.MUTED)


def background_started_prompt(name: str, folder: str, *, size_bytes: int = 0, ahead: int = 0,
                              facts: list[str] = ()) -> str:
    """Continue, go back to the download options, or open Downloads; returns "next" or "back".

    *ahead* is how many jobs were active before this one: two run at a time,
    so a third queues. *facts* are extra words for the line under the name
    (a batch's counts).
    """
    items = [
        SelectItem(t("Continue to What's Next"), value="next",
                   description=t("The download keeps going. Downloads (D on the main menu) follows it, "
                                 "and a message says when it is done.")),
        SelectItem(t("Back to download options"), value="back",
                   description=t("Keep this torrent's options open. The download keeps going.")),
        SelectItem(t("Open Downloads"), value="downloads", hint="D",
                   description=t("Every download: follow it, stop it or open its folder.")),
    ]
    intro = [Text(name, style="bold"), _ahead_line(size_bytes, ahead, folder, facts)]
    start = 0
    while True:
        picked = arrow_select(items, title=t("Downloading in the background"), intro=intro, start_index=start,
                              footer=t("↑/↓ select  •  Enter confirm  •  D downloads  •  Esc back to download options"),
                              hotkeys={"D": "downloads", "d": "downloads"})
        if picked is None:
            return "back"
        if isinstance(picked, tuple):
            picked = 2
        choice = items[picked].value
        if choice != "downloads":
            return choice
        downloads_screen()
        start = 2


# --- quitting with downloads running --------------------------------------------------------

def quit_prompt() -> bool:
    """Keep Torrent Finder open (the default; Esc and Ctrl+C too) or stop every download and quit."""
    jobs = [job for job in _jobs() if job.state in downloads.ACTIVE_STATES]
    count = len(jobs)
    items = [
        SelectItem(t("Keep Torrent Finder open"), value="stay", hint="Esc",
                   description=t("The downloads carry on. Downloads (D on the main menu) follows them.")),
        SelectItem(tn("Stop {n} download and quit", "Stop {n} downloads and quit", count), value="quit",
                   description=t("aria2c keeps the partial files; downloading the same torrent to the same folder "
                                 "later resumes them.")),
    ]
    intro = [Text(tn("{n} download is running:", "{n} downloads are running:", count), style=theme.MUTED)]
    for job in jobs[:3]:
        intro.append(Text.assemble((job.title, ""), ("  ", ""), _state_hint(job)))
    if count > 3:
        intro.append(Text(tn("… and {n} more", "… and {n} more", count - 3), style=theme.MUTED))
    picked = arrow_select(items, title=t("Exit"), intro=intro,
                          footer=t("↑/↓ select  •  Enter confirm  •  Esc keep open"))
    return picked is not None and items[picked].value == "quit"


def stop_all() -> None:
    """Stop every job and the engine, with a spinner while aria2c saves its partial files."""
    with console.status(t("[accent]Stopping downloads…[/accent]"), spinner=theme.SPINNER):
        downloads.shutdown_all()


# --- the download menu's setting row ---------------------------------------------------------

def setting_label() -> str:
    return t("Downloads run: in background") if enabled() else t("Downloads run: in this screen")


SETTING_HELP = N_("aria2c downloads keep going while you search; Downloads (D on the main menu) follows them. "
                  "'In this screen' watches each download here, as before.")


def toggle_setting(item: SelectItem) -> None:
    from torrent_finder.state import save_setting
    save_setting(SETTING, not enabled())
    item.label = setting_label()
