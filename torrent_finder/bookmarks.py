"""Persistent listing handles and search snapshots. Saving never resolves/downloads.

Every change is committed against the collection as currently saved, so a
bookmark added or removed in another window is never undone by this one.
"""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from torrent_finder import store
from torrent_finder.providers.combined_provider import provider_label, result_identity
from torrent_finder.state import provider_snapshot


def now():
    return datetime.now(timezone.utc).isoformat()


def _validated(data):
    rows = data.get("bookmarks", [])
    def valid(entry):
        return (isinstance(entry, dict) and entry.get("kind") in ("result", "search")
                and all(isinstance(entry.get(key), str) and entry[key] for key in ("id", "name", "provider", "saved_at"))
                and isinstance(entry.get("queries"), list) and entry["queries"]
                and all(isinstance(q, str) for q in entry["queries"])
                and isinstance(entry.get("search_profile"), dict)
                and (entry["kind"] == "search" or (isinstance(entry.get("result"), dict) and "fetched_at" in entry)))
    if not isinstance(rows, list) or not all(valid(e) for e in rows) or len({e["id"] for e in rows}) != len(rows):
        raise ValueError("Cannot read saved bookmarks; existing data was preserved.")
    return rows


def entries():
    return deepcopy(_validated(store.read()))


def _change(edit):
    """Commit *edit(rows)* against the saved collection; raises when saving fails."""
    def apply(data):
        rows = deepcopy(_validated(data))
        edit(rows)
        data["bookmarks"] = rows
    store.commit(apply)


def context(provider, queries):
    return {"provider": provider.slug, "queries": list(queries),
            "search_profile": provider.snapshot() if getattr(provider, "is_combined", False) else provider_snapshot(provider)}


def save_results(provider, results):
    new = []
    for row in results:
        value = deepcopy(dict(row))
        value.setdefault("provider_slug", provider.slug)
        value.setdefault("provider_label", provider_label(provider))
        queries = (row.get("matched_queries") or ([row["from_work"]] if row.get("from_work") else None)
                   or getattr(provider, "last_queries", None) or [row.get("name", "")])
        new.append({"id": uuid4().hex, "kind": "result", "name": value["name"],
                    "saved_at": now(), "fetched_at": value.get("fetched_at") or now(),
                    "result": value, **context(provider, queries)})

    def edit(saved):
        for entry in new:
            identity = result_identity(entry["result"])
            existing = next((e for e in saved
                             if e.get("kind") == "result" and result_identity(e["result"]) == identity), None)
            if existing is None:
                saved.append(entry)
            elif "listing_hash" in entry["result"] and "listing_hash" not in existing["result"]:
                # Saved again after picking it: keep the hash resolved since.
                for key in ("listing_hash", "info_hash"):
                    existing["result"][key] = entry["result"][key]
    _change(edit)
    return "Bookmarked. Open Bookmarks from the main menu or quick actions to review."


def save_search(provider, query):
    entry = {"id": uuid4().hex, "kind": "search", "name": query, "saved_at": now(),
             **context(provider, [query])}

    def edit(saved):
        if not any(e.get("kind") == "search" and e["provider"] == entry["provider"] and e["queries"] == entry["queries"]
                   and e["search_profile"] == entry["search_profile"] for e in saved):
            saved.append(entry)
    _change(edit)
    return True


def remove(identity):
    def edit(saved):
        saved[:] = [e for e in saved if e["id"] != identity]
    _change(edit)


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
    checked = now()

    def edit(saved):
        entry = next((e for e in saved if e["id"] == identity), None)
        if entry is None or entry["kind"] != "result":
            return
        entry["checked_at"] = checked
        match = next((r for r in results if result_identity(r) == result_identity(entry["result"])), None)
        entry["refresh_status"] = "Listing found" if match is not None else "Not returned by this search; saved listing retained"
        if match is not None:
            refreshed = deepcopy(dict(match))
            for key in ("provider_slug", "provider_label", "listing_hash"):
                if key in entry["result"]:
                    refreshed.setdefault(key, entry["result"][key])
            if "listing_hash" in refreshed and refreshed["listing_hash"] == refreshed.get("info_hash"):
                # A fresh listing is unresolved again; keep the hash resolved earlier.
                refreshed["info_hash"] = entry["result"]["info_hash"]
            entry["result"] = refreshed
            entry["name"] = match["name"]
            entry["fetched_at"] = match.get("fetched_at") or checked
    if any(e["id"] == identity and e["kind"] == "result" for e in entries()):
        _change(edit)
