"""Review saved listings and searches using their original acquisition path."""

from rich.markup import escape
from torrent_finder import bookmarks
from torrent_finder.providers import display_name_for
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.utils import relative_time


def _when(timestamp) -> str:
    """``2h ago``, or the saved text itself when it is not a time this app wrote."""
    return relative_time(timestamp) or str(timestamp or "unknown")


def _description(entry) -> str:
    lines = [f"{display_name_for(str(entry.get('provider', '')))} · saved {_when(entry.get('saved_at'))}"]
    if entry["kind"] == "result":
        lines.append(f"Metadata fetched {_when(entry.get('fetched_at'))} · {entry.get('refresh_status', 'Not refreshed')}")
    lines.append("Saved metadata does not confirm current availability.")
    return escape("\n".join(lines))


def bookmark_menu():
    while True:
        saved = bookmarks.entries()
        items = [SelectItem(e["name"], e, hint=e["kind"], description=_description(e)) for e in saved]
        items.append(SelectItem("Back", None))
        if any(e["kind"] == "result" for e in saved):
            items.insert(len(items) - 1, SelectItem("Compare saved results in one table", "compare"))
        footer = "Enter review • Esc back" if saved else (
            "No bookmarks yet. In search results, b saves a listing; Quick actions → "
            "Bookmark current search saves a search.\nEsc back")
        pick = arrow_select(items, title="Bookmarks / download later", status=f"{len(saved)} saved", footer=footer)
        if pick is None or items[pick].value is None:
            return None
        entry = items[pick].value
        if entry == "compare":
            return "compare", [e for e in saved if e["kind"] == "result"]
        actions = [SelectItem("Open saved result / download options" if entry["kind"] == "result" else "Run saved search", "open"),
                   SelectItem("Refresh listing with its saved search", "refresh", enabled=entry["kind"] == "result"),
                   SelectItem("Remove bookmark", "remove"), SelectItem("Back", "back")]
        chosen = arrow_select(actions, title=escape(entry["name"]), footer="Enter choose • Esc back")
        if chosen is None:
            continue
        action = actions[chosen].value
        if action == "remove":
            bookmarks.remove(entry["id"])
        elif action != "back":
            return action, entry
