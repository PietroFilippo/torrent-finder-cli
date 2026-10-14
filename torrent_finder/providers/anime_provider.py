"""Anime torrent provider — searches Nyaa by default, with optional Apibay/SolidTorrents."""

# i18n: converted
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.i18n import N_
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.resolvers import CreatorFacet, anilist
from torrent_finder.language_tags import has_brazilian_audio, has_brazilian_subtitles


class AnimeProvider(BaseProvider):
    name = N_("Anime")
    slug = "anime"
    icon = "🍙"
    categories = [201, 205, 207, 208]  # Movies, TV, HD Movies, HD TV
    knaben_categories = (6_000_000,)  # Anime parent category
    solidtorrents_category = "Anime"  # i18n: ignore — service/engine identity, including external category values
    nyaa_category = "1_2"  # Anime - English-translated
    nyaa_categories = {"1_2": N_("English-translated"), "1_3": N_("Non-English-translated"),
                       "1_4": N_("Raw"), "1_0": N_("All Anime (including music videos)")}
    prefer_title_matches = True
    nyaa_title_discovery = True
    # A title that matches nothing is retried under AniList's names, like Manga.
    looks_up_aliases = True
    alias_catalog = "anime"

    supports_subtitles = True
    supports_episode_picker = True

    presets = [
        FilterPreset(N_("PT-BR audio tags"), FilterConfig(name_predicate=has_brazilian_audio),
                     description=N_("Filename evidence only. Not PT-PT or subtitle tags. Choose an appropriate Nyaa category separately.")),
        FilterPreset(N_("PT-BR subtitle tags"), FilterConfig(name_predicate=has_brazilian_subtitles),
                     description=N_("Explicit Brazilian subtitle tags in the name; generic Portuguese does not qualify. Tracks are not verified.")),
        FilterPreset(N_("720p"), FilterConfig(quality=["720p"])),
        FilterPreset(N_("1080p"), FilterConfig(quality=["1080p"])),
        FilterPreset(N_("4K"), FilterConfig(quality=["2160p", "4k"])),
        FilterPreset(N_("Dual Audio"), FilterConfig(include_keywords=["dual audio"])),  # i18n: ignore — literal service or release-name match data
        FilterPreset(N_("Subbed"), FilterConfig(include_keywords=["sub"])),
        FilterPreset(N_("Batch"), FilterConfig(include_keywords=["batch"])),
        FilterPreset(N_("Trusted Uploaders"), FilterConfig(include_keywords=[
            "subsplease", "erai-raws", "erai", "horriblesubs",
            "judas", "toonshub", "commie", "mtbb",
        ])),
    ]

    # Search by creator (Tab → Search by creator). AniList resolves the person/
    # studio to a filmography; each picked title is then searched on Nyaa.
    creator_facets = [
        CreatorFacet(
            key="director", label=N_("Director"), icon="🎬",
            search_entities=anilist.staff_search,
            list_works=anilist.director_works,
            note=N_("Find a director's anime via AniList, then search each title."),
        ),
        CreatorFacet(
            key="studio", label=N_("Studio"), icon="🏢",
            search_entities=anilist.studio_search,
            list_works=anilist.studio_works,
            note=N_("Find a studio's anime via AniList, then search each title."),
        ),
    ]

    def _init_engines(self) -> list[SearchEngine]:
        """Nyaa and category-scoped Knaben on, other public engines off."""
        return [
            SearchEngine("Nyaa", "🍙", self._search_nyaa, enabled=True),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine(
                "Knaben", "🧭", self._search_knaben,  # i18n: ignore — service/engine identity, including external category values
                enabled=True, emergency_fallback=True,
            ),
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=False),  # i18n: ignore — service/engine identity, including external category values
            SearchEngine(
                "SolidTorrents", "🔗", self._search_solidtorrents,  # i18n: ignore — service/engine identity, including external category values
                enabled=False,
            ),
        ]
