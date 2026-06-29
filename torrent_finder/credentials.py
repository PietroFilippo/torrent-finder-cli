"""Optional API credentials for subtitle providers.

Credentials are read at runtime from two sources, in order:

1. Environment variables (recommended) — e.g. ``OPENSUBTITLES_USERNAME``.
2. A local ``subtitle_credentials.json`` next to this file (gitignored).

The in-program credentials manager writes to source #2 (the JSON file), never
to environment variables. Real values must NEVER be committed; the JSON file is
listed in ``.gitignore``. See README for setup.
"""

import json
import os
from pathlib import Path

from torrent_finder.constants import data_path

_CRED_FILE = Path(data_path("subtitle_credentials.json"))

# Maps the public env-var name -> the key used inside the JSON fallback file.
_FILE_KEYS = {
    "OPENSUBTITLES_USERNAME": "opensubtitles_username",
    "OPENSUBTITLES_PASSWORD": "opensubtitles_password",
    "OPENSUBTITLES_APIKEY": "opensubtitles_apikey",
    "ADDIC7ED_USERNAME": "addic7ed_username",
    "ADDIC7ED_PASSWORD": "addic7ed_password",
    "JIMAKU_API_KEY": "jimaku_api_key",
    "RUTRACKER_USERNAME": "rutracker_username",
    "RUTRACKER_PASSWORD": "rutracker_password",
    "ONLINE_FIX_USERNAME": "online_fix_username",
    "ONLINE_FIX_PASSWORD": "online_fix_password",
    "TMDB_API_KEY": "tmdb_api_key",
    "IGDB_CLIENT_ID": "igdb_client_id",
    "IGDB_CLIENT_SECRET": "igdb_client_secret",
}

_file_cache: dict | None = None


def _load_file() -> dict:
    """Read the gitignored JSON file once, tolerating a missing/broken file."""
    global _file_cache
    if _file_cache is None:
        _file_cache = {}
        try:
            if _CRED_FILE.exists():
                data = json.loads(_CRED_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _file_cache = data
        except Exception:
            _file_cache = {}
    return _file_cache


def _file_key(env_key: str) -> str:
    return _FILE_KEYS.get(env_key, env_key)


def get_credential(env_key: str) -> str | None:
    """Return a credential by env-var name, or None if unset everywhere.

    Environment wins over the file so a user can override per-shell without
    editing anything on disk.
    """
    val = os.environ.get(env_key)
    if val and val.strip():
        return val.strip()
    file_val = _load_file().get(_file_key(env_key))
    if isinstance(file_val, str) and file_val.strip():
        return file_val.strip()
    return None


def env_overrides(env_key: str) -> bool:
    """True if an environment variable is set for this key.

    The env value takes precedence over the file, so the in-program manager
    warns when one would shadow a saved value.
    """
    val = os.environ.get(env_key)
    return bool(val and val.strip())


def credential_source(env_key: str) -> str | None:
    """Where the active value comes from: ``"env"``, ``"file"``, or ``None``."""
    if env_overrides(env_key):
        return "env"
    file_val = _load_file().get(_file_key(env_key))
    if isinstance(file_val, str) and file_val.strip():
        return "file"
    return None


def file_has(env_key: str) -> bool:
    """True if the JSON file holds a value for this key (ignoring env)."""
    file_val = _load_file().get(_file_key(env_key))
    return isinstance(file_val, str) and bool(file_val.strip())


def _restrict_permissions(path: Path) -> None:
    """Best-effort: restrict the credentials file to the owner on POSIX.

    On Windows we leave NTFS inheritance alone — the file lives under the
    user's profile, and forcing ACLs via icacls is fragile (it can lock the
    owner out of their own file).
    """
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


def save_credentials(updates: dict) -> None:
    """Persist credentials to the gitignored JSON file.

    ``updates`` maps env-var names to values; a value of ``None`` or empty
    string removes that key. The in-memory cache is invalidated so the change
    takes effect immediately within the running program.
    """
    data: dict = {}
    try:
        if _CRED_FILE.exists():
            existing = json.loads(_CRED_FILE.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data = existing
    except Exception:
        data = {}

    for env_key, value in updates.items():
        fkey = _file_key(env_key)
        if value is None or not str(value).strip():
            data.pop(fkey, None)
        else:
            data[fkey] = str(value).strip()

    # Write atomically, then lock down permissions.
    tmp = _CRED_FILE.with_name(_CRED_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _CRED_FILE)
    _restrict_permissions(_CRED_FILE)

    global _file_cache
    _file_cache = None  # force reload on next read


def opensubtitles_config() -> dict | None:
    """Provider config for subliminal's ``opensubtitlescom`` provider.

    Returns ``None`` when no username/password is configured, so callers can
    silently fall back to the anonymous provider set.
    """
    username = get_credential("OPENSUBTITLES_USERNAME")
    password = get_credential("OPENSUBTITLES_PASSWORD")
    if not username or not password:
        return None
    cfg = {"username": username, "password": password}
    apikey = get_credential("OPENSUBTITLES_APIKEY")
    if apikey:
        cfg["apikey"] = apikey
    return cfg


def addic7ed_config() -> dict | None:
    """Provider config for subliminal's ``addic7ed`` provider (TV series).

    Returns ``None`` when no username/password is configured; the provider
    then runs anonymously with tighter limits.
    """
    username = get_credential("ADDIC7ED_USERNAME")
    password = get_credential("ADDIC7ED_PASSWORD")
    if not username or not password:
        return None
    return {"username": username, "password": password}


def jimaku_api_key() -> str | None:
    """Jimaku API key for anime subtitle lookups, or None if unset."""
    return get_credential("JIMAKU_API_KEY")


def rutracker_config() -> dict | None:
    """Username/password for the RuTracker provider, or None when unset."""
    username = get_credential("RUTRACKER_USERNAME")
    password = get_credential("RUTRACKER_PASSWORD")
    if not username or not password:
        return None
    return {"username": username, "password": password}


def online_fix_config() -> dict | None:
    """Username/password for the Online-Fix provider, or None when unset."""
    username = get_credential("ONLINE_FIX_USERNAME")
    password = get_credential("ONLINE_FIX_PASSWORD")
    if not username or not password:
        return None
    return {"username": username, "password": password}
