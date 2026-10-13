"""Additional offline category screens for the standard snapshot harness.

Run from the repository root:
    python tests/capture_i18n_categories.py categories-owned-pt pt-BR
    python scripts/ui_snapshots.py check categories-owned-pt
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import isolation  # noqa: F401 — all state and credentials are temporary
from scripts import ui_snapshots as snapshots
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.resolvers import topics
from torrent_finder.resolvers.titles import CATALOGS, TitleMatch
from torrent_finder.resolvers.types import Entity, Work
from torrent_finder.ui import combined, creator, discovery, titles
from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut


def scenarios():
    anime = AnimeProvider()
    draft = CombinedProvider([anime, MangaProvider()])
    work = Work("Fixture title", alt_titles=("Alternate fixture title",), year=2024,
                subtitle="2024 · TV", role="Director (eps 1-3)")
    match = TitleMatch("anime", "123", work, "")
    criteria = [topics.Topic("genre", "Action", "Action", "Service-provided description")]

    def matching():
        with patch.object(discovery, "_lookup", return_value=([match], True)):
            discovery._browse_works(anime, CATALOGS[0], criteria, None, lambda *_: "back")

    def shared():
        get_query_with_shortcut(PROMPT, screen_renderer=combined._shared_filter_screen("include_keywords"))

    return [
        ("combined-settings", lambda: combined.combined_filter_menu(draft)),
        ("combined-choose", lambda: combined._choose_providers(draft)),
        ("combined-configure", lambda: combined._configure_provider(draft)),
        ("combined-profiles", lambda: combined._manage_profiles(draft, draft.profile_draft())),
        ("combined-profile-name", lambda: combined._profile_name(draft.profile_draft())),
        ("combined-shared-rules", shared),
        ("discovery-catalogs", lambda: discovery.discovery_flow(anime, None, lambda *_: "back")),
        ("discovery-topics", lambda: discovery._choose_topics(CATALOGS[0], criteria)),
        ("discovery-works", matching),
        ("title-catalogs", lambda: titles.title_search_flow(anime, None, lambda *_: "back")),
        ("title-names", lambda: titles.pick_names(match)),
        ("creator-name", lambda: creator._name_input(anime, anime.creator_facets[0])),
        ("creator-entities", lambda: creator._pick_entity(
            [Entity("1", "First creator", "Service detail"), Entity("2", "Second creator")], anime.creator_facets[0])),
        ("creator-partial", lambda: creator._works_select_prompt(
            [work], Entity("1", "Fixture creator"), anime.creator_facets[0],
            has_prev=True, has_next=True, page_no=2, total_pages=3)),
    ]


if __name__ == "__main__":
    with patch.object(snapshots, "_scenarios", scenarios):
        snapshots.capture(sys.argv[1], "citrinitas:lang=" + sys.argv[2])
