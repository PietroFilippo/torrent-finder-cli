"""Search history browser — arrow-select menu over past searches."""

from datetime import datetime, timedelta, timezone

from constants import console
from providers import PROVIDERS
from state import clear_history, load_history
from ui.selector import SelectItem, arrow_select
from ui.prompts import _make_banner_panel

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
    # Filter state (persists across hotkey cycles within a single menu session)
    prov_idx = 0   # index into _PROVIDER_OPTIONS
    date_idx = 0   # index into _DATE_OPTIONS
    sort_idx = 0   # index into _SORT_OPTIONS

    while True:
        history = load_history()
        prov_filter = _PROVIDER_OPTIONS[prov_idx]
        date_filter = _DATE_OPTIONS[date_idx]
        sort_order = _SORT_OPTIONS[sort_idx]

        # Apply filters
        filtered = _filter_by_provider(history, prov_filter)
        filtered = _filter_by_date(filtered, date_filter)
        filtered = _sort_entries(filtered, sort_order)

        # Build title with active filters
        filter_tags = []
        if prov_filter != "All":
            filter_tags.append(f"{_provider_icon(prov_filter)} {prov_filter}")
        if date_filter != "All time":
            filter_tags.append(date_filter)
        if sort_order != "Newest first":
            filter_tags.append(sort_order)
        title = "Search History"
        if filter_tags:
            title += " — " + "  •  ".join(filter_tags)

        # Build items
        items: list[SelectItem] = []

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
                icon = _provider_icon(prov)
                time_str = _relative_time(ts)
                label = f"{icon}  {query}"
                hint = f"{prov}  •  {time_str}" if time_str else prov
                items.append(SelectItem(label=label, value=entry, hint=hint))

            items.append(SelectItem(label="🗑  Clear history", value="clear", is_action=True))

        items.append(SelectItem(label="↩  Go Back", value="back", is_action=True))

        # Footer with filter hotkey hints
        footer = (
            "↑/↓ navigate  •  Enter re-run  •  Esc back\n"
            f" [bold yellow]P[/bold yellow] provider: [cyan]{prov_filter}[/cyan]  •  "
            f"[bold yellow]D[/bold yellow] date: [cyan]{date_filter}[/cyan]  •  "
            f"[bold yellow]S[/bold yellow] sort: [cyan]{sort_order}[/cyan]"
        )

        def on_action(idx, items_list):
            if items_list[idx].value == "clear":
                clear_history()
                to_remove = [i for i, it in enumerate(items_list) if not it.is_action]
                for i in reversed(to_remove):
                    items_list.pop(i)
                for it in items_list:
                    if it.value == "clear":
                        it.hint = "✅ Cleared!"
                        it.enabled = False
                return True
            return False

        result = arrow_select(
            items,
            title=title,
            banner=_make_banner_panel(),
            on_action=on_action,
            footer=footer,
            hotkeys={
                "P": "provider", "p": "provider",
                "D": "date", "d": "date",
                "S": "sort", "s": "sort",
            },
        )

        # Handle hotkey cycling — rebuild the menu with the next filter value
        if isinstance(result, tuple) and result[0] == "hotkey":
            _, action, _ = result
            if action == "provider":
                prov_idx = (prov_idx + 1) % len(_PROVIDER_OPTIONS)
            elif action == "date":
                date_idx = (date_idx + 1) % len(_DATE_OPTIONS)
            elif action == "sort":
                sort_idx = (sort_idx + 1) % len(_SORT_OPTIONS)
            continue

        if result is None:
            return None

        selected = items[result].value
        if isinstance(selected, dict):
            return (selected["query"], selected["provider"])

        return None
