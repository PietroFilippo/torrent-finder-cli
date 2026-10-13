"""torrent-finder-cli — terminal torrent search across multiple sources.

See ``torrent_finder.main:main`` for the entry point (also exposed as the
``torrent-finder`` console script and ``python -m torrent_finder``).
"""

import re
import subprocess
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_described: list[str] = []


def _describe() -> None:
    try:
        _described.append(subprocess.run(
            ["git", "describe", "--tags", "--long", "--match", "v[0-9]*"], cwd=_ROOT,
            capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass


# ``_version.py`` is written when the package is built, so a git checkout keeps
# the last build's version after ``git pull``; its tags never go stale. Asking
# git takes a tenth of a second on Windows, so it runs while the app imports.
_describing = threading.Thread(target=_describe, daemon=True) if (_ROOT / ".git").exists() else None
if _describing:
    _describing.start()


def _checkout_version() -> "str | None":
    """A git checkout's version from its tags, as setuptools-scm names it (None outside one)."""
    if not _describing:
        return None
    _describing.join(3)
    match = re.fullmatch(r"v(\d+(?:\.\d+)*)-(\d+)-g[0-9a-f]+", _described[0] if _described else "")
    if not match:
        return None
    tag, distance = match.group(1), int(match.group(2))
    if not distance:
        return tag
    # Commits after a tag: the next patch release's dev build (v0.9.0 + 5 commits -> 0.9.1.dev5).
    parts = tag.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return f"{'.'.join(parts)}.dev{distance}"


def _built_version() -> str:
    try:
        # Written by setuptools-scm at build time (installed / frozen copies).
        from torrent_finder._version import __version__ as built
        return built
    except Exception:
        # Never built: the installed dist metadata, then a sentinel.
        try:
            from importlib.metadata import version

            return version("torrent-finder-cli")
        except Exception:
            return "0+unknown"


def __getattr__(name: str):
    # ``__version__`` is worked out on first use, by when git has usually answered.
    if name == "__version__":
        value = _checkout_version() or _built_version()
        globals()["__version__"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
