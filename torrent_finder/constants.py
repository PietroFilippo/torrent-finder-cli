"""Shared constants, theme, and console instance."""

import os
import shutil
import sys

from rich.console import Console
from rich.theme import Theme

# Theme & Console
custom_theme = Theme(
    {
        "title": "bold magenta",
        "info": "dim cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "highlight": "bold white",
    }
)

console = Console(theme=custom_theme)

# --- User data directory ------------------------------------------------------
# State, credentials, and (by default) downloads live in a per-user directory,
# not next to the code — so the app works when installed via pip/pipx or as a
# frozen binary, where the package directory is shared/read-only.
APP_DIRNAME = "torrent-finder-cli"
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def user_data_dir() -> str:
    """Per-user data directory for this app (not created here — see ``data_path``)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_DIRNAME)


def data_path(name: str) -> str:
    """Absolute path to a persisted file in the user data dir (dir created).

    On first use, migrates a legacy copy that lived next to the code so existing
    users keep their settings/credentials. The old repo-root location (richest,
    pre-packaging) wins over a transient copy inside the package dir. The copy is
    non-destructive (the original stays).
    """
    d = user_data_dir()
    os.makedirs(d, exist_ok=True)
    target = os.path.join(d, name)
    if not os.path.exists(target):
        for legacy in (os.path.join(_PKG_DIR, os.pardir, name), os.path.join(_PKG_DIR, name)):
            if os.path.isfile(legacy):
                try:
                    shutil.copy2(legacy, target)
                except OSError:
                    pass
                break
    return target


# API
API_URL = "https://apibay.org/q.php"
RESULTS_PER_PAGE = 20
DOWNLOADS_DIR = os.path.join(user_data_dir(), "downloads")


def get_download_dir() -> str:
    """Return the user's effective download directory.

    Reads the persisted ``download_dir`` setting; falls back to the
    default ``DOWNLOADS_DIR`` when unset, empty, or non-string. Callers
    are responsible for creating the directory before writing into it
    (existing ``os.makedirs(..., exist_ok=True)`` patterns still apply).
    """
    from torrent_finder.state import load_setting
    saved = load_setting("download_dir", None)
    if isinstance(saved, str) and saved.strip():
        return saved
    return DOWNLOADS_DIR

TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://exodus.desync.com:6969",
    "udp://open.demonii.com:1337/announce",
]

# Apibay category IDs
CATEGORIES = {
    # Video
    "video_all": 200,
    "video_movies": 201,
    "video_tv": 205,
    "video_hd_movies": 207,
    "video_hd_tv": 208,
    # Games
    "games_all": 400,
    "games_pc": 401,
    "games_mac": 402,
    "games_psx": 403,
    "games_xbox": 404,
    "games_wii": 405,
    "games_handheld": 406,
    "games_ios": 407,
    "games_android": 408,
    # Other
    "other_ebooks": 601,
    "other_comics": 602,  # manga / scanlation packs land here on apibay/TPB
}
