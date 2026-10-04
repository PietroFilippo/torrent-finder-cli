"""Providers keep distinct identities on screen, listings keep theirs, and Ctrl+C in a field cancels only it."""

import io
import unittest
from unittest.mock import patch

import readchar
from rich.console import Console

from torrent_finder import acquisition, bookmarks
from torrent_finder.name_rules import NameRules
from torrent_finder.providers.combined_provider import result_identity
from torrent_finder.providers.fitgirl_provider import FitGirlProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.ui import history as history_ui, name_rules as name_rules_ui, prompts, stats as stats_ui
from isolation import isolate_store


class GeneralProviderTests(unittest.TestCase):
    """A13: Games · General and Manga · General stay separate."""

    def test_history_filter_isolates_each_general_provider(self):
        entries = [{"query": "Halo", "provider": "games"}, {"query": "Saki", "provider": "manga"}]
        self.assertIn("games", history_ui._PROVIDER_OPTIONS)
        self.assertIn("manga", history_ui._PROVIDER_OPTIONS)
        for slug, label, query in (("games", "Games · General", "Halo"), ("manga", "Manga · General", "Saki")):
            with self.subTest(slug=slug):
                self.assertEqual([e["query"] for e in history_ui._filter_by_provider(entries, slug)], [query])
                self.assertEqual(history_ui._option_label(slug), label)
        self.assertEqual(history_ui._filter_by_provider(entries, None), entries)
        self.assertEqual(history_ui._option_label(None), "All")

    def test_stats_show_both_general_counters(self):
        shown = stats_ui._by_display_name({"games": 3, "manga": 5, "removed-provider": 1})
        self.assertEqual(shown, {"Games · General": 3, "Manga · General": 5, "removed-provider": 1})

    def test_bookmarks_record_the_qualified_provider_label(self):
        isolate_store(self)
        bookmarks.save_results(GameProvider(), [dict(name="Halo", source="Apibay", info_hash="a" * 40)])
        self.assertEqual(bookmarks.entries()[0]["result"]["provider_label"], "Games · General")


class LazyMagnetIdentityTests(unittest.TestCase):
    """A15: resolving a FitGirl / RuTracker hash keeps the listing's identity."""

    def listing(self):
        return dict(name="Game", source="FitGirl", info_hash="fg:1",
                    fg_post_url="https://fitgirl.test/game", page_url="https://fitgirl.test/game")

    def pick(self, row):
        with patch("torrent_finder.fitgirl.resolve_info_hash", return_value="b" * 40), \
             patch.object(acquisition, "console", Console(file=io.StringIO())):
            return acquisition.FitGirlAcquisition().pick(row)

    def test_save_pick_save_is_one_bookmark_and_refresh_still_finds_it(self):
        isolate_store(self)
        row = self.listing()
        bookmarks.save_results(FitGirlProvider(), [row])
        self.assertEqual(self.pick(row).action, "menu")
        self.assertEqual((row["info_hash"], row["listing_hash"]), ("b" * 40, "fg:1"))
        bookmarks.save_results(FitGirlProvider(), [row])
        saved = bookmarks.entries()
        self.assertEqual(len(saved), 1)

        bookmarks.refresh(saved[0]["id"], [self.listing()])  # the same page, unresolved again
        refreshed = bookmarks.entries()[0]
        self.assertEqual(refreshed["refresh_status"], "Listing found")
        self.assertEqual(refreshed["result"]["info_hash"], "b" * 40)

    def test_resolved_listing_and_real_cross_source_hashes(self):
        row = self.listing()
        before = result_identity(row)
        self.pick(row)
        self.assertEqual(result_identity(row), before)
        self.assertEqual(result_identity({"source": "Nyaa", "info_hash": "A" * 40}),
                         result_identity({"source": "Knaben", "info_hash": "a" * 40}))


class FieldInterruptTests(unittest.TestCase):
    """A17: Ctrl+C inside a text field cancels the field, never the app."""

    def read(self, keys, **kwargs):
        with patch.object(prompts.readchar, "readkey", side_effect=keys), \
             patch.object(prompts, "console", Console(file=io.StringIO(), width=80, height=24)), \
             patch.object(prompts.sys, "stdout", io.StringIO()):
            return prompts.get_query_with_shortcut("Field: ", **kwargs)

    def test_typed_or_raised_ctrl_c_cancels_like_esc(self):
        for interrupt in ("\x03", KeyboardInterrupt()):
            with self.subTest(interrupt=interrupt):
                self.assertEqual(self.read(["a", interrupt]), "GO_BACK")
                self.assertEqual(self.read(["a", interrupt], screen_renderer=lambda target: None), "GO_BACK")

    def test_main_search_prompt_still_receives_ctrl_c(self):
        with self.assertRaises(KeyboardInterrupt):
            self.read(["a", "\x03"], propagate_interrupt=True)

    def test_nested_name_rule_field_keeps_the_draft(self):
        original = NameRules(all_words="Saki")
        choices = iter(["all_words", "phrase", "apply"])

        def choose(items, **kwargs):
            value = next(choices)
            return next(i for i, item in enumerate(items) if item.value == value)

        keys = ["x", KeyboardInterrupt(),          # All words: typed, then Ctrl+C
                "T", "e", "s", "t", readchar.key.ENTER]  # Exact phrase: applied
        with patch.object(name_rules_ui, "arrow_select", side_effect=choose), \
             patch.object(prompts.readchar, "readkey", side_effect=keys), \
             patch.object(prompts, "console", Console(file=io.StringIO(), width=80, height=24)), \
             patch.object(prompts.sys, "stdout", io.StringIO()):
            result = name_rules_ui.edit_name_rules(original)
        self.assertEqual((result.all_words, result.phrase), ("Saki", "Test"))


if __name__ == "__main__":
    unittest.main()
