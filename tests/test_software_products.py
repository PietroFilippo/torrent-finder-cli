"""Desktop ranks the searched program above longer products containing its name,
searches Knaben alongside APIBay, and honours a typed platform (P05).

Names come from the 2026-10-03 audit's Knaben rows, where "Adobe Photoshop
Lightroom Classic" was the top result for "Adobe Photoshop".
"""

import unittest
from contextlib import ExitStack
from unittest.mock import patch

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from torrent_finder.providers.software_provider import SoftwareProvider
from torrent_finder.result_view import product_title_score
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import search_many


def row(name, seeders, source="Knaben", n=[0]):
    n[0] += 1
    return SearchResult(name=name, info_hash=f"{n[0]:040x}", seeders=seeders, source=source)


def search(query, knaben=None, apibay=None):
    calls = []

    def engine(name, rows):
        def run(_self, q):
            calls.append((name, q))
            return list((rows or {}).get(q, []))
        return run

    with ExitStack() as stack:
        stack.enter_context(patch.object(SoftwareProvider, "_search_knaben", engine("Knaben", knaben)))
        stack.enter_context(patch.object(SoftwareProvider, "_search_apibay", engine("Apibay", apibay)))
        return search_many(SoftwareProvider(), [query]), calls


class ProductScoreTests(unittest.TestCase):
    def test_details_after_the_name_keep_it_the_same_product(self):
        for name, query, score in (
            ("Adobe Photoshop 2024 v25.0 Final + Crack (macOS)", "Adobe Photoshop", 3),
            ("Adobe Photoshop CC 2019 v11.0.0 + Patch For Mac", "Photoshop", 3),
            ("Adobe Photoshop CS6 16.0 (Multilanguage) MacOS", "Photoshop", 3),
            ("[RUS] Adobe Photoshop for Mac 2024 v. 25.7.0", "Photoshop 2024", 3),
            ("FL Studio Producer Edition 21", "FL Studio", 3),
            ("Final Cut Pro X 10.7", "Final Cut Pro", 3),
            ("7-Zip 24.07 (x64)", "7-Zip", 3),
            ("MATLAB R2024a (x64)", "MATLAB", 3),
            # Another name word: another product, still listed below.
            ("Adobe Photoshop Lightroom Classic CC 2021 v16.4.1", "Adobe Photoshop", 1),
            ("Adobe Photoshop Elements 2024", "Photoshop", 1),
            ("[RUS] Adobe Photoshop Lightroom 2024 v. 13.0.1", "Photoshop 2024", 1),
            ("ABLETON LiVE PLUGiNS PACK (02) [dada]", "Ableton Live", 1),
            ("Microsoft Office Tab Enterprise 14", "Microsoft Office", 1),
            ("7 Days to Die", "7-Zip", 0),
            ("Adobe Photoshop 2025", "Adobe Photoshop CS6", 0),
        ):
            with self.subTest(name=name, query=query):
                self.assertEqual(product_title_score(name, query), score)


class DesktopSearchTests(unittest.TestCase):
    def test_the_searched_program_ranks_above_longer_products(self):
        knaben = {"Adobe Photoshop": [row("Adobe Photoshop Lightroom Classic CC 2021 v16.4.1", 900),
                                      row("Adobe Photoshop Elements 2024", 500),
                                      row("Adobe Photoshop CC v25.0 Multilingual (x64)", 40)]}
        results, _ = search("Adobe Photoshop", knaben)
        self.assertEqual([r.name for r in results], ["Adobe Photoshop CC v25.0 Multilingual (x64)",
                                                     "Adobe Photoshop Lightroom Classic CC 2021 v16.4.1",
                                                     "Adobe Photoshop Elements 2024"])

    def test_knaben_searches_alongside_apibay_by_default(self):
        results, calls = search("VLC", knaben={"VLC": [row("vlc-3.0.21-win64.exe", 10)]},
                                apibay={"VLC": [row("VLC media player 3.0.21", 50, "Apibay")]})
        self.assertEqual(sorted(calls), [("Apibay", "VLC"), ("Knaben", "VLC")])
        self.assertEqual(len(results), 2)
        self.assertFalse(any(d.status == "skipped" for d in results.session.diagnostics))

    def test_a_typed_platform_searches_the_name_and_lists_that_platform_first(self):
        knaben = {"Photoshop": [row("Adobe Photoshop 2024 v25.0 (x64) Multilingual", 900),
                                row("Adobe Photoshop 2024 v25.7.0 for Mac", 30)]}
        results, calls = search("Photoshop mac", knaben)
        self.assertIn(("Knaben", "Photoshop"), calls)
        self.assertEqual(results[0].name, "Adobe Photoshop 2024 v25.7.0 for Mac")
        self.assertIn("1 result(s) carry a macOS tag and are listed first; the title alone was searched too.",
                      results.notices)


if __name__ == "__main__":
    unittest.main()
