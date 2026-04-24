"""Search history browser — arrow-select menu over past searches."""

from datetime import datetime, timedelta, timezone

from constants import console
from providers import PROVIDERS
from state import clear_history, load_history
from ui.selector import SelectItem, arrow_select
from ui.prompts import _make_banner_panel, confirm_prompt

# Helpers

def _relative_time(iso_ts: str) -> str:
    """Turn an ISO-8601 timestamp into a human-friendly relative string."""
    try:
        dt = datetime.fromisoformat(iso_ts)
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
    except Exception:
        return ""

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


def _provider_icon(name: str) -> str:
    """Look up the emoji icon for a provider by name."""
    for p in PROVIDERS:
        if p.name == name:
            return p.icon
    return "🔍"


def _parse_ts(iso_ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso_ts)
    except Exception:
        return None


# Filter definitions

# Provider filter: cycle through All → each provider name → All
_PROVIDER_OPTIONS = ["All"] + [p.name for p in PROVIDERS]

# Date range filter
_DATE_OPTIONS = ["All time", "Today", "This week", "This month"]

# Sort order
_SORT_OPTIONS = ["Newest first", "Oldest first"]


def _filter_by_provider(entries: list[dict], provider: str) -> list[dict]:
    if provider == "All":
        return entries
    return [e for e in entries if e.get("provider") == provider]


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

def history_select_prompt() -> tuple[str, str] | None:
    """Display the search history menu with filtering hotkeys.

    Returns ``(query, provider_name)`` when the user picks an entry,
    or ``None`` on cancel / empty history / go-back.
    """
    # Mutable filter state — shared by key_action callbacks and callable title/footer
    fstate = {
        "prov_idx": 0,   # index into _PROVIDER_OPTIONS
        "date_idx": 0,   # index into _DATE_OPTIONS
        "sort_idx": 0,   # index into _SORT_OPTIONS
    }

    history = load_history()

    # --- helpers to build / rebuild the items list in place ---

    def _current_filters():
        return (
            _PROVIDER_OPTIONS[fstate["prov_idx"]],
            _DATE_OPTIONS[fstate["date_idx"]],
            _SORT_OPTIONS[fstate["sort_idx"]],
        )

    def _rebuild(items: list[SelectItem]) -> None:
        """Clear *items* and repopulate from current history + active filters."""
        prov_filter, date_filter, sort_order = _current_filters()

        filtered = _filter_by_provider(history, prov_filter)
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
                icon = _provider_icon(prov)
                time_str = _relative_time(ts)
                label = f"{icon}  {query}"
                hint = f"{prov}  •  {time_str}" if time_str else prov
                if presets:
                    hint += f"  •  filters: {', '.join(presets)}"
                items.append(SelectItem(label=label, value=entry, hint=hint))

            items.append(SelectItem(label="🗑  Clear history", value="clear", is_action=True))

        items.append(SelectItem(label="↩  Go Back", value="back", is_action=True))

    # --- dynamic title / footer (callables resolved each render) ---

    def _title():
        prov_filter, date_filter, sort_order = _current_filters()
        tags = []
        if prov_filter != "All":
            tags.append(f"{_provider_icon(prov_filter)} {prov_filter}")
        if date_filter != "All time":
            tags.append(date_filter)
        if sort_order != "Newest first":
            tags.append(sort_order)
        t = "Search History"
        if tags:
            t += " — " + "  •  ".join(tags)
        return t

    def _footer():
        prov_filter, date_filter, sort_order = _current_filters()
        return (
            "↑/↓ navigate  •  Enter re-run  •  Esc back\n"
            f" [bold yellow]P[/bold yellow] provider: [cyan]{prov_filter}[/cyan]  •  "
            f"[bold yellow]D[/bold yellow] date: [cyan]{date_filter}[/cyan]  •  "
            f"[bold yellow]S[/bold yellow] sort: [cyan]{sort_order}[/cyan]"
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
        nonlocal history
        if items_list[idx].value == "clear":
            if not confirm_prompt(
                "[bold red]Clear all search history?[/bold red]\n\n"
                "This will delete every saved search permanently."
            ):
                return True  # stay
            clear_history()
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
        },
    )

    if result is None:
        return None

    selected = items[result].value
    if isinstance(selected, dict):
        return (selected["query"], selected["provider"])

    return None

