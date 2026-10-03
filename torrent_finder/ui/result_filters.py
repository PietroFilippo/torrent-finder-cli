"""Interactive controls for refining an already-fetched result list."""

from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.result_view import SORT_ORDERS


def choose_result_sort(order: str) -> str:
    items = [SelectItem(label, value, hint="active" if value == order else "",
                        description="Recommended uses title relevance where available, then preferences. Other sorts override that ranking; required filters still apply.")
             for value, label in SORT_ORDERS.items()]
    selected = arrow_select(items, title="Result order", footer="Enter choose • Esc keep current order")
    return order if selected is None else items[selected].value


def refine_results(query: str, mode: str, order: str) -> tuple[str, str, str]:
    from torrent_finder.ui.prompts import get_query_with_shortcut
    while True:
        items = [
            SelectItem("Words in name", ("match", "contains")),
            SelectItem("Exact media title (ignore release tags)", ("match", "title")),
            SelectItem("Exact full torrent filename", ("match", "filename")),
            *(SelectItem(label, ("sort", key), description="Changes this result list only. Other sorts override preferences; required filters still apply.")
              for key, label in SORT_ORDERS.items()),
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
