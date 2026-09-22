import unittest
from unittest.mock import Mock, patch

from torrent_finder import fitgirl, online_fix
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.result_view import matches_name, result_indices, title_score, timestamp
from torrent_finder.nyaa import discovery_query
from torrent_finder.search_result import SearchResult


class SearchRefinementTests(unittest.TestCase):
    def test_exact_title_preserves_releases_but_excludes_sequels(self):
        self.assertTrue(matches_name("[Group] Saki (2009) 1080p BluRay", "Saki", "title"))
        self.assertTrue(matches_name("[Group] Saki - 01 [720p].mkv", "Saki", "title"))
        self.assertFalse(matches_name("[Group] Saki Zenkoku-hen 1080p", "Saki", "title"))
        self.assertFalse(matches_name("Tenkou-saki 1080p", "Saki", "title"))

    def test_newest_uses_upload_date_and_keeps_original_indexes(self):
        rows = [{"name":"Saki old", "uploaded_at":10}, {"name":"Saki unknown"},
                {"name":"Saki new", "uploaded_at":30}, {"name":"Other", "uploaded_at":90}]
        self.assertEqual(result_indices(rows, "Saki", order="newest"), [2, 0, 1])
        self.assertEqual(result_indices(rows, "Saki new", "filename"), [2])

    def test_title_may_be_a_year_and_invalid_dates_do_not_break_the_table(self):
        self.assertTrue(matches_name("1917 (2019) 1080p", "1917", "title"))
        self.assertEqual(timestamp(float("inf")), 0)
        self.assertEqual(timestamp(10**30), 0)
        self.assertEqual(timestamp("invalid"), 0)
        self.assertEqual(result_indices([{"size": 1}, {"size": 10**12}], order="size"), [1, 0])

    def test_a_sequel_in_rss_does_not_prevent_original_title_discovery(self):
        rss = Mock(text='<rss xmlns:n="https://nyaa.si/xmlns/nyaa"><channel><item><title>Saki Zenkoku-hen 1080p</title><n:infoHash>' + 'a'*40 + '</n:infoHash></item></channel></rss>')
        with patch("torrent_finder.providers.base.requests.get", return_value=rss), \
             patch("torrent_finder.nyaa.popular", return_value=[SearchResult(name="Saki 1080p", info_hash='b'*40)]) as popular:
            result = AnimeProvider().search("Saki")
        popular.assert_called_once()
        self.assertEqual(result[0].name, "Saki 1080p")

    def test_saki_recovers_older_exact_title_from_catalog(self):
        rss = Mock(text='<rss xmlns:n="https://nyaa.si/xmlns/nyaa"><channel><item><title>[Group] Tenkou-saki 1080p</title><n:infoHash>' + 'a'*40 + '</n:infoHash><n:seeders>999</n:seeders></item></channel></rss>')
        html = Mock(text='<table><tr><td></td><td><a href="/view/10" title="[Group] Saki (2009) 1080p">Saki</a></td><td><a href="magnet:?xt=urn:btih:' + 'b'*40 + '">magnet</a></td><td>1 GiB</td><td data-timestamp="100">date</td><td>10</td><td>2</td><td>100</td></tr></table>')
        with patch("torrent_finder.providers.base.requests.get", side_effect=[rss, html]):
            result = AnimeProvider().search("Saki")
        self.assertEqual(title_score(result[0].name, "Saki"), 3)
        self.assertEqual(result[0].get("uploaded_at"), 100)

    def test_discovery_excludes_dominant_unrelated_series_without_changing_original_query(self):
        recent = [SearchResult(name=f"[Group] Tenkou-saki - {i:02d} [1080p]") for i in range(10)]
        self.assertEqual(discovery_query("Saki", recent), "Saki -tenkou")
        self.assertEqual(discovery_query("Saki", [SearchResult(name="Saki Zenkoku-hen")]), "Saki")

    def test_fitgirl_discards_search_matches_only_in_post_body(self):
        html = ''.join(f'<article id="post-{i}" class="category-lossless-repack"><h1 class="entry-title"><a href="https://fitgirl-repacks.site/{i}">{name}</a></h1>mentions Saki</article>' for i,name in [(1,"Saki Game"),(2,"Unrelated Game")])
        session = Mock()
        session.get.return_value.text = html
        with patch.object(fitgirl, "_http", return_value=session):
            self.assertEqual([r.name for r in fitgirl.search("Saki")], ["Saki Game"])

    def test_online_fix_does_not_borrow_neighbor_title_or_keep_sidebar_noise(self):
        html = '<a href="/games/action/1-saki.html"></a><a href="/games/action/2-other.html"><img alt="Unrelated Game"></a>'
        session = Mock()
        session.get.return_value.text = html
        with patch.object(online_fix, "_anon_http", return_value=session):
            rows = online_fix.search("Saki")
        self.assertEqual([r.name for r in rows], ["Saki"])
