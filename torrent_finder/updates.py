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
import shutil
import subprocess
import sys
import time

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
        return latest != current


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


def notice_line(info: "dict | None") -> str:
    """Rich-markup line for an update info dict (no network), or '' if None."""
    if not info:
        return ""
    if info["kind"] == "git":
        n = info["behind"]
        s = "s" if n != 1 else ""
        return (
            f"[warning]⬆ Update available — your copy is {n} commit{s} behind.[/warning] "
            f"Run [highlight]git pull[/highlight] to update (or open Tab → Update)."
        )
    latest = info.get("latest")
    if info["kind"] == "pip":
        cmd = "pipx upgrade torrent-finder-cli" if _pipx_install() else "pip install -U torrent-finder-cli"
        return (
            f"[warning]⬆ Update available — v{latest}.[/warning] "
            f"Run [highlight]{cmd}[/highlight] (or open Tab → Update)."
        )
    return (
        f"[warning]⬆ Update available — v{latest}.[/warning] "
        f"Download it from [highlight]{_RELEASES_URL}[/highlight]."
    )


def update_notice(force: bool = False) -> str:
    """Convenience: check + format in one call (keeps the original call site)."""
    return notice_line(check_for_update(force=force))


def run_update(info: dict) -> "tuple[bool, str]":
    """Perform the update for the detected install kind. Returns (ok, message).

    git/pip run with live output (the user sees progress); a frozen binary just
    opens the Releases page (a running .exe can't replace itself on Windows).
    """
    kind = info.get("kind")
    if kind == "git":
        try:
            r = subprocess.run(["git", "-C", _REPO_DIR, "pull", "--ff-only"])
            ok = r.returncode == 0
            return (ok, "Updated — restart to use the new version." if ok
                    else "git pull failed — resolve it manually, then restart.")
        except Exception as e:
            return (False, f"git pull failed: {e}")

    if kind == "binary":
        try:
            import webbrowser
            webbrowser.open(_RELEASES_URL)
            return (True, f"Opened the Releases page — download v{info.get('latest')}.")
        except Exception:
            return (False, f"Open {_RELEASES_URL} to download the new version.")

    # pip / pipx
    cmd = (["pipx", "upgrade", "torrent-finder-cli"] if _pipx_install()
           else [sys.executable, "-m", "pip", "install", "-U", "torrent-finder-cli"])
    try:
        r = subprocess.run(cmd)
        ok = r.returncode == 0
        return (ok, "Updated — restart to use the new version." if ok
                else "Update failed — try: pipx upgrade torrent-finder-cli")
    except Exception as e:
        return (False, f"Update failed: {e}. Try: pipx upgrade torrent-finder-cli")
