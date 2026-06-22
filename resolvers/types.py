"""Shared types for the 'search by creator' resolver layer.

A *creator facet* turns a person/company name into a list of works, which the
caller then feeds into the normal provider search. Each facet is two functions:
``search_entities`` (name -> disambiguation candidates) and ``list_works``
(a chosen candidate -> the titles to search for).
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Entity:
    """A disambiguation candidate — a specific person, studio, company, etc.

    ``id`` is the resolver-native identifier (stringified) used to fetch works;
    ``detail`` is a one-line hint shown in the picker (occupation, known-for).
    """
    id: str
    name: str
    detail: str = ""


@dataclass(frozen=True)
class Work:
    """One title to search torrents for.

    ``title`` is the primary query (e.g. romaji); ``alt_titles`` are extra
    query strings (e.g. the English title) searched and merged for recall.
    Frozen + tuple so a Work is hashable and safe to dedupe.
    """
    title: str
    alt_titles: tuple = ()
    year: "int | None" = None
    subtitle: str = ""   # display hint, e.g. "2001 · MOVIE"
    role: str = ""       # raw creator role, e.g. "Director" or "Director (eps 1-12)"


@dataclass
class CreatorFacet:
    """A way to search a provider by a creator role (director, studio, …)."""
    key: str                                   # stable id, e.g. "director"
    label: str                                 # display label, e.g. "Director"
    search_entities: Callable[[str], list]     # name -> list[Entity] | None (None = service down)
    list_works: Callable[..., tuple]           # (Entity, page=1) -> (list[Work], has_more)
    note: str = ""                             # optional one-line UI hint
    icon: str = ""                             # optional emoji for the source menu
