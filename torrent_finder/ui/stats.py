"""Stats viewer — arrow-select menu showing usage counters.

Mirrors the history screen layout: one SelectItem per metric, grouped by
section headers; counts that compare (per provider, per method, top queries)
carry a bar scaled to their section's largest. First use, sessions and
runtime sit in the header. arrow_select's built-in windowing handles
scrolling, so there's no bespoke redraw/overscroll logic and no flicker.
"""

from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.providers import display_name_for
from torrent_finder.ui import theme
from torrent_finder.stats import (
    average_seeders,
    days_since_first_use,
    get_all_stats,
    reset_stats,
)
from torrent_finder.ui.prompts import _make_banner_panel, confirm_prompt
from torrent_finder.ui.selector import SelectItem, arrow_select


def _by_display_name(by_slug: dict) -> dict:
    """Reshape a slug-keyed counter dict into a display-name-keyed one for rendering."""
    return {display_name_for(slug): count for slug, count in by_slug.items()}


def _fmt_runtime(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    mins = seconds // 60
    if mins < 60:
        return f"{mins}m {seconds % 60}s"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h {mins % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def _fmt_first_use(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except Exception:
        return "—"


def _header(label: str) -> SelectItem:
    """Section header: windowable (scrolls with content), rendered dim bold, skipped on nav."""
    return SelectItem(
        label=f"─── {label} ───",
        value="section_header",
        enabled=False,   # skipped by _next_enabled so cursor won't stop here
    )


def _metric(label: str, value: "str | Text") -> SelectItem:
    """Read-only metric row: cursor CAN stop here (so window scrolls) but Enter is a no-op."""
    return SelectItem(
        label=label,
        value="metric",
        enabled=True,
        passive=True,   # navigable, but Enter does nothing
        hint=value,
    )


# Method keys as the download menu names them.
METHOD_NAMES = {
    "open_magnet": "Open in client",
    "aria": "aria2c download",
    "webtorrent_download": "webtorrent download",
    "peerflix_download": "peerflix download",
    "stream_webtorrent": "Stream · webtorrent",
    "stream_peerflix": "Stream · peerflix",
    "subtitles": "Subtitle search",
}
_BAR_MAX = 20


def _bar_width(note_width: int, count_width: int) -> int:
    """Bar cells that keep a bar, its count and note inline beside the label (half the content width)."""
    room = theme.inner_width(console.size.width) // 2 - 2 - count_width - 2 - (note_width + 2 if note_width else 0)
    return max(4, min(_BAR_MAX, room))


def _bar_hint(value: int, largest: int, width: int, count_width: int, note: str = "") -> Text:
    """``▇▇▇▇▇▇      64  note``: a deep-shade bar, the count in text colour, an optional steel note."""
    hint = Text()
    cells = theme.bar(value, largest, width)
    hint.append(cells, style=theme.DEEP)
    hint.append(" " * (width - len(cells) + 2))
    hint.append(str(value).rjust(count_width), style="default")
    if note:
        hint.append("  " + note)
    return hint


def _bars(title: str, rows: list[tuple[str, int, str]]) -> list[SelectItem]:
    """A section of (label, count, note) rows, each with a bar scaled to the largest count."""
    if not rows:
        return []
    largest = max(count for _, count, _ in rows)
    count_width = max(len(str(count)) for _, count, _ in rows)
    width = _bar_width(max(len(note) for _, _, note in rows), count_width)
    return [_header(title)] + [_metric(label, _bar_hint(count, largest, width, count_width, note))
                               for label, count, note in rows]


def header_status(stats: dict) -> str:
    """``since 2026-06-11 · 41 sessions · 6h 12m``."""
    parts = []
    first = _fmt_first_use(stats.get("first_use"))
    if first != "—":
        parts.append(f"since {first}")
    sessions = int(stats.get("session_count", 0) or 0)
    parts.append(f"{sessions} session{'s' if sessions != 1 else ''}")
    parts.append(_fmt_runtime(stats.get("total_runtime_s", 0.0)))
    return " · ".join(parts)


def _value(text: str) -> Text:
    return Text.assemble((text, "default"))  # a figure reads in the text colour, like a count beside a bar


def _summary_items(stats: dict) -> list[SelectItem]:
    avg = average_seeders()
    return [
        _header("Summary"),
        _metric("Searches", _value(str(stats.get("searches_total", 0)))),
        _metric("Torrents picked", _value(str(stats.get("picked_count", 0)))),
        _metric("Avg seeders of picks", _value(f"{avg:.1f}" if avg else "—")),
        _metric("Episode picker uses", _value(str(stats.get("episode_picker_uses", 0)))),
        _metric("Magnet dispatches", _value(str(stats.get("magnet_dispatches", 0)))),
        _metric("Days since first use", _value(str(days_since_first_use()))),
    ]


def _method_items(stats: dict) -> list[SelectItem]:
    picks = stats.get("method_picks", {})
    done = stats.get("method_completed", {})
    completable = {"aria", "peerflix_download", "webtorrent_download", "subtitles"}
    rows = []
    for method in sorted(set(picks) | set(done), key=lambda m: (-picks.get(m, 0), m)):
        picked, completed = picks.get(method, 0), done.get(method, 0)
        if method in completable:
            note = f"{completed} done · {completed / picked * 100:.0f}%" if picked else f"{completed} done"
        elif method == "open_magnet":
            note = "handed to the client"
        else:  # streams
            note = "started"
        rows.append((METHOD_NAMES.get(method, method.replace("_", " ")), picked, note))
    return _bars("Download methods", rows)


def _kv_items(title: str, data: dict, top_n: int | None = None) -> list[SelectItem]:
    """A title + one bar row per (k, v) pair, biggest first. Empty data → empty list (section omitted)."""
    if not data:
        return []
    items = sorted(data.items(), key=lambda kv: kv[1], reverse=True)
    if top_n:
        items = items[:top_n]
    return _bars(title, [(str(key), int(value or 0), "") for key, value in items])


def _build_items(stats: dict) -> list[SelectItem]:
    """Sections → trailing Reset + Go Back. Metrics are navigable so the window scrolls with them."""
    items: list[SelectItem] = []
    items.extend(_summary_items(stats))
    items.extend(_method_items(stats))
    items.extend(_kv_items("Searches by Provider", _by_display_name(stats.get("searches_by_provider", {}))))
    items.extend(_kv_items("Torrents Picked by Provider", _by_display_name(stats.get("torrents_picked_by_provider", {}))))
    items.extend(_kv_items("Top 10 Queries", stats.get("top_queries", {}), top_n=10))
    items.extend(_kv_items(
        "Creator Searches by Facet",
        {k.capitalize(): v for k, v in stats.get("creator_searches_by_facet", {}).items()},
    ))
    items.extend(_kv_items("Top 10 Creators Searched", stats.get("top_creators", {}), top_n=10))
    items.extend(_kv_items("Filter Preset Usage", stats.get("preset_usage", {})))

    # Blank spacer between last section and trailing action buttons
    items.append(SelectItem(label="", value="spacer", enabled=False))

    # Trailing actions
    items.append(SelectItem(
        label="Reset all stats",
        value="reset",
        is_action=True,
        description="Wipes every counter (asks for confirmation)",
    ))
    items.append(SelectItem(
        label="Back",
        value="back",
        is_action=True,
    ))
    return items


def stats_page() -> None:
    """Show the stats menu. Loops until the user picks Go Back or hits Esc."""
    notice = ""  # shown above the footer, e.g. a failed reset
    while True:
        stats = get_all_stats()
        items = _build_items(stats)

        def on_action(idx, items_list):
            nonlocal notice
            val = items_list[idx].value
            if val == "reset":
                if confirm_prompt(
                    "[error]Reset all stats?[/error]\n\n"
                    "This will delete all usage counters permanently."
                ):
                    try:
                        reset_stats()
                    except (OSError, ValueError) as error:
                        from rich.markup import escape
                        notice = f"[error]Stats were not reset:[/error] {escape(str(error))}"
                        return True  # stay; the saved counters are unchanged
                    notice = ""
                    return False  # exit to outer loop → rebuild
                return True  # stay
            return False  # Go Back → exit

        result = arrow_select(
            items,
            title="Usage stats",
            status=header_status(stats),
            banner=_make_banner_panel(),
            on_action=on_action,
            footer=lambda: (notice + "\n" if notice else "") + "↑/↓ scroll  •  Enter on action  •  Esc back",
        )

        if result is None:
            return

        action = items[result].value
        if action == "reset":
            # Came back from reset confirm — re-enter loop to rebuild items
            continue
        return
