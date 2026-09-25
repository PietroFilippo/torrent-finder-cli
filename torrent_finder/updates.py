"""Install-aware 'update available' check + one-click update.

Three install kinds, each with its own check + update path:
  - git    : a source checkout — compares against the upstream branch; updates
             with ``git pull``.
  - pip    : installed via pip/pipx — compares ``__version__`` to the latest on
             PyPI; updates with pipx/pip.
  - binary : a frozen build — compares to PyPI (tags drive both releases); points
             the user at the GitHub Releases page.

Fail-silent and rate-limited (network at most once per day); the cheap local
comparison runs every launch.
"""

import os
import re
import shutil
import subprocess
import sys
import time
import json
from pathlib import Path
from uuid import uuid4

from torrent_finder import __version__
from torrent_finder.state import load_setting, save_setting

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
        md.distribution("torrent-finder-cli")
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
        def key(v: str) -> tuple:
            return tuple(int(n) for n in re.findall(r"\d+", v.split("+")[0]))
        return key(latest) > key(current)
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
    """High-visibility notice: black-on-yellow headline + bright action text.

    ``not dim`` is load-bearing: the selector footer renders with a dim base
    style, which would grey the notice out without it. No ``bold`` on the
    headline: terminals render bold black as bright black (grey), which is
    barely readable on the yellow background.
    """
    return (
        f"[not dim black on yellow] ⬆ {headline} [/not dim black on yellow] "
        f"[not dim bold yellow]{action}[/not dim bold yellow]"
    )


def notice_line(info: "dict | None") -> str:
    """Rich-markup line for an update info dict (no network), or '' if None."""
    if not info:
        return ""
    if info["kind"] == "git":
        n = info["behind"]
        s = "s" if n != 1 else ""
        return _banner(
            f"UPDATE AVAILABLE — {n} commit{s} behind",
            "Press [not dim bold white]U[/not dim bold white] on the menu to update, "
            "or run [not dim bold white]git pull[/not dim bold white].",
        )
    latest = info.get("latest")
    if info["kind"] == "pip":
        cmd = "pipx upgrade torrent-finder-cli" if _pipx_install() else "pip install -U torrent-finder-cli"
        return _banner(
            f"UPDATE AVAILABLE — v{latest}",
            "Press [not dim bold white]U[/not dim bold white] on the menu to update, "
            f"or run [not dim bold white]{cmd}[/not dim bold white].",
        )
    return _banner(
        f"UPDATE AVAILABLE — v{latest}",
        "Press [not dim bold white]U[/not dim bold white] on the menu to open "
        f"[not dim bold white]{_RELEASES_URL}[/not dim bold white].",
    )


def update_notice(force: bool = False) -> str:
    """Convenience: check + format in one call (keeps the original call site)."""
    return notice_line(check_for_update(force=force))


def needs_exit_before_update(info: dict) -> bool:
    return sys.platform == "win32" and info.get("kind") == "pip"


def _update_files() -> tuple[Path, Path]:
    from torrent_finder.constants import machine_state_path
    return Path(machine_state_path("update-status.json")), Path(machine_state_path("update.log"))


def _open_update_viewer(status: Path, job_id: str) -> bool:
    try:
        subprocess.Popen(
            [sys.executable, "-m", "torrent_finder.ui.update_progress",
             "--watch", str(status), "--job-id", job_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_CONSOLE, close_fds=True,
        )
        return True
    except OSError:
        # The installer is independent; a missing display must not cancel it.
        return False


def _schedule_update(command: list[str], *, show_progress=False, info=None) -> tuple[bool, str]:
    from torrent_finder.update_worker import write_status
    status, log = _update_files()
    if status.exists():
        try:
            previous = json.loads(status.read_text(encoding="utf-8"))
            if isinstance(previous, dict) and previous.get("state") == "pending" and time.time() - float(previous.get("started_at", 0)) < 1900:
                return True, "An update is already waiting. Close all Torrent Finder windows so it can finish."
        except (OSError, ValueError, TypeError):
            pass
    job = {"job_id": uuid4().hex, "started_at": time.time(),
           "current": (info or {}).get("current", ""), "latest": (info or {}).get("latest", "")}
    try:
        write_status(status, state="pending", phase="waiting", log=str(log), **job)
        subprocess.Popen(
            [sys.executable, "-m", "torrent_finder.update_worker", "--parent", str(os.getpid()),
             "--status", str(status), "--log", str(log), "--", *command],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError as error:
        try:
            write_status(status, state="failed", log=str(log), error=str(error), **job)
        except OSError:
            pass
        return False, f"Could not start the updater: {error}"
    if show_progress and _open_update_viewer(status, job["job_id"]):
        return True, "Update queued. Press any key to close this app and begin. Follow progress in the separate updater window."
    return True, f"Update queued. This app will close to release its launcher. Wait for the update before reopening. Log: {log}"


def consume_update_report() -> str:
    status, log = _update_files()
    try:
        data = json.loads(status.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ""
        state = data.get("state")
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


def _run_logged_update(command):
    _, log = _update_files()
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=900)
    return result.returncode == 0, log


def run_update(info: dict, *, on_progress=None) -> "tuple[bool, str]":
    """Perform the update for the detected install kind. Returns (ok, message).

    Windows pip installs queue a helper and require the caller to exit first.
    Installer output goes to update.log; on_progress receives stage and detail.
    Binaries open Releases without claiming an installation completed.
    """
    kind = info.get("kind")
    def progress(stage, detail):
        if on_progress:
            on_progress(stage, detail)

    if kind == "git":
        try:
            progress("installing", "Downloading the latest source changes.")
            ok, log = _run_logged_update(["git", "-C", _REPO_DIR, "pull", "--ff-only"])
            return (ok, "Updated — restart to use the new version." if ok
                    else f"git pull failed — resolve it manually, then restart. Log: {log}")
        except Exception as e:
            return (False, f"git pull failed: {e}")

    if kind == "binary":
        try:
            import webbrowser
            progress("opening", "Opening the download page in your browser.")
            if not webbrowser.open(_RELEASES_URL):
                return False, f"Open {_RELEASES_URL} to download the new version."
            return (True, f"Opened the Releases page — download v{info.get('latest')}.")
        except Exception:
            return (False, f"Open {_RELEASES_URL} to download the new version.")

    # pip / pipx
    cmd = (["pipx", "upgrade", "torrent-finder-cli"] if _pipx_install()
           else [sys.executable, "-m", "pip", "install", "-U", "torrent-finder-cli"])
    if needs_exit_before_update(info):
        if on_progress:
            progress("preparing", "Preparing a separate updater window.")
            return _schedule_update(cmd, show_progress=True, info=info)
        return _schedule_update(cmd)
    manual = "pipx upgrade torrent-finder-cli" if _pipx_install() else "python -m pip install -U torrent-finder-cli"
    try:
        progress("installing", "Downloading and installing the latest version.")
        ok, log = _run_logged_update(cmd)
        return (ok, "Updated — restart to use the new version." if ok
                else f"Update failed — close the app, then try: {manual}. Log: {log}")
    except Exception as e:
        return (False, f"Update failed: {e}. Close the app, then try: {manual}")
