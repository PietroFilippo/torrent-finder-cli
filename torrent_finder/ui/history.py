"""Search history browser — arrow-select menu over past searches."""

from datetime import datetime, timedelta, timezone

from torrent_finder.constants import console
from torrent_finder.providers import PROVIDERS, display_name_for
from torrent_finder.state import clear_history, load_history
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.ui.prompts import _make_banner_panel, confirm_prompt

# Helpers

def _relative_time(iso_ts: str) -> str:
    """Turn an ISO-8601 timestamp into a human-friendly relative string."""
    dt = _parse_ts(iso_ts)
    if dt is None:
        return ""
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())

    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    return f"{months}mo ago"


def _option_label(provider: str | None) -> str:
    """The provider filter as shown: "All" or the qualified label (Games · General)."""
    return "All" if provider is None else display_name_for(provider)


def _parse_ts(iso_ts: str) -> datetime | None:
    """The entry's moment, or None when the timestamp is missing, malformed or has no timezone.

    History is always recorded in UTC. A timezone-less value (hand-edited or
    from elsewhere) has no reliable moment, so it sorts as oldest and matches
    no date range instead of guessing one.
    """
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return None
    return dt if dt.utcoffset() is not None else None


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
    }

    history = load_history()
    notice = ""  # shown above the footer, e.g. a failed Clear history

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
                label="No results match the current filters",
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
        t = "Search History"
        if tags:
            t += " — " + "  •  ".join(tags)
        return t

    def _footer():
        prov_filter, date_filter, sort_order, type_filter = _current_filters()
        return (
            (notice + "\n" if notice else "")
            + "↑/↓ navigate  •  Enter re-run  •  Esc back\n"
            f"[bold]Filters:[/bold]  [warning]P[/warning] provider: [muted]{_option_label(prov_filter)}[/muted]  •  "
            f"[warning]T[/warning] type: [muted]{type_filter}[/muted]  •  "
            f"[warning]D[/warning] date: [muted]{date_filter}[/muted]  •  "
            f"[warning]S[/warning] sort: [muted]{sort_order}[/muted]"
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

    # --- on_action for Clear History ---

    def on_action(idx, items_list):
        nonlocal history, notice
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
        },
    )

    if result is None:
        return None

    selected = items[result].value
    if isinstance(selected, dict):
        return selected

    return None

