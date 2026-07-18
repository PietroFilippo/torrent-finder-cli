import unittest
import warnings
from unittest.mock import Mock, patch

warnings.filterwarnings("ignore", module=".*requests.*")
warnings.filterwarnings("ignore", message=".*urllib3.*")

from torrent_finder import libgen
from torrent_finder.acquisition import LibgenAcquisition, for_result
from torrent_finder.providers import get_provider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.search_result import SearchResult

_MD5 = "92651ea7d95073ba4c8d345285b6bf74"

# One result row in the libgen.li table layout: 9 cells — title (with series
# noise + edition anchor), author, publisher, year, language, pages, size,
# extension, mirror links (the md5 lives here).
_ROW_HTML = f"""
<table>
<tr><td>Show covers junk</td><td>nav</td></tr>
<tr>
  <td><b>Dune 7;Le cycle</b><br>
      <a href="edition.php?id=6090675">Dune: The Gateway Collection <i></i></a></td>
  <td>Herbert, Frank</td>
  <td>Gateway</td>
  <td>2010</td>
  <td>English</td>
  <td>0</td>
  <td>832 kB</td>
  <td>epub</td>
  <td><a href="/ads.php?md5={_MD5}"><span>1</span></a></td>
</tr>
</table>
"""

_ADS_HTML = f'<a href="get.php?md5={_MD5}&amp;key=FTBTL3Q4EFKIQF6L">GET</a>'


def _response(text: str, status: int = 200) -> Mock:
    response = Mock()
    response.status_code = status
    response.text = text
    return response


class LibgenSearchTests(unittest.TestCase):
    def test_parses_result_rows(self):
        with patch.object(
            libgen.requests, "get", return_value=_response(_ROW_HTML)
        ):
            results = libgen.search("dune")

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(
            r.name, "Dune: The Gateway Collection — Herbert, Frank [epub, English]"
        )
        self.assertEqual(r.info_hash, f"libgen:{_MD5}")
        self.assertEqual(r.source, "Libgen")
        self.assertEqual(r.size, 851968)  # 832 kB
        self.assertEqual(r["lg_md5"], _MD5)
        self.assertEqual(r["lg_ext"], "epub")
        self.assertIn(f"/ads.php?md5={_MD5}", r.page_url)

    def test_mirror_failover_on_network_error(self):
        import requests as requests_mod

        calls = []

        def flaky_get(url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise requests_mod.ConnectionError("mirror down")
            return _response(_ROW_HTML)

        with patch.object(libgen.requests, "get", side_effect=flaky_get):
            results = libgen.search("dune")

        self.assertEqual(len(results), 1)
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])

    def test_all_mirrors_down_gives_empty(self):
        import requests as requests_mod

        with patch.object(
            libgen.requests,
            "get",
            side_effect=requests_mod.ConnectionError("down"),
        ):
            self.assertEqual(libgen.search("dune"), [])

    def test_parse_size(self):
        self.assertEqual(libgen.parse_size("832 kB"), 851968)
        self.assertEqual(libgen.parse_size("1.4 MB"), int(1.4 * 1024**2))
        self.assertEqual(libgen.parse_size("2 GB"), 2 * 1024**3)
        self.assertEqual(libgen.parse_size(""), 0)
        self.assertEqual(libgen.parse_size("garbage"), 0)


class LibgenResolveTests(unittest.TestCase):
    def test_resolves_keyed_get_link_on_first_live_mirror(self):
        with patch.object(
            libgen.requests, "get", return_value=_response(_ADS_HTML)
        ):
            url = libgen.resolve_download_url(_MD5)

        self.assertEqual(
            url, f"https://libgen.li/get.php?md5={_MD5}&key=FTBTL3Q4EFKIQF6L"
        )

    def test_returns_none_without_md5(self):
        self.assertIsNone(libgen.resolve_download_url(""))


class BookProviderTests(unittest.TestCase):
    def test_registered_with_books_slug_and_book_alias(self):
        self.assertIsInstance(get_provider("books"), BookProvider)
        self.assertIsInstance(get_provider("book"), BookProvider)

    def test_default_engines_need_no_credentials(self):
        provider = BookProvider()
        enabled = {e.name for e in provider.engines if e.enabled}
        self.assertEqual(enabled, {"Libgen", "Apibay"})

    def test_apibay_covers_ebook_and_audiobook_categories(self):
        self.assertEqual(set(BookProvider.categories), {601, 102})

    def test_file_picker_enabled_for_torrent_bundles(self):
        self.assertTrue(BookProvider.supports_episode_picker)

    def test_apibay_falls_back_to_book_category_requests(self):
        # cat=0 falsely returns the sentinel for many book titles that the
        # category-scoped search finds (e.g. "Metamorphosis").
        no_results = Mock()
        no_results.raise_for_status.return_value = None
        no_results.json.return_value = [{"id": "0", "name": "No results returned"}]
        ebooks = Mock()
        ebooks.raise_for_status.return_value = None
        ebooks.json.return_value = [
            {
                "id": "1",
                "name": "The Metamorphosis - Kafka [epub]",
                "info_hash": "c" * 40,
                "seeders": "12",
                "leechers": "1",
                "size": "300000",
                "category": "601",
            }
        ]

        with patch(
            "torrent_finder.providers.base.requests.get",
            side_effect=[no_results, ebooks, no_results],
        ) as get:
            results = BookProvider()._search_apibay("Metamorphosis")

        self.assertEqual(
            [r.name for r in results], ["The Metamorphosis - Kafka [epub]"]
        )
        from urllib.parse import parse_qs
        cats = [
            parse_qs(call.kwargs["params"])["cat"][0]
            for call in get.call_args_list
        ]
        self.assertEqual(cats, ["0", "601", "102"])

    def test_libgen_rows_sort_above_torrents(self):
        # Default seeders-descending sort would bury Libgen (seeders=0) under
        # every torrent row; Books keeps Libgen first in site relevance order.
        libgen_a = SearchResult(name="A [epub]", source="Libgen")
        libgen_b = SearchResult(name="B [pdf]", source="Libgen")
        torrent_low = SearchResult(name="T low", source="Apibay", seeders=1)
        torrent_high = SearchResult(name="T high", source="Apibay", seeders=50)

        ordered = BookProvider()._sort_results(
            [torrent_low, libgen_a, torrent_high, libgen_b]
        )

        self.assertEqual(
            [r.name for r in ordered],
            ["A [epub]", "B [pdf]", "T high", "T low"],
        )


class LibgenAcquisitionTests(unittest.TestCase):
    def _result(self) -> SearchResult:
        return SearchResult(
            name="Dune [epub, English]",
            info_hash=f"libgen:{_MD5}",
            source="Libgen",
            page_url=f"https://libgen.li/ads.php?md5={_MD5}",
            handle={"lg_md5": _MD5},
            extra={"lg_ext": "epub"},
        )

    def test_libgen_source_routes_to_direct_download(self):
        adapter = for_result(self._result())
        self.assertIsInstance(adapter, LibgenAcquisition)
        self.assertEqual(adapter.style, "direct-download")
        self.assertIsNone(adapter.magnet(self._result()))

    def test_batch_item_saves_directly(self):
        with patch.object(
            libgen, "resolve_download_url", return_value="https://x/get.php"
        ), patch.object(
            libgen, "download_file", return_value="C:/dl/dune.epub"
        ) as dl:
            outcome = LibgenAcquisition().batch_item(
                self._result(),
                download_dir="C:/dl",
                cancel_event=None,
                set_status=lambda s: None,
            )

        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.saved_direct)
        self.assertEqual(dl.call_args.args[2], f"libgen-{_MD5[:8]}.epub")

    def test_batch_item_falls_back_to_manual_url(self):
        with patch.object(libgen, "resolve_download_url", return_value=None):
            outcome = LibgenAcquisition().batch_item(
                self._result(),
                download_dir="C:/dl",
                cancel_event=None,
                set_status=lambda s: None,
            )

        self.assertFalse(outcome.ok)
        self.assertIn("ads.php", outcome.manual_url)


if __name__ == "__main__":
    unittest.main()
