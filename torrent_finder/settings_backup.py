"""Versioned local transfer files with validation, preview and atomic restoration."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from torrent_finder import store
from torrent_finder.name_rules import NameRules
from torrent_finder.result_view import SORT_ORDERS
from torrent_finder.search_profiles import ProfileLibrary
from torrent_finder.state import compact_history, load_history

PREFERENCES = {"download_dir", "hide_stream_output", "search_profiles", "combined_search", "appearance"}


def _object(value, allowed=None):
    if not isinstance(value, dict) or (allowed is not None and set(value) - set(allowed)):
        raise ValueError("Invalid or unsupported backup fields; nothing was imported.")


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError("Expected a list of text values; nothing was imported.")


def _sort(data):
    if "result_sort" in data and (not isinstance(data["result_sort"], str) or data["result_sort"] not in SORT_ORDERS):
        raise ValueError("Invalid result order")
    NameRules.restore(data.get("name_rules", {}))


def validate_provider(data):
    _object(data, {"engines", "engine_modes", "explicitly_disabled_engines", "active_presets",
                   "preferred_presets", "result_sort", "name_rules", "nyaa_category"})
    _sort(data)
    for key in ("active_presets", "preferred_presets", "explicitly_disabled_engines"):
        _strings(data.get(key, []))
    engines, modes = data.get("engines", {}), data.get("engine_modes", {})
    _object(engines)
    _object(modes)
    if any(type(v) is not bool for v in engines.values()) or any(v not in ("on", "off", "auto") for v in modes.values()):
        raise ValueError("Invalid engine settings")
    if "nyaa_category" in data and data["nyaa_category"] not in ("1_0", "1_2", "1_3", "1_4"):
        raise ValueError("Invalid Nyaa Anime category")


def validate_profile(data):
    _object(data, {"selected", "providers", "shared", "result_sort", "name_rules"})
    _sort(data)
    if "selected" in data:
        _strings(data["selected"])
        if not data["selected"]:
            raise ValueError("A profile must select at least one provider")
    providers = data.get("providers", {})
    _object(providers)
    for state in providers.values():
        validate_provider(state)
    shared = data.get("shared", {})
    _object(shared, {"include_keywords", "exclude_keywords"})
    for values in shared.values():
        _strings(values)


def validate_payload(data):
    _object(data, {"providers", "settings", "history"})
    providers, settings = data.get("providers", {}), data.get("settings", {})
    _object(providers)
    _object(settings, PREFERENCES)
    for value in providers.values():
        validate_provider(value)
    for key, value in settings.items():
        if key == "download_dir" and value is not None and not isinstance(value, str):
            raise ValueError("Invalid download folder")
        if key == "hide_stream_output" and type(value) is not bool:
            raise ValueError("Invalid stream preference")
        if key == "appearance":
            _object(value, {"theme", "focus", "density", "painting"})
            if any(not isinstance(item, str) for item in value.values()):
                raise ValueError("Invalid appearance settings")
        if key == "combined_search":
            validate_profile(value)
        if key == "search_profiles":
            library = ProfileLibrary(value)
            _object(value, {"version", "active", "profiles"})
            for entry in library.entries:
                _object(entry, {"id", "name", "settings"})
                validate_profile(entry["settings"])
    if "history" in data:
        if not isinstance(data["history"], list):
            raise ValueError("Invalid history")
        for entry in data["history"]:
            _object(entry, {"query", "provider", "timestamp", "presets", "kind", "facet", "name", "search_profile", "queries"})
            if "queries" in entry:
                queries = entry["queries"]
                if not isinstance(queries, list) or not 1 <= len(queries) <= 6 or any(not isinstance(q, str) or not q.strip() for q in queries):
                    raise ValueError("Invalid alternate-title history queries")
            for key in ("query", "provider", "timestamp"):
                if not isinstance(entry.get(key), str):
                    raise ValueError("Invalid history entry")
            if not _has_timezone(entry["timestamp"]):
                raise ValueError(f"Invalid history timestamp {entry['timestamp']!r}: use ISO 8601 with a "
                                 "timezone, e.g. 2026-10-03T12:00:00+00:00")
            for key in ("kind", "facet", "name"):
                if key in entry and entry[key] is not None and not isinstance(entry[key], str):
                    raise ValueError("Invalid history entry")
            _strings(entry.get("presets", []))
            if "search_profile" in entry:
                validate_profile(entry["search_profile"])


def _has_timezone(timestamp):
    try:
        return datetime.fromisoformat(timestamp).utcoffset() is not None
    except ValueError:
        return False


def export_settings(path, *, history=False):
    if store.problem() is not None:
        raise ValueError("Existing settings cannot be read; repair them before exporting.")
    current = store.read()
    data = {"providers": deepcopy(current.get("providers", {})),
            "settings": {k: deepcopy(v) for k, v in current.get("settings", {}).items() if k in PREFERENCES}}
    if history:
        data["history"] = load_history()  # full form: backups stay self-contained
    validate_payload(data)
    _export(path, {"format": "torrent-finder-settings", "version": 1, "data": data})


def _export(path, document):
    target = Path(path).expanduser().resolve()
    # Export never overwrites an existing file, including the app's own state.
    if target.exists():
        raise ValueError("Export file already exists. Choose a new filename.")
    # Exclusive creation prevents a second process racing the existence check.
    with target.open("x", encoding="utf-8") as stream:
        try:
            import os
            if os.name == "posix":
                os.chmod(target, 0o600)
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            target.unlink(missing_ok=True)
            raise


def read_backup(path, *, credentials=False):
    target = Path(path).expanduser()
    if target.stat().st_size > 10_000_000:
        raise ValueError("Backup is larger than the 10 MB limit")
    document = json.loads(target.read_text(encoding="utf-8-sig"))
    _object(document, {"format", "version", "data"})
    expected = "torrent-finder-credentials" if credentials else "torrent-finder-settings"
    if document.get("format") != expected or document.get("version") != 1:
        raise ValueError("Wrong backup type or unsupported version")
    data = document.get("data")
    if credentials:
        from torrent_finder.credentials import _FILE_KEYS
        _object(data, _FILE_KEYS)
        if any(not isinstance(v, str) for v in data.values()):
            raise ValueError("Invalid credential values")
    else:
        validate_payload(data)
    return deepcopy(data)


def prepare_import(data, mode="merge"):
    """Return a detached candidate and human-readable preview; no writes.

    Apply it with ``store.commit(import_change(data, mode))``, which merges
    into the settings as saved at that moment rather than this candidate.
    """
    _check_import(data, mode)
    result = deepcopy(store.read())
    return result, _apply_import(result, data, mode)


def import_change(data, mode="merge"):
    """Store operation applying a validated backup; see ``prepare_import``."""
    _check_import(data, mode)
    return lambda document: _apply_import(document, data, mode)


def _check_import(data, mode):
    validate_payload(data)
    if mode not in ("merge", "replace"):
        raise ValueError("Choose merge or replace")


def _apply_import(result, data, mode):
    """Apply *data* to the settings document *result* in place; return the preview lines."""
    incoming = deepcopy(data)
    previous = store.section(result, "settings")
    changes = ["Merge: imported provider/preferences win; other settings stay." if mode == "merge"
               else "Replace: replace portable provider/preferences; keep machine settings, stats and bookmarks."]
    if mode == "replace":
        result["providers"] = incoming.get("providers", {})
        for key in PREFERENCES:
            previous.pop(key, None)
    else:
        store.section(result, "providers").update(incoming.get("providers", {}))
    settings = incoming.get("settings", {})
    if "combined_search" in settings and "search_profiles" not in settings:
        settings["search_profiles"] = {"version": 1, "active": "default", "profiles": [
            {"id": "default", "name": "Default", "settings": deepcopy(settings["combined_search"])}]}
    if mode == "merge" and "search_profiles" in settings:
        existing = previous.get("search_profiles")
        if existing is None:
            existing = {"version": 1, "active": "default", "profiles": [
                {"id": "default", "name": "Default", "settings": previous.get("combined_search", {})}]}
        library = ProfileLibrary(existing)
        for entry in settings["search_profiles"]["profiles"]:
            match = library.find(entry["name"])
            if match:
                match["settings"] = entry["settings"]
                changes.append("Replace profile: " + entry["name"])
            else:
                entry["id"] = uuid4().hex
                library.entries.append(entry)
                changes.append("Add profile: " + entry["name"])
        settings["search_profiles"] = library.data
    previous.update(settings)
    if "search_profiles" in settings:
        for entry in settings["search_profiles"]["profiles"]:
            config = entry["settings"]
            changes.append(f"Profile {entry['name']}: " + ", ".join(config.get("selected", ["all default providers"])))
            rules = NameRules.restore(config.get("name_rules", {})).summary()
            if rules:
                changes.append(f"Name rules ({entry['name']}): {rules}")
    if "search_profiles" in previous:
        previous["combined_search"] = deepcopy(ProfileLibrary(previous["search_profiles"]).current["settings"])
    changes += ["Provider settings: " + (", ".join(incoming.get("providers", {})) or "none"),
                "Preferences: " + (", ".join(settings) or "none"),
                "Credentials are separate and will not change."]
    if "history" in incoming:
        result["history"] = (store._merge_history([(0, {"history": result.get("history", [])}),
                                                  (1, {"history": incoming["history"]})]) if mode == "merge"
                             else incoming["history"][:store.HISTORY_LIMIT])
        compact_history(result)
        changes.append(f"History: {len(result['history'])} entries after {mode}")
    else:
        changes.append("History: unchanged (not included)")
    if "download_dir" in settings:
        changes.append("Download folder: " + str(settings["download_dir"] or "default") + " (check it exists on this computer)")
    return changes


def export_credentials(path):
    from torrent_finder import credentials
    values = credentials.export_file_values()
    _export(path, {"format": "torrent-finder-credentials", "version": 1, "data": values})
