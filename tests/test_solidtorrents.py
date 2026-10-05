"""A SolidTorrents rate limit pauses it app-wide for its Retry-After, and says so."""

import time
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch

import isolation  # noqa: F401  # redirected settings and the shared test baseline
from torrent_finder.providers import base
from torrent_finder.providers.anime_provider import AnimeProvider
from torrent_finder.providers.book_provider import BookProvider
from torrent_finder.search_errors import SearchError


def response(status=200, headers=None, results=()):
    reply = Mock(status_code=status, headers=headers or {})
    reply.json.return_value = {"results": list(results)}
    reply.raise_for_status.side_effect = None if status < 400 else Exception(f"HTTP {status}")
    return reply


class SolidTorrentsCooldownTests(unittest.TestCase):
    def setUp(self):
        cooldown = patch.object(base, "_SOLIDTORRENTS_COOLDOWN", base.Cooldown("SolidTorrents"))
        self.cooldown = cooldown.start()
        self.addCleanup(cooldown.stop)

    def search(self, provider, reply):
        with patch.object(base.requests, "get", return_value=reply) as get:
            try:
                return provider._search_solidtorrents("Saki"), get
            except SearchError as error:
                return error, get

    def test_rate_limit_pauses_every_provider_for_retry_after(self):
        error, _ = self.search(AnimeProvider(), response(429, {"Retry-After": "120"}))
        self.assertIsInstance(error, SearchError)
        self.assertIn("slow down", str(error))
        self.assertAlmostEqual(self.cooldown.until - time.monotonic(), 120, delta=2)

        error, get = self.search(BookProvider(), response(results=[{"title": "Saki", "infohash": "A" * 40}]))
        self.assertIsInstance(error, SearchError)  # still cooling down: not asked again
        get.assert_not_called()

        self.cooldown.until = 0.0  # the pause is over
        rows, get = self.search(BookProvider(), response(results=[{"title": "Saki", "infohash": "A" * 40}]))
        get.assert_called_once()
        self.assertEqual([r.info_hash for r in rows], ["a" * 40])

    def test_retry_after_as_a_date_or_missing(self):
        later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
        for headers, expected in (({"Retry-After": later}, 30), ({}, base.Cooldown.DEFAULT_SECONDS),
                                  ({"Retry-After": "99999"}, base.Cooldown.MAX_SECONDS)):
            with self.subTest(headers=headers):
                self.cooldown.until = 0.0
                self.search(AnimeProvider(), response(429, headers))
                self.assertAlmostEqual(self.cooldown.until - time.monotonic(), expected, delta=2)


if __name__ == "__main__":
    unittest.main()
