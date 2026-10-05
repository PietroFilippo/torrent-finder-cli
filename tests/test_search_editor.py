"""The search editor: engine and preset states, recent searches filtered as you type."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import isolation  # noqa: F401  # redirects saved settings before anything reads them
from isolation import isolate_store
from readchar import key as K
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from torrent_finder import state
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.ui import prompts, theme

HISTORY = ["dune part two", "frieren", "Dune 2021 remux", "dune prophecy"]


def spans(text: Text) -> dict:
    return {text.plain[span.start:span.end]: str(span.style) for span in text.spans}


class StatusLineTests(unittest.TestCase):
    def test_engine_modes_read_as_states(self):
        provider = MovieProvider()
        modes = {engine.name: engine.mode for engine in provider.engines}
        line = prompts.engines_line(provider)
        self.assertTrue(line.plain.startswith("Engines  "))
        for name, mode in modes.items():
            if mode == "on":
                self.assertIn(f"{name} On", line.plain)
            elif mode == "auto":
                self.assertIn(f"{name} Auto", line.plain)
            else:
                self.assertIn(name, line.plain.split(" · ")[-1])  # the Off ones come last, together
        styles = spans(line)
        self.assertEqual(styles.get("On"), theme.GOOD)
        self.assertEqual(styles["Engines  "], theme.MUTED)
        self.assertNotIn("Apibay ", styles)  # engine names keep the normal text colour

    def test_presets_show_their_selection_word(self):
        provider = MovieProvider()
        self.assertIn("no presets", prompts.filters_line(provider).plain)
        provider.preferred_presets.append(next(p for p in provider.presets if p.name == "1080p"))
        line = prompts.filters_line(provider)
        self.assertIn("Prefer 1080p", line.plain)
        self.assertNotIn("no presets", line.plain)
        self.assertEqual(spans(line)["Prefer"], theme.state_style("prefer"))
        self.assertEqual(spans(line)["Ctrl+F"], theme.KEY)


class RecallTests(unittest.TestCase):
    def run_field(self, keys, initial=""):
        frames = []
        renderer = prompts.make_search_screen_renderer("", "", True, title="Movies & Series",
                                                       provider=MovieProvider(), recent_hints={"frieren": "2h ago"})
        real = prompts._render_query_frame

        def record(*args, **kwargs):
            frames.append(kwargs.get("recall"))
            return real(*args, **kwargs)

        screen = Console(file=io.StringIO(), width=80, height=24, color_system=None)
        with patch.object(prompts, "console", screen), \
             patch.object(prompts.sys, "stdout", io.StringIO()), \
             patch.object(prompts, "_render_query_frame", side_effect=record), \
             patch.object(prompts.readchar, "readkey", side_effect=keys):
            result = prompts.get_query_with_shortcut(prompts.PROMPT, initial=initial, history=HISTORY,
                                                     screen_renderer=renderer)
        return result, frames

    def test_matching_ignores_case_and_keeps_the_newest_first(self):
        self.assertEqual(prompts.matching_history(HISTORY, " DUNE "),
                         ["dune part two", "Dune 2021 remux", "dune prophecy"])
        self.assertEqual(prompts.matching_history(HISTORY, ""), HISTORY)

    def test_up_walks_the_searches_that_match_what_was_typed(self):
        result, frames = self.run_field(list("dune") + [K.UP, K.UP, K.ENTER])
        self.assertEqual(result, "Dune 2021 remux")
        self.assertEqual(frames[-1], ("dune", ["dune part two", "Dune 2021 remux", "dune prophecy"], 1))

    def test_down_past_the_newest_returns_to_the_typed_text(self):
        result, _ = self.run_field(list("fri") + [K.UP, K.DOWN, K.ENTER])
        self.assertEqual(result, "fri")

    def test_typing_after_a_recall_filters_by_the_new_text(self):
        result, frames = self.run_field([K.UP] + list(" x") + [K.ENTER])
        self.assertEqual(result, "dune part two x")
        self.assertEqual(frames[-1], ("dune part two x", [], -1))

    def test_nothing_matching_leaves_the_field_alone(self):
        result, _ = self.run_field(list("zzz") + [K.UP, K.ENTER])
        self.assertEqual(result, "zzz")


class RecentListFrameTests(unittest.TestCase):
    def frame(self, width, height, typed="dune", selected=-1):
        renderer = prompts.make_search_screen_renderer("", "", True, title="Movies & Series",
                                                       provider=MovieProvider(),
                                                       recent_hints={"dune part two": "2h ago"})
        recall = (typed, prompts.matching_history(HISTORY, typed), selected)
        content, row, col = prompts._render_query_frame(renderer, prompts.PROMPT, [], list(typed), len(typed),
                                                        width, height, recall=recall)
        return Text.from_ansi(content).plain.split("\n"), row

    def test_the_list_sits_under_the_field_with_its_notes(self):
        lines, row = self.frame(80, 24)
        self.assertIn("› dune", lines[row - 1])
        below = "\n".join(lines[row:])
        self.assertIn("RECENT  matching dune", below)
        self.assertRegex(below, "dune part two +2h ago")  # notes line up beside the widest search
        self.assertNotIn("frieren", below)

    def test_the_chosen_search_carries_the_cursor_bar(self):
        lines, _ = self.frame(80, 24, typed="dune", selected=2)
        self.assertTrue(any(line.strip().startswith(theme.CURSOR + " dune prophecy") for line in lines))

    def test_small_windows_drop_the_list_before_the_field_or_keys(self):
        for width, height in ((40, 8), (40, 12), (50, 16), (80, 24)):
            with self.subTest(width=width, height=height):
                lines, row = self.frame(width, height)
                self.assertLessEqual(len(lines), height)
                self.assertTrue(all(cell_len(line) <= width for line in lines))
                self.assertIn("› dune", lines[row - 1])
                self.assertIn("Esc", lines[-1])


class HistoryNotesTests(unittest.TestCase):
    def test_each_past_search_gets_its_age_and_name_count(self):
        isolate_store(self)
        state.add_history_entry("dune", "movies")
        state.add_history_entry("Frieren", "anime", queries=["Frieren", "Sousou no Frieren"])
        self.assertEqual(state.history_notes("movies"), {"dune": "just now"})
        self.assertEqual(state.history_notes("anime"), {"Frieren": "just now · 2 names"})


if __name__ == "__main__":
    unittest.main()
