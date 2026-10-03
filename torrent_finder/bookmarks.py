"""Persistent listing handles and search snapshots. Saving never resolves/downloads."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from torrent_finder import store
from torrent_finder.providers.combined_provider import result_identity
from torrent_finder.state import provider_snapshot


def now():
    return datetime.now(timezone.utc).isoformat()


def entries():
    data = store.read().get("bookmarks", [])
    def valid(entry):
        return (isinstance(entry, dict) and entry.get("kind") in ("result", "search")
                and all(isinstance(entry.get(key), str) and entry[key] for key in ("id", "name", "provider", "saved_at"))
                and isinstance(entry.get("queries"), list) and entry["queries"]
                and all(isinstance(q, str) for q in entry["queries"])
                and isinstance(entry.get("search_profile"), dict)
                and (entry["kind"] == "search" or (isinstance(entry.get("result"), dict) and "fetched_at" in entry)))
    if not isinstance(data, list) or not all(valid(e) for e in data) or len({e["id"] for e in data}) != len(data):
        raise ValueError("Cannot read saved bookmarks; existing data was preserved.")
    return deepcopy(data)


def _save(rows):
    data = deepcopy(store.read())
    data["bookmarks"] = rows
    store.commit(data)


def context(provider, queries):
    return {"provider": provider.slug, "queries": list(queries),
            "search_profile": provider.snapshot() if getattr(provider, "is_combined", False) else provider_snapshot(provider)}


def save_results(provider, results):
    saved = entries()
    for row in results:
        value = deepcopy(dict(row))
        value.setdefault("provider_slug", provider.slug)
        value.setdefault("provider_label", provider.name)
        identity = result_identity(value)
        if any(e.get("kind") == "result" and result_identity(e["result"]) == identity for e in saved):
            continue
        queries = (row.get("matched_queries") or ([row["from_work"]] if row.get("from_work") else None)
                   or getattr(provider, "last_queries", None) or [row.get("name", "")])
        saved.append({"id": uuid4().hex, "kind": "result", "name": value["name"],
                      "saved_at": now(), "fetched_at": value.get("fetched_at") or now(),
                      "result": value, **context(provider, queries)})
    _save(saved)
    return "Bookmarked. Open Bookmarks from the main menu or quick actions to review."


def save_search(provider, query):
    saved = entries()
    entry = {"id": uuid4().hex, "kind": "search", "name": query, "saved_at": now(),
             **context(provider, [query])}
    if not any(e.get("kind") == "search" and e["provider"] == entry["provider"] and e["queries"] == entry["queries"]
               and e["search_profile"] == entry["search_profile"] for e in saved):
        saved.append(entry)
    _save(saved)
    return True


def remove(identity):
    _save([e for e in entries() if e["id"] != identity])


def search_provider(entry):
    from torrent_finder.providers import get_provider_by_slug
    from torrent_finder.providers.combined_provider import CombinedProvider
    from torrent_finder.state import apply_provider_state
    original = get_provider_by_slug(entry["provider"])
    if original is None:
        raise ValueError("This bookmark's provider is unavailable.")
    if getattr(original, "is_combined", False):
        provider = CombinedProvider(original.templates)
        provider.restore_history(entry["search_profile"])
    else:
        provider = type(original)()
        apply_provider_state(provider, entry["search_profile"])
    return provider


def refresh(identity, results):
    """Update an exact listing identity only; keep old handles when absent."""
    saved = entries()
    entry = next((e for e in saved if e["id"] == identity), None)
    if entry is None or entry["kind"] != "result":
        return
    entry["checked_at"] = now()
    match = next((r for r in results if result_identity(r) == result_identity(entry["result"])), None)
    entry["refresh_status"] = "Listing found" if match is not None else "Not returned by this search; saved listing retained"
    if match is not None:
        refreshed = deepcopy(dict(match))
        for key in ("provider_slug", "provider_label"):
            if key in entry["result"]:
                refreshed.setdefault(key, entry["result"][key])
        entry["result"] = refreshed
        entry["name"] = match["name"]
        entry["fetched_at"] = match.get("fetched_at") or now()
    _save(saved)
