"""Review saved listings and searches using their original acquisition path."""

from rich.markup import escape
from torrent_finder import bookmarks
from torrent_finder.ui.selector import SelectItem, arrow_select


def bookmark_menu():
    while True:
        saved = bookmarks.entries()
        items = [SelectItem(e["name"], e, hint=e["kind"], description=escape(
            f"{e['provider']} • Saved {e['saved_at']}\n"
            + (f"Metadata fetched {e['fetched_at']} • {e.get('refresh_status', 'Not refreshed')}\n" if e["kind"] == "result" else "")
            + "Saved metadata does not confirm current availability.")) for e in saved]
        items.append(SelectItem("Back", None))
        if any(e["kind"] == "result" for e in saved):
            items.insert(len(items) - 1, SelectItem("Compare saved results in one table", "compare"))
        footer = "Enter review • Esc back" if saved else (
            "No bookmarks yet. In search results, b saves a listing; Quick actions → "
            "Bookmark current search saves a search.\nEsc back")
        pick = arrow_select(items, title=f"Bookmarks / download later ({len(saved)})", footer=footer)
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
