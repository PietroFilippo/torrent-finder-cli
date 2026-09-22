"""Interactive controls for refining an already-fetched result list."""

from torrent_finder.ui.selector import SelectItem, arrow_select


def refine_results(query: str, mode: str, order: str) -> tuple[str, str, str]:
    from torrent_finder.ui.prompts import get_query_with_shortcut
    while True:
        items = [
            SelectItem("Words in name", ("match", "contains")),
            SelectItem("Exact media title (ignore release tags)", ("match", "title")),
            SelectItem("Exact full torrent filename", ("match", "filename")),
            SelectItem("Original search order", ("sort", "relevance")),
            SelectItem("Most seeders", ("sort", "seeds")),
            SelectItem("Newest uploads (unknown dates last)", ("sort", "newest")),
            SelectItem("Name A–Z", ("sort", "name")),
            SelectItem("Largest size", ("sort", "size")),
            SelectItem("Clear name filter", ("clear", "")),
            SelectItem("Apply and return", ("done", "")),
        ]
        for item in items:
            action, value = item.value
            if (action == "match" and value == mode) or (action == "sort" and value == order):
                item.hint = "active"
        selected = arrow_select(items, title="Refine results", footer="Enter choose  •  Esc apply and return")
        if selected is None:
            return query, mode, order
        action, value = items[selected].value
        if action == "sort":
            order = value
        elif action == "clear":
            query = ""
        elif action == "done":
            return query, mode, order
        else:
            entered = get_query_with_shortcut("Filter name: ", initial=query)
            if isinstance(entered, str) and entered != "GO_BACK":
                query, mode = entered.strip(), value
