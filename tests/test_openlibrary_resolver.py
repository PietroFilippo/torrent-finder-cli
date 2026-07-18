import unittest
import warnings
from unittest.mock import Mock, patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder.providers import creator_facet_choices
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.resolvers import openlibrary
from torrent_finder.resolvers.types import Entity


def _response(payload) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


class AuthorSearchTests(unittest.TestCase):
    def test_maps_docs_to_entities(self):
        payload = {
            "numFound": 2,
            "docs": [
                {"key": "OL26320A", "name": "J.R.R. Tolkien",
                 "top_work": "The Hobbit", "work_count": 355},
                {"key": "OL2623360A", "name": "Christopher Tolkien",
                 "top_work": "The Silmarillion", "work_count": 41},
            ],
        }
        with patch.object(openlibrary.requests, "get", return_value=_response(payload)):
            entities = openlibrary.author_search("tolkien")

        self.assertEqual(len(entities), 2)
        self.assertEqual(entities[0].id, "OL26320A")
        self.assertEqual(entities[0].name, "J.R.R. Tolkien")
        self.assertIn("The Hobbit", entities[0].detail)
        self.assertIn("355 works", entities[0].detail)

    def test_network_failure_returns_none_not_empty(self):
        import requests as requests_mod

        with patch.object(
            openlibrary.requests, "get",
            side_effect=requests_mod.ConnectionError("down"),
        ):
            self.assertIsNone(openlibrary.author_search("tolkien"))


class AuthorWorksTests(unittest.TestCase):
    def _payload(self, titles, num_found):
        return {
            "numFound": num_found,
            "docs": [
                {"title": t, "first_publish_year": 1950 + i}
                for i, t in enumerate(titles)
            ],
        }

    def test_maps_docs_to_works_with_pagination(self):
        payload = self._payload(["The Hobbit", "The Silmarillion"], num_found=300)
        with patch.object(
            openlibrary.requests, "get", return_value=_response(payload)
        ) as get:
            works, has_more = openlibrary.author_works(
                Entity(id="OL26320A", name="J.R.R. Tolkien"), page=2
            )

        self.assertEqual([w.title for w in works], ["The Hobbit", "The Silmarillion"])
        self.assertEqual(works[0].year, 1950)
        self.assertTrue(has_more)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["offset"], 50)  # page 2
        self.assertEqual(params["sort"], "editions")

    def test_last_page_reports_no_more(self):
        payload = self._payload(["The Hobbit"], num_found=1)
        with patch.object(openlibrary.requests, "get", return_value=_response(payload)):
            works, has_more = openlibrary.author_works(
                Entity(id="OL26320A", name="J.R.R. Tolkien")
            )

        self.assertEqual(len(works), 1)
        self.assertFalse(has_more)

    def test_duplicate_titles_are_collapsed(self):
        payload = self._payload(["The Hobbit", "the hobbit"], num_found=2)
        with patch.object(openlibrary.requests, "get", return_value=_response(payload)):
            works, _ = openlibrary.author_works(
                Entity(id="OL26320A", name="J.R.R. Tolkien")
            )

        self.assertEqual(len(works), 1)


class BookAuthorFacetTests(unittest.TestCase):
    def test_books_provider_has_keyless_author_facet(self):
        facets = BookProvider.creator_facets
        self.assertEqual([f.key for f in facets], ["author"])
        self.assertEqual(facets[0].requires_cred, "")  # always on, no key needed

    def test_author_is_a_cli_by_choice(self):
        self.assertIn("author", creator_facet_choices())


if __name__ == "__main__":
    unittest.main()
