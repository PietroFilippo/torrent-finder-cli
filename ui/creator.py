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

_WORKS_PAGE = 100   # titles per page in the works picker (and the no-pagination threshold)


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


def _works_select_prompt(works, entity, facet, preselected=None, page_no=1,
                         total_pages=None, has_prev=False, has_next=False):
    """Multi-select one page of titles. Nothing is checked by default.

    ``works`` is the current page's window; ``preselected`` is the set of titles
    checked across all pages (so checks survive page flips). Titles a creator only
    partly directed are flagged with ⚠ + the episode list. ``a``/``i``/``c`` act
    on the visible page; ``n``/``p`` move between pages. Returns:
      - ``("confirm", {checked titles on this page})``,
      - ``("next", {checked …})`` / ``("prev", {checked …})`` for page moves,
      - ``None`` if cancelled (Esc / Back — leaves the works picker).
    """
    preselected = preselected or set()
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
            label=w.title, value=("work", w), toggled=(w.title in preselected),
            hint=hint, description=description,
        ))
        work_item_indexes.append(len(items) - 1)

    items.append(SelectItem(label="Select all  [a]", value="all", is_action=True))
    items.append(SelectItem(label="Invert selection  [i]", value="invert", is_action=True))
    items.append(SelectItem(label="Clear  [c]", value="clear", is_action=True))
    prev_idx = next_idx = None
    if has_prev:
        items.append(SelectItem(
            label="◀  Previous page  [p]", value="prev", is_action=True,
            description="Go back to the previous page of titles.",
        ))
        prev_idx = len(items) - 1
    if has_next:
        items.append(SelectItem(
            label="▶  Next page  [n]", value="next", is_action=True,
            description="Load the next page of titles (ordered by popularity).",
        ))
        next_idx = len(items) - 1
    items.append(SelectItem(label="✅ Confirm  [w]", value="confirm", is_action=True))
    confirm_idx = len(items) - 1
    items.append(SelectItem(label="↩ Back", value="cancel", is_action=True))

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

    def _go_prev(cursor, items_list):
        return prev_idx if prev_idx is not None else True

    def _go_next(cursor, items_list):
        return next_idx if next_idx is not None else True

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
        "p": _go_prev, "P": _go_prev,
        "n": _go_next, "N": _go_next,
        "v": _set_anchor, "V": _range_toggle,
        " ": _toggle_current,
    }

    nav_bits = []
    if has_prev:
        nav_bits.append("[bold yellow]p[/bold yellow] prev")
    if has_next:
        nav_bits.append("[bold yellow]n[/bold yellow] next")
    nav = ("  •  " + " / ".join(nav_bits) + " page") if nav_bits else ""
    footer = (
        "↑/↓ nav  •  Space/Enter toggle  •  "
        "[bold yellow]a[/bold yellow]ll/[bold yellow]i[/bold yellow]nvert/[bold yellow]c[/bold yellow]lear  •  "
        "[bold green]w[/bold green] confirm" + nav + "  •  Esc back\n"
        "Pick titles to search (none selected by default; a/i/c act on this page)."
    )
    if any_partial:
        footer += "\n[bold yellow]⚠  = director handled only some episodes (highlight a title for details)[/bold yellow]"

    page_label = f"page {page_no}" + (f"/{total_pages}" if total_pages else "")
    result = arrow_select(
        items,
        title=f"{facet.label}: {entity.name} — {page_label}",
        multi=True,
        banner=_make_banner_panel(),
        on_action=on_action,
        key_actions=key_actions,
        footer=footer,
    )

    if result is None:
        return None
    val = items[result].value
    checked = {items[i].value[1].title for i in work_item_indexes if items[i].toggled}
    if val in ("next", "prev", "confirm"):
        return (val, checked)
    return None


def _fill_to(cache, facet, entity, need):
    """Fetch network chunks into ``cache['all']`` until it covers ``need`` titles
    or the source is exhausted. Mutates ``cache``; used by network-paged facets
    (Jikan magazine). Eager facets (AniList, net_more=False) never call this.
    """
    while len(cache["all"]) < need and cache["net_more"]:
        batch, net_more = facet.list_works(entity, cache["net_page"])
        have = {w.title for w in cache["all"]}
        cache["all"].extend(w for w in batch if w.title not in have)
        cache["net_page"] += 1
        cache["net_more"] = bool(net_more and batch)
        if not batch:
            break
    return True


def _start_prefetch(facet, entity, net_page, net_more, have_titles, target_total):
    """Background-fetch the next network page(s) into a *holder* (never the shared
    cache, so the worker and main thread don't mutate the same objects).
    ``_apply_prefetch`` merges the holder into the cache on the main thread.
    """
    holder = {"thread": None, "done": False, "works": [],
              "net_page": net_page, "net_more": net_more}

    def work():
        try:
            seen = set(have_titles)
            acc, np, more = [], net_page, net_more
            while len(have_titles) + len(acc) < target_total and more:
                batch, more = facet.list_works(entity, np)
                for w in batch:
                    if w.title not in seen:
                        seen.add(w.title)
                        acc.append(w)
                np += 1
                more = bool(more and batch)
            holder["works"], holder["net_page"], holder["net_more"] = acc, np, more
        except Exception:
            pass
        finally:
            holder["done"] = True

    t = threading.Thread(target=work, daemon=True)
    t.start()
    holder["thread"] = t
    return holder


def _apply_prefetch(cache):
    """Join any in-flight prefetch and merge its results into the cache (main
    thread only). Shows a spinner only if the prefetch hasn't finished yet."""
    holder = cache.pop("prefetch", None)
    if holder is None:
        return
    if not holder["done"]:
        with console.status("[bold cyan]Fetching more titles…[/bold cyan]", spinner="dots"):
            holder["thread"].join()
    have = {w.title for w in cache["all"]}
    cache["all"].extend(w for w in holder["works"] if w.title not in have)
    cache["net_page"] = holder["net_page"]
    cache["net_more"] = holder["net_more"]


def _name_input(provider, facet):
    """Prompt for a creator name. Returns the name, or None to go back (Esc).

    Always starts with an empty box (matching the keyword prompt): going back or
    retrying after "not found" doesn't keep the previously typed text.
    """
    clear_screen()
    console.print(f"[title]Search {provider.name} by {facet.label}[/title]")
    if facet.note:
        console.print(f"[dim]{facet.note}[/dim]")
    console.print("[dim]Type a name and press Enter  •  Esc to go back[/dim]")
    try:
        name = get_query_with_shortcut(f"[info]{facet.label} name:[/info] ")
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
            new_name = _name_input(provider, facet)
            if new_name is None:
                return "back"
            if new_name != name:
                entities = None  # different query → re-resolve
            name = new_name
            stage = "resolve"

        elif stage == "resolve":
            if entities is None:
                cancelled, result = _run_cancellable(
                    lambda: facet.search_entities(name),
                    f"Looking up {facet.label.lower()}…",
                )
                if cancelled:
                    stage = "name"
                    continue
                if result is None:
                    # Resolver signalled the lookup service was unreachable (vs.
                    # a genuine empty result). Leave `entities` None so retrying
                    # the name refetches instead of caching the failure.
                    _notice(
                        f"Couldn't reach the {facet.label.lower()} lookup service "
                        "(it may be temporarily down). Try again in a bit."
                    )
                    stage = "name"
                    continue
                entities = result
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
            cache = works_by_entity.get(entity.id)
            if cache is None:
                cancelled, res = _run_cancellable(
                    lambda: facet.list_works(entity, 1),
                    f"Fetching titles for {entity.name}…",
                )
                if cancelled:
                    stage = "entity" if disambig_shown else "name"
                    continue
                if res is None:  # resolver raised — treat as service unavailable
                    _notice(
                        f"Couldn't reach the {facet.label.lower()} lookup service "
                        "(it may be temporarily down). Try again in a bit."
                    )
                    stage = "entity" if disambig_shown else "name"
                    continue
                batch, net_more = res
                cache = {
                    "all": batch,        # all titles fetched so far (grows for Jikan)
                    "page_idx": 0,       # current page (0-based)
                    "net_page": 2,       # next network page to fetch
                    "net_more": net_more,
                    "toggled": set(),    # checked titles across all pages
                }
                works_by_entity[entity.id] = cache
            _apply_prefetch(cache)  # merge any page prefetched in the background
            if not cache["all"]:
                _notice(f"No titles found for {entity.name}.")
                stage = "entity" if disambig_shown else "name"
                continue

            # Make sure the current page has data (network-paged facets fetch on
            # demand; eager AniList already has everything). Usually a no-op now —
            # the background prefetch has already covered it.
            need = (cache["page_idx"] + 1) * _WORKS_PAGE
            if len(cache["all"]) < need and cache["net_more"]:
                _run_cancellable(
                    lambda: _fill_to(cache, facet, entity, need),
                    "Fetching more titles…",
                )
            # Stepped past the end (e.g. a cancelled/empty fetch) → clamp back.
            while cache["page_idx"] > 0 and cache["page_idx"] * _WORKS_PAGE >= len(cache["all"]):
                cache["page_idx"] -= 1

            page = cache["page_idx"]
            window = cache["all"][page * _WORKS_PAGE:(page + 1) * _WORKS_PAGE]
            has_prev = page > 0
            has_next = len(cache["all"]) > (page + 1) * _WORKS_PAGE or cache["net_more"]
            total_pages = None if cache["net_more"] else (len(cache["all"]) + _WORKS_PAGE - 1) // _WORKS_PAGE

            # Prefetch the next page in the background so "Next page" feels instant
            # (network-paged facets only; eager AniList already has everything).
            nxt_need = (page + 2) * _WORKS_PAGE
            if cache["net_more"] and len(cache["all"]) < nxt_need:
                cache["prefetch"] = _start_prefetch(
                    facet, entity, cache["net_page"], cache["net_more"],
                    {w.title for w in cache["all"]}, nxt_need,
                )

            outcome = _works_select_prompt(
                window, entity, facet, preselected=cache["toggled"],
                page_no=page + 1, total_pages=total_pages, has_prev=has_prev, has_next=has_next,
            )
            if outcome is None:
                stage = "entity" if disambig_shown else "name"
                continue
            action, checked = outcome
            # Merge this page's checks into the global set (drop the page's titles
            # first so un-checks are honoured), then act on the chosen button.
            page_titles = {w.title for w in window}
            cache["toggled"] = (cache["toggled"] - page_titles) | checked
            if action == "next":
                cache["page_idx"] += 1
                continue
            if action == "prev":
                cache["page_idx"] = max(0, page - 1)
                continue
            # action == "confirm"
            picked = [w for w in cache["all"] if w.title in cache["toggled"]]
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
