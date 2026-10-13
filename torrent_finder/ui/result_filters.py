"""Interactive controls for refining an already-fetched result list."""

# i18n: converted
from torrent_finder.i18n import t
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.result_view import SORT_ORDERS


def choose_result_sort(order: str) -> str:
    items = [SelectItem(t(label), value, hint=t("active") if value == order else "",
                        description=t("Recommended uses title relevance where available, then preferences. Other sorts override that ranking; required filters still apply."))
             for value, label in SORT_ORDERS.items()]
    selected = arrow_select(items, title=t("Result order"), footer=t("Enter choose • Esc keep current order"))
    return order if selected is None else items[selected].value


def refine_results(query: str, mode: str, order: str) -> tuple[str, str, str]:
    from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut, input_screen
    while True:
        items = [
            SelectItem(t("Words in name"), ("match", "contains")),
            SelectItem(t("Exact media title (ignore release tags)"), ("match", "title")),
            SelectItem(t("Exact full torrent filename"), ("match", "filename")),
            *(SelectItem(t(label), ("sort", key), description=t("Changes this result list only. Other sorts override preferences; required filters still apply."))
              for key, label in SORT_ORDERS.items()),
            SelectItem(t("Clear name filter"), ("clear", "")),
            SelectItem(t("Apply and return"), ("done", "")),
        ]
        for item in items:
            action, value = item.value
            if (action == "match" and value == mode) or (action == "sort" and value == order):
                item.hint = t("active")
        selected = arrow_select(items, title=t("Refine results"), footer=t("Enter choose  •  Esc apply and return"))
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
            entered = get_query_with_shortcut(PROMPT, initial=query, screen_renderer=input_screen(
                t("Refine results › {label}", label=items[selected].label),
                t("Matches the names of the fetched results; empty shows every name.")))
            if isinstance(entered, str) and entered != "GO_BACK":
                query, mode = entered.strip(), value
