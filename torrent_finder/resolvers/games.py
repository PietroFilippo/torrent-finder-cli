"""Games creator resolver — dispatches per request.

Uses IGDB (richer data, dev/publisher split via involved_companies) when both
Twitch creds are configured, otherwise the keyless Wikidata fallback (P178
developer / P123 publisher). Keeps the developer/publisher facets **always
available** — IGDB is an optional upgrade, not a gate.

Note IGDB's company search is role-agnostic (the developer/publisher split
happens in the works step), while Wikidata's search pre-filters to companies
that actually developed/published a game.
"""

from torrent_finder import credentials
from torrent_finder.resolvers import igdb, wikidata


def _use_igdb() -> bool:
    return bool(credentials.get_credential("IGDB_CLIENT_ID")
                and credentials.get_credential("IGDB_CLIENT_SECRET"))


def developer_search(name):
    return igdb.company_search(name) if _use_igdb() else wikidata.developer_search(name)


def developer_works(entity, page=1):
    return (igdb.developer_works(entity, page) if _use_igdb()
            else wikidata.developer_works(entity, page))


def publisher_search(name):
    return igdb.company_search(name) if _use_igdb() else wikidata.publisher_search(name)


def publisher_works(entity, page=1):
    return (igdb.publisher_works(entity, page) if _use_igdb()
            else wikidata.publisher_works(entity, page))
