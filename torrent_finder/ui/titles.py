"""Identify one catalog work, review its names, then search selected providers."""

import threading

from rich.markup import escape

from torrent_finder.resolvers.titles import (MAX_ALIASES, MAX_CATALOG_PAGES, TitleMatch,
                                           catalogs_for, distinct_names, search_titles, resolve_names)
from torrent_finder.resolvers.types import Work
from torrent_finder.search_errors import SearchError
from torrent_finder.search_session import search_many
from torrent_finder.ui.creator import _notice, _run_cancellable
from torrent_finder.ui.prompts import _make_banner_panel, get_query_with_shortcut, clear_screen
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.ui.layout import ellipsize_cells


def pick_names(match):
    names = distinct_names((match.work.title, *match.work.alt_titles))
    selected = set(names[:MAX_ALIASES])
    message = ""
    if match.note:
        from torrent_finder.ui.search_diagnostics import read_details
        read_details(match.note, "Catalog notice")
    while True:
        items = [SelectItem(name, toggled=name in selected, value=name,
                            description=escape(ellipsize_cells(match.work.subtitle, 60)) or "Space toggles this name.") for name in names]
        items += [SelectItem("Add a name manually", value="add", is_action=True),
                  SelectItem("Search selected names", value="search", is_action=True),
                  SelectItem("Back to titles", value="back", is_action=True)]
        def toggle_name(cursor, rows):
            if cursor < len(names):
                rows[cursor].cycle_toggle()
            return True
        index = arrow_select(items, title=f"Names to search (up to {MAX_ALIASES})", multi=True,
                             banner=_make_banner_panel(),
                             footer=escape(message) if message else "Space toggle • w search • Esc back",
                             key_actions={"w": lambda *_: len(names) + 1, " ": toggle_name})
        selected = {item.value for item in items[:len(names)] if item.toggled}
        if index is None or items[index].value == "back":
            return None
        if items[index].value == "add":
            value = get_query_with_shortcut("Additional title: ")
            if isinstance(value, str) and value not in {"", "GO_BACK"}:
                names = distinct_names([*names, value])
                if len(selected) < MAX_ALIASES:
                    selected.add(names[-1])
        else:
            queries = [name for name in names if name in selected]
            if 1 <= len(queries) <= MAX_ALIASES:
                return queries
            message = f"Choose between 1 and {MAX_ALIASES} names."


def title_search_flow(provider, cli_filters, browse_fn, initial=""):
    catalogs = catalogs_for(provider)
    while True:
        items = [SelectItem(c.label, value=c,
                            description=("Needs " + ", ".join(c.missing_credentials()) + ". Configure in Credentials."
                                         if c.missing_credentials() else "Identify a work by year/type, then choose its release names.")) for c in catalogs]
        items.append(SelectItem("Enter known names manually", value="manual",
                                description="Use names you know. Catalogs are unavailable for Desktop/Mobile Software; manual names work with every provider."))
        items.append(SelectItem("Back", value=None, is_action=True))
        picked = arrow_select(items, title="Alternate-title search", banner=_make_banner_panel(),
                              footer="Catalog identifies works; release availability varies.")
        if picked is None or items[picked].value is None:
            return "back"
        catalog = items[picked].value
        if catalog != "manual" and catalog.missing_credentials():
            _notice("Configure " + ", ".join(catalog.missing_credentials()) + " in Credentials.")
            continue
        query = get_query_with_shortcut("Identify title: ", initial=initial)
        initial = ""
        if not isinstance(query, str) or query == "GO_BACK" or not query.strip():
            continue
        page = 1
        while True:
            if catalog == "manual":
                matches, more = [TitleMatch("manual", "", Work(query.strip()))], False
            else:
                cancelled, value = _run_cancellable(lambda: search_titles(catalog, query, page), "Looking up catalog titles…")
                if cancelled:
                    break
                if isinstance(value, SearchError) or value is None:
                    _notice(str(value) if value else "Catalog lookup failed; try again later.")
                    break
                matches, more = value
            choices = [SelectItem(m.work.title, value=m, hint=ellipsize_cells(m.work.subtitle, 60),
                                  description=escape(f"{m.catalog} · ID {m.id}")) for m in matches]
            if not matches:
                choices.append(SelectItem("No catalog matches on this page", passive=True))
            if page > 1:
                choices.append(SelectItem("Previous catalog page", value="prev", is_action=True))
            if more:
                choices.append(SelectItem("Next catalog page", value="next", is_action=True))
            choices.append(SelectItem("Back", value=None, is_action=True))
            index = (0 if catalog == "manual" else arrow_select(
                choices, title=f"Choose work · page {page}/{MAX_CATALOG_PAGES} max", banner=_make_banner_panel(),
                footer="Check year/type to distinguish sequels and adaptations."))
            if index is None or choices[index].value is None:
                break
            choice = choices[index].value
            if choice in ("prev", "next"):
                page += 1 if choice == "next" else -1
                continue
            cancelled, match = _run_cancellable(lambda: resolve_names(choice), "Reading alternate names…")
            if cancelled:
                continue
            if not isinstance(match, TitleMatch):
                _notice("Could not read the selected work's names. Try again.")
                continue
            queries = pick_names(match)
            if not queries:
                if catalog == "manual":
                    break
                continue
            cancel = threading.Event()
            cancelled, results = _run_cancellable(
                lambda: search_many(provider, queries, cli_filters, cancel_event=cancel,
                                    work_titles={q: match.work.title for q in queries}),
                "Searching selected names (30s limit)…", cancel=cancel)
            if cancelled:
                continue
            if results is None or isinstance(results, SearchError):
                _notice(str(results) if results else "Search failed; try again later.")
                continue
            provider.last_queries = queries
            from torrent_finder.state import add_history_entry
            from torrent_finder.stats import record_search
            presets = [p.name for p in provider.active_presets]
            extra = {"search_profile": provider.snapshot()} if getattr(provider, "is_combined", False) else {}
            # The exact chosen query list survives history and bookmark replay;
            # replays do not silently ask the catalog for different names.
            add_history_entry(match.work.title, provider.slug, presets, queries=queries, **extra)
            record_search(provider.slug, match.work.title, presets)
            clear_screen()
            if browse_fn(provider, results, note="Names searched: " + "; ".join(queries)) == "next":
                return "next"
