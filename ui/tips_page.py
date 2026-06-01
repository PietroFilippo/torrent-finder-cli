"""Scrollable tips browser with search and category filtering."""

from __future__ import annotations

from rich.markup import escape

from constants import console
from ui.selector import SelectItem, arrow_select
from ui.tips import TIP_CATEGORIES, Tip, TipCategory, find_tips


_CATEGORY_OPTIONS = ("All",) + tuple(category.name for category in TIP_CATEGORIES)


def _header(label: str) -> SelectItem:
    """Section header: scrolls with content, skipped by navigation."""
    return SelectItem(
        label=f"--- {label} ---",
        value="section_header",
        enabled=False,
    )


def _tip_item(category: TipCategory, tip: Tip) -> SelectItem:
    """Read-only tip row: navigable for scrolling, Enter is a no-op."""
    return SelectItem(
        label=tip.text,
        value=("tip", category.name, tip),
        enabled=True,
        passive=True,
        hint=", ".join(tip.tags),
        description=f"Category: {category.name}",
    )


def _active_category(category_idx: int) -> str | None:
    category = _CATEGORY_OPTIONS[category_idx]
    return None if category == "All" else category


def _matching_by_category(query: str, category_idx: int) -> list[tuple[TipCategory, list[Tip]]]:
    """Return matching tips grouped in catalog order."""
    selected_category = _active_category(category_idx)
    matches = find_tips(query=query, category=selected_category)
    grouped: list[tuple[TipCategory, list[Tip]]] = []

    for category in TIP_CATEGORIES:
        tips = [tip for matched_category, tip in matches if matched_category.name == category.name]
        if tips:
            grouped.append((category, tips))

    return grouped


def _match_count(query: str, category_idx: int) -> int:
    return sum(len(tips) for _, tips in _matching_by_category(query, category_idx))


def _first_enabled(items: list[SelectItem]) -> int:
    for idx, item in enumerate(items):
        if item.enabled:
            return idx
    return 0


def _build_items(query: str, category_idx: int) -> list[SelectItem]:
    """Build grouped tip rows plus pinned action buttons."""
    items: list[SelectItem] = []
    grouped = _matching_by_category(query, category_idx)

    if not grouped:
        items.append(SelectItem(
            label="No tips match the current search/filter",
            value="empty_placeholder",
            enabled=False,
            is_action=True,
        ))
    else:
        for category, tips in grouped:
            items.append(_header(category.name))
            for tip in tips:
                items.append(_tip_item(category, tip))

    items.append(SelectItem(label="", value="spacer", enabled=False))
    items.append(SelectItem(
        label="Search tips  [/]",
        value="search",
        is_action=True,
        description="Type text to match against categories, tip text, and tags.",
    ))
    items.append(SelectItem(
        label=f"Category: {_CATEGORY_OPTIONS[category_idx]}  [c]",
        value="category",
        is_action=True,
        description="Cycle the category filter.",
    ))
    items.append(SelectItem(
        label="Clear search/filter  [x]",
        value="clear",
        is_action=True,
        enabled=bool(query.strip()) or category_idx != 0,
        description="Reset the search text and category filter.",
    ))
    items.append(SelectItem(label="Go Back", value="back", is_action=True))
    return items


def tips_page() -> None:
    """Show all tips in a grouped, searchable, filterable scroll view."""
    from ui.prompts import _make_banner_panel

    state = {
        "query": "",
        "category_idx": 0,
        "start": 0,
    }

    def _title() -> str:
        parts = ["Tips"]
        category = _CATEGORY_OPTIONS[state["category_idx"]]
        if category != "All":
            parts.append(f"category: {escape(category)}")
        if state["query"]:
            parts.append(f'search: "{escape(state["query"])}"')
        parts.append(f"{_match_count(state['query'], state['category_idx'])} shown")
        return " - ".join(parts)

    def _footer() -> str:
        category = _CATEGORY_OPTIONS[state["category_idx"]]
        query_label = escape(state["query"]) if state["query"] else "none"
        return (
            "↑/↓ scroll  •  [bold yellow]/[/bold yellow] search  •  "
            f"[bold yellow]C[/bold yellow] category: [cyan]{escape(category)}[/cyan]  •  "
            f"[bold yellow]X[/bold yellow] clear  •  Esc back\n"
            f" Search: [cyan]{query_label}[/cyan]"
        )

    def _cycle_category(cursor: int, items_list: list[SelectItem]):
        state["category_idx"] = (state["category_idx"] + 1) % len(_CATEGORY_OPTIONS)
        items_list[:] = _build_items(state["query"], state["category_idx"])
        return ("jump", _first_enabled(items_list))

    def _clear(cursor: int, items_list: list[SelectItem]):
        state["query"] = ""
        state["category_idx"] = 0
        items_list[:] = _build_items(state["query"], state["category_idx"])
        return ("jump", _first_enabled(items_list))

    def _search_now(cursor: int, items_list: list[SelectItem]):
        for idx, item in enumerate(items_list):
            if item.value == "search":
                return idx
        return True

    while True:
        items = _build_items(state["query"], state["category_idx"])
        start = min(state["start"], len(items) - 1)
        if not items[start].enabled:
            start = _first_enabled(items)

        result = arrow_select(
            items,
            title=_title,
            banner=_make_banner_panel(),
            start_index=start,
            footer=_footer,
            key_actions={
                "/": _search_now,
                "c": _cycle_category,
                "C": _cycle_category,
                "x": _clear,
                "X": _clear,
            },
        )

        if result is None:
            return

        state["start"] = result if isinstance(result, int) else 0
        action = items[result].value

        if action == "search":
            try:
                query = console.input("[info]Search tips: [/info]").strip()
            except (EOFError, KeyboardInterrupt):
                return
            state["query"] = query
            state["start"] = 0
            continue

        if action == "category":
            state["category_idx"] = (state["category_idx"] + 1) % len(_CATEGORY_OPTIONS)
            state["start"] = 0
            continue

        if action == "clear":
            state["query"] = ""
            state["category_idx"] = 0
            state["start"] = 0
            continue

        if action == "back":
            return
