"""Search progress: one line per provider with each engine's state and its results."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import requests
from rich.cells import cell_len
from rich.console import Console

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.providers.combined_provider import EngineProgress, ProviderProgress, SearchProgress
from torrent_finder.search_diagnostics import Diagnostic
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession, _engine_status
from torrent_finder.ui import search_progress, theme


def row(number):
    return SearchResult(name=f"Saki {number}", info_hash=f"{number:040x}", source="Nyaa")


class Fixture(BaseProvider):
    name, slug, icon, categories = "Fixture", "anime", "", []

    def __init__(self, slug, *engines):
        self.slug = slug
        super().__init__()
        self.engines = list(engines)

    def _init_engines(self):
        return []


def diagnostic(status, kept=0):
    return Diagnostic("Anime", "Nyaa", "saki", 0, status, kept=kept)


class EngineStatusTests(unittest.TestCase):
    def test_one_status_per_engine_from_all_its_attempts(self):
        self.assertEqual(_engine_status([diagnostic("results", 3), diagnostic("pending")]), "searching")
        self.assertEqual(_engine_status([diagnostic("empty"), diagnostic("results", 2)]), "results")
        self.assertEqual(_engine_status([diagnostic("timeout"), diagnostic("empty")]), "timeout")
        self.assertEqual(_engine_status([diagnostic("skipped")]), "skipped")


class ProviderProgressTests(unittest.TestCase):
    def test_each_provider_reports_its_state_engines_and_results(self):
        good = Fixture("anime", SearchEngine("Nyaa", "", lambda q: [row(1), row(2)]),
                       SearchEngine("Knaben", "", lambda q: [row(2)]))
        failing = Fixture("manga", SearchEngine("Nyaa", "", lambda q: (_ for _ in ()).throw(requests.Timeout())),
                          SearchEngine("Off", "", lambda q: [], enabled=False))
        seen = []
        SearchSession([good, failing], ["saki"], combined=True).run(on_progress=seen.append)
        final = seen[-1].providers
        self.assertEqual([line.label for line in final], ["Fixture", "Manga · General"])
        anime, manga = final
        self.assertEqual((anime.state, anime.results), ("done", 2))  # distinct rows, not 2 + 1
        self.assertEqual([(e.name, e.status, e.kept) for e in anime.engines],
                         [("Nyaa", "results", 2), ("Knaben", "results", 1)])
        self.assertEqual((manga.state, manga.results), ("failed", 0))
        self.assertEqual([(e.name, e.status) for e in manga.engines], [("Nyaa", "timeout"), ("Off", "off")])
        self.assertEqual(seen[0].providers[0].state, "running")  # published before any engine answered


class ProgressFrameTests(unittest.TestCase):
    def progress(self, count=3):
        lines = [ProviderProgress("Movies & Series", "done", 28, (EngineProgress("Apibay", "results", 20),
                                                                   EngineProgress("YTS", "off"))),
                 ProviderProgress("Anime", "running", 0, (EngineProgress("Nyaa", "searching"),
                                                          EngineProgress("Knaben", "auto"))),
                 ProviderProgress("Manga · General", "failed", 0, (EngineProgress("Knaben", "timeout"),
                                                                   EngineProgress("Nyaa", "blocked")))]
        lines += [ProviderProgress(f"Provider {i}", "running", 0, ()) for i in range(count - 3)]
        return SearchProgress(1, count, 28, ("Anime",), tuple(lines))

    def frame(self, progress, width, height):
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(search_progress, "console", screen):
            frame = search_progress.progress_frame("Search across providers › dune",
                                                   "Searching 3 providers for: dune",
                                                   ["Results appear when the search finishes or after 30 seconds."],
                                                   progress, 4.2, "Contacting providers…")
        screen.print(frame)
        return frame, screen.file.getvalue().rstrip("\n").split("\n")

    def test_lines_name_engine_states_and_results(self):
        frame, lines = self.frame(self.progress(), 100, 30)
        text = "\n".join(lines)
        movies = next(line for line in lines if "Movies & Series" in line)
        self.assertIn(theme.CHECK, movies)
        self.assertIn("Apibay 20", movies)
        self.assertNotIn("YTS", movies)  # Off engines are not listed
        self.assertTrue(movies.rstrip().endswith("28 results"))
        self.assertIn("Nyaa searching · Knaben auto, if needed", text)
        manga = next(line for line in lines if "Manga" in line)
        self.assertIn("×", manga)
        self.assertIn("Knaben timed out · Nyaa blocked", manga)
        self.assertTrue(manga.rstrip().endswith("failed"))
        self.assertNotIn("Waiting:", text)  # the provider lines say it already
        manga_line = next(r for r in frame.renderables if hasattr(r, "plain") and "Manga" in r.plain)
        styles = {manga_line.plain[s.start:s.end]: str(s.style) for s in manga_line.spans}
        self.assertEqual(styles["timed out"], theme.WARN)
        self.assertEqual(styles["blocked"], theme.BAD)

    def test_long_provider_lists_are_summed_up_to_fit(self):
        for width, height in ((40, 12), (50, 16), (80, 24)):
            with self.subTest(width=width, height=height):
                _, lines = self.frame(self.progress(count=14), width, height)
                text = "\n".join(lines)
                self.assertLessEqual(len(lines), height)
                self.assertTrue(all(cell_len(line) <= width for line in lines))
                self.assertIn("providers finished", text)
                self.assertIn("Esc cancel", text)
                if "Provider 10" not in text:  # what does not fit is summed up, never dropped silently
                    self.assertRegex(text, r"\+\d+ more providers · \d+ searching")


if __name__ == "__main__":
    unittest.main()
