"""Stats viewer — arrow-select menu showing usage counters.

Mirrors the history screen layout: one SelectItem per metric, grouped by
section headers. arrow_select's built-in windowing handles scrolling, so
there's no bespoke redraw/overscroll logic and no flicker.
"""

import sys

import readchar
from rich.panel import Panel
from rich.text import Text

from constants import console
from stats import (
    average_seeders,
    days_since_first_use,
    get_all_stats,
    reset_stats,
)
from ui.prompts import _make_banner_panel
from ui.selector import SelectItem, arrow_select


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


def _metric(label: str, value: str) -> SelectItem:
    """Read-only metric row: cursor CAN stop here (so window scrolls) but Enter is a no-op."""
    return SelectItem(
        label=label,
        value="metric",
        enabled=True,
        passive=True,   # navigable, but Enter does nothing
        hint=value,
    )


def _summary_items(stats: dict) -> list[SelectItem]:
    avg = average_seeders()
    return [
        _header("Summary"),
        _metric("First use", _fmt_first_use(stats.get("first_use"))),
        _metric("Days since first use", str(days_since_first_use())),
        _metric("Sessions", str(stats.get("session_count", 0))),
        _metric("Total runtime", _fmt_runtime(stats.get("total_runtime_s", 0.0))),
        _metric("Searches", str(stats.get("searches_total", 0))),
        _metric("Torrents picked", str(stats.get("picked_count", 0))),
        _metric("Avg seeders of picks", f"{avg:.1f}" if avg else "—"),
        _metric("Episode picker uses", str(stats.get("episode_picker_uses", 0))),
        _metric("Magnet dispatches", str(stats.get("magnet_dispatches", 0))),
    ]


def _method_items(stats: dict) -> list[SelectItem]:
    picks = stats.get("method_picks", {})
    done = stats.get("method_completed", {})
    rows = sorted(set(picks) | set(done))
    if not rows:
        return []

    completable = {"aria", "peerflix_download", "webtorrent_download", "subtitles"}

    out: list[SelectItem] = [_header("Methods (picks • completions • rate)")]
    for m in rows:
        p = picks.get(m, 0)
        c = done.get(m, 0)
        if m in completable:
            rate = f"{(c / p * 100):.0f}%" if p else "—"
            value = f"picked {p}  •  done {c}  •  {rate}"
        elif m == "open_magnet":
            value = f"dispatched {p}"
        else:  # streams
            value = f"started {p}"
        out.append(_metric(m, value))
    return out


def _kv_items(title: str, data: dict, top_n: int | None = None) -> list[SelectItem]:
    """Build a title + one row per (k, v) pair. Empty data → empty list (section omitted)."""
    if not data:
        return []
    items = sorted(data.items(), key=lambda kv: kv[1], reverse=True)
    if top_n:
        items = items[:top_n]
    out: list[SelectItem] = [_header(title)]
    for k, v in items:
        out.append(_metric(str(k), str(v)))
    return out


def _build_items(stats: dict) -> list[SelectItem]:
    """Sections → trailing Reset + Go Back. Metrics are navigable so the window scrolls with them."""
    items: list[SelectItem] = []
    items.extend(_summary_items(stats))
    items.extend(_method_items(stats))
    items.extend(_kv_items("Searches by Provider", stats.get("searches_by_provider", {})))
    items.extend(_kv_items("Torrents Picked by Provider", stats.get("torrents_picked_by_provider", {})))
    items.extend(_kv_items("Top 10 Queries", stats.get("top_queries", {}), top_n=10))
    items.extend(_kv_items("Filter Preset Usage", stats.get("preset_usage", {})))

    # Blank spacer between last section and trailing action buttons
    items.append(SelectItem(label="", value="spacer", enabled=False))

    # Trailing actions
    items.append(SelectItem(
        label="🔄 Reset all stats",
        value="reset",
        is_action=True,
        description="Wipes every counter (asks for confirmation)",
    ))
    items.append(SelectItem(
        label="↩ Go Back",
        value="back",
        is_action=True,
    ))
    return items


def _confirm_reset() -> bool:
    panel = Panel(
        Text.from_markup(
            "[bold red]Reset all stats?[/bold red]\n\n"
            "This will delete all usage counters permanently.\n\n"
            "[bold yellow]Y[/bold yellow] confirm  •  any other key cancel"
        ),
        title="[bold red]Confirm[/bold red]",
        border_style="red",
        padding=(1, 2),
    )
    sys.stdout.write("\033[?1049h\033[?25l\033[H\033[2J")
    sys.stdout.flush()
    try:
        console.print(panel)
        key = readchar.readkey()
        return key.lower() == "y"
    finally:
        sys.stdout.write("\033[?25h\033[?1049l\033[2J\033[H")
        sys.stdout.flush()


def stats_page() -> None:
    """Show the stats menu. Loops until the user picks Go Back or hits Esc."""
    while True:
        stats = get_all_stats()
        items = _build_items(stats)

        def on_action(idx, items_list):
            val = items_list[idx].value
            if val == "reset":
                if _confirm_reset():
                    reset_stats()
                    return False  # exit to outer loop → rebuild
                return True  # stay
            return False  # Go Back → exit

        result = arrow_select(
            items,
            title="📊 Usage Stats",
            banner=_make_banner_panel(),
            on_action=on_action,
            footer="↑/↓ scroll  •  Enter on action  •  Esc back",
        )

        if result is None:
            return

        action = items[result].value
        if action == "reset":
            # Came back from reset confirm — re-enter loop to rebuild items
            continue
        return
