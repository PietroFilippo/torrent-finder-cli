"""Optional API credentials for subtitle providers.

Credentials are read at runtime from two sources, in order:

1. Environment variables (recommended) — e.g. ``OPENSUBTITLES_USERNAME``.
2. A local ``subtitle_credentials.json`` next to this file (gitignored).

Real values must NEVER be committed. The JSON file is listed in
``.gitignore`` and the code only ever *reads* these — see README for setup.
"""

import json
import os
from pathlib import Path

_CRED_FILE = Path(__file__).resolve().parent / "subtitle_credentials.json"

# Maps the public env-var name -> the key used inside the JSON fallback file.
_FILE_KEYS = {
    "OPENSUBTITLES_USERNAME": "opensubtitles_username",
    "OPENSUBTITLES_PASSWORD": "opensubtitles_password",
    "OPENSUBTITLES_APIKEY": "opensubtitles_apikey",
    "ADDIC7ED_USERNAME": "addic7ed_username",
    "ADDIC7ED_PASSWORD": "addic7ed_password",
    "JIMAKU_API_KEY": "jimaku_api_key",
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


def get_credential(env_key: str) -> str | None:
    """Return a credential by env-var name, or None if unset everywhere.

    Environment wins over the file so a user can override per-shell without
    editing anything on disk.
    """
    val = os.environ.get(env_key)
    if val and val.strip():
        return val.strip()
    file_key = _FILE_KEYS.get(env_key, env_key)
    file_val = _load_file().get(file_key)
    if isinstance(file_val, str) and file_val.strip():
        return file_val.strip()
    return None


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
