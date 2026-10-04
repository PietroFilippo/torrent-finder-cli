"""Search-session and source fixes from the 2026-10-04 final review."""

import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import requests

import isolation  # noqa: F401  (keeps the user's settings out of reach)
from test_book_provider import _ROW_HTML, _response
from torrent_finder import knaben, libgen
from torrent_finder.providers.manga_provider import MangaProvider
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.providers.software_provider import SoftwareProvider
from torrent_finder.resolvers import titles
from torrent_finder.search_control import SearchControl, SearchInterrupted, SharedResults
from torrent_finder.search_diagnostics import RequestTrace, record_failure
from torrent_finder.search_result import SearchResult
from torrent_finder.search_session import SearchSession, search_many
from torrent_finder.utils import build_magnet


def row(name, n=[0]):
    n[0] += 1
    return SearchResult(name=name, info_hash=f"{n[0]:040x}", seeders=1, source="Nyaa")


class MangaSources:
    """Fake Manga engines answering {(engine, query): rows}; records calls and lookups."""

    def __init__(self, answers, aliases=None):
        self.answers, self.aliases, self.calls, self.lookups = answers, aliases or {}, [], []

    def __enter__(self):
        self.stack = ExitStack()

        def engine(name):
            def search(_self, query, *category):
                key = name if not category else {"3_2": "Non-English", "3_3": "Raw"}[category[0]]
                self.calls.append((key, query))
                return list(self.answers.get((key, query), []))
            return search

        for method, name in (("_search_nyaa", "Nyaa"), ("_search_nyaa_in", None),
                             ("_search_apibay", "Apibay"), ("_search_knaben", "Knaben")):
            self.stack.enter_context(patch.object(MangaProvider, method, engine(name)))

        def known_aliases(catalog, query, limit=2):
            self.lookups.append(query)
            return self.aliases.get(query, ())
        self.stack.enter_context(patch.object(titles, "known_aliases", known_aliases))
        self.stack.enter_context(patch.object(MangaProvider, "looks_up_aliases", True))
        return self

    def __exit__(self, *exc):
        self.stack.close()


class StoppedSearchTests(unittest.TestCase):
    def test_an_engine_stopped_before_it_runs_is_interrupted_not_empty(self):
        stopped = threading.Event()
        stopped.set()
        with self.assertRaises(SearchInterrupted):
            SearchControl(30, cancel_event=stopped).run_engine("anime", "Nyaa", lambda: ["row"],
                                                               threading.Semaphore(1))


class SharedResultsTests(unittest.TestCase):
    def test_a_search_that_recorded_a_failure_is_not_reused(self):
        shared, calls = SharedResults(30.0), []

        def search(query):
            calls.append(query)
            record_failure(message="Source returned HTTP 503.")
            return []
        with RequestTrace():
            shared.run("Celeste", search)
            shared.run("Celeste", search)
        self.assertEqual(calls, ["Celeste", "Celeste"])


class OtherSpellingFixTests(unittest.TestCase):
    def test_auto_only_engines_run_the_other_spelling(self):
        with MangaSources({("Knaben", "Mob Psycho 100"): [row("Mob Psycho 100 v01-13 (Digital)")]}) as sources:
            provider = MangaProvider()  # engines bind the patched methods
            for engine in provider.engines:
                engine.set_mode("auto" if engine.name == "Knaben" else "off")
            results = SearchSession([provider], ["Mob Psycho Hundred"]).run()
        self.assertEqual([r.name for r in results], ["Mob Psycho 100 v01-13 (Digital)"])
        self.assertEqual(sources.calls, [("Knaben", "Mob Psycho Hundred"), ("Knaben", "Mob Psycho 100")])

    def test_the_catalog_gets_the_title_and_the_typed_word_stays_on_the_alias(self):
        answers = {("Non-English", "Yokohama Kaidashi Kikou"): [row("Yokohama Kaidashi Kikou v01 (Português) PT-BR")]}
        with MangaSources(answers, aliases={"Yokohama Shopping Log": ("Yokohama Kaidashi Kikou",)}) as sources:
            results = search_many(MangaProvider(), ["Yokohama Shopping Log portugues"])
        self.assertEqual(sources.lookups, ["Yokohama Shopping Log"])
        self.assertIn(("Nyaa", "Yokohama Kaidashi Kikou portugues"), sources.calls)
        self.assertIn(("Non-English", "Yokohama Kaidashi Kikou"), sources.calls)  # the typed preset still applies
        self.assertEqual([r.name for r in results], ["Yokohama Kaidashi Kikou v01 (Português) PT-BR"])

    def test_rows_found_under_another_spelling_belong_to_the_typed_title(self):
        answers = {("Nyaa", "21st Century Boys"): [row("21st Century Boys v01-02 (complete)")],
                   ("Nyaa", "Monster"): [row("Monster v01-18 (Digital)")]}
        with MangaSources(answers):
            results = search_many(MangaProvider(), ["Twenty First Century Boys", "Monster"])
        found = {r.name: (r["matched_queries"], r["from_work"]) for r in results}
        self.assertEqual(found["21st Century Boys v01-02 (complete)"],
                         (["Twenty First Century Boys"], "Twenty First Century Boys"))

    def test_typed_preset_notices_once_and_only_when_rows_are_shown(self):
        answers = {("Nyaa", "21st Century Boys"): [row("21st Century Boys v01-02 (complete)")]}
        with MangaSources(answers):
            results = search_many(MangaProvider(), ["Twenty First Century Boys raw"])
        self.assertEqual(sum("Raw (Japanese) tag" in notice for notice in results.notices), 1)
        with MangaSources({}):
            results = search_many(MangaProvider(), ["Berserk portugues"])
        self.assertFalse(any("tag" in notice for notice in results.notices))


class QueryExpansionTests(unittest.TestCase):
    def test_movies_stay_within_the_expansion_cap(self):
        provider = MovieProvider()
        provider.preferred_presets = [p for p in provider.presets if p.query_terms]
        self.assertLessEqual(len(provider.expand_queries("Finding Nemo 1080p")), 4)

    def test_apibay_never_falls_back_to_the_typed_word(self):
        retries = list(SoftwareProvider()._apibay_retry_queries("Gimp portable"))
        self.assertNotIn("portable", [q.casefold() for q in retries])


class SourceFixTests(unittest.TestCase):
    def test_libgen_mirror_failover_is_not_an_error(self):
        responses = [requests.ConnectionError("libgen.li down"), _response(_ROW_HTML)]

        def get(*_args, **_kwargs):
            answer = responses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with patch.object(libgen.requests, "get", side_effect=get), RequestTrace() as trace:
            rows = libgen.search("dune")
        self.assertTrue(rows)
        self.assertEqual(trace.failures, [])

    def test_knaben_drops_hashes_magnets_cannot_carry(self):
        payload = {"hits": [{"title": "v2 only", "hash": "a" * 64}, {"title": "v1", "hash": "b" * 40}]}
        response = Mock()
        response.json.return_value = payload
        with patch.object(knaben.requests, "get", return_value=response):
            rows = knaben.search("x", (3_000_000,))
        self.assertEqual([r.name for r in rows], ["v1"])

    def test_magnets_encode_a_malformed_hash(self):
        magnet = build_magnet('abc" --save-path=C:\\x', "Name")
        self.assertNotIn('"', magnet)
        self.assertNotIn(" ", magnet.split("&dn=")[0])


if __name__ == "__main__":
    unittest.main()
