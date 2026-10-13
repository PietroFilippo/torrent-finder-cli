"""Choose catalog terms, inspect works, then explicitly search their release names."""

# i18n: converted
import threading
from rich.markup import escape

from torrent_finder.i18n import t
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
        read_details(str(value) if value else t("Catalog request failed. Try again later."), t("Discovery unavailable"))
        return None
    return value


def _choose_topics(catalog, selected, initial=""):
    selected = list(selected)
    limit = 1 if catalog.key == "books" else topics.MAX_TOPICS
    while True:
        items = [SelectItem(t("Remove: {name}", name=topic.name), topic, hint=topics.kind_label(topic.kind), description=escape(topic.detail)) for topic in selected]
        items += [SelectItem(t("Add topic / keyword"), "add", enabled=len(selected) < limit,
                             description=t("One phrase at a time: time travel, mahjong, psychological, survival or co-op. Choose the catalog's matching term.")),
                  SelectItem(t("Browse matching titles"), "browse", enabled=bool(selected),
                             description=t("Match ALL chosen catalog terms. AniList tags require at least 60% relevance. Release availability is checked after selecting titles.")),
                  SelectItem(t("Back"), None)]
        index = arrow_select(items, title=t("Topics › {catalog}", catalog=t(catalog.label)), status=t("{count} of {limit} chosen", count=len(selected), limit=limit),
                             banner=_make_banner_panel(), footer=t("Enter add/remove • Esc back • Catalog vocabulary varies"))
        if index is None or items[index].value is None:
            return None
        action = items[index].value
        if action == "browse":
            return selected
        if action != "add":
            selected.remove(action)
            continue
        phrase = get_query_with_shortcut(PROMPT, initial=initial, screen_renderer=input_screen(
            t("{catalog} › find topic", catalog=t(catalog.label)), t("One phrase; you choose the catalog term next."),
            keys=t("Enter confirm  •  Esc cancel")))
        initial = ""
        if not isinstance(phrase, str) or phrase in {"GO_BACK", ""}:
            continue
        matches = _lookup(lambda: topics.find_topics(catalog, phrase), t("Finding catalog topics…"))
        if matches is None:
            continue
        if not matches:
            read_details(t("No catalog topic matched that phrase. Try a shorter English term or a related catalog label. "
                         "For co-op survival, add co-op and survival separately. Nothing was silently dropped or searched as a release name."),
                         t("No matching topic"))
            continue
        choices = [SelectItem(topic.name, topic, hint=topics.kind_label(topic.kind), description=escape(topic.detail or t("Catalog term; select to require it."))) for topic in matches]
        choices.append(SelectItem(t("Back"), None))
        pick = arrow_select(choices, title=t("Choose the intended catalog term"), footer=t("Enter choose • Esc back"))
        if pick is not None and choices[pick].value is not None and choices[pick].value not in selected:
            selected.append(choices[pick].value)


def _browse_works(provider, catalog, criteria, cli_filters, browse_fn):
    page, selected, cache = 1, {}, {}
    while True:
        if page not in cache:
            value = _lookup(lambda: topics.discover(catalog, criteria, page), t("Finding matching works…"))
            if value is None:
                return "back"
            cache[page] = value
        matches, more = cache[page]
        items = [SelectItem(m.work.title, m.id, toggled=m.id in selected,
                            hint=ellipsize_cells(m.work.subtitle, 60), description=escape(m.note + t("\nCatalog ID: {id}", id=m.id))) for m in matches]
        if not matches:
            items.append(SelectItem(t("No works match all selected topics"), passive=True))
        if page > 1:
            items.append(SelectItem(t("Previous page"), "prev", is_action=True))
        if more:
            items.append(SelectItem(t("Next page"), "next", is_action=True))
        search_index = len(items)
        items += [SelectItem(t("Review names and search selected titles"), "search", is_action=True),
                  SelectItem(t("Back to topics"), None, is_action=True)]
        def toggle(cursor, rows):
            if cursor < len(matches):
                rows[cursor].cycle_toggle()
            return True
        index = arrow_select(items, title=t("Matching titles"), status=t("page {page} of up to {limit}", page=page, limit=topics.MAX_PAGES),
                             multi=True, banner=_make_banner_panel(),
                             footer=t("Space select (up to {limit}) • W review • Esc back", limit=topics.MAX_WORKS),
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
            read_details(t("Choose between 1 and {limit} titles across all pages.", limit=topics.MAX_WORKS), t("Title selection"))
            continue
        queries, origins = topics.query_plan(list(selected.values()))
        review = [SelectItem(q, passive=True, description=escape(origins[q])) for q in queries]
        review += [SelectItem(t("Search these names"), "search"), SelectItem(t("Back to titles"), None)]
        pick = arrow_select(review, title=t("Review release searches"), banner=_make_banner_panel(),
                            footer=escape(t("Providers: {providers}\nUp to 2 names per title • Existing filters apply • Esc back", providers=topics.scope_label(provider))))
        if pick is None or review[pick].value != "search":
            continue
        cancel = threading.Event()
        cancelled, results = _run_cancellable(
            lambda: search_many(provider, queries, cli_filters, cancel_event=cancel, work_titles=origins),
            t("Searching selected titles (30s limit)…"), cancel=cancel)
        if cancelled:
            continue
        if results is None or isinstance(results, SearchError):
            read_details(t("Release search failed. Try again later."), t("Search unavailable"))
            continue
        provider.last_queries = queries
        from torrent_finder.state import add_history_entry
        from torrent_finder.stats import record_search
        label = "Topic discovery: " + ", ".join(t.name for t in criteria)  # i18n: ignore — persisted name; translate only when drawn
        presets = [p.name for p in provider.active_presets]
        extra = {"search_profile": provider.snapshot()} if getattr(provider, "is_combined", False) else {}
        add_history_entry(label, provider.slug, presets, queries=queries, **extra)
        record_search(provider.slug, label, presets)
        if browse_fn(provider, results, note=t("Topic discovery: {topics}. Catalog metadata identifies works; release availability varies.", topics=", ".join(topic.name for topic in criteria))) == "next":
            return "next"


def discovery_flow(provider, cli_filters, browse_fn, initial=""):
    catalogs = topics.discovery_catalogs(provider)
    while True:
        items = [SelectItem(t(c.label), c, description=escape(
            t("Needs {credentials}", credentials=", ".join(c.missing_credentials())) if c.missing_credentials() else
            t("Release providers: {providers}", providers=topics.scope_label(topics.scope_for(provider, c))))) for c in catalogs]
        items += [SelectItem(t("Discovery coverage / keyword help"), "help"), SelectItem(t("Back"), None)]
        index = arrow_select(items, title=t("Discover by topic / genre"), banner=_make_banner_panel(),
                             footer=t("Choose a catalog • Software has no topic catalog • Esc back"))
        if index is None or items[index].value is None:
            return "back"
        catalog = items[index].value
        if catalog == "help":
            read_details(t("Keywords find catalog terms, then those terms find works. Add one phrase at a time; all selected terms must match. "
                         "Anime/Manga: AniList genres and tags with at least 60% tag relevance. Movies/Series: TMDB genres and keywords. Games: IGDB genres, themes, modes and keywords. "
                         "Books: one Open Library subject. TMDB/IGDB need credentials. English catalog terms work best; arbitrary sentences are not semantic search. "
                         "Desktop/Mobile Software have no purpose catalog here; use their ordinary literal keyword search. "
                         "Combined searches use only the selected providers compatible with the chosen catalog, shown before searching. "
                         "At most 3 pages, 3 titles and 2 names per title. Catalog labels do not guarantee torrent availability or working multiplayer."),
                         t("Discovery coverage"))
            continue
        if catalog.missing_credentials():
            read_details(t("Configure {credentials} in Credentials.", credentials=", ".join(catalog.missing_credentials())), t("Catalog credentials"))
            continue
        selected = []
        while True:
            selected = _choose_topics(catalog, selected, initial)
            initial = ""
            if not selected:
                break
            if _browse_works(topics.scope_for(provider, catalog), catalog, selected, cli_filters, browse_fn) == "next":
                return "next"
