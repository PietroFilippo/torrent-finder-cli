import io
import unittest
from unittest.mock import patch

import readchar
from rich.console import Console

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.creator_search import fan_out
from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.base import SearchEngine
from torrent_finder.resolvers.types import Work
from torrent_finder.result_view import result_indices
from torrent_finder.search_result import SearchResult
from torrent_finder.state import apply_provider_state, provider_snapshot
from torrent_finder.ui import prompts, table


def row(name, identity, seeds):
    return SearchResult(name=name, info_hash=identity * 40, source="Nyaa", seeders=seeds)


def preset(provider, name):
    return next(p for p in provider.presets if p.name == name)


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.provider = AnimeProvider()
        self.rows = [row("Example 480p", "a", 300), row("Example 720p", "b", 100), row("Example 1080p", "c", 1)]
        self.provider.engines = [SearchEngine("Fixture", "", lambda _: self.rows)]

    def test_prefer_ranks_matches_but_require_removes_nonmatches(self):
        self.provider.preferred_presets = [preset(self.provider, "1080p")]
        self.assertEqual([r.name for r in self.provider.search("Example")],
                         ["Example 1080p", "Example 480p", "Example 720p"])
        self.provider.active_presets, self.provider.preferred_presets = self.provider.preferred_presets, []
        self.assertEqual([r.name for r in self.provider.search("Example")], ["Example 1080p"])

    def test_unavailable_preference_retains_every_result(self):
        self.provider.preferred_presets = [preset(self.provider, "4K")]
        found = self.provider.search("Example")
        self.assertTrue(all(row.get("fetched_at") for row in found))
        self.assertEqual([{k: v for k, v in row.items() if k != "fetched_at"} for row in found],
                         [dict(row) for row in self.rows])
        self.provider.active_presets = [preset(self.provider, "4K")]
        self.assertEqual(self.provider.search("Example"), [])

    def test_title_relevance_stays_ahead_of_preferences_in_solo_combined_and_multititle_search(self):
        self.rows = [row("Example 720p", "a", 1), row("Another Example Story 1080p", "b", 100)]
        self.provider.preferred_presets = [preset(self.provider, "1080p")]
        self.assertEqual(self.provider.search("Example")[0].name, "Example 720p")
        combined = CombinedProvider([self.provider])
        combined.restore({})
        with patch.object(AnimeProvider, "_init_engines", return_value=self.provider.engines):
            self.assertEqual(combined.search("Example")[0].name, "Example 720p")
        self.assertEqual(fan_out(self.provider, [Work(title="Example")])[0].name, "Example 720p")

    def test_duplicate_alias_prefers_matching_name_without_mutating_source_rows(self):
        self.rows = [row("Example", "a", 8), row("Example 1080p", "a", 8)]
        self.provider.preferred_presets = [preset(self.provider, "1080p")]
        self.assertEqual([r.name for r in self.provider.search("Example")], ["Example 1080p"])
        self.assertEqual(self.rows[0].name, "Example")
        self.assertNotIn("preference_score", self.rows[1])

    def test_explicit_sorts_override_preference_ranking_without_changing_identity(self):
        self.provider.preferred_presets = [preset(self.provider, "1080p")]
        rows = self.provider.search("Example")
        self.assertEqual([rows[i].name for i in result_indices(rows, order="seeds")],
                         ["Example 480p", "Example 720p", "Example 1080p"])
        self.assertEqual(rows[0].info_hash, "c" * 40)

    def test_strict_brazilian_requirement_is_never_relaxed_by_resolution_preference(self):
        provider = MovieProvider()
        provider.active_presets = [preset(provider, "Dublado (PT-BR)")]
        provider.preferred_presets = [preset(provider, "1080p")]
        provider.engines = [SearchEngine("Fixture", "", lambda _: [
            row("Example 1080p Audio PT-PT", "a", 400),
            row("Example 1080p Audio English Subs PT-BR", "b", 300),
            row("Example 1080p Dual Audio", "c", 200),
            row("Example 720p Audio PT-BR", "d", 2)])]
        self.assertEqual([r.name for r in provider.search("Example")], ["Example 720p Audio PT-BR"])

    def test_required_preset_wins_if_a_snapshot_lists_both_modes(self):
        apply_provider_state(self.provider, {"active_presets": ["1080p"], "preferred_presets": ["1080p", "720p"]})
        self.assertEqual([p.name for p in self.provider.preferred_presets], ["720p"])
        self.assertEqual([r.name for r in self.provider.search("Example")], ["Example 1080p"])

    def test_legacy_presets_remain_require_and_snapshot_retains_preferences(self):
        apply_provider_state(self.provider, {"active_presets": ["1080p"]})
        self.assertEqual(self.provider.preferred_presets, [])
        self.provider.preferred_presets = [preset(self.provider, "Batch")]
        self.provider.result_sort = "newest"
        restored = AnimeProvider()
        apply_provider_state(restored, provider_snapshot(self.provider))
        self.assertIn("Require: 1080p; Prefer: Batch", restored.filter_summary())
        self.assertEqual(restored.result_sort, "newest")

    def test_preferred_search_terms_and_required_engines_are_bounded_and_not_persisted(self):
        calls = []
        shaped = FilterPreset("Tag", FilterConfig(include_keywords=["tag"]),
                              query_terms=("tag", "more", "again", "last", "extra"), require_engines=("Extra",))
        self.provider.preferred_presets = [shaped]
        self.provider.engines = [SearchEngine("Extra", "", lambda q: calls.append(q) or [row("Other", "a", 1)], enabled=False)]
        self.assertEqual([r.name for r in self.provider.search("Example")], ["Other"])
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.provider.engines[0].mode, "off")

    def test_multititle_and_creator_results_keep_preferences_and_cache_rows_unchanged(self):
        self.provider.preferred_presets = [preset(self.provider, "1080p")]
        self.provider.engines[0].search_fn = lambda q: [
            row("Example 1080p" if q == "Alt" else "Example", "a", 1),
            row("Example 720p", "b", 100)]
        rows = fan_out(self.provider, [Work(title="Example", alt_titles=("Alt",))])
        self.assertEqual([r.name for r in rows], ["Example 1080p", "Example 720p"])
        self.assertEqual(rows[0].from_work, "Example")

    def test_combined_preferences_remain_scoped_to_the_originating_provider(self):
        from torrent_finder.providers.manga_provider import MangaProvider
        provider = CombinedProvider([AnimeProvider(), MangaProvider()])
        provider.restore({})
        provider.children[0].preferred_presets = [preset(provider.children[0], "1080p")]
        with patch.object(AnimeProvider, "_init_engines", return_value=[SearchEngine("Fixture", "", lambda _: self.rows)]), \
             patch.object(MangaProvider, "_init_engines", return_value=[SearchEngine("Fixture", "", lambda _: [row("Example volume 1", "d", 500)])]):
            rows = provider.search("Example")
        self.assertEqual(rows[0].name, "Example 1080p")
        self.assertEqual(len(rows), 4)
        manga = next(r for r in rows if r["provider_slug"] == "manga")
        self.assertEqual(manga["preference_score"], 0)

    def test_table_initial_sort_returns_original_acquisition_index(self):
        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(table, "console", screen), patch.object(table.readchar, "readkey", return_value=readchar.key.ENTER):
            chosen = table.interactive_select(self.rows, initial_order="name")
        self.assertEqual(chosen, ("one", 2))

    def test_menu_bulk_controls_and_cancel_preserve_semantics(self):
        original = provider_snapshot(self.provider)
        def interact(items, **kwargs):
            preset_rows = [item for item in items if isinstance(item.value, tuple) and item.value[0] == "preset"]
            kwargs["key_actions"]["a"](0, items)
            self.assertTrue(all(item.toggle_state == "Require" for item in preset_rows))
            kwargs["key_actions"]["i"](0, items)
            self.assertTrue(all(item.toggle_state == "Off" for item in preset_rows))
            preset_rows[0].cycle_toggle()
            self.assertEqual(preset_rows[0].toggle_state, "Require")
            preset_rows[0].cycle_toggle()
            self.assertEqual(preset_rows[0].toggle_state, "Prefer")
            kwargs["key_actions"]["c"](0, items)
            self.assertTrue(all(item.toggle_state == "Off" for item in preset_rows))
            return None
        with patch.object(prompts, "arrow_select", side_effect=interact):
            prompts.filter_menu(self.provider)
        self.assertEqual(provider_snapshot(self.provider), original)


if __name__ == "__main__":
    unittest.main()
