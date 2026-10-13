"""Stats viewer — arrow-select menu showing usage counters.

Mirrors the history screen layout: one SelectItem per metric, grouped by
section headers; counts that compare (per provider, per method, top queries)
carry a bar scaled to their section's largest. First use, sessions and
runtime sit in the header. arrow_select's built-in windowing handles
scrolling, so there's no bespoke redraw/overscroll logic and no flicker.
"""

# i18n: converted
from rich.cells import cell_len
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.i18n import N_, t, tn
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
    "open_magnet": N_("Open in client"),
    "aria": N_("aria2c download"),
    "webtorrent_download": N_("webtorrent download"),
    "peerflix_download": N_("peerflix download"),
    "stream_webtorrent": N_("Stream · webtorrent"),
    "stream_peerflix": N_("Stream · peerflix"),
    "subtitles": N_("Subtitle search"),
}
FACET_NAMES = {
    "director": N_("Director"),
    "studio": N_("Studio"),
    "author": N_("Author"),
    "developer": N_("Developer"),
    "publisher": N_("Publisher"),
    "writer": N_("Writer"),
    "magazine": N_("Magazine"),
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
    hint.append(" " * (width - cell_len(cells) + 2))
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
    width = _bar_width(max(cell_len(note) for _, _, note in rows), count_width)
    return [_header(title)] + [_metric(label, _bar_hint(count, largest, width, count_width, note))
                               for label, count, note in rows]


def header_status(stats: dict) -> str:
    """``since 2026-06-11 · 41 sessions · 6h 12m``."""
    parts = []
    first = _fmt_first_use(stats.get("first_use"))
    if first != "—":
        parts.append(t("since {date}", date=first))
    sessions = int(stats.get("session_count", 0) or 0)
    parts.append(tn("{n} session", "{n} sessions", sessions))
    parts.append(_fmt_runtime(stats.get("total_runtime_s", 0.0)))
    return " · ".join(parts)


def _value(text: str) -> Text:
    return Text.assemble((text, "default"))  # a figure reads in the text colour, like a count beside a bar


def _summary_items(stats: dict) -> list[SelectItem]:
    avg = average_seeders()
    return [
        _header(t("Summary")),
        _metric(t("Searches"), _value(str(stats.get("searches_total", 0)))),
        _metric(t("Torrents picked"), _value(str(stats.get("picked_count", 0)))),
        _metric(t("Avg seeders of picks"), _value(f"{avg:.1f}" if avg else "—")),
        _metric(t("Episode picker uses"), _value(str(stats.get("episode_picker_uses", 0)))),
        _metric(t("Magnet dispatches"), _value(str(stats.get("magnet_dispatches", 0)))),
        _metric(t("Days since first use"), _value(str(days_since_first_use()))),
    ]


def _method_items(stats: dict) -> list[SelectItem]:
    picks = stats.get("method_picks", {})
    done = stats.get("method_completed", {})
    completable = {"aria", "peerflix_download", "webtorrent_download", "subtitles"}
    rows = []
    for method in sorted(set(picks) | set(done), key=lambda m: (-picks.get(m, 0), m)):
        picked, completed = picks.get(method, 0), done.get(method, 0)
        if method in completable:
            note = (tn("{n} done · {percent:.0f}%", "{n} done · {percent:.0f}%", completed,
                       percent=completed / picked * 100)
                    if picked else tn("{n} done", "{n} done", completed))
        elif method == "open_magnet":
            note = t("handed to the client")
        else:  # streams
            note = t("started")
        label = t(METHOD_NAMES[method]) if method in METHOD_NAMES else method.replace("_", " ")
        rows.append((label, picked, note))
    return _bars(t("Download methods"), rows)


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
    items.extend(_kv_items(t("Searches by Provider"), _by_display_name(stats.get("searches_by_provider", {}))))
    items.extend(_kv_items(t("Torrents Picked by Provider"), _by_display_name(stats.get("torrents_picked_by_provider", {}))))
    items.extend(_kv_items(t("Top 10 Queries"), stats.get("top_queries", {}), top_n=10))
    items.extend(_kv_items(
        t("Creator Searches by Facet"),
        {t(FACET_NAMES[k]) if k in FACET_NAMES else k.capitalize(): v
         for k, v in stats.get("creator_searches_by_facet", {}).items()},
    ))
    items.extend(_kv_items(t("Top 10 Creators Searched"), stats.get("top_creators", {}), top_n=10))
    items.extend(_kv_items(t("Filter Preset Usage"), {t(k): v for k, v in stats.get("preset_usage", {}).items()}))

    # Blank spacer between last section and trailing action buttons
    items.append(SelectItem(label="", value="spacer", enabled=False))

    # Trailing actions
    items.append(SelectItem(
        label=t("Reset all stats"),
        value="reset",
        is_action=True,
        description=t("Wipes every counter (asks for confirmation)"),
    ))
    items.append(SelectItem(
        label=t("Back"),
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
                    t("[error]Reset all stats?[/error]\n\n"
                      "This will delete all usage counters permanently.")
                ):
                    try:
                        reset_stats()
                    except (OSError, ValueError) as error:
                        from rich.markup import escape
                        notice = t("[error]Stats were not reset:[/error] {error}", error=escape(str(error)))
                        return True  # stay; the saved counters are unchanged
                    notice = ""
                    return False  # exit to outer loop → rebuild
                return True  # stay
            return False  # Go Back → exit

        result = arrow_select(
            items,
            title=t("Usage stats"),
            status=header_status(stats),
            banner=_make_banner_panel(),
            on_action=on_action,
            footer=lambda: (notice + "\n" if notice else "") + t("↑/↓ scroll  •  Enter on action  •  Esc back"),
        )

        if result is None:
            return

        action = items[result].value
        if action == "reset":
            # Came back from reset confirm — re-enter loop to rebuild items
            continue
        return
