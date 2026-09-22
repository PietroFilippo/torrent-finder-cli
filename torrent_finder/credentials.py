"""Optional API credentials for subtitle providers.

Credentials are read at runtime from two sources, in order:

1. Environment variables (recommended) — e.g. ``OPENSUBTITLES_USERNAME``.
2. ``subtitle_credentials.json`` in the machine-stable user data directory.

The in-program credentials manager writes to source #2 (the JSON file), never
to environment variables. Real values must NEVER be committed; the JSON file is
listed in ``.gitignore``. See README for setup.
"""

import json
import os
import tempfile
import threading
from pathlib import Path

from torrent_finder.credential_registry import credential_file_keys
from torrent_finder.constants import legacy_data_paths, machine_state_path

_CRED_FILE = Path(machine_state_path("subtitle_credentials.json"))
_LEGACY_CRED_PATHS = legacy_data_paths("subtitle_credentials.json")
_lock = threading.RLock()

# Maps public env-var names to JSON keys, derived from the credential registry.
_FILE_KEYS = credential_file_keys()

_file_cache: dict | None = None
_file_problem = ""


def storage_problem() -> str:
    _load_file()
    return _file_problem


def _read_credentials(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Credential file must contain a JSON object")
    return data


def _write_file(data: dict) -> None:
    _CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp files prevent two app instances from sharing a partial write.
    fd, name = tempfile.mkstemp(prefix="credentials-", suffix=".tmp", dir=_CRED_FILE.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
        _restrict_permissions(temp)
        os.replace(temp, _CRED_FILE)
    finally:
        temp.unlink(missing_ok=True)


def _migrate_legacy_file() -> None:
    if _CRED_FILE.exists():
        return  # Existing file (including explicit clears) is authoritative.
    copies = []
    for candidate in _LEGACY_CRED_PATHS:
        path = Path(candidate)
        if path == _CRED_FILE:
            continue
        try:
            copies.append((path.stat().st_mtime, _read_credentials(path)))
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            raise OSError(f"Cannot read legacy credentials at {path}; the file was preserved.") from error
    if copies:
        # Keep each integration's username/password from the same source.
        # The newest file containing that integration wins as a complete group.
        from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
        merged = {}
        for _mtime, data in sorted(copies, key=lambda pair: pair[0]):
            for spec in CREDENTIAL_REGISTRY:
                keys = [_file_key(field.env_key) for field in spec.fields]
                if any(key in data for key in keys):
                    for key in keys:
                        merged.pop(key, None)
                        if key in data:
                            merged[key] = data[key]
        _write_file(merged)


def _load_file() -> dict:
    """Read the gitignored JSON file once, tolerating a missing/broken file."""
    global _file_cache, _file_problem
    with _lock:
        if _file_cache is None:
            try:
                _migrate_legacy_file()
                _file_cache = _read_credentials(_CRED_FILE) if _CRED_FILE.exists() else {}
                _file_problem = ""
            except (OSError, ValueError):
                # Do not cache a transient read error as an empty credential store.
                _file_problem = f"Cannot read or migrate credentials to {_CRED_FILE}. Existing files were preserved."
                return {}
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
    global _file_cache, _file_problem
    with _lock:
        _migrate_legacy_file()
        # A read/parse failure must abort, never overwrite other saved entries.
        data = _read_credentials(_CRED_FILE) if _CRED_FILE.exists() else {}
        for env_key, value in updates.items():
            fkey = _file_key(env_key)
            if value is None or not str(value).strip():
                data.pop(fkey, None)
            else:
                data[fkey] = str(value).strip()
        _write_file(data)
        _file_cache = None
        _file_problem = ""


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


def madokami_config() -> dict | None:
    """Username/password for the Madokami provider, or None when unset."""
    username = get_credential("MADOKAMI_USERNAME")
    password = get_credential("MADOKAMI_PASSWORD")
    if not username or not password:
        return None
    return {"username": username, "password": password}
