"""Lightweight 'update available' check for git-clone installs.

Compares the local checkout against its upstream tracking branch. Fail-silent:
if git is missing, this isn't a git repo, there's no upstream, or the network
is down, the check returns 0 and the program starts normally.

The remote ``git fetch`` is rate-limited to once per day (last-run timestamp
persisted via the settings store). The cheap local ``rev-list`` count runs every
launch against the last-fetched ref, so the notice disappears immediately after
a ``git pull`` instead of lingering until the next daily fetch.
"""

import os
import subprocess
import time

from torrent_finder.state import load_setting, save_setting

_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
_FETCH_INTERVAL = 86400  # seconds — hit the remote at most once per day


def _git(*args: str, timeout: int = 4) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", _REPO_DIR, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def commits_behind(force: bool = False) -> int:
    """How many commits the local checkout is behind its upstream.

    Returns 0 when up to date — or when the answer is unknown for any reason
    (no git, not a repo, no upstream, offline, timeout). Never raises.
    """
    try:
        # Require a git repo with an upstream tracking branch (e.g. origin/main).
        if _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").returncode != 0:
            return 0

        last = load_setting("last_update_check", 0)
        try:
            due = (time.time() - float(last)) >= _FETCH_INTERVAL
        except (TypeError, ValueError):
            due = True
        if force or due:
            # Only stamp the timestamp on a successful fetch, so a failed/offline
            # attempt retries next launch instead of going quiet for a day.
            if _git("fetch", "--quiet").returncode == 0:
                save_setting("last_update_check", time.time())

        r = _git("rev-list", "--count", "HEAD..@{u}")
        return int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    except Exception:
        return 0


def update_notice(force: bool = False) -> str:
    """Rich-markup line to show at startup, or '' when up to date / unknown."""
    n = commits_behind(force=force)
    if n <= 0:
        return ""
    plural = "s" if n != 1 else ""
    return (
        f"[warning]⬆ Update available — your copy is {n} commit{plural} behind.[/warning] "
        f"Run [highlight]git pull[/highlight] to update."
    )
