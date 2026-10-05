"""Results: release tags, the ranking reason, source counts, feedback colours and the key list."""

import io
import unittest
import warnings
from unittest.mock import patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

import readchar
from rich.console import Console
from rich.text import Text

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.providers.combined_provider import CombinedProvider
from torrent_finder.providers.game_provider import GameProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.result_details import release_tags, tag_matches
from torrent_finder.result_view import ranking_notes
from torrent_finder.search_result import SearchResult
from torrent_finder.ui import table, theme


def result(name, number=1, **extra):
    return SearchResult(name=name, info_hash=f"{number:040x}", source=extra.pop("source", "Apibay"),
                        seeders=extra.pop("seeders", 50), size=1_000_000_000, **extra)


class ReleaseTagTests(unittest.TestCase):
    def test_tags_come_from_the_release_part_of_the_name(self):
        self.assertEqual(release_tags("Dune Part Two 2024 1080p WEB-DL DDP5.1 Atmos H.264-FLUX"),
                         ["1080p", "WEB-DL", "H.264", "DDP5.1", "Atmos", "group FLUX"])
        self.assertEqual(release_tags("Dune.2024.2160p.UHD.BluRay.x265.HDR.DV.TrueHD.7.1-GRP"),
                         ["2160p", "BluRay", "HDR", "DV", "x265", "TrueHD 7.1", "group GRP"])
        self.assertEqual(release_tags("[SubsPlease] Frieren - 01 (1080p)"), ["1080p", "group SubsPlease"])

    def test_title_words_are_never_tags(self):
        self.assertEqual(release_tags("Charlotte's Web 2006 1080p BluRay x264"), ["1080p", "BluRay", "x264"])
        self.assertNotIn("CAM", release_tags("The.Cam.Girl.2020.720p.WEB.h264-GROUP"))
        self.assertEqual(release_tags("Dune - Frank Herbert (epub)"), [])

    def test_language_tags_follow_the_portuguese_rules(self):
        tags = release_tags("Dune.Parte.Dois.2024.1080p.WEB-DL.DUAL.5.1.Dublado.PT-BR")
        self.assertIn("PT-BR audio", tags)
        self.assertIn("Dual audio", tags)
        self.assertFalse(any(tag.startswith("group") for tag in tags))  # "-BR" is not a release group

    def test_a_tag_matches_the_preset_that_asks_for_it(self):
        self.assertTrue(tag_matches("1080p", ["1080p"]))
        self.assertTrue(tag_matches("x265", ["x265 / HEVC"]))
        self.assertTrue(tag_matches("PT-BR audio", ["Dublado (PT-BR)"]))
        self.assertFalse(tag_matches("720p", ["1080p"]))
        self.assertFalse(tag_matches("group FLUX", ["1080p"]))


class RankingNotesTests(unittest.TestCase):
    def setUp(self):
        self.movies = MovieProvider()
        self.movies.preferred_presets = [next(p for p in self.movies.presets if p.name == "1080p")]

    def test_title_match_and_preferences_explain_the_order(self):
        describe = ranking_notes(self.movies, ["dune part two"])
        self.assertEqual(describe(result("Dune Part Two 2024 1080p WEB-DL")),
                         ("exact title, prefers 1080p", ("1080p",)))
        self.assertEqual(describe(result("Dune Part Two Extended 2024 720p")),
                         ("title starts with the search", ()))
        self.assertEqual(describe(result("Dune 2021 720p")), ("title differs from the search", ()))

    def test_providers_ranked_by_seeders_explain_only_preferences(self):
        games = GameProvider()
        self.assertFalse(games.prefer_title_matches)
        self.assertEqual(ranking_notes(games, ["elden ring"])(result("Elden Ring-RUNE")), ("", ()))

    def test_combined_rows_use_their_own_provider(self):
        combined = CombinedProvider([MovieProvider()])
        combined.restore({})
        child = combined.children[0]
        child.preferred_presets = [next(p for p in child.presets if p.name == "4K / 2160p")]
        describe = ranking_notes(combined, ["dune"])
        row = result("Dune 2021 2160p UHD BluRay")
        row["provider_slug"] = "movies"
        reason, preferred = describe(row)
        self.assertEqual(preferred, ("4K / 2160p",))
        self.assertTrue(reason.startswith("exact title"))

    def test_saved_rows_without_a_search_give_no_title_note(self):
        describe = ranking_notes(self.movies, [])
        self.assertEqual(describe({"name": "Dune 1080p", "seeders": 3}), ("prefers 1080p", ("1080p",)))


class TableNotesTests(unittest.TestCase):
    rows = [result("Dune Part Two 2024 1080p WEB-DL DDP5.1 H.264-FLUX", 1, source="Apibay"),
            result("Dune Part Two 2024 720p HDCAM x264", 2, source="Knaben"),
            result("Dune Part Two 2024 2160p BluRay x265", 3, source="Knaben")]

    def caption(self, describe, width=100, height=30):
        screen = Console(file=io.StringIO(), width=width, height=height, color_system=None)
        with patch.object(table, "console", screen):
            built = table.build_table(self.rows, 0, 0, 3, 3, describe=describe)
        return built.caption

    def test_the_focused_row_shows_its_tags_and_why_it_ranks_there(self):
        movies = MovieProvider()
        movies.preferred_presets = [next(p for p in movies.presets if p.name == "1080p")]
        caption = self.caption(ranking_notes(movies, ["dune part two"]))
        self.assertIn("Tags: 1080p ✓ · WEB-DL · H.264 · DDP5.1 · group FLUX", caption.plain)
        self.assertIn("Ranked: exact title, prefers 1080p", caption.plain)
        ticked = next(span for span in caption.spans if caption.plain[span.start:span.end] == "1080p ✓")
        self.assertEqual(str(ticked.style), theme.GOOD)

    def test_without_notes_the_tags_still_show(self):
        caption = self.caption(None)
        self.assertIn("Tags: 1080p · WEB-DL", caption.plain)
        self.assertNotIn("Ranked:", caption.plain)

    def test_short_windows_keep_their_single_metadata_line(self):
        caption = self.caption(None, width=60, height=14)
        self.assertNotIn("Tags:", caption.plain)

    def test_sources_are_counted_in_the_view_line(self):
        self.assertEqual(table._source_counts(self.rows), "Knaben 2 · Apibay 1")
        many = [result(f"r{i}", i, source=f"S{i % 6}") for i in range(12)]
        self.assertTrue(table._source_counts(many).endswith("· +2"))


class TableInteractionTests(unittest.TestCase):
    def run_table(self, keys, **kwargs):
        screen = Console(file=io.StringIO(), width=100, height=30, color_system=None)
        frames = []
        real = table.Live.update

        def capture(live, renderable, *args, **kw):
            frames.append(renderable)
            return real(live, renderable, *args, **kw)

        with patch.object(table, "console", screen), \
             patch.object(table.Live, "update", capture), \
             patch.object(table.readchar, "readkey", side_effect=keys):
            outcome = table.interactive_select(list(TableNotesTests.rows), **kwargs)
        return outcome, frames

    def view_line(self, frame):
        return next(item.plain for item in frame.renderables if isinstance(item, Text)
                    and (item.plain.strip().startswith("Sort:") or "Bookmark" in item.plain))

    def test_the_view_line_names_sources_and_hides_an_empty_name_filter(self):
        _, frames = self.run_table([readchar.key.DOWN, readchar.key.ESC])
        line = self.view_line(frames[-1])
        self.assertIn("Sources: Knaben 2 · Apibay 1", line)
        self.assertNotIn("all names", line)

    def test_a_saved_bookmark_reads_green_and_a_failure_red(self):
        _, frames = self.run_table(["b", readchar.key.ESC], on_bookmark=lambda rows: "Bookmarked.")
        status = next(item for item in frames[-1].renderables if isinstance(item, Text) and "Bookmarked" in item.plain)
        self.assertEqual(str(status.style), theme.GOOD)

        def refuse(rows):
            raise OSError("disk full")

        _, frames = self.run_table(["b", readchar.key.ESC], on_bookmark=refuse)
        status = next(item for item in frames[-1].renderables if isinstance(item, Text) and "not saved" in item.plain)
        self.assertEqual(str(status.style), theme.BAD)

    def test_question_mark_lists_every_results_key(self):
        shown = []
        with patch("torrent_finder.ui.selector.show_keys", side_effect=lambda *a, **kw: shown.append((a, kw))):
            self.run_table(["?", readchar.key.ESC])
        (title, footer), kw = shown[0]
        self.assertIn("Enter open", footer.plain)
        self.assertIn(("0-9", "jump to a result number"), kw["extra"])
        self.assertIn(("r", "retry failed sources"), kw["extra"])


if __name__ == "__main__":
    unittest.main()
