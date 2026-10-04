"""Anime torrent provider — searches Nyaa by default, with optional Apibay/SolidTorrents."""

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.resolvers import CreatorFacet, anilist
from torrent_finder.language_tags import has_brazilian_audio, has_brazilian_subtitles


class AnimeProvider(BaseProvider):
    name = "Anime"
    slug = "anime"
    icon = "🍙"
    categories = [201, 205, 207, 208]  # Movies, TV, HD Movies, HD TV
    knaben_categories = (6_000_000,)  # Anime parent category
    solidtorrents_category = "Anime"
    nyaa_category = "1_2"  # Anime - English-translated
    nyaa_categories = {"1_2": "English-translated", "1_3": "Non-English-translated",
                       "1_4": "Raw", "1_0": "All Anime (including music videos)"}
    prefer_title_matches = True
    nyaa_title_discovery = True

    supports_subtitles = True
    supports_episode_picker = True

    presets = [
        FilterPreset("PT-BR audio tags", FilterConfig(name_predicate=has_brazilian_audio),
                     description="Filename evidence only. Not PT-PT or subtitle tags. Choose an appropriate Nyaa category separately."),
        FilterPreset("PT-BR subtitle tags", FilterConfig(name_predicate=has_brazilian_subtitles),
                     description="Explicit Brazilian subtitle tags in the name; generic Portuguese does not qualify. Tracks are not verified."),
        FilterPreset("720p", FilterConfig(quality=["720p"])),
        FilterPreset("1080p", FilterConfig(quality=["1080p"])),
        FilterPreset("4K", FilterConfig(quality=["2160p", "4k"])),
        FilterPreset("Dual Audio", FilterConfig(include_keywords=["dual audio"])),
        FilterPreset("Subbed", FilterConfig(include_keywords=["sub"])),
        FilterPreset("Batch", FilterConfig(include_keywords=["batch"])),
        FilterPreset("Trusted Uploaders", FilterConfig(include_keywords=[
            "subsplease", "erai-raws", "erai", "horriblesubs",
            "judas", "toonshub", "commie", "mtbb",
        ])),
    ]

    # Search by creator (Tab → Search by creator). AniList resolves the person/
    # studio to a filmography; each picked title is then searched on Nyaa.
    creator_facets = [
        CreatorFacet(
            key="director", label="Director", icon="🎬",
            search_entities=anilist.staff_search,
            list_works=anilist.director_works,
            note="Find a director's anime via AniList, then search each title.",
        ),
        CreatorFacet(
            key="studio", label="Studio", icon="🏢",
            search_entities=anilist.studio_search,
            list_works=anilist.studio_works,
            note="Find a studio's anime via AniList, then search each title.",
        ),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Nyaa on, category-scoped Knaben auto, other public engines off."""
        return [
            SearchEngine("Nyaa", "🍙", self._search_nyaa, enabled=True),
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,
                enabled=False, emergency_fallback=True,
            ),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=False),
            SearchEngine(
                "SolidTorrents", "🔗", self._search_solidtorrents,
                enabled=False,
            ),
        ]
