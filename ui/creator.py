"""'Search by creator' interactive flow.

Opened from a creator-capable provider's source screen (choose how to search →
by director/studio/…). Walks the user through: name → disambiguation →
multi-select titles → torrent results → download, with Esc stepping back one
screen at every stage (and backing out past the name prompt returning to the
source screen). The shared torrent-results + download UI is supplied by the
caller as ``browse_fn`` so this flow reuses the same path as keyword search.
"""

import re
import threading
import time

import readchar

from constants import console
from creator_search import fan_out
from stats import record_search
from ui.prompts import _make_banner_panel, clear_screen, get_query_with_shortcut
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


def _role_episode_note(role: str) -> str:
    """Return the episode qualifier of a creator role, or "".

    AniList writes partial-direction credits as e.g. "Director (eps 8, 10, 13-23)";
    this returns "eps 8, 10, 13-23" for those and "" for a whole-series role.
    """
    if not role:
        return ""
    m = re.search(r"\(([^)]*)\)", role)
    if not m:
        return ""
    inside = m.group(1).strip()
    return inside if re.search(r"\beps?\b", inside, re.I) else ""


def _pick_entity(entities, facet):
    """Disambiguate between candidate people/studios. Auto-picks a lone match.

    Returns the chosen Entity, or None to go back.
    """
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
    """Multi-select the titles to search. Nothing is checked by default.

    Titles the creator only partly directed (specific episodes) are flagged with
    ⚠ and the episode list. Returns the chosen list[Work], or None if cancelled.
    """
    items: list[SelectItem] = []
    work_item_indexes: list[int] = []
    any_partial = False
    for w in works:
        note = _role_episode_note(w.role)
        hint = w.subtitle
        description = ""
        if note:
            any_partial = True
            hint = f"{w.subtitle}  ⚠  {note}" if w.subtitle else f"⚠  {note}"
            description = (
                f"⚠  {entity.name} directed only specific episodes: {note}. "
                "The torrent search still covers the whole title."
            )
        items.append(SelectItem(
            label=w.title, value=("work", w), toggled=False, hint=hint, description=description,
        ))
        work_item_indexes.append(len(items) - 1)

    items.append(SelectItem(label="Select all  [a]", value="all", is_action=True))
    items.append(SelectItem(label="Invert selection  [i]", value="invert", is_action=True))
    items.append(SelectItem(label="Clear  [c]", value="clear", is_action=True))
    items.append(SelectItem(label="✅ Confirm  [w]", value="confirm", is_action=True))
    items.append(SelectItem(label="↩ Back", value="cancel", is_action=True))

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

    footer = (
        "↑/↓ nav  •  Space/Enter toggle  •  "
        "[bold yellow]a[/bold yellow]ll/[bold yellow]i[/bold yellow]nvert/[bold yellow]c[/bold yellow]lear  •  "
        "[bold green]w[/bold green] confirm  •  Esc back\n"
        "Pick titles to search (none selected by default)."
    )
    if any_partial:
        footer += "\n[bold yellow]⚠  = director handled only some episodes (highlight a title for details)[/bold yellow]"

    result = arrow_select(
        items,
        title=f"{facet.label}: {entity.name} — {len(works)} title(s)",
        multi=True,
        banner=_make_banner_panel(),
        on_action=on_action,
        key_actions=key_actions,
        footer=footer,
    )

    if result is None or items[result].value != "confirm":
        return None
    return [items[i].value[1] for i in work_item_indexes if items[i].toggled]


def _name_input(provider, facet, initial: str = ""):
    """Prompt for a creator name. Returns the name, or None to go back (Esc)."""
    clear_screen()
    console.print(f"[title]Search {provider.name} by {facet.label}[/title]")
    if facet.note:
        console.print(f"[dim]{facet.note}[/dim]")
    console.print("[dim]Type a name and press Enter  •  Esc to go back[/dim]")
    try:
        name = get_query_with_shortcut(f"[info]{facet.label} name:[/info] ", initial=initial)
    except (EOFError, KeyboardInterrupt):
        return None
    # Esc -> "GO_BACK", Tab -> ("ACTIONS", ...); both go back here, as does empty.
    if not isinstance(name, str) or name in ("GO_BACK", "") or not name.strip():
        return None
    return name.strip()


def creator_search_flow(provider, cli_filters, facet, browse_fn):
    """Drive the full by-creator journey with step-back navigation.

    Stages: name → (disambiguation) → works → torrent results → download. Esc at
    any stage steps back one screen; backing out past the name prompt returns to
    the source screen. ``browse_fn(provider, results)`` runs the shared
    results + download UI and returns "back" (Esc'd the results) or "next" (a
    download completed).

    Returns "back" (user left the journey → source screen) or "next" (a download
    completed → caller shows "what's next?").
    """
    name = ""
    entities = None
    entity = None
    disambig_shown = False
    works_by_entity: dict = {}
    picked = None
    stage = "name"

    while True:
        if stage == "name":
            new_name = _name_input(provider, facet, initial=name)
            if new_name is None:
                return "back"
            if new_name != name:
                entities = None  # different query → re-resolve
            name = new_name
            stage = "resolve"

        elif stage == "resolve":
            if entities is None:
                cancelled, entities = _run_cancellable(
                    lambda: facet.search_entities(name),
                    f"Looking up {facet.label.lower()}…",
                )
                if cancelled:
                    stage = "name"
                    continue
                entities = entities or []
            if not entities:
                _notice(f"No {facet.label.lower()} found for “{name}”.")
                stage = "name"
                continue
            stage = "entity"

        elif stage == "entity":
            if len(entities) == 1:
                entity = entities[0]
                disambig_shown = False
            else:
                entity = _pick_entity(entities, facet)
                if entity is None:
                    stage = "name"
                    continue
                disambig_shown = True
            stage = "works"

        elif stage == "works":
            if entity.id not in works_by_entity:
                cancelled, works = _run_cancellable(
                    lambda: facet.list_works(entity),
                    f"Fetching titles for {entity.name}…",
                )
                if cancelled:
                    stage = "entity" if disambig_shown else "name"
                    continue
                works_by_entity[entity.id] = works or []
            works = works_by_entity[entity.id]
            if not works:
                _notice(f"No titles found for {entity.name}.")
                stage = "entity" if disambig_shown else "name"
                continue
            picked = _works_select_prompt(works, entity, facet)
            if not picked:
                stage = "entity" if disambig_shown else "name"
                continue
            stage = "results"

        elif stage == "results":
            cancel = threading.Event()
            cancelled, results = _run_cancellable(
                lambda: fan_out(provider, picked, cli_filters, cancel_event=cancel),
                f"Searching {provider.name} for {len(picked)} title(s)…",
                cancel=cancel,
            )
            if cancelled:
                stage = "works"
                continue
            results = results or []
            if not results:
                _notice("No torrents found for the selected title(s).")
                stage = "works"
                continue
            label = f"{facet.label}: {entity.name}"
            record_search(provider.slug, label, [p.name for p in getattr(provider, "active_presets", [])])
            if browse_fn(provider, results) == "back":
                stage = "works"
                continue
            return "next"
