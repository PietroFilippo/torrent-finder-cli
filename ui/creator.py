"""'Search by creator' interactive flow.

Opened from the search-prompt quick-actions menu (Tab → Search by creator) for
providers that declare ``creator_facets``. Walks the user through:
facet → name → disambiguation → multi-select works → fan-out search, and hands
the merged results back to the main loop for the normal results table.
"""

import threading
import time

import readchar

from constants import console
from creator_search import fan_out
from ui.prompts import _make_banner_panel, clear_screen
from ui.selector import SelectItem, arrow_select
from utils import start_esc_listener


def _run_cancellable(fn, message: str, cancel: "threading.Event | None" = None):
    """Run ``fn()`` on a worker thread under a spinner; Esc aborts.

    Returns ``(cancelled, value)``. On Esc, ``cancelled`` is True and the
    abandoned worker is left to finish in the background (daemon thread).
    """
    out: dict = {}

    def work() -> None:
        try:
            out["v"] = fn()
        except Exception:
            out["v"] = None
        finally:
            out["done"] = True

    cancel = cancel or threading.Event()
    threading.Thread(target=work, daemon=True).start()
    stop = start_esc_listener(cancel)
    try:
        with console.status(f"[bold cyan]{message}[/bold cyan]", spinner="dots"):
            while not out.get("done") and not cancel.is_set():
                time.sleep(0.05)
    finally:
        stop.set()
    return (cancel.is_set(), out.get("v"))


def _notice(msg: str) -> None:
    console.print(f"[warning] {msg}[/warning]")
    console.print("[dim]Press any key to continue...[/dim]")
    readchar.readkey()


def _pick_facet(facets):
    """Pick a facet (Director/Studio/…). Auto-picks when there's only one."""
    if len(facets) == 1:
        return facets[0]
    items = [SelectItem(label=f.label, value=f, description=f.note) for f in facets]
    items.append(SelectItem(label="↩  Back", value="__back__", is_action=True))
    idx = arrow_select(items, title="Search by…", banner=_make_banner_panel())
    if idx is None:
        return None
    val = items[idx].value
    return None if val == "__back__" else val


def _pick_entity(entities, facet):
    """Disambiguate between candidate people/studios. Auto-picks a lone match."""
    if len(entities) == 1:
        return entities[0]
    items = [SelectItem(label=e.name, value=e, description=e.detail) for e in entities]
    items.append(SelectItem(label="↩  Back", value="__back__", is_action=True))
    idx = arrow_select(
        items,
        title=f"Select {facet.label.lower()}",
        banner=_make_banner_panel(),
        footer="↑/↓ navigate  •  Enter select  •  Esc back",
    )
    if idx is None:
        return None
    val = items[idx].value
    return None if val == "__back__" else val


def _works_select_prompt(works, entity, facet):
    """Multi-select the titles to search. Defaults to all checked.

    Returns the chosen list[Work], or None if cancelled.
    """
    items: list[SelectItem] = []
    work_item_indexes: list[int] = []
    for w in works:
        items.append(SelectItem(label=w.title, value=("work", w), toggled=True, hint=w.subtitle))
        work_item_indexes.append(len(items) - 1)

    items.append(SelectItem(label="Select all  [a]", value="all", is_action=True))
    items.append(SelectItem(label="Invert selection  [i]", value="invert", is_action=True))
    items.append(SelectItem(label="Clear  [c]", value="clear", is_action=True))
    items.append(SelectItem(label="✅ Confirm  [w]", value="confirm", is_action=True))
    items.append(SelectItem(label="↩ Cancel", value="cancel", is_action=True))

    confirm_idx = len(items) - 2
    anchor = {"idx": None}

    def _work_set() -> set:
        return set(work_item_indexes)

    def _select_all(cursor, items_list):
        for i in work_item_indexes:
            items_list[i].toggled = True
        return True

    def _invert(cursor, items_list):
        for i in work_item_indexes:
            items_list[i].toggled = not items_list[i].toggled
        return True

    def _clear(cursor, items_list):
        for i in work_item_indexes:
            items_list[i].toggled = False
        return True

    def _confirm_now(cursor, items_list):
        return confirm_idx

    def _set_anchor(cursor, items_list):
        if cursor not in _work_set():
            return True
        if anchor["idx"] is not None and 0 <= anchor["idx"] < len(items_list):
            items_list[anchor["idx"]].marker = ""
        anchor["idx"] = cursor
        items_list[cursor].marker = "📍"
        return True

    def _range_toggle(cursor, items_list):
        if anchor["idx"] is None:
            return _set_anchor(cursor, items_list)
        work_set = _work_set()
        lo, hi = sorted([anchor["idx"], cursor])
        target = not items_list[anchor["idx"]].toggled
        for i in range(lo, hi + 1):
            if i in work_set:
                items_list[i].toggled = target
        items_list[anchor["idx"]].marker = ""
        anchor["idx"] = None
        return True

    def _toggle_current(cursor, items_list):
        if cursor in _work_set():
            items_list[cursor].toggled = not items_list[cursor].toggled
        return True

    def on_action(idx, items_list):
        val = items_list[idx].value
        if val == "all":
            return _select_all(idx, items_list)
        if val == "invert":
            return _invert(idx, items_list)
        if val == "clear":
            return _clear(idx, items_list)
        return False

    key_actions = {
        "a": _select_all, "A": _select_all,
        "i": _invert, "I": _invert,
        "c": _clear, "C": _clear,
        "w": _confirm_now, "W": _confirm_now,
        "v": _set_anchor, "V": _range_toggle,
        " ": _toggle_current,
    }

    result = arrow_select(
        items,
        title=f"{facet.label}: {entity.name} — {len(works)} title(s)",
        multi=True,
        banner=_make_banner_panel(),
        on_action=on_action,
        key_actions=key_actions,
        footer=(
            "↑/↓ nav  •  Space/Enter toggle  •  "
            "[bold yellow]a[/bold yellow]ll/[bold yellow]i[/bold yellow]nvert/[bold yellow]c[/bold yellow]lear  •  "
            "[bold green]w[/bold green] confirm  •  Esc cancel\n"
            "Confirm runs a torrent search for each checked title."
        ),
    )

    if result is None or items[result].value != "confirm":
        return None
    return [items[i].value[1] for i in work_item_indexes if items[i].toggled]


def creator_search_flow(provider, cli_filters=None):
    """Run the by-creator flow for ``provider``.

    Returns ``(label, results)`` on success (``results`` may be empty), or
    None if the user cancelled at any step.
    """
    facets = list(getattr(provider, "creator_facets", []) or [])
    if not facets:
        return None

    clear_screen()
    facet = _pick_facet(facets)
    if facet is None:
        return None

    clear_screen()
    console.print(f"[title]Search {provider.name} by {facet.label}[/title]")
    if facet.note:
        console.print(f"[dim]{facet.note}[/dim]")
    console.print("[dim]Type a name and press Enter. Leave empty to cancel.[/dim]")
    try:
        name = console.input(f"[info]{facet.label} name:[/info] ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not name:
        return None

    cancelled, entities = _run_cancellable(
        lambda: facet.search_entities(name), f"Looking up {facet.label.lower()}…"
    )
    if cancelled:
        return None
    entities = entities or []
    if not entities:
        _notice(f"No {facet.label.lower()} found for “{name}”.")
        return None

    entity = _pick_entity(entities, facet)
    if entity is None:
        return None

    cancelled, works = _run_cancellable(
        lambda: facet.list_works(entity), f"Fetching titles for {entity.name}…"
    )
    if cancelled:
        return None
    works = works or []
    if not works:
        _notice(f"No titles found for {entity.name}.")
        return None

    picked = _works_select_prompt(works, entity, facet)
    if not picked:
        return None

    cancel = threading.Event()
    cancelled, results = _run_cancellable(
        lambda: fan_out(provider, picked, cli_filters, cancel_event=cancel),
        f"Searching {provider.name} for {len(picked)} title(s)…",
        cancel=cancel,
    )
    if cancelled:
        return None

    return (f"{facet.label}: {entity.name}", results or [])
