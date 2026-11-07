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
        def section(label: str) -> SelectItem:
            return SelectItem(label, "section_header", enabled=False)

        items = [
            section(t("Name matching")),
            SelectItem(t("Words in name"), ("match", "contains"),
                       description=t("Keeps the results whose names contain every word you type.")),
            SelectItem(t("Exact media title (ignore release tags)"), ("match", "title"),
                       description=t("Keeps the results whose title is exactly what you type, whatever the tags.")),
            SelectItem(t("Exact full torrent filename"), ("match", "filename"),
                       description=t("Keeps the results whose whole name is exactly what you type.")),
            SelectItem(t("Clear name filter"), ("clear", ""),
                       description=t("Shows every fetched result again.")),
            section(t("Order")),
            *(SelectItem(t(label), ("sort", key), description=t("Changes this result list only. Other sorts override preferences; required filters still apply."))
              for key, label in SORT_ORDERS.items()),
            SelectItem(t("Apply and return"), ("done", ""), is_action=True),
        ]
        for item in items:
            if not isinstance(item.value, tuple):
                continue  # a section heading
            action, value = item.value
            if (action == "match" and value == mode) or (action == "sort" and value == order):
                item.hint = t("active")
        first = next(i for i, item in enumerate(items) if isinstance(item.value, tuple))
        selected = arrow_select(items, title=t("Refine results"), start_index=first,
                                footer=t("Enter choose  •  Esc apply and return"))
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
