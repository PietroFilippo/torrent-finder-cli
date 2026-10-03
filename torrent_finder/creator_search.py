"""Run chosen catalog works through the shared bounded search session."""

from torrent_finder.resolvers.titles import MAX_ALIASES, distinct_names
from torrent_finder.search_session import SearchSession


def fan_out(provider, works, cli_filters=None, cancel_event=None, max_workers=6):
    queries, origins = [], {}
    for work in works:
        for query in distinct_names((work.title, *work.alt_titles))[:MAX_ALIASES]:
            if query not in origins:
                queries.append(query)
                origins[query] = work.title
    return SearchSession([provider], queries, cli_filters, work_titles=origins,
                         workers=max(1, min(6, max_workers))).run(cancel_event=cancel_event)
