import io
import threading
import unittest
from unittest.mock import Mock, patch

import readchar
from rich.cells import cell_len
from rich.console import Console, Group
from rich.text import Text

from torrent_finder import main
from torrent_finder.acquisition import PickOutcome
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.combined_provider import CombinedProvider, CombinedResults
from torrent_finder.ui import combined, prompts, table


class CombinedUITests(unittest.TestCase):
    def test_nested_settings_save_together_or_cancel_without_touching_solo(self):
        for finish in ("save", "cancel"):
            with self.subTest(finish=finish):
                anime, manga = AnimeProvider(), MangaProvider()
                provider = CombinedProvider([anime, manga])
                provider.restore({})
                original = provider.snapshot()
                actions = iter(["providers", "configure", "include_keywords", finish])
                nested_actions = iter([0, None])

                def choose(items, title, **kwargs):
                    if title == "Choose providers":
                        kwargs["key_actions"]["c"](0, items)
                        kwargs["key_actions"][" "](0, items)
                        return kwargs["key_actions"]["w"](0, items)
                    if title == "Provider engines and presets":
                        return next(nested_actions)
                    action = next(actions)
                    return next(i for i, item in enumerate(items) if item.value == action)

                def choose_preset(items, **kwargs):
                    for item in items:
                        if isinstance(item.value, tuple) and item.value[0] == "preset" and item.value[1].name == "1080p":
                            item.toggled = True
                    return next(i for i, item in enumerate(items) if item.value == "confirm")

                with patch.object(combined, "arrow_select", side_effect=choose), \
                     patch.object(prompts, "arrow_select", side_effect=choose_preset), \
                     patch.object(prompts, "get_query_with_shortcut", return_value="batch, dual audio"), \
                     patch("torrent_finder.state.save_state") as solo_save, \
                     patch.object(provider, "save_profile") as save:
                    prompts.filter_menu(provider)
                solo_save.assert_not_called()
                self.assertEqual(anime.active_presets, [])
                self.assertEqual(manga.active_presets, [])
                if finish == "save":
                    save.assert_called_once()
                    self.assertEqual(provider.selected_slugs, {"anime"})
                    self.assertEqual(provider.children[0].active_presets[0].name, "1080p")
                    self.assertEqual(provider.shared_filters.include_keywords, ["batch", "dual audio"])
                else:
                    save.assert_not_called()
                    self.assertEqual(provider.snapshot(), original)

    def test_mixed_results_use_their_own_download_actions_and_stats(self):
        provider = CombinedProvider([AnimeProvider(), MangaProvider()])
        rows = [dict(name="Saki", info_hash=letter * 40, source="Nyaa", provider_slug=slug)
                for letter, slug in [("a", "manga"), ("b", "anime")]]
        adapter = Mock()
        adapter.pick.return_value = PickOutcome("menu", "magnet:?xt=urn:btih:" + "a" * 40)
        with patch.object(main, "clear_screen"), \
             patch.object(main, "interactive_select", side_effect=[("one", 0), ("one", 1), None]), \
             patch.object(main.acquisition, "for_result", return_value=adapter), \
             patch.object(main, "download_method_prompt", return_value="back") as methods, \
             patch.object(main, "record_torrent_picked") as stats:
            self.assertEqual(main._browse_results(provider, rows), "back")
        self.assertEqual([call.kwargs["show_streaming"] for call in methods.call_args_list], [False, True])
        self.assertEqual([call.kwargs["show_subtitles"] for call in methods.call_args_list], [False, True])
        self.assertEqual([call.args[0] for call in stats.call_args_list], ["manga", "anime"])
        self.assertEqual([call.args[0] for call in adapter.pick.call_args_list], rows)

    def test_combined_cli_can_choose_anime_and_manga(self):
        args = main._build_parser().parse_args(["-t", "all", "--providers", "anime", "manga", "-q", "Saki"])
        self.assertEqual((args.type, args.providers, args.query), ("all", ["anime", "manga"], "Saki"))

    def test_provider_selection_requires_combined_mode_before_startup(self):
        with patch("sys.argv", ["torrent", "--providers", "anime"]), \
             patch("sys.stderr", io.StringIO()), \
             patch.object(main, "show_security_warning") as warning:
            with self.assertRaises(SystemExit) as error:
                main._main_loop()
        self.assertEqual(error.exception.code, 2)
        warning.assert_not_called()

    def test_cli_search_surfaces_partial_failures_and_saves_its_profile(self):
        provider = CombinedProvider([AnimeProvider(), MangaProvider()])
        provider.restore({})
        results = CombinedResults([dict(name="Saki", source="Nyaa", provider_slug="anime")],
                                  ["Madokami: not logged in"])
        with patch("sys.argv", ["torrent", "-y", "-t", "all", "-q", "Saki"]), \
             patch.object(main, "console") as console, \
             patch.object(main, "advise_limited_terminal"), \
             patch.object(main, "get_provider", return_value=provider), \
             patch.object(provider, "search_many", return_value=results) as search, \
             patch.object(main, "check_for_update", return_value=None), \
             patch.object(main, "consume_update_report", return_value=None), \
             patch.object(main, "start_esc_listener", return_value=threading.Event()), \
             patch.object(main, "record_search"), \
             patch("torrent_finder.state.add_history_entry") as history, \
             patch.object(main, "browse_results", return_value="next") as browse, \
             patch.object(main, "_handle_whats_next", return_value="EXIT"), \
             patch.object(main, "_goodbye"):
            main._main_loop()
        self.assertEqual(search.call_args.args[0], ["Saki"])
        self.assertEqual(browse.call_args.kwargs["note"], "Madokami: not logged in")
        self.assertEqual(history.call_args.kwargs["search_profile"], provider.snapshot())
        output = "\n".join(str(call.args[0]) for call in console.print.call_args_list)
        self.assertIn("Searching 2 providers for:", output)
        self.assertIn("Press Enter to view results so far", output)
        self.assertNotIn("Searching Search across providers", output)
        self.assertNotIn("Ctrl+F", output)

    def test_mixed_table_frame_fits_compact_windows_and_identifies_the_provider(self):
        rows = [dict(name=f"Saki volume {i}", source="Nyaa", provider_slug="manga",
                     provider_label="Manga · General", seeders=2) for i in range(40)]
        note = "Madokami: not logged in. Open Credentials to enter your login.\nRuTracker: not logged in. Open Credentials to enter your login."
        for width, height in [(40, 16), (60, 20), (80, 24), (128, 30)]:
            with self.subTest(width=width, height=height):
                screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
                with patch.object(table, "console", screen), patch.object(prompts, "console", screen):
                    count = table._visible_count(len(rows), height, width, note, False, True)
                    rendered_table = table.build_table(rows, 0, 0, count, len(rows))
                    heading = Text("Torrent Search CLI") if height < 28 else prompts._make_banner_panel()
                    screen.print(Group(heading, Text("contains: all names • sort: relevance"), table._note_preview(note), rendered_table))
                rendered = screen.file.getvalue()
                self.assertIn("Provider: Manga · General", rendered)
                self.assertIn("Esc back", rendered)
                self.assertLessEqual(len(rendered.splitlines()), height)
                self.assertTrue(all(cell_len(line) <= width for line in rendered.splitlines()))

    def test_reading_search_notices_keeps_the_selection(self):
        screen = Console(file=io.StringIO(), width=60, height=20, color_system=None)
        rows = [dict(name="Saki", source="Nyaa"), dict(name="Saki volume 1", source="Nyaa")]
        note = "Madokami: not logged in. Open Credentials to enter your login."
        with patch.object(table, "console", screen), \
             patch.object(table, "_show_search_notices") as show, \
             patch.object(table.readchar, "readkey", side_effect=[readchar.key.DOWN, "n", readchar.key.ENTER]):
            self.assertEqual(table.interactive_select(rows, note), ("one", 1))
        show.assert_called_once_with(note)
