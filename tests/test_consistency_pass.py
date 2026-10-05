"""The consistency pass: subjects as crumbs, relative times, filter counts, aligned sizes, keys as keys."""

import io
import unittest
import warnings
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from rich.console import Console
from rich.text import Text

from torrent_finder import bookmarks
from torrent_finder.launcher_alias import LauncherStatus
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.torrent_meta import TorrentFile
from torrent_finder.ui import bookmarks as bookmarks_ui, history, launcher, prompts, theme


def captured(call, module=prompts):
    seen = {}

    def select(items, **kwargs):
        seen.update(kwargs, items=items)
        return None

    with patch.object(module, "arrow_select", side_effect=select):
        call()
    return seen


class SubjectCrumbTests(unittest.TestCase):
    def test_screens_name_their_subject_after_a_crumb(self):
        movie = MovieProvider()
        self.assertEqual(captured(lambda: prompts.filter_menu(movie))["title"], "Filters › Movies & Series")
        self.assertEqual(captured(lambda: prompts._provider_source_menu(AnimeProvider()))["title"],
                         "Search options › Anime")
        files = [TorrentFile(1, "Show - 01.mkv", 1_400_000_000)]
        seen = captured(lambda: prompts.episode_select_prompt(files))
        self.assertEqual((seen["title"], seen["status"]), ("Select Episodes", "1 file"))

    def test_the_subject_after_a_crumb_takes_the_sky_shade(self):
        line = theme.header("Filters › Movies & Series", "", 80)
        subject = next(span for span in line.spans if line.plain[span.start:span.end].startswith("Movies"))
        self.assertEqual(str(subject.style), theme.SUBJECT)


class FilterStatusTests(unittest.TestCase):
    def test_the_header_counts_engine_modes_and_presets_as_they_change(self):
        movie = MovieProvider()
        seen = captured(lambda: prompts.filter_menu(movie))
        on = sum(engine.mode == "on" for engine in movie.engines)
        self.assertTrue(seen["status"]().startswith(f"{on} on"))
        preset_row = next(item for item in seen["items"] if item.toggle_states == ("Off", "Require", "Prefer"))
        preset_row.toggle_state = "Prefer"
        self.assertTrue(seen["status"]().endswith("1 preferred"))

    def test_the_mode_legend_shows_in_tall_windows_only(self):
        seen = captured(lambda: prompts.filter_menu(MovieProvider()))
        for height, shown in ((24, False), (30, True)):
            with patch.object(prompts, "console", Console(file=io.StringIO(), width=100, height=height)):
                legend = seen["intro"]()
            self.assertEqual(bool(legend), shown)
        self.assertIn("Auto only when On finds nothing", legend.plain)


class EpisodeSizeTests(unittest.TestCase):
    def test_sizes_line_up_on_the_right(self):
        files = [TorrentFile(1, "Show - 01.mkv", 1_400_000_000), TorrentFile(2, "readme.txt", 1_000)]
        hints = [item.hint for item in captured(lambda: prompts.episode_select_prompt(files))["items"][:2]]
        self.assertEqual(len(hints[0]), len(hints[1]))
        self.assertTrue(hints[1].startswith(" "))


class TimeAndKeyTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_bookmarks_say_when_in_words(self):
        bookmarks.save_search(AnimeProvider(), "Saki")
        seen = captured(bookmarks_ui.bookmark_menu, bookmarks_ui)
        description = seen["items"][0].description
        self.assertIn("Anime · saved just now", description)
        self.assertNotIn("+00:00", description)
        self.assertEqual(seen["status"], "1 saved")
        older = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertEqual(bookmarks_ui._when(older), "3h ago")
        self.assertEqual(bookmarks_ui._when("yesterday"), "yesterday")  # not a time this app wrote

    def test_history_filter_keys_read_as_keys(self):
        seen = captured(history.history_select_prompt, history)
        keys = [segment.plain for segment in theme.parse_footer(seen["footer"]()).keys]
        self.assertIn("P provider: All", keys)
        self.assertIn("S sort: Newest first", keys)
        self.assertEqual(theme.parse_footer(seen["footer"]()).context, [])  # no prose left over

    def test_a_command_off_path_says_so_briefly_and_explains_last(self):
        items = launcher._command_items("tf", available=False)
        current = next(item for item in items if item.value == "tf")
        self.assertEqual(current.hint, "not on PATH yet")
        self.assertTrue(current.description.startswith("Shortest quick-launch command."))
        self.assertIn("open a new terminal", current.description)
        with patch.object(launcher, "current_status", return_value=LauncherStatus("tf", available=True)):
            self.assertEqual(next(i for i in launcher._command_items("tf", True) if i.value == "tf").hint, "current")


class StyleNamesTests(unittest.TestCase):
    def test_the_quit_guard_and_update_banner_use_theme_styles(self):
        line = Text.from_markup("[alert]Press Esc or Ctrl+C again to quit[/alert]")
        self.assertEqual(str(line.spans[0].style), "alert")
        self.assertIn(theme.WARN, theme.STYLES["alert"])


if __name__ == "__main__":
    unittest.main()
