import io
import unittest
from unittest.mock import patch

from rich.console import Console

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder import store
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.search_profiles import ProfileLibrary
from torrent_finder.ui import combined, prompts, selector, result_filters
from isolation import isolate_store


class ProfileUITests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        mocked = patch.object(store, "commit", wraps=store.commit)
        self.commit = mocked.start()
        self.addCleanup(mocked.stop)
        self.provider = CombinedProvider([AnimeProvider(), MangaProvider()])
        self.provider.snapshot()

    def choose_actions(self, actions):
        actions = iter(actions)
        def choose(items, **kwargs):
            expected = next(actions)
            if expected is None:
                return None
            return next(i for i, item in enumerate(items) if item.value == expected)
        return choose

    def test_copy_rename_edit_and_switch_commit_as_one_transaction(self):
        actions = ["profiles", ("copy", None), "profiles", ("rename", None), "sort",
                   "profiles", ("select", "default"), "save"]
        with patch.object(combined, "arrow_select", side_effect=self.choose_actions(actions)), \
             patch.object(prompts, "get_query_with_shortcut", side_effect=["Older anime", "Anime + Manga"]), \
             patch.object(combined, "choose_result_sort", return_value="newest"):
            combined.combined_filter_menu(self.provider)
        library = ProfileLibrary.load()
        self.assertEqual(library.current["name"], "Default")
        self.assertEqual(library.current["settings"]["result_sort"], "relevance")
        self.assertEqual(library.find("Anime + Manga")["settings"]["result_sort"], "newest")
        self.commit.assert_called_once()

    def test_cancel_discards_copies_renames_switches_and_sorts(self):
        before = self.provider.snapshot()
        actions = ["profiles", ("copy", None), "profiles", ("rename", None), "sort", "cancel"]
        with patch.object(combined, "arrow_select", side_effect=self.choose_actions(actions)), \
             patch.object(prompts, "get_query_with_shortcut", side_effect=["Copy", "Renamed"]), \
             patch.object(combined, "choose_result_sort", return_value="newest"):
            combined.combined_filter_menu(self.provider)
        self.assertEqual(self.provider.snapshot(), before)
        self.assertNotIn("search_profiles", store.read().get("settings", {}))
        self.commit.assert_not_called()

    def test_delete_requires_confirmation_and_outer_save(self):
        library = self.provider.profile_draft()
        added = library.create("Remove me", self.provider.snapshot())
        library.save()
        self.provider.use_profile(added)
        before = ProfileLibrary.load().data
        self.commit.reset_mock()
        for confirmed, finish in ((False, "save"), (True, "cancel"), (True, "save")):
            with self.subTest(confirmed=confirmed, finish=finish), \
                 patch.object(combined, "arrow_select", side_effect=self.choose_actions(["profiles", ("delete", None), finish])), \
                 patch.object(prompts, "confirm_prompt", return_value=confirmed):
                combined.combined_filter_menu(self.provider)
            saved = ProfileLibrary.load()
            if confirmed and finish == "save":
                self.assertEqual([e["name"] for e in saved.entries], ["Default"])
                self.assertEqual(self.provider.profile_name, "Default")
            else:
                self.assertEqual(saved.data, before)

    def test_invalid_name_shows_error_and_allows_correction(self):
        library = self.provider.profile_draft()
        rendered = []
        answers = iter(["default", "", "  New name  "])
        def input_name(*args, screen_renderer, **kwargs):
            screen = Console(file=io.StringIO(), width=60)
            screen_renderer(screen)
            rendered.append(screen.file.getvalue())
            return next(answers)
        with patch.object(prompts, "get_query_with_shortcut", side_effect=input_name):
            self.assertEqual(combined._profile_name(library), "New name")
        self.assertIn("already exists", rendered[1])
        self.assertIn("1–60", rendered[2])

    def test_solo_sort_and_preference_are_saved_together_or_cancelled(self):
        for saved in (False, True):
            provider = AnimeProvider()
            calls = []
            visits = []
            def choose(items, **kwargs):
                pref = next(item for item in items if item.label == "1080p")
                index = next(i for i, item in enumerate(items) if item.value == "sort")
                if not visits:
                    pref.toggle_state = "Prefer"
                    visits.append(True)
                    return index
                self.assertEqual(pref.toggle_state, "Prefer")
                self.assertIn("Newest", items[index].label)
                return next(i for i, item in enumerate(items) if item.value == "confirm") if saved else None
            with patch.object(prompts, "arrow_select", side_effect=choose), \
                 patch.object(result_filters, "choose_result_sort", return_value="newest"):
                prompts.filter_menu(provider, on_save=lambda: calls.append(True))
            self.assertEqual(provider.result_sort, "newest" if saved else "relevance")
            self.assertEqual([p.name for p in provider.preferred_presets], ["1080p"] if saved else [])
            self.assertEqual(provider.active_presets, [])
            self.assertEqual(calls, [True] if saved else [])

    def test_profile_and_preset_frames_fit_small_terminals(self):
        # Exercise each focused row, including contextual help and pinned actions.
        captured = []
        def capture(items, **kwargs):
            captured.append((items, kwargs))
            return None
        with patch.object(combined, "arrow_select", side_effect=capture):
            combined.combined_filter_menu(self.provider)
        with patch.object(prompts, "arrow_select", side_effect=capture):
            prompts.filter_menu(self.provider.children[0])
            prompts.filter_menu(MovieProvider())
        for width, height in ((40, 16), (60, 20), (80, 24), (120, 32)):
            for items, kwargs in captured:
                for cursor, item in enumerate(items):
                    if not item.enabled:
                        continue
                    with self.subTest(width=width, height=height, item=item.label):
                        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                        with patch.object(selector, "console", screen), patch.object(prompts, "console", screen):
                            screen.print(selector._build_panel(items, cursor, kwargs["title"], kwargs.get("multi", False), footer=kwargs["footer"]))
                        self.assertLessEqual(len(screen.file.getvalue().splitlines()), height)


if __name__ == "__main__":
    unittest.main()
