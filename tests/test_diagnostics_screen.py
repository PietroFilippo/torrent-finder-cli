"""Search diagnostics: sections, states in their colours with their evidence, the header status."""

import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from rich.text import Text

from torrent_finder.search_diagnostics import Diagnostic
from torrent_finder.ui import search_diagnostics as screen, theme


def session(queries=("dune part two",)):
    diagnostics = [Diagnostic("Movies & Series", name, queries[0], 0, status, raw=raw, kept=kept, seconds=secs)
                   for name, status, raw, kept, secs in (("Apibay", "results", 28, 20, 0.9),
                                                         ("Knaben", "timeout", 0, 0, 30.0),
                                                         ("YTS", "blocked", 0, 0, 1.2),
                                                         ("SolidTorrents", "off", 0, 0, 0))]
    return SimpleNamespace(
        can_retry=True, can_load_more=True, queries=list(queries), diagnostics=diagnostics,
        page_status=lambda: ["Movies & Series / Apibay · dune part two: next page: 2",
                             "Movies & Series / Knaben · dune part two: page incomplete; retry failed sources first"])


class DiagnosticsScreenTests(unittest.TestCase):
    def capture(self, current=None):
        captured = {}

        def select(items, **kwargs):
            captured.update(kwargs, items=items)
            return None

        with patch.object(screen, "arrow_select", side_effect=select):
            screen.diagnostics_menu(current or session())
        return captured

    def test_rows_come_in_sections(self):
        captured = self.capture()
        sections = [item.label for item in captured["items"] if item.value == "section_header"]
        self.assertEqual(sections, ["Actions", "Sources", "Pages"])
        retry = next(item for item in captured["items"] if item.value == "retry")
        self.assertEqual(retry.hint, "Knaben")  # blocked sources are not retryable
        more = next(item for item in captured["items"] if item.value == "more")
        self.assertEqual(more.hint, "1 source with more pages")

    def test_sources_show_their_state_in_colour_and_what_backs_it(self):
        items = self.capture()["items"]
        rows = {item.label.plain: item.hint for item in items if isinstance(item.value, Diagnostic)}
        self.assertEqual(rows["Movies & Series · Apibay"].plain, "results    20 of 28 kept · 0.9 s")
        self.assertEqual(rows["Movies & Series · Knaben"].plain, "timed out  30.0 s · retryable")
        self.assertEqual(rows["Movies & Series · YTS"].plain, "blocked    1.2 s · not retryable")
        self.assertEqual(rows["Movies & Series · SolidTorrents"].plain.strip(), "off")
        for label, style in (("Apibay", theme.GOOD), ("Knaben", theme.WARN), ("YTS", theme.BAD)):
            hint = rows[f"Movies & Series · {label}"]
            self.assertEqual(str(hint.spans[0].style), style)

    def test_the_header_names_the_search_and_how_many_attempts_failed(self):
        captured = self.capture()
        self.assertEqual(Text.from_markup(captured["title"]).plain, "Search diagnostics › dune part two")
        self.assertEqual(Text.from_markup(captured["status"]).plain, "2 of 3 failed")
        calm = session()
        calm.diagnostics = calm.diagnostics[:1]
        self.assertEqual(screen.diagnostics_status(calm), "1 source answered")

    def test_pages_read_in_a_few_words_and_keep_the_full_status(self):
        items = self.capture()["items"]
        pages = [item for item in items if isinstance(item.value, tuple) and item.value[0] == "pages"]
        self.assertEqual([(p.label.plain, p.hint) for p in pages],
                         [("Movies & Series · Apibay", "next page 2"), ("Movies & Series · Knaben", "retry first")])
        self.assertIn("page incomplete; retry failed sources first", pages[1].description)

    def test_several_names_show_which_name_each_row_searched(self):
        items = self.capture(session(("dune part two", "dune")))["items"]
        labels = [item.label.plain for item in items if isinstance(item.value, Diagnostic)]
        self.assertIn("Movies & Series · Apibay · dune part two", labels)


if __name__ == "__main__":
    unittest.main()
