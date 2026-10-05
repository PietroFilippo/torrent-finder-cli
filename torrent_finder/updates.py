"""Install-aware 'update available' check + one-click update.

Three install kinds, each with its own check + update path:
  - git    : a source checkout — compares against the upstream branch; updates
             with ``git pull``.
  - pip    : installed via pip/pipx — compares ``__version__`` to the latest on
             PyPI; updates with pip, then lets pipx refresh its records.
  - binary : a frozen build — compares to PyPI (tags drive both releases); points
             the user at the GitHub Releases page.

Fail-silent and rate-limited (network at most once per day); the cheap local
comparison runs every launch.

Updates run in the app's own terminal (ADR-0024): installer commands run out of
sight with their output in update.log, pip reports download progress, and on
Windows the running launcher is renamed out of the installer's way first.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from torrent_finder import __version__
from torrent_finder.state import load_setting, save_setting

PACKAGE = "torrent-finder-cli"
_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
_FETCH_INTERVAL = 86400  # seconds — hit the network at most once per day
_PYPI_JSON = "https://pypi.org/pypi/torrent-finder-cli/json"
_RELEASES_URL = "https://github.com/PietroFilippo/torrent-finder-cli/releases"


def _git(*args: str, timeout: int = 4) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", _REPO_DIR, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def install_kind() -> str:
    """How this copy was installed: 'git', 'pip', 'binary', or 'unknown'."""
    if getattr(sys, "frozen", False):
        return "binary"
    try:
        if _git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true":
            return "git"
    except Exception:
        pass
    try:
        import importlib.metadata as md
        md.distribution(PACKAGE)
        return "pip"
    except Exception:
        return "unknown"


def _due(force: bool) -> bool:
    last = load_setting("last_update_check", 0)
    try:
        return force or (time.time() - float(last)) >= _FETCH_INTERVAL
    except (TypeError, ValueError):
        return True


# ---- git installs -----------------------------------------------------------

def commits_behind(force: bool = False) -> int:
    """How many commits the checkout is behind its upstream. 0 if unknown."""
    try:
        if _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode != 0:
            return 0
        if _due(force):
            # Stamp only on a successful fetch, so an offline attempt retries next
            # launch instead of going quiet for a day.
            if _git("fetch", "--quiet").returncode == 0:
                save_setting("last_update_check", time.time())
        r = _git("rev-list", "--count", "HEAD..@{u}")
        return int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    except Exception:
        return 0


# ---- pip / binary installs --------------------------------------------------

def _fetch_pypi_latest() -> "str | None":
    try:
        import requests
        r = requests.get(_PYPI_JSON, timeout=4)
        r.raise_for_status()
        return r.json()["info"]["version"]
    except Exception:
        return None


def _latest_version(force: bool = False) -> "str | None":
    """Latest PyPI version, fetched at most once/day and cached in settings."""
    if _due(force):
        v = _fetch_pypi_latest()
        if v:
            save_setting("last_pypi_version", v)
            save_setting("last_update_check", time.time())
            return v
    return load_setting("last_pypi_version", None)


def _version_key(version: str) -> tuple:
    """Naive numeric release key: ``0.9.1`` → ``(0, 9, 1)``; local parts ignored."""
    return tuple(int(n) for n in re.findall(r"\d+", version.split("+")[0]))


def _is_newer(latest: "str | None", current: str) -> bool:
    if not latest or not current or current == "0+unknown":
        return False
    try:
        from packaging.version import parse
        return parse(latest) > parse(current)
    except Exception:
        pass
    # No ``packaging`` on this install — naive numeric compare. Must never
    # treat mere inequality as newer: a cached older latest (e.g. 0.3.0 right
    # after updating to 0.3.1) would nag on every launch.
    try:
        return _version_key(latest) > _version_key(current)
    except Exception:
        return False


def _pipx_install() -> bool:
    """Heuristic: is this running from a pipx-managed venv?"""
    return "pipx" in sys.executable.lower() and shutil.which("pipx") is not None


# ---- public API -------------------------------------------------------------

def check_for_update(force: bool = False) -> "dict | None":
    """Return an info dict when an update is available, else None. Never raises.

    ``{"kind": "git", "behind": n}`` or ``{"kind": "pip"|"binary",
    "current": ..., "latest": ...}``.
    """
    try:
        kind = install_kind()
        if kind == "git":
            n = commits_behind(force)
            return {"kind": "git", "behind": n} if n > 0 else None
        if kind in ("pip", "binary"):
            latest = _latest_version(force)
            if _is_newer(latest, __version__):
                return {"kind": kind, "current": __version__, "latest": latest}
        return None
    except Exception:
        return None


def _banner(headline: str, action: str) -> str:
    """High-visibility notice: the theme's banner headline + bright action text.

    The ``banner`` styles (ui/theme.py) carry ``not dim``, which is
    load-bearing: the selector footer renders with a dim base style, which
    would grey the notice out without it. The headline is not bold: terminals
    render bold black as bright black (grey), barely readable on the banner.
    """
    return f"[banner] {headline} [/banner] [banner.action]{action}[/banner.action]"


def status_label(info: "dict | None") -> str:
    """A few words for a header status: ``update 0.8.2 ready``, ``3 commits behind``; '' when current."""
    if not info:
        return ""
    if info.get("kind") == "git":
        count = info.get("behind", 0)
        return f"{count} commit{'s' if count != 1 else ''} behind"
    return f"update {info.get('latest')} ready" if info.get("latest") else "update ready"


def notice_line(info: "dict | None") -> str:
    """Rich-markup line for an update info dict (no network), or '' if None."""
    if not info:
        return ""
    if info["kind"] == "git":
        n = info["behind"]
        s = "s" if n != 1 else ""
        return _banner(
            f"UPDATE AVAILABLE — {n} commit{s} behind",
            "Press [not dim bold]U[/not dim bold] on the menu to update, "
            "or run [not dim bold]git pull[/not dim bold].",
        )
    latest = info.get("latest")
    if info["kind"] == "pip":
        cmd = "pipx upgrade torrent-finder-cli" if _pipx_install() else "pip install -U torrent-finder-cli"
        return _banner(
            f"UPDATE AVAILABLE — v{latest}",
            "Press [not dim bold]U[/not dim bold] on the menu to update, "
            f"or run [not dim bold]{cmd}[/not dim bold].",
        )
    return _banner(
        f"UPDATE AVAILABLE — v{latest}",
        "Press [not dim bold]U[/not dim bold] on the menu to open "
        f"[not dim bold]{_RELEASES_URL}[/not dim bold].",
    )


def update_notice(force: bool = False) -> str:
    """Convenience: check + format in one call (keeps the original call site)."""
    return notice_line(check_for_update(force=force))


# ---- installing -------------------------------------------------------------

_STEP_TIMEOUT = 900          # seconds one installer command may run
_RAW_PROGRESS_PIP = (24, 1)  # the first pip with ``--progress-bar raw``
_MOVED_KEY = "moved_launchers"
_MOVED_NAME = re.compile(r"\.exe\.[0-9a-f]{8}\.old$")


class UpdateResult(NamedTuple):
    ok: bool
    message: str
    restart: bool = False  # a new version is on disk: restart to run it


class RestartRequested(SystemExit):
    """Leave the app so ``main()`` can start the updated version in this terminal."""

    def __init__(self) -> None:
        super().__init__(0)


def _update_files() -> tuple[Path, Path]:
    from torrent_finder.constants import machine_state_path
    return Path(machine_state_path("update-status.json")), Path(machine_state_path("update.log"))


def consume_update_report() -> str:
    """Report a Windows update that an older version queued in a hidden helper.

    Versions before in-place updates closed the app and installed afterwards,
    recording the result in update-status.json for the next launch.
    """
    status, log = _update_files()
    try:
        data = json.loads(status.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ""
        state = data.get("state")
        if state == "succeeded" and data.get("reopen") == "waiting" and time.time() < float(data.get("reopen_at", 0)) + 10:
            # The worker still owns this report while counting down to reopen.
            return ""
        if state == "pending":
            if time.time() - float(data.get("started_at", 0)) < 1900:
                return f"Update is still pending. Close other Torrent Finder windows and check {log}."
            data["error"] = "The updater did not report completion."
        status.replace(status.with_name("last-update-status.json"))
        if state == "succeeded":
            return "Package update completed successfully."
        return f"Update did not complete. Close all Torrent Finder windows, then retry from your terminal. Details: {log}. {data.get('error', '')}"
    except (OSError, ValueError, TypeError):
        return ""


# Windows keeps a running program's file from being replaced or deleted, but
# lets it be renamed. pip and pipx must write this app's launcher (the
# torrent-finder.exe that started it), so the update moves it aside first.
#
# The launcher is also a zip that Python keeps on sys.path, and every metadata
# lookup leaves it open in a way that forbids renaming. pip moves each file
# aside to uninstall and, when one move fails, does not put back the ones it
# already moved: the app is gone. So the update reads metadata first, lets go
# of the launcher, moves it, and checks nothing pip moves is still held open.

def _launcher_names() -> list[str]:
    """The console scripts this package installs: ``torrent-finder`` and ``torrent``."""
    try:
        import importlib.metadata as md
        names = [entry.name for entry in md.distribution(PACKAGE).entry_points
                 if entry.group == "console_scripts"]
    except Exception:
        names = []
    return names or ["torrent-finder", "torrent"]


def _installed_files() -> list[Path]:
    """The files pip moves aside to uninstall this package (Windows only, where that can fail)."""
    if os.name != "nt":
        return []
    try:
        import importlib.metadata as md
        distribution = md.distribution(PACKAGE)
        return [Path(os.path.normpath(distribution.locate_file(file))) for file in distribution.files or []]
    except Exception:
        return []


def _release_launcher() -> None:
    """Close the launcher zip that Python's metadata cache keeps open (a reference cycle: gc)."""
    import gc
    import importlib
    import importlib.metadata as md
    importlib.invalidate_caches()
    finder = getattr(md, "MetadataPathFinder", None)
    if finder is not None:  # the call above clears it too on newer Pythons
        finder.invalidate_caches()
    gc.collect()


def _held_open(path: Path) -> bool:
    """Whether a program holds *path* open in a way that forbids moving it (Windows)."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    # Rename (DELETE) access, sharing everything: refused only when another
    # handle forbids it. FILE_FLAG_OPEN_REPARSE_POINT: a link, not its target.
    handle = kernel.CreateFileW(str(path), 0x00010000, 0x7, None, 3, 0x00200000, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return ctypes.get_last_error() == 32  # ERROR_SHARING_VIOLATION
    kernel.CloseHandle(handle)
    return False


def _launcher_candidates(names: list[str]) -> list[Path]:
    """Every launcher a pip or pipx install may have for this app."""
    folders = [Path(sys.executable).parent,
               Path(os.environ.get("PIPX_BIN_DIR") or Path.home() / ".local" / "bin")]
    for scheme in (sysconfig.get_default_scheme(), f"{os.name}_user"):
        try:
            folders.append(Path(sysconfig.get_path("scripts", scheme)))
        except KeyError:
            pass
    folders += [Path(found).parent for found in map(shutil.which, names) if found]
    seen, candidates = set(), []
    for folder in folders:
        for name in names:
            path = folder / f"{name}.exe"
            key = os.path.normcase(os.path.abspath(path))
            if key not in seen and os.path.lexists(path):
                seen.add(key)
                candidates.append(path)
    return candidates


def _in_use(path: Path) -> bool:
    """Whether a program runs from *path*: Windows refuses to open it for writing."""
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def _move_running_launchers(names: list[str]) -> list[tuple[Path, Path]]:
    """Rename this app's running launchers aside; returns (original, moved) pairs. Windows only."""
    if os.name != "nt":
        return []
    _release_launcher()
    token = uuid4().hex[:8]
    moved = []
    for path in _launcher_candidates(names):
        if not _in_use(path):
            continue
        aside = path.with_name(f"{path.name}.{token}.old")
        try:
            os.replace(path, aside)
        except OSError:
            continue  # held by another window: the check before pip finds it
        moved.append((path, aside))
    return moved


def _settle_launchers(moved: list[tuple[Path, Path]]) -> None:
    """Put back launchers the installer did not replace; delete the rest once nothing runs them."""
    leftovers = []
    for original, aside in moved:
        if not os.path.lexists(original):
            try:
                os.replace(aside, original)
                continue
            except OSError:
                pass
        try:
            aside.unlink()
        except OSError:
            leftovers.append(str(aside))  # still running this very app
    if leftovers:
        try:
            known = load_setting(_MOVED_KEY, [])
            save_setting(_MOVED_KEY, [*(known if isinstance(known, list) else []), *leftovers])
        except Exception:
            pass


def remove_moved_launchers() -> None:
    """At startup: delete launchers earlier updates moved aside, once their app has exited."""
    try:
        paths = load_setting(_MOVED_KEY, [])
        if not paths:
            return
        remaining = []
        for path in paths if isinstance(paths, list) else []:
            if not isinstance(path, str) or not _MOVED_NAME.search(path):
                continue  # only ever delete files this module named
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                remaining.append(path)
        if remaining != paths:
            save_setting(_MOVED_KEY, remaining)
    except Exception:
        pass


def _pipx_tracks_index() -> bool:
    """Whether pipx installed this app by name (not from a file, URL or git), so pip may update it from PyPI.

    Otherwise ``pipx upgrade`` would put back the user's own source after pip.
    """
    try:
        metadata = json.loads((Path(sys.prefix) / "pipx_metadata.json").read_text(encoding="utf-8"))
        source = str(metadata["main_package"]["package_or_url"]).strip()
    except Exception:
        return True
    return re.fullmatch(r"torrent[-_.]finder[-_.]cli(\[[^\]]*\])?\s*([<>=!~].*)?", source, re.IGNORECASE) is not None


def _pip_command() -> "list[str] | None":
    """pip's upgrade command for this Python, with machine-readable progress when pip has it."""
    try:
        import importlib.metadata as md
        raw = _version_key(md.version("pip"))[:2] >= _RAW_PROGRESS_PIP
    except Exception:
        return None  # e.g. a pipx venv made by uv: pipx does the whole update
    return [sys.executable, "-m", "pip", "install", "--upgrade",
            "--progress-bar", "raw" if raw else "off", PACKAGE]


_PIP_PROGRESS = re.compile(r"^Progress (\d+) of (\d+)$")
_PIP_DOWNLOAD = re.compile(r"^\s*Downloading (\S+)")
_PIP_INSTALLING = re.compile(r"^Installing collected packages: (.+)$")
_PIP_INSTALLED = re.compile(r"^Successfully installed\b.*?\btorrent[-_]finder[-_]cli-(\S+)", re.IGNORECASE)
_PIP_CURRENT = re.compile(r"^Requirement already satisfied: torrent[-_]finder[-_]cli\b", re.IGNORECASE)
_PIPX_UPGRADED = re.compile(r"\bupgraded package torrent-finder-cli from \S+ to (\S+?),?\s", re.IGNORECASE)
_PIPX_CURRENT = re.compile(r"\btorrent-finder-cli is already at latest version\b", re.IGNORECASE)


class _InstallerOutput:
    """Reads pip and pipx output: stages, download bytes, the installed version and the last error."""

    def __init__(self, report):
        self.report = report
        self.file = ""
        self.version = ""
        self.satisfied = False   # the installed version was listed as satisfying the request
        self.installing = False
        self.error = ""

    @property
    def current(self) -> bool:
        """Nothing newer was found. ``pip -U`` lists the installed version as satisfied before upgrading it."""
        return self.satisfied and not self.installing and not self.version

    def feed(self, line: str) -> None:
        if match := _PIP_PROGRESS.match(line):
            done, total = int(match[1]), int(match[2])
            self.report("downloading", self.file, done=done, total=total or None)
        elif match := _PIP_DOWNLOAD.match(line):
            name = match[1].rsplit("/", 1)[-1]
            if not name.endswith(".metadata"):
                self.file = name
                self.report("downloading", name)
        elif match := _PIP_INSTALLING.match(line):
            self.installing = True
            self.report("installing", f"Installing {match[1]}.")
        elif match := _PIP_INSTALLED.match(line):
            self.version = match[1]
            self.report("installing", f"Installed {PACKAGE} {self.version}.", latest=self.version)
        elif match := _PIPX_UPGRADED.search(line + " "):
            self.version = match[1]  # pipx says so at the very end: the stage stays
        elif _PIP_CURRENT.match(line) or _PIPX_CURRENT.search(line):
            self.satisfied = True
        elif line.startswith("ERROR: "):
            self.error = line[len("ERROR: "):].strip()


def _stream(command: list[str], log, on_line) -> int:
    """Run one installer command out of sight and wait for it; returns its exit code.

    The output goes to *log* and, line by line, to *on_line*. On Windows the
    command gets a hidden console of its own, so no window or tab opens and
    Ctrl+C in the app's terminal cannot stop it halfway; elsewhere it runs in
    a session of its own for the same reason.
    """
    log.write(f"$ {' '.join(command)}\n")
    log.flush()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
           "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1", "GIT_TERMINAL_PROMPT": "0"}
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt",
        )
    except OSError as error:
        log.write(f"{error}\n")
        on_line(f"ERROR: could not start {command[0]}: {error}")
        return -1
    expired = threading.Event()

    def expire():
        expired.set()
        process.kill()

    timer = threading.Timer(_STEP_TIMEOUT, expire)
    timer.daemon = True
    timer.start()
    try:
        for line in process.stdout:
            log.write(line)
            try:
                on_line(line.rstrip("\n"))
            except Exception:
                pass  # a display problem must never abandon a running installer
        code = process.wait()
    finally:
        timer.cancel()
        process.stdout.close()
    if expired.is_set():
        on_line(f"ERROR: stopped after {_STEP_TIMEOUT // 60} minutes without finishing.")
    log.write(f"(exit code {code})\n")
    log.flush()
    return code


@contextmanager
def _patient(on_interrupt):
    """While an update runs, Ctrl+C only calls *on_interrupt*: stopping halfway could break the install."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGINT, lambda *_: on_interrupt and on_interrupt())
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous if previous is not None else signal.default_int_handler)


def _failed(error: str, log: Path, manual: str) -> str:
    reason = f"The installer stopped: {error}" if error else "The installer stopped with an error."
    return f"{reason}\nDetails: {log}\nOr close Torrent Finder and run: {manual}"


def _update_checkout(log, log_path: Path, report) -> UpdateResult:
    report("downloading", "Downloading the latest source changes.")
    current = []
    code = _stream(["git", "-C", _REPO_DIR, "pull", "--ff-only"], log,
                   lambda line: current.append(True) if line.startswith("Already up to date") else None)
    if code != 0:
        return UpdateResult(False, f"git pull failed — resolve it manually, then restart. Log: {log_path}")
    if current:
        return UpdateResult(True, "This checkout is already up to date.")
    return UpdateResult(True, "Downloaded the latest source changes.", restart=True)


def _update_package(info: dict, log, log_path: Path, report) -> UpdateResult:
    report("preparing", "Getting ready to update.")
    pipx = _pipx_install()
    manual = "pipx upgrade torrent-finder-cli" if pipx else "python -m pip install -U torrent-finder-cli"
    # Metadata lookups reopen the launcher: make them all before moving it.
    pip = _pip_command() if not pipx or _pipx_tracks_index() else None
    installed, names = _installed_files(), _launcher_names()
    if not pip and not pipx:
        return UpdateResult(False, f"pip is not available to this Python. Close Torrent Finder, then run: {manual}")
    output = _InstallerOutput(report)
    moved = _move_running_launchers(names)
    try:
        busy = next((path for path in installed if _held_open(path)), None)
        if busy:
            return UpdateResult(False, f"Another program has {busy.name} open, most likely another Torrent "
                                       "Finder window. Close it, then update again. Nothing was changed.")
        note = ""
        if pip:
            report("downloading", "Looking for the latest version on PyPI.")
            if _stream(pip, log, output.feed) != 0:
                return UpdateResult(False, _failed(output.error, log_path, manual))
        if pipx and not output.current:
            if pip:  # pip installed the update; pipx refreshes its records and its copy of the command
                report("finishing", "Updating pipx's copy of the torrent-finder command.")
            else:
                report("installing", "Upgrading with pipx. This can take a minute.")
            if _stream(["pipx", "upgrade", PACKAGE], log, output.feed) != 0:
                if not pip:
                    return UpdateResult(False, _failed(output.error, log_path, manual))
                note = f"\npipx could not refresh its records. Later, run: {manual}"
        if output.current:
            return UpdateResult(True, "Torrent Finder is already up to date.")
        version = output.version or info.get("latest") or ""
        return UpdateResult(True, f"Torrent Finder {version} is installed.".replace("  ", " ") + note, restart=True)
    finally:
        _settle_launchers(moved)


def run_update(info: dict, *, on_progress=None, on_interrupt=None) -> UpdateResult:
    """Perform the update for the detected install kind, in this terminal.

    *on_progress(stage, detail, **extra)* receives the stages (preparing,
    downloading, installing, finishing, opening); while pip downloads, extra
    carries ``done`` and ``total`` bytes. Ctrl+C cannot stop an install
    halfway, so it only calls *on_interrupt*. Installer output goes to
    update.log. Binaries open Releases without claiming an installation
    completed.
    """
    kind = info.get("kind")

    def report(stage, detail="", **extra):
        if on_progress:
            on_progress(stage, detail, **extra)

    if kind == "binary":
        try:
            import webbrowser
            report("opening", "Opening the download page in your browser.")
            if not webbrowser.open(_RELEASES_URL):
                return UpdateResult(False, f"Open {_RELEASES_URL} to download the new version.")
            return UpdateResult(True, f"Opened the Releases page — download v{info.get('latest')}.")
        except Exception:
            return UpdateResult(False, f"Open {_RELEASES_URL} to download the new version.")

    _, log_path = _update_files()
    try:
        log = log_path.open("w", encoding="utf-8")
    except OSError as error:
        return UpdateResult(False, f"Could not write the update log {log_path}: {error}")
    with log, _patient(on_interrupt):
        if kind == "git":
            return _update_checkout(log, log_path, report)
        return _update_package(info, log, log_path, report)


def _restart_command(args: list[str]) -> list[str]:
    """Start the app the way it was started: its launcher, or ``python -m torrent_finder``."""
    started = sys.argv[0] if sys.argv else ""
    if os.name == "nt" and not os.path.isfile(started) and os.path.isfile(started + ".exe"):
        started += ".exe"  # console-script wrappers drop the .exe from argv[0]
    if started.endswith(".py") or not os.path.isfile(started):
        return [sys.executable, "-m", "torrent_finder", *args]
    return [started, *args]


def relaunch(args: list[str]) -> int:
    """Start the updated app in this terminal; returns its exit code.

    POSIX replaces this process. Windows cannot, so this process waits for the
    new one, leaving Ctrl+C to it, and the shell gets its prompt back only
    when the new app exits. Raises OSError when the app cannot start.
    """
    command = _restart_command(args)
    if os.name != "nt":
        try:
            os.execv(command[0], command)
        except OSError:
            command = [sys.executable, "-m", "torrent_finder", *args]
            os.execv(sys.executable, command)
    previous = signal.signal(signal.SIGINT, lambda *_: None)
    try:
        return subprocess.call(command)
    finally:
        signal.signal(signal.SIGINT, previous if previous is not None else signal.default_int_handler)
