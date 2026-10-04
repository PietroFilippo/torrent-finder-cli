import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.console import Console
from torrent_finder import main
from torrent_finder.ui import prompts, selector, table
from isolation import isolate_store


class GlobalActionsTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_main_menu_exposes_quick_actions_without_duplicate_bookmarks(self):
        def select(items, **kwargs):
            self.assertNotIn("__bookmarks__", [item.value for item in items])
            self.assertNotIn("b", kwargs["hotkeys"])
            self.assertNotIn("B", kwargs["hotkeys"])
            return next(i for i, item in enumerate(items) if item.value == "__actions__")
        with patch.object(prompts, "arrow_select", side_effect=select):
            self.assertEqual(prompts.provider_select_prompt(), "__actions__")

    def test_whats_next_exposes_requested_destinations(self):
        for action in ("main", "actions"):
            def select(items, **kwargs):
                self.assertNotIn("bookmarks", [item.value for item in items])
                return next(i for i, item in enumerate(items) if item.value == action)
            with patch.object(prompts, "arrow_select", side_effect=select):
                self.assertEqual(prompts.search_again_prompt(), action)

    def test_whats_next_hotkeys_route_through_the_real_selector(self):
        for key, action in (("r", "search"), ("p", "provider"), ("m", "main"),
                            ("\t", "actions"), ("q", "exit")):
            for pressed in {key, key.upper()}:
                with self.subTest(key=pressed), \
                     patch.object(selector, "console", Console(file=io.StringIO(), width=80, height=30)), \
                     patch.object(selector.sys, "stdout", io.StringIO()), \
                     patch.object(selector.readchar, "readkey", return_value=pressed):
                    self.assertEqual(prompts.search_again_prompt(), action)

    def test_whats_next_local_hotkeys_open_their_pages_and_return(self):
        targets = (("h", "torrent_finder.ui.history.history_select_prompt"),
                   ("s", "torrent_finder.ui.stats.stats_page"),
                   ("t", "torrent_finder.ui.tips_page.tips_page"),
                   ("c", "torrent_finder.ui.prompts.credentials_menu"))
        for key, target in targets:
            for pressed in (key, key.upper()):
                with self.subTest(key=pressed), patch(target, return_value=None) as page, \
                     patch.object(selector, "console", Console(file=io.StringIO(), width=40, height=16)), \
                     patch.object(selector.sys, "stdout", io.StringIO()), \
                     patch.object(selector.readchar, "readkey", side_effect=[pressed, "r"]):
                    self.assertEqual(prompts.search_again_prompt(), "search")
                    page.assert_called_once()

    def test_whats_next_history_shortcut_can_replay_an_entry(self):
        entry = {"provider": "anime", "query": "Saki"}
        with patch("torrent_finder.ui.history.history_select_prompt", return_value=entry), \
             patch.object(selector, "console", Console(file=io.StringIO(), width=80, height=30)), \
             patch.object(selector.sys, "stdout", io.StringIO()), \
             patch.object(selector.readchar, "readkey", return_value="h"):
            self.assertEqual(prompts.search_again_prompt(), ("history", entry))

    def test_whats_next_resize_drops_long_tip_and_keeps_choices_visible(self):
        output = io.StringIO()
        terminal = Console(file=output, width=100, height=32, color_system=None)

        def resize_and_render(items, **kwargs):
            terminal.width, terminal.height = 40, 16
            terminal.print(selector._build_panel(items, 0, kwargs["title"], False,
                                                 footer=kwargs["footer"]()))
            return None

        with patch.object(prompts, "console", terminal), patch.object(selector, "console", terminal), \
             patch("torrent_finder.ui.tips.random_tip", return_value="Long tip " * 30), \
             patch.object(prompts, "arrow_select", side_effect=resize_and_render):
            prompts.search_again_prompt()
        rendered = output.getvalue()
        self.assertNotIn("Long tip", rendered)
        self.assertIn("Usage stats", rendered)
        self.assertLessEqual(len(rendered.splitlines()), 15)

    def test_main_option_clears_provider(self):
        with patch.object(main, "search_again_prompt", return_value="main"):
            self.assertEqual(main._handle_whats_next(object()), (None, None, None, None))

    def test_global_filters_choose_scope_each_time(self):
        provider = SimpleNamespace(name="Anime")
        with patch.object(prompts, "quick_actions_menu", side_effect=["filter", "filter", None]), \
             patch.object(prompts, "action_provider_prompt", side_effect=[None, provider]) as choose, \
             patch.object(main, "filter_menu") as filters:
            main._quick_actions_flow()
        self.assertEqual(choose.call_count, 2)
        filters.assert_called_once_with(provider)

    def test_provider_filters_never_prompt_for_another_provider(self):
        provider = SimpleNamespace(name="Anime")
        with patch.object(prompts, "quick_actions_menu", side_effect=["filter", None]) as menu, \
             patch.object(prompts, "action_provider_prompt") as choose, \
             patch.object(main, "filter_menu") as filters:
            main._quick_actions_flow(provider)
        choose.assert_not_called()
        filters.assert_called_once_with(provider)
        self.assertIs(menu.call_args.kwargs["provider"], provider)

    def test_general_titles_and_discovery_select_provider(self):
        provider = SimpleNamespace(name="Anime")
        for action, target in (("titles", "torrent_finder.ui.titles.title_search_flow"),
                               ("discover", "torrent_finder.ui.discovery.discovery_flow")):
            with patch.object(prompts, "quick_actions_menu", side_effect=[action, None]), \
                 patch.object(prompts, "action_provider_prompt", return_value=provider), \
                 patch(target, return_value="back") as flow:
                main._quick_actions_flow()
            self.assertIs(flow.call_args.args[0], provider)

    def test_whats_next_actions_are_global_even_with_current_provider(self):
        with patch.object(main, "search_again_prompt", side_effect=["actions", "search"]), \
             patch.object(main, "_quick_actions_flow", return_value=None) as flow, \
             patch.object(main, "clear_screen"):
            main._handle_whats_next("current")
        self.assertNotIn("provider", flow.call_args.kwargs)
        self.assertEqual(flow.call_args.args, ())

    def test_bookmarks_return_to_whats_next(self):
        with patch.object(main, "search_again_prompt", side_effect=["actions", "search"]), \
             patch.object(prompts, "quick_actions_menu", side_effect=["bookmarks", None]), \
             patch.object(main, "_bookmarks_flow") as bookmarks, patch.object(main, "clear_screen"):
            self.assertEqual(main._handle_whats_next("current"), (None, "current", None, None))
        bookmarks.assert_called_once()

    def test_saved_search_replays_its_names_from_global_bookmarks(self):
        provider = SimpleNamespace(slug="anime", name="Anime", active_presets=[])
        entry = {"kind": "search", "queries": ["Saki", "咲-Saki-"]}
        with patch("torrent_finder.ui.bookmarks.bookmark_menu", side_effect=[("open", entry), None]), \
             patch("torrent_finder.bookmarks.search_provider", return_value=provider), \
             patch("torrent_finder.ui.creator._run_cancellable", side_effect=lambda fn, *a, **k: (False, fn())), \
             patch("torrent_finder.search_session.search_many", return_value=[]) as search, \
             patch("torrent_finder.state.add_history_entry"), patch.object(main, "record_search"), \
             patch.object(main, "browse_results") as browse:
            main._bookmarks_flow()
        self.assertEqual(search.call_args.args[1], entry["queries"])
        self.assertEqual(provider.last_queries, entry["queries"])
        browse.assert_called_once_with(provider, [])

    def test_import_updates_detached_provider_scope_in_place(self):
        provider = SimpleNamespace(name="Detached", is_combined=True, use_profile=Mock())
        with patch.object(prompts, "quick_actions_menu", side_effect=["backup", None]), \
             patch("torrent_finder.ui.backup.backup_menu", return_value=True), \
             patch("torrent_finder.state.reload_state"), \
             patch("torrent_finder.search_profiles.ProfileLibrary.load", return_value=SimpleNamespace(current={"id": "new"})), \
             patch.object(main, "get_provider", return_value=Mock()):
            main._quick_actions_flow(provider)
        provider.use_profile.assert_called_once_with({"id": "new"})

    def test_expanded_details_have_no_inverted_background(self):
        result = {"name": "[Nozomi] Saki (720p Complete BD)", "info_hash": "a" * 40, "source": "Nyaa",
                  "provider_slug": "anime", "provider_label": "Anime", "size": 1000, "seeders": 41, "leechers": 2}
        for width in (40, 120):
            output = Console(file=io.StringIO(), width=width, height=30, force_terminal=True)
            with patch.object(table, "console", output):
                rendered = table.build_table([result], 0, 0, 1, 1, expanded=True)
                segments = list(output.render(rendered))
            self.assertTrue(any("Details" in seg.text for seg in segments))
            self.assertFalse(any(seg.style and seg.style.reverse for seg in segments))
            self.assertTrue(any(">> 0" in seg.text for seg in segments))


if __name__ == "__main__":
    unittest.main()
