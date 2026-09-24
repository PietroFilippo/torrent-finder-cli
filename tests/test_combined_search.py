import threading
import time
import unittest
from unittest.mock import patch

from torrent_finder.filters import FilterConfig, FilterPreset
from torrent_finder.providers import get_provider, provider_for_result
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.providers.combined_provider import CombinedProvider, result_identity
from torrent_finder.search_errors import SearchError
from torrent_finder.search_result import SearchResult
from torrent_finder import state


def row(name, key, source="Nyaa", **extra):
    return SearchResult(name=name, info_hash=key, source=source, **extra)


class AnimeFixture(AnimeProvider):
    rows = []

    def _fetch(self, query):
        return self.rows

    def _init_engines(self):
        return [SearchEngine("Nyaa", "", self._fetch)]


class MangaFixture(BaseProvider):
    slug, name, icon, categories = "manga", "Manga", "", []
    rows = []
    presets = [FilterPreset("By Volume", FilterConfig(include_keywords=["volume"]))]

    def _fetch(self, query):
        return self.rows

    def _init_engines(self):
        return [SearchEngine("Nyaa", "", self._fetch)]


class CombinedSearchTests(unittest.TestCase):
    def setUp(self):
        self.anime, self.manga = AnimeFixture(), MangaFixture()
        self.combined = CombinedProvider([self.anime, self.manga])
        self.combined.restore({})
        self.addCleanup(setattr, AnimeFixture, "rows", [])
        self.addCleanup(setattr, MangaFixture, "rows", [])

    def test_anime_and_new_combined_profile_have_no_default_resolution(self):
        self.assertEqual(AnimeProvider().active_presets, [])
        self.anime.active_presets = [p for p in self.anime.presets if p.name == "1080p"]
        self.combined.restore({})
        self.assertEqual(self.combined.children[0].active_presets, [])
        self.assertEqual(self.anime.active_presets[0].name, "1080p")
        AnimeFixture.rows = [row("Saki 480p", "a" * 40)]
        self.assertEqual(len(self.combined.search("Saki")), 1)

    def test_provider_filters_and_engines_stay_independent(self):
        AnimeFixture.rows = [row("Saki 480p", "a" * 40), row("Saki 1080p", "b" * 40)]
        MangaFixture.rows = [row("Saki volume 1", "c" * 40), row("Saki chapter 1", "d" * 40)]
        anime, manga = self.combined.children
        anime.active_presets = [p for p in anime.presets if p.name == "1080p"]
        manga.active_presets = list(manga.presets)
        results = self.combined.search("Saki")
        self.assertEqual({r.name for r in results}, {"Saki 1080p", "Saki volume 1"})
        self.assertEqual(self.anime.active_presets, [])
        self.assertEqual(self.manga.active_presets, [])
        anime.engines[0].set_mode("off")
        self.assertEqual([r["provider_slug"] for r in self.combined.search("Saki")], ["manga"])
        self.assertEqual(self.anime.engines[0].mode, "on")

    def test_shared_rules_use_only_names_and_apply_before_deduplication(self):
        AnimeFixture.rows = [row("Saki", "a" * 40)]
        MangaFixture.rows = [row("Saki volume 1", "a" * 40), row("Other", "b" * 40, source="volume")]
        self.combined.shared_filters.include_keywords = ["volume"]
        self.assertEqual([r.name for r in self.combined.search("Saki")], ["Saki volume 1"])
        self.combined.shared_filters.exclude_keywords = ["volume"]
        self.assertEqual(self.combined.search("Saki"), [])

    def test_provider_selection_does_not_search_excluded_sources(self):
        self.combined.selected_slugs = {"anime"}
        with patch.object(MangaFixture, "_fetch", side_effect=AssertionError("excluded")) as manga:
            self.combined.search("Saki")
        manga.assert_not_called()
        self.combined.selected_slugs.clear()
        with self.assertRaisesRegex(SearchError, "No providers selected"):
            self.combined.search("Saki")

    def test_shared_rules_preserve_matching_alias_inside_one_provider(self):
        AnimeFixture.rows = [row("Saki", "a" * 40), row("Saki batch", "a" * 40)]
        self.combined.shared_filters.include_keywords = ["batch"]
        self.assertEqual([r.name for r in self.combined.search("Saki")], ["Saki batch"])

    def test_engine_modes_and_preset_queries_remain_provider_scoped(self):
        calls = []
        preset = FilterPreset("Dubbed", FilterConfig(), query_terms=("dublado",), require_engines=("Required",))
        def engines(provider):
            def engine(name, mode):
                item = SearchEngine(name, "", lambda q: calls.append((provider.slug, name, q)) or [], emergency_fallback=mode == "auto")
                item.set_mode(mode)
                return item
            return [engine("Primary", "on"), engine("Backup", "auto"), engine("Off", "off"), engine("Required", "off")]
        with patch.object(AnimeFixture, "presets", [preset]), \
             patch.object(AnimeFixture, "_init_engines", engines), \
             patch.object(MangaFixture, "_init_engines", engines):
            self.combined.restore({})
            self.combined.children[0].active_presets = [preset]
            self.combined.search("Saki")
        self.assertIn(("anime", "Required", "Saki dublado"), calls)
        self.assertIn(("anime", "Backup", "Saki"), calls)
        self.assertIn(("manga", "Backup", "Saki"), calls)
        self.assertFalse(any(name == "Off" for _, name, _ in calls))
        self.assertFalse(any(slug == "manga" and (name == "Required" or q != "Saki") for slug, name, q in calls))
        self.assertEqual(self.combined.children[0].engines[-1].mode, "off")

    def test_auth_error_preserves_other_results_and_reports_missing_login(self):
        AnimeFixture.rows = [row("Saki", "a" * 40)]
        with patch.object(MangaFixture, "_fetch", side_effect=SearchError("Madokami: not logged in")):
            results = self.combined.search("Saki")
        self.assertEqual(len(results), 1)
        self.assertEqual(results.notices, ("Madokami: not logged in",))

    def test_duplicate_torrents_keep_all_provider_and_query_origins(self):
        AnimeFixture.rows = [row("Saki", "a" * 40)]
        MangaFixture.rows = [row("Saki", "a" * 40)]
        results = self.combined.search_many(["Saki", "Saki manga"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["matched_providers"], ["anime", "manga"])
        self.assertEqual(results[0]["matched_queries"], ["Saki", "Saki manga"])
        self.assertIs(provider_for_result(results[0], self.combined), get_provider("anime"))
        self.assertNotIn("provider_slug", AnimeFixture.rows[0])

    def test_placeholder_ids_are_scoped_to_their_source(self):
        self.assertNotEqual(result_identity(row("X", "12", "RuTracker")), result_identity(row("X", "12", "Online-Fix")))
        AnimeFixture.rows = [row("X", "12", "RuTracker")]
        MangaFixture.rows = [row("X", "12", "Online-Fix")]
        self.assertEqual(len(self.combined.search("X")), 2)

    def test_shared_seed_requirement_does_not_remove_direct_downloads(self):
        AnimeFixture.rows = [row("Saki", "a" * 40, seeders=0)]
        MangaFixture.rows = [row("Saki", "madokami:/Saki", "Madokami")]
        results = self.combined.search("Saki", FilterConfig(min_seeds=10))
        self.assertEqual([r.source for r in results], ["Madokami"])

    def test_saved_combined_profile_does_not_change_solo_settings(self):
        solo = {"providers": {"anime": {"active_presets": ["1080p"]}}}
        self.combined.selected_slugs = {"manga"}
        self.combined.shared_filters.exclude_keywords = ["sample"]
        with patch.object(state.store, "_cache", solo), patch.object(state.store, "_dirty", False), \
             patch.object(state.store, "flush"):
            self.combined.save_profile()
            restored = CombinedProvider([self.anime, self.manga])
            self.assertEqual(restored.snapshot(), self.combined.snapshot())
        self.assertEqual(solo["providers"]["anime"]["active_presets"], ["1080p"])

    def test_explicit_combined_resolution_choice_survives_restore(self):
        child = self.combined.children[0]
        child.active_presets = [p for p in child.presets if p.name == "1080p"]
        saved = self.combined.snapshot()
        self.combined.restore(saved)
        self.assertEqual(self.combined.children[0].active_presets[0].name, "1080p")

    def test_history_copies_and_replays_the_combined_profile(self):
        from torrent_finder.main import _history_pick
        self.combined.selected_slugs = {"manga"}
        profile = self.combined.snapshot()
        with patch.object(state.store, "_cache", {}), patch.object(state.store, "_dirty", False):
            state.add_history_entry("Saki", "all", search_profile=profile)
            profile["selected"].clear()
            entry = state.load_history()[0]
        self.combined.selected_slugs = {"anime"}
        with patch("torrent_finder.main.get_provider", return_value=self.combined):
            _history_pick(entry)
        self.assertEqual(self.combined.selected_slugs, {"manga"})

    def test_one_request_budget_covers_multiple_providers_and_queries(self):
        lock = threading.Lock()
        active, peak = 0, 0
        def fetch(_query):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(active, peak)
            time.sleep(0.02)
            with lock:
                active -= 1
            return []
        def engines(_self):
            return [SearchEngine(str(i), "", fetch) for i in range(4)]
        with patch.object(AnimeFixture, "_init_engines", engines), \
             patch.object(MangaFixture, "_init_engines", engines), \
             patch("torrent_finder.providers.combined_provider._REQUEST_LIMIT", 2):
            self.combined.search_many(["one", "two", "three"])
        self.assertEqual(peak, 2)

    def test_cancel_prevents_queued_engine_requests(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(AnimeFixture, "_fetch") as anime, patch.object(MangaFixture, "_fetch") as manga:
            self.combined.search_many(["one", "two"], cancel_event=cancelled)
        anime.assert_not_called()
        manga.assert_not_called()
