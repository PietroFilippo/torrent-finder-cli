"""Search history browser — arrow-select menu over past searches."""

from datetime import datetime, timezone

from constants import console
from providers import PROVIDERS
from state import clear_history, load_history
from ui.selector import SelectItem, arrow_select
from ui.prompts import _make_banner_panel


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


def history_select_prompt() -> tuple[str, str] | None:
    """Display the search history menu.

    Returns ``(query, provider_name)`` when the user picks an entry,
    or ``None`` on cancel / empty history / go-back.
    """
    history = load_history()

    items: list[SelectItem] = []

    if not history:
        items.append(SelectItem(
            label="No searches yet — your history will appear here",
            value="empty_placeholder",
            enabled=False,
            is_action=True,
        ))
    else:
        for entry in history:
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

    def on_action(idx, items_list):
        if items_list[idx].value == "clear":
            clear_history()
            # Remove all non-action items to give visual feedback
            to_remove = [i for i, it in enumerate(items_list) if not it.is_action]
            for i in reversed(to_remove):
                items_list.pop(i)
            # Disable the clear button itself
            for it in items_list:
                if it.value == "clear":
                    it.hint = "✅ Cleared!"
                    it.enabled = False
            return True  # stay in menu
        return False  # exit for back / regular items

    idx = arrow_select(
        items,
        title="Search History",
        banner=_make_banner_panel(),
        on_action=on_action,
        footer="↑/↓ navigate  •  Enter re-run search  •  Esc go back",
    )

    if idx is None:
        return None

    selected = items[idx].value
    if isinstance(selected, dict):
        return (selected["query"], selected["provider"])

    return None
