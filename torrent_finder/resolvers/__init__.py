"""Resolver layer for 'search by creator'.

Translates a person/company name into the list of works to search for, using
external metadata APIs (AniList today; TMDB/IGDB/Jikan in later phases). The
torrent backends stay keyword-only — this package is the lookup that sits in
front of them.
"""

from torrent_finder.resolvers.types import CreatorFacet, Entity, Work

__all__ = ["CreatorFacet", "Entity", "Work"]
