"""Review saved listings and searches using their original acquisition path."""

# i18n: converted
from rich.markup import escape
from torrent_finder import bookmarks
from torrent_finder.i18n import N_, t, tn
from torrent_finder.providers import display_name_for
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.utils import relative_time


def _when(timestamp) -> str:
    """``2h ago``, or the saved text itself when it is not a time this app wrote."""
    return relative_time(timestamp) or str(timestamp or t("unknown"))


def _description(entry) -> str:
    lines = [t("{provider} · saved {when}", provider=display_name_for(str(entry.get('provider', ''))),
               when=_when(entry.get('saved_at')))]
    if entry["kind"] == "result":
        lines.append(t("Metadata fetched {when} · {status}", when=_when(entry.get('fetched_at')),
                       status=bookmarks.refresh_status_label(entry.get('refresh_status', N_("Not refreshed")))))
    lines.append(t("Saved metadata does not confirm current availability."))
    return escape("\n".join(lines))


def bookmark_menu():
    while True:
        saved = bookmarks.entries()
        items = [SelectItem(_display_name(e), e, hint=t("result") if e["kind"] == "result" else t("search"), description=_description(e)) for e in saved]
        items.append(SelectItem(t("Back"), None))
        if any(e["kind"] == "result" for e in saved):
            items.insert(len(items) - 1, SelectItem(t("Compare saved results in one table"), "compare"))
        footer = t("Enter review • Esc back") if saved else t(
            "No bookmarks yet. In search results, b saves a listing; Quick actions → "
            "Bookmark current search saves a search.\nEsc back")
        pick = arrow_select(items, title=t("Bookmarks / download later"), status=tn("{n} saved", "{n} saved", len(saved)), footer=footer)
        if pick is None or items[pick].value is None:
            return None
        entry = items[pick].value
        if entry == "compare":
            return "compare", [e for e in saved if e["kind"] == "result"]
        actions = [SelectItem(t("Open saved result / download options") if entry["kind"] == "result" else t("Run saved search"), "open"),
                   SelectItem(t("Refresh listing with its saved search"), "refresh", enabled=entry["kind"] == "result"),
                   SelectItem(t("Remove bookmark"), "remove"), SelectItem(t("Back"), "back")]
        chosen = arrow_select(actions, title=escape(_display_name(entry)), footer=t("Enter choose • Esc back"))
        if chosen is None:
            continue
        action = actions[chosen].value
        if action == "remove":
            bookmarks.remove(entry["id"])
        elif action != "back":
            return action, entry


def _display_name(entry) -> str:
    """Localize library handles for display, retaining the saved bookmark name."""
    path = entry.get("result", {}).get("mdk_path") if entry["kind"] == "result" else None
    if path:
        from torrent_finder.madokami import localized_display_name
        return localized_display_name(path)
    return entry["name"]
