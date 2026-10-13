"""Search history browser — arrow-select menu over past searches."""

from datetime import datetime, timedelta, timezone

import readchar
from rich.markup import escape

from torrent_finder.providers import PROVIDERS, display_name_for
from torrent_finder.state import clear_history, load_history, remove_history_entry, restore_history_entry
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.ui.prompts import _make_banner_panel, confirm_prompt
from torrent_finder.utils import parse_timestamp, relative_time

# Helpers

_relative_time = relative_time  # shared with bookmarks and the main menu


def _option_label(provider: str | None) -> str:
    """The provider filter as shown: "All" or the qualified label (Games · General)."""
    return "All" if provider is None else display_name_for(provider)


def _parse_ts(iso_ts: str) -> datetime | None:
    """The entry's moment; a timezone-less one sorts as oldest and matches no date range."""
    return parse_timestamp(iso_ts)


# Filter definitions

# Provider filter: cycle through All (None) → each provider slug → All. Slugs,
# not names: Games and Manga both have a provider named "General".
_PROVIDER_OPTIONS = [None] + [p.slug for p in PROVIDERS]

# Date range filter
_DATE_OPTIONS = ["All time", "Today", "This week", "This month"]

# Sort order
_SORT_OPTIONS = ["Newest first", "Oldest first"]

# Type filter — keyword searches vs by-creator entries
_TYPE_OPTIONS = ["All", "Keyword", "By-creator"]


def _filter_by_provider(entries: list[dict], provider: str | None) -> list[dict]:
    if provider is None:
        return entries
    return [e for e in entries if e.get("provider") == provider]


def _filter_by_type(entries: list[dict], type_filter: str) -> list[dict]:
    if type_filter == "All":
        return entries
    if type_filter == "Keyword":
        return [e for e in entries if e.get("kind", "keyword") == "keyword"]
    return [e for e in entries if e.get("kind") == "creator"]


def _filter_by_date(entries: list[dict], date_range: str) -> list[dict]:
    if date_range == "All time":
        return entries
    now = datetime.now(timezone.utc)
    if date_range == "Today":
        cutoff = now - timedelta(days=1)
    elif date_range == "This week":
        cutoff = now - timedelta(weeks=1)
    elif date_range == "This month":
        cutoff = now - timedelta(days=30)
    else:
        return entries
    result = []
    for e in entries:
        dt = _parse_ts(e.get("timestamp", ""))
        if dt and dt >= cutoff:
            result.append(e)
    return result


def _filter_by_text(entries: list[dict], text: str) -> list[dict]:
    """Entries whose search text, saved names, creator name or provider contain *text* (case-folded)."""
    needle = text.casefold().strip()
    if not needle:
        return entries

    def matches(entry: dict) -> bool:
        parts = [str(entry.get("query", "")), str(entry.get("name", "") or ""),
                 display_name_for(str(entry.get("provider", "")))]
        parts += [str(alias) for alias in entry.get("queries", []) or []]
        return any(needle in part.casefold() for part in parts)
    return [e for e in entries if matches(e)]


def _sort_entries(entries: list[dict], order: str) -> list[dict]:
    reverse = order == "Newest first"
    return sorted(
        entries,
        key=lambda e: _parse_ts(e.get("timestamp", "")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=reverse,
    )


# Public prompt

def history_select_prompt() -> dict | None:
    """Display the search history menu with filtering hotkeys.

    Returns the selected history **entry dict** (keyword or creator), or ``None``
    on cancel / empty history / go-back. The caller routes it: keyword entries
    re-run a normal search, creator entries (``kind == "creator"``) replay the
    by-creator flow via ``facet`` + ``name``.
    """
    # Mutable filter state — shared by key_action callbacks and callable title/footer
    fstate = {
        "prov_idx": 0,   # index into _PROVIDER_OPTIONS
        "date_idx": 0,   # index into _DATE_OPTIONS
        "sort_idx": 0,   # index into _SORT_OPTIONS
        "type_idx": 0,   # index into _TYPE_OPTIONS
        "search": "",    # text the entries must contain (/ asks for it)
    }

    history = load_history()
    notice = ""  # shown above the footer, e.g. a failed Clear history
    removed: "tuple[dict, int] | None" = None  # the last entry removed with x, and where it was: u puts it back

    # --- helpers to build / rebuild the items list in place ---

    def _current_filters():
        return (
            _PROVIDER_OPTIONS[fstate["prov_idx"]],
            _DATE_OPTIONS[fstate["date_idx"]],
            _SORT_OPTIONS[fstate["sort_idx"]],
            _TYPE_OPTIONS[fstate["type_idx"]],
        )

    def _rebuild(items: list[SelectItem]) -> None:
        """Clear *items* and repopulate from current history + active filters."""
        prov_filter, date_filter, sort_order, type_filter = _current_filters()

        filtered = _filter_by_provider(history, prov_filter)
        filtered = _filter_by_type(filtered, type_filter)
        filtered = _filter_by_date(filtered, date_filter)
        filtered = _filter_by_text(filtered, fstate["search"])
        filtered = _sort_entries(filtered, sort_order)

        items.clear()

        if not history:
            items.append(SelectItem(
                label="No searches yet — your history will appear here",
                value="empty_placeholder",
                enabled=False,
                is_action=True,
            ))
        elif not filtered:
            items.append(SelectItem(
                label=(f"No searches contain “{fstate['search']}” — / changes the text; empty clears it"
                       if fstate["search"] else "No results match the current filters"),
                value="empty_placeholder",
                enabled=False,
                is_action=True,
            ))
        else:
            for entry in filtered:
                query = entry.get("query", "")
                prov = entry.get("provider", "")
                ts = entry.get("timestamp", "")
                presets = entry.get("presets", [])
                display = display_name_for(prov)
                time_str = _relative_time(ts)
                label = query
                hint = f"{display}  •  {time_str}" if time_str else display
                if presets:
                    hint += f"  •  filters: {', '.join(presets)}"
                aliases = entry.get("queries", [])
                if aliases:
                    hint += f"  •  {len(aliases)} names"
                items.append(SelectItem(label=label, value=entry, hint=hint,
                                        description="Replays saved names; n in results lists them." if aliases else ""))

            items.append(SelectItem(label="Clear history", value="clear", is_action=True))

        items.append(SelectItem(label="Back", value="back", is_action=True))

    # --- dynamic title / footer (callables resolved each render) ---

    def _title():
        prov_filter, date_filter, sort_order, type_filter = _current_filters()
        tags = []
        if prov_filter is not None:
            tags.append(_option_label(prov_filter))
        if type_filter != "All":
            tags.append(type_filter)
        if date_filter != "All time":
            tags.append(date_filter)
        if sort_order != "Newest first":
            tags.append(sort_order)
        if fstate["search"]:
            tags.append(f'"{escape(fstate["search"])}"')
        return " › ".join(["Search History", " · ".join(tags)] if tags else ["Search History"])

    def _footer():
        prov_filter, date_filter, sort_order, type_filter = _current_filters()
        search = f"Search: {escape(fstate['search'])}\n" if fstate["search"] else ""  # the key bar says / search
        undo = "  •  U undo" if removed else ""
        return (
            (notice + "\n" if notice else "")
            + search
            + f"↑/↓ navigate  •  Enter re-run  •  / search  •  X remove{undo}  •  Esc back\n"
            f"P provider: {escape(_option_label(prov_filter))}  •  T type: {type_filter}  •  "
            f"D date: {date_filter}  •  S sort: {sort_order}"
        )

    # --- key_action callbacks (cycle filter + rebuild in-place) ---

    def _cycle(key_name: str, options_len: int):
        """Return a key_action callback that cycles fstate[key_name]."""
        def handler(cursor, items_list):
            fstate[key_name] = (fstate[key_name] + 1) % options_len
            _rebuild(items_list)
            # Jump cursor to first enabled item
            for i, it in enumerate(items_list):
                if it.enabled:
                    return ("jump", i)
            return True
        return handler

    def _jump_to(items_list, index: int):
        """Keep the cursor on a selectable row near *index* after the list changed."""
        enabled = [i for i, it in enumerate(items_list) if it.enabled]
        if not enabled:
            return True
        return ("jump", min(enabled, key=lambda i: (abs(i - index), i)))

    def _search(cursor, items_list):
        """/ asks for text the entries must contain; empty text clears the search."""
        from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut, input_screen
        typed = get_query_with_shortcut(PROMPT, initial=fstate["search"], screen_renderer=input_screen(
            "Search history", "Matches the search text, saved names, creator names and providers; "
                              "empty clears the search."))
        if not isinstance(typed, str) or typed == "GO_BACK":
            return True
        fstate["search"] = typed.strip()
        _rebuild(items_list)
        return _jump_to(items_list, 0)

    def _remove(cursor, items_list):
        """x removes the focused search; u puts it back."""
        nonlocal notice, removed
        entry = items_list[cursor].value
        if not isinstance(entry, dict):
            return True
        try:
            remove_history_entry(entry)
        except (OSError, ValueError) as error:
            notice = f"[error]The search was not removed:[/error] {escape(str(error))}"
            return True
        removed = (entry, history.index(entry))
        history.remove(entry)
        notice = f"Removed “{escape(str(entry.get('query', '')))}” · [key]U[/key] puts it back"
        _rebuild(items_list)
        return _jump_to(items_list, cursor)

    def _undo(cursor, items_list):
        nonlocal notice, removed
        if removed is None:
            return True
        entry, index = removed
        try:
            restore_history_entry(entry, index)
        except (OSError, ValueError) as error:
            notice = f"[error]The search was not restored:[/error] {escape(str(error))}"
            return True
        history.insert(min(index, len(history)), entry)
        removed = None
        notice = f"Put back “{escape(str(entry.get('query', '')))}”"
        _rebuild(items_list)
        back = next((i for i, it in enumerate(items_list) if it.value is entry), cursor)
        return _jump_to(items_list, back)

    # --- on_action for Clear History ---

    def on_action(idx, items_list):
        nonlocal history, notice, removed
        if items_list[idx].value == "clear":
            if not confirm_prompt(
                "[error]Clear all search history?[/error]\n\n"
                "This will delete every saved search permanently."
            ):
                return True  # stay
            try:
                clear_history()
            except (OSError, ValueError) as error:
                from rich.markup import escape
                notice = f"[error]History was not cleared:[/error] {escape(str(error))}"
                return True  # stay; the saved history is unchanged
            notice = ""
            history = []
            removed = None
            _rebuild(items_list)
            return True
        return False

    # --- build initial items and run ---

    items: list[SelectItem] = []
    _rebuild(items)

    result = arrow_select(
        items,
        title=_title,
        banner=_make_banner_panel(),
        on_action=on_action,
        footer=_footer,
        key_actions={
            "P": _cycle("prov_idx", len(_PROVIDER_OPTIONS)),
            "p": _cycle("prov_idx", len(_PROVIDER_OPTIONS)),
            "D": _cycle("date_idx", len(_DATE_OPTIONS)),
            "d": _cycle("date_idx", len(_DATE_OPTIONS)),
            "S": _cycle("sort_idx", len(_SORT_OPTIONS)),
            "s": _cycle("sort_idx", len(_SORT_OPTIONS)),
            "T": _cycle("type_idx", len(_TYPE_OPTIONS)),
            "t": _cycle("type_idx", len(_TYPE_OPTIONS)),
            "/": _search,
            "X": _remove,
            "x": _remove,
            readchar.key.DELETE: _remove,
            "U": _undo,
            "u": _undo,
        },
    )

    if result is None:
        return None

    selected = items[result].value
    if isinstance(selected, dict):
        return selected

    return None

