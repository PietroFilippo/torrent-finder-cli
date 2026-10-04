"""Books rank listings by the requested work's author when it is reliably known."""

import unittest
from unittest.mock import Mock, patch

from torrent_finder import creator_search
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.resolvers import openlibrary, titles
from torrent_finder.resolvers.types import Entity, Work
from torrent_finder.result_view import book_title_score
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession
import isolation  # noqa: F401  (keeps Open Library lookups off unless a test stubs them)

ECO = ("Umberto Eco",)


def libgen(title, author, n):
    name = f"{title} — {author} [epub, English]" if author else f"{title} [epub, English]"
    return SearchResult(name=name, info_hash=f"libgen:{n}", source="Libgen", extra={"lg_author": author})


class AuthorScoreTests(unittest.TestCase):
    def test_matching_author_first_clearly_different_author_last(self):
        query = "The Name of the Rose"
        self.assertEqual(book_title_score("The Name of the Rose — Eco, Umberto [epub, English]", query, ECO,
                                          "Eco, Umberto"), 4)
        self.assertEqual(book_title_score("The Name of the Rosé — Blum, Christine E [epub, English]", query, ECO,
                                          "Blum, Christine E"), 2)
        torrent = "[английский] Umberto Eco - The Name Of The Rose / Умберто Эко - Имя розы [1986, PDF]"
        self.assertEqual(book_title_score(torrent, query, ECO), 4)
        self.assertEqual(book_title_score("The Name of the Rose (Folio Society)", query, ECO), 3)
        self.assertEqual(book_title_score("The Name of the Rosé — Blum [epub, English]", query, (), "Blum"), 3)

    def test_unknown_authors_stay_neutral(self):
        shelley = ("Mary Shelley",)
        self.assertEqual(book_title_score("Frankenstein - Mary Wollstonecraft Shelley", "Frankenstein", shelley), 4)
        # A torrent name's other words aren't a reliable author: only a match counts.
        self.assertEqual(book_title_score("Frankenstein - Junji Ito Story Collection (2018)", "Frankenstein",
                                          shelley), 3)
        self.assertEqual(book_title_score("Tomorrow and Tomorrow and Tomorrow — Зевин, Габриэль [epub, Russian]",
                                          "Tomorrow and Tomorrow and Tomorrow", ("Gabrielle Zevin",),
                                          "Зевин, Габриэль"), 3)  # another script
        self.assertEqual(book_title_score("Dune [epub, English]", "Dune", ("Frank Herbert",), ""), 3)


class DominantAuthorTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(openlibrary, "_dominant_authors", {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def lookup(self, title, docs):
        with patch.object(openlibrary, "_get", return_value={"docs": docs}) as get:
            return openlibrary.dominant_author(title), get

    def test_only_a_clearly_dominant_work_names_an_author(self):
        found, _ = self.lookup("Tomorrow and Tomorrow and Tomorrow", [
            {"title": "Tomorrow, and Tomorrow, and Tomorrow", "author_name": ["Gabrielle Zevin"], "edition_count": 17},
            {"title": "Tomorrow and Tomorrow and Tomorrow", "author_name": ["Aldous Huxley"], "edition_count": 5}])
        self.assertEqual(found, ("Gabrielle Zevin",))
        found, _ = self.lookup("Metamorphosis", [
            {"title": "Metamorphosis", "author_name": ["Franz Kafka"], "edition_count": 40},
            {"title": "Metamorphosis", "author_name": ["Someone Else"], "edition_count": 30}])
        self.assertEqual(found, ())  # not dominant enough
        found, _ = self.lookup("The Name of the Rose", [
            {"title": "The Name of the Rose", "author_name": ["Lope de Vega"], "edition_count": 1}])
        self.assertEqual(found, ())  # too rare to trust

    def test_results_are_cached_but_failures_are_not(self):
        docs = [{"title": "Dune", "author_name": ["Frank Herbert"], "edition_count": 155}]
        self.assertEqual(self.lookup("Dune", docs)[0], ("Frank Herbert",))
        found, get = self.lookup("Dune", docs)
        self.assertEqual(found, ("Frank Herbert",))
        get.assert_not_called()
        with patch.object(openlibrary, "_get", return_value=None):
            self.assertEqual(openlibrary.dominant_author("Dracula"), ())
        self.assertNotIn("dracula", openlibrary._dominant_authors)


class AuthorSourcesTests(unittest.TestCase):
    def search(self, query, rows, **session):
        with patch.object(BookProvider, "_search_libgen", return_value=list(rows)), \
             patch.object(BookProvider, "_search_apibay", return_value=[]), \
             patch.object(BookProvider, "_search_knaben", return_value=[]), \
             patch.object(BookProvider, "_search_solidtorrents", return_value=[]):
            return SearchSession([BookProvider()], [query], **session).run()

    ROWS = [libgen("The Name of the Rosé", "Blum, Christine E", 1),
            libgen("The Name of the Rose", "", 2),
            libgen("The Name of the Rose", "Eco, Umberto", 3)]

    def test_plain_search_looks_up_the_author_alongside(self):
        with patch.object(BookProvider, "looks_up_authors", True), \
             patch.object(BookProvider, "lookup_authors", return_value=ECO) as lookup:
            results = self.search("The Name of the Rose", self.ROWS)
        lookup.assert_called_once_with("The Name of the Rose")
        self.assertEqual([r.get("lg_author") for r in results], ["Eco, Umberto", "", "Blum, Christine E"])

    def test_known_authors_skip_the_lookup(self):
        with patch.object(BookProvider, "looks_up_authors", True), \
             patch.object(BookProvider, "lookup_authors") as lookup:
            results = self.search("The Name of the Rose", self.ROWS, work_authors={"The Name of the Rose": ECO})
        lookup.assert_not_called()
        self.assertEqual(results[0].get("lg_author"), "Eco, Umberto")

    def test_author_search_and_identify_title_carry_authors(self):
        entity = Entity(id="OL1A", name="Umberto Eco", detail="")
        with patch.object(openlibrary, "_get", return_value={"numFound": 1, "docs": [
                {"title": "The Name of the Rose", "first_publish_year": 1980}]}):
            works, _ = openlibrary.author_works(entity)
        self.assertEqual(works[0].authors, ECO)
        with patch.object(creator_search, "SearchSession") as session:
            creator_search.fan_out(BookProvider(), works)
        self.assertEqual(session.call_args.kwargs["work_authors"], {"The Name of the Rose": ECO})

        catalog = next(c for c in titles.CATALOGS if c.key == "books")
        with patch.object(openlibrary, "_get", return_value={"numFound": 1, "docs": [
                {"key": "/works/OL1W", "title": "The Name of the Rose", "first_publish_year": 1980,
                 "author_name": ["Umberto Eco"]}]}):
            matches, _ = titles.search_titles(catalog, "The Name of the Rose")
        self.assertEqual(matches[0].work.authors, ECO)


if __name__ == "__main__":
    unittest.main()
