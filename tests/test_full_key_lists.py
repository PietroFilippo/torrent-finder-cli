"""The ? list keeps full screen keys even when the footer is compact."""

import io
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import isolation  # noqa: F401
from isolation import isolate_store
from fake_downloads import FakeManager, install
from rich.console import Console
from readchar import key as K

from torrent_finder import i18n
from torrent_finder.ui import prompts, selector, table


class FullKeyListTests(unittest.TestCase):
    def setUp(self):
        isolate_store(self)
        install(self, None)

    def keys_for(self, run, width=40, height=12):
        shown = []
        screen = Console(file=io.StringIO(), width=width, height=height, legacy_windows=False)

        def show(title, footer, extra=selector._STANDARD_KEYS):
            shown.append(selector.key_pairs(footer, extra))

        with ExitStack() as stack:
            for module in (prompts, selector, table):
                stack.enter_context(patch.object(module, "console", screen))
            stack.enter_context(patch.object(selector, "_render", return_value=True))
            stack.enter_context(patch.object(selector, "show_keys", side_effect=show))
            stack.enter_context(patch.object(selector.threading, "Thread"))
            stack.enter_context(patch.object(selector.readchar, "readkey", side_effect=["?", K.ESC]))
            stack.enter_context(patch.object(table, "Live"))
            stack.enter_context(patch("sys.stdout", io.StringIO()))
            run()
        self.assertEqual(len(shown), 1)
        return shown[0]

    @staticmethod
    def named(pairs):
        return {part.strip() for key, _ in pairs for part in key.split("/")}

    def test_main_menu_keys_are_identical_in_narrow_and_wide_windows(self):
        for language in ("en", "pt-BR"):
            i18n.use(language)
            for with_downloads in (False, True):
                install(self, FakeManager() if with_downloads else None)
                run = lambda: prompts.provider_select_prompt(update_available=True)
                narrow = self.keys_for(run)
                wide = self.keys_for(run, 200, 50)
                self.assertEqual(narrow, wide)
                expected = {"↑", "↓", "Enter", "F", "H", "S", "T", "U", "Tab", "Esc", "Ctrl+C"}
                if with_downloads:
                    expected.add("D")
                self.assertTrue(expected <= self.named(narrow), narrow)

    def test_update_key_only_appears_when_available(self):
        pairs = self.keys_for(prompts.provider_select_prompt)
        self.assertNotIn("U", self.named(pairs))
        self.assertIn("T", self.named(pairs))

    def test_idle_update_adds_u_to_the_full_key_list(self):
        captured = {}
        with patch.object(prompts, "arrow_select", side_effect=lambda items, **kw: captured.update(kw)):
            prompts.provider_select_prompt(refresh_update=lambda: ({"kind": "git", "behind": 1}, "update"))
        self.assertNotIn("U", self.named(selector.key_pairs(captured["help_footer"]())))
        self.assertTrue(captured["refresh"]())
        self.assertIn("U", self.named(selector.key_pairs(captured["help_footer"]())))

    def test_quick_actions_includes_enter_and_every_jump_key(self):
        for language in ("en", "pt-BR"):
            i18n.use(language)
            pairs = self.keys_for(lambda: prompts.quick_actions_menu(update_available=True))
            self.assertTrue({"Enter", "F", "A", "H", "D", "B", "L", "E", "Q", "G", "S", "T", "U", "Esc", "Ctrl+C"}
                            <= self.named(pairs), pairs)

    def test_results_keep_every_key_and_full_action_labels_at_any_width(self):
        rows = [dict(name="Short", source="Nyaa", info_hash="a" * 40, seeders=10, leechers=1, size=1024)]
        run = lambda: table.interactive_select(rows, on_bookmark=lambda picked: "Saved")
        for language in ("en", "pt-BR"):
            i18n.use(language)
            narrow, wide = self.keys_for(run), self.keys_for(run, 200, 50)
            self.assertEqual(narrow, wide)
            self.assertTrue({"↑", "↓", "Enter", "Space", "i", "f", "b", "a", "c", "←", "→",
                             "0-9", "Home", "End", "PgUp", "PgDn", "d", "n", "r", "m", "[", "]", "Esc", "Ctrl+C"}
                            <= self.named(narrow), narrow)

    def test_selector_uses_the_dynamic_full_footer_for_help(self):
        pairs = self.keys_for(lambda: selector.arrow_select(
            [selector.SelectItem("Row")], footer="Esc back",
            help_footer=lambda: "Enter open • T tips • Esc back"))
        self.assertIn(("Enter", "open"), pairs)
        self.assertIn(("T", "tips"), pairs)
