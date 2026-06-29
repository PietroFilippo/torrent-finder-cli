"""Movies & Series creator resolver — dispatches per request.

Uses TMDB (richer data) when a ``TMDB_API_KEY`` is configured, otherwise the
keyless Wikidata fallback. This keeps the Movies & Series director/studio facets
**always available** — a TMDB key is an optional quality upgrade, not a gate.

The key is stable within a single creator flow (the Credentials menu isn't
reachable mid-flow), so ``search`` and ``works`` for one journey always hit the
same backend — the Entity id produced by one is consumed by the same one.
"""

from torrent_finder import credentials
from torrent_finder.resolvers import tmdb, wikidata


def _use_tmdb() -> bool:
    return bool(credentials.get_credential("TMDB_API_KEY"))


def director_search(name):
    return tmdb.person_search(name) if _use_tmdb() else wikidata.person_search(name)


def director_works(entity, page=1):
    return (tmdb.director_works(entity, page) if _use_tmdb()
            else wikidata.director_works(entity, page))


def studio_search(name):
    return tmdb.company_search(name) if _use_tmdb() else wikidata.company_search(name)


def studio_works(entity, page=1):
    return (tmdb.company_works(entity, page) if _use_tmdb()
            else wikidata.company_works(entity, page))
