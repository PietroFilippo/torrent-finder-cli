"""Choose catalog terms, inspect works, then explicitly search their release names."""

import threading
from rich.markup import escape

from torrent_finder.resolvers import topics
from torrent_finder.search_errors import SearchError
from torrent_finder.search_session import search_many
from torrent_finder.ui.creator import _run_cancellable
from torrent_finder.ui.layout import ellipsize_cells
from torrent_finder.ui.prompts import PROMPT, _make_banner_panel, get_query_with_shortcut, input_screen
from torrent_finder.ui.search_diagnostics import read_details
from torrent_finder.ui.selector import SelectItem, arrow_select


def _lookup(fn, message):
    cancelled, value = _run_cancellable(fn, message)
    if cancelled:
        return None
    if value is None or isinstance(value, SearchError):
        read_details(str(value) if value else "Catalog request failed. Try again later.", "Discovery unavailable")
        return None
    return value


def _choose_topics(catalog, selected, initial=""):
    selected = list(selected)
    limit = 1 if catalog.key == "books" else topics.MAX_TOPICS
    while True:
        items = [SelectItem(f"Remove: {t.name}", t, hint=t.kind, description=escape(t.detail)) for t in selected]
        items += [SelectItem("Add topic / keyword", "add", enabled=len(selected) < limit,
                             description="One phrase at a time: time travel, mahjong, psychological, survival or co-op. Choose the catalog's matching term."),
                  SelectItem("Browse matching titles", "browse", enabled=bool(selected),
                             description="Match ALL chosen catalog terms. AniList tags require at least 60% relevance. Release availability is checked after selecting titles."),
                  SelectItem("Back", None)]
        index = arrow_select(items, title=f"{catalog.label} · topics ({len(selected)}/{limit})",
                             banner=_make_banner_panel(), footer="Enter add/remove • Esc back • Catalog vocabulary varies")
        if index is None or items[index].value is None:
            return None
        action = items[index].value
        if action == "browse":
            return selected
        if action != "add":
            selected.remove(action)
            continue
        phrase = get_query_with_shortcut(PROMPT, initial=initial, screen_renderer=input_screen(
            f"{catalog.label} › find topic", "One phrase; you choose the catalog term next."))
        initial = ""
        if not isinstance(phrase, str) or phrase in {"GO_BACK", ""}:
            continue
        matches = _lookup(lambda: topics.find_topics(catalog, phrase), "Finding catalog topics…")
        if matches is None:
            continue
        if not matches:
            read_details("No catalog topic matched that phrase. Try a shorter English term or a related catalog label. "
                         "For co-op survival, add co-op and survival separately. Nothing was silently dropped or searched as a release name.",
                         "No matching topic")
            continue
        choices = [SelectItem(t.name, t, hint=t.kind, description=escape(t.detail or "Catalog term; select to require it.")) for t in matches]
        choices.append(SelectItem("Back", None))
        pick = arrow_select(choices, title="Choose the intended catalog term", footer="Enter choose • Esc back")
        if pick is not None and choices[pick].value is not None and choices[pick].value not in selected:
            selected.append(choices[pick].value)


def _browse_works(provider, catalog, criteria, cli_filters, browse_fn):
    page, selected, cache = 1, {}, {}
    while True:
        if page not in cache:
            value = _lookup(lambda: topics.discover(catalog, criteria, page), "Finding matching works…")
            if value is None:
                return "back"
            cache[page] = value
        matches, more = cache[page]
        items = [SelectItem(m.work.title, m.id, toggled=m.id in selected,
                            hint=ellipsize_cells(m.work.subtitle, 60), description=escape(m.note + f"\nCatalog ID: {m.id}")) for m in matches]
        if not matches:
            items.append(SelectItem("No works match all selected topics", passive=True))
        if page > 1:
            items.append(SelectItem("Previous page", "prev", is_action=True))
        if more:
            items.append(SelectItem("Next page", "next", is_action=True))
        search_index = len(items)
        items += [SelectItem("Review names and search selected titles", "search", is_action=True),
                  SelectItem("Back to topics", None, is_action=True)]
        def toggle(cursor, rows):
            if cursor < len(matches):
                rows[cursor].cycle_toggle()
            return True
        index = arrow_select(items, title=f"Matching titles · page {page}/{topics.MAX_PAGES} max",
                             multi=True, banner=_make_banner_panel(),
                             footer=f"Space select (up to {topics.MAX_WORKS}) • W review • Esc back",
                             key_actions={" ": toggle, "w": lambda *_: search_index, "W": lambda *_: search_index})
        for item, match in zip(items, matches):
            if item.toggled:
                selected[match.id] = match
            else:
                selected.pop(match.id, None)
        if index is None or items[index].value is None:
            return "back"
        action = items[index].value
        if action in {"prev", "next"}:
            page += 1 if action == "next" else -1
            continue
        if not 1 <= len(selected) <= topics.MAX_WORKS:
            read_details(f"Choose between 1 and {topics.MAX_WORKS} titles across all pages.", "Title selection")
            continue
        queries, origins = topics.query_plan(list(selected.values()))
        review = [SelectItem(q, passive=True, description=escape(origins[q])) for q in queries]
        review += [SelectItem("Search these names", "search"), SelectItem("Back to titles", None)]
        pick = arrow_select(review, title="Review release searches", banner=_make_banner_panel(),
                            footer=escape("Providers: " + topics.scope_label(provider) + "\nUp to 2 names per title • Existing filters apply • Esc back"))
        if pick is None or review[pick].value != "search":
            continue
        cancel = threading.Event()
        cancelled, results = _run_cancellable(
            lambda: search_many(provider, queries, cli_filters, cancel_event=cancel, work_titles=origins),
            "Searching selected titles (30s limit)…", cancel=cancel)
        if cancelled:
            continue
        if results is None or isinstance(results, SearchError):
            read_details("Release search failed. Try again later.", "Search unavailable")
            continue
        provider.last_queries = queries
        from torrent_finder.state import add_history_entry
        from torrent_finder.stats import record_search
        label = "Topic discovery: " + ", ".join(t.name for t in criteria)
        presets = [p.name for p in provider.active_presets]
        extra = {"search_profile": provider.snapshot()} if getattr(provider, "is_combined", False) else {}
        add_history_entry(label, provider.slug, presets, queries=queries, **extra)
        record_search(provider.slug, label, presets)
        if browse_fn(provider, results, note=label + ". Catalog metadata identifies works; release availability varies.") == "next":
            return "next"


def discovery_flow(provider, cli_filters, browse_fn, initial=""):
    catalogs = topics.discovery_catalogs(provider)
    while True:
        items = [SelectItem(c.label, c, description=escape(
            "Needs " + ", ".join(c.missing_credentials()) if c.missing_credentials() else
            "Release providers: " + topics.scope_label(topics.scope_for(provider, c)))) for c in catalogs]
        items += [SelectItem("Discovery coverage / keyword help", "help"), SelectItem("Back", None)]
        index = arrow_select(items, title="Discover by topic / genre", banner=_make_banner_panel(),
                             footer="Choose a catalog • Software has no topic catalog • Esc back")
        if index is None or items[index].value is None:
            return "back"
        catalog = items[index].value
        if catalog == "help":
            read_details("Keywords find catalog terms, then those terms find works. Add one phrase at a time; all selected terms must match. "
                         "Anime/Manga: AniList genres and tags with at least 60% tag relevance. Movies/Series: TMDB genres and keywords. Games: IGDB genres, themes, modes and keywords. "
                         "Books: one Open Library subject. TMDB/IGDB need credentials. English catalog terms work best; arbitrary sentences are not semantic search. "
                         "Desktop/Mobile Software have no purpose catalog here; use their ordinary literal keyword search. "
                         "Combined searches use only the selected providers compatible with the chosen catalog, shown before searching. "
                         "At most 3 pages, 3 titles and 2 names per title. Catalog labels do not guarantee torrent availability or working multiplayer.",
                         "Discovery coverage")
            continue
        if catalog.missing_credentials():
            read_details("Configure " + ", ".join(catalog.missing_credentials()) + " in Credentials.", "Catalog credentials")
            continue
        selected = []
        while True:
            selected = _choose_topics(catalog, selected, initial)
            initial = ""
            if not selected:
                break
            if _browse_works(topics.scope_for(provider, catalog), catalog, selected, cli_filters, browse_fn) == "next":
                return "next"
