"""Books rank the requested work first, and Knaben helps when Libgen returns other books."""

import unittest
from unittest.mock import patch

from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.result_view import book_title_score
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession


def row(name, source, n=1, seeders=0):
    return SearchResult(name=name, info_hash=f"{n:040x}" if source != "Libgen" else f"libgen:{n}",
                        source=source, seeders=seeders)


class BookTitleScoreTests(unittest.TestCase):
    def test_original_work_outranks_titles_that_contain_it(self):
        query = "Pride and Prejudice"
        cases = {  # names shaped like the audit's real Libgen / Apibay / Knaben rows
            "Pride and Prejudice — Austen, Jane [epub, English]": 3,
            "Jane Austen - Pride and Prejudice (Penguin Classics) (epub,mobi)": 3,
            "Pride and Prejudice by Jane Austen.epub": 3,
            "[английский] Jane Austen - Pride and Prejudice / Джейн Остин - Гордость и предубеждение [2021, EPUB, ENG]": 3,
            "Pride and Prejudice and Zombies — Seth Grahame-Smith [epub, English]": 2,
            "To Match Mr. Darcy: A Modern Pride and Prejudice Novella Variation — Nora Jane Crawford [epub, English]": 1,
            "Mansfield Park — Austen, Jane [epub, English]": 0,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(book_title_score(name, query), expected)

    def test_author_words_format_words_and_repeated_words(self):
        self.assertEqual(book_title_score("Dune — Herbert, Frank Patrick(Author) [fb2, English]", "Dune Frank Herbert"), 3)
        self.assertEqual(book_title_score("Dune Messiah by Frank Herbert EPUB", "Dune"), 2)
        self.assertEqual(book_title_score("Dune - Audiobook Collection 2015", "Dune audiobook"), 3)
        query = "Tomorrow and Tomorrow and Tomorrow"
        self.assertEqual(book_title_score("Tomorrow, and Tomorrow, and Tomorrow by Gabrielle Zevin EPUB", query), 3)
        self.assertEqual(book_title_score("Tomorrow and Tomorrow — Sweterlitsch, Thomas [epub, English]", query), 0)
        self.assertEqual(book_title_score("Stand by Me — King, Stephen [epub, English]", "Stand by Me"), 3)


class BooksSearchTests(unittest.TestCase):
    def search(self, provider_class, query, libgen=(), apibay=(), knaben=()):
        with patch.object(provider_class, "_search_apibay", return_value=list(apibay)), \
             patch.object(provider_class, "_search_knaben", return_value=list(knaben)), \
             patch.object(provider_class, "_search_solidtorrents", return_value=[]), \
             patch.object(BookProvider, "_search_libgen", return_value=list(libgen)):
            return SearchSession([provider_class()], [query]).run()

    def test_requested_work_comes_first_and_libgen_leads_among_equals(self):
        results = self.search(BookProvider, "Pride and Prejudice",
                              libgen=[row("A Pride and Prejudice Variation — Someone [epub, English]", "Libgen", 1),
                                      row("Pride and Prejudice — Austen, Jane [epub, English]", "Libgen", 2)],
                              apibay=[row("Jane Austen - Pride and Prejudice (epub)", "Apibay", 3, seeders=50)])
        self.assertEqual([r.name[:30] for r in results], [
            "Pride and Prejudice — Austen, ",  # exact, direct download first
            "Jane Austen - Pride and Prejud",  # exact torrent
            "A Pride and Prejudice Variatio",  # contains the title
        ])

    def test_knaben_helps_when_libgen_returns_only_other_books(self):
        zevin = row("Tomorrow, and Tomorrow, and Tomorrow by Gabrielle Zevin EPUB", "Knaben", 9, seeders=12)
        results = self.search(BookProvider, "Tomorrow and Tomorrow and Tomorrow",
                              libgen=[row("Tomorrow and Tomorrow — Sweterlitsch, Thomas [epub, English]", "Libgen", 1)],
                              knaben=[zevin])
        self.assertEqual(results[0].name, zevin.name)
        knaben = next(d for d in results.session.diagnostics if d.engine == "Knaben")
        self.assertEqual(knaben.status, "results")

    def test_knaben_stays_unneeded_when_a_matching_title_was_found(self):
        results = self.search(BookProvider, "Pride and Prejudice",
                              libgen=[row("A Pride and Prejudice Variation — Someone [epub, English]", "Libgen", 1)],
                              knaben=[row("Pride and Prejudice by Jane Austen.epub", "Knaben", 9)])
        knaben = next(d for d in results.session.diagnostics if d.engine == "Knaben")
        self.assertEqual(knaben.status, "skipped")
        self.assertIn("matching the title", knaben.message)

    def test_other_providers_keep_the_raw_row_rule(self):
        results = self.search(MovieProvider, "The Matrix",
                              apibay=[row("Completely unrelated film 2020 1080p", "Apibay", 1, seeders=5)],
                              knaben=[row("The Matrix 1999 1080p", "Knaben", 2)])
        knaben = next(d for d in results.session.diagnostics if d.engine == "Knaben")
        self.assertEqual(knaben.status, "skipped")


if __name__ == "__main__":
    unittest.main()
