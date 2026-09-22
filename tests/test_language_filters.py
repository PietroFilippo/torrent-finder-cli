"""Portuguese language presets: matching precision + the search-time seam.

Fixtures combine observed release names with synthetic ambiguity regressions.
"""

import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

from torrent_finder.filters import FilterConfig, FilterPreset, apply_filters
from torrent_finder.providers.base import BaseProvider, SearchEngine
from torrent_finder.providers.movie_provider import MovieProvider
from torrent_finder.search_result import SearchResult


def _row(name: str, source: str = "Apibay", seeders: int = 10) -> SearchResult:
    return SearchResult(
        name=name,
        info_hash=f"{abs(hash(name)):040x}"[:40],
        seeders=seeders,
        leechers=0,
        size=1,
        source=source,
    )


def _preset(provider, name: str) -> FilterPreset:
    return next(p for p in provider.presets if p.name == name)


class PortugueseDubMatchingTests(unittest.TestCase):
    def setUp(self):
        self.config = _preset(MovieProvider(), "Dublado (PT-BR)").config

    def _kept(self, names: list[str]) -> list[str]:
        rows = [_row(name) for name in names]
        return [r.name for r in apply_filters(rows, self.config)]

    def test_keeps_real_portuguese_dub_releases(self):
        names = [
            "Toy Story 3 (2010) 1080p HD Dublado pt-BR",
            "Toy Story (1995) 720p Dublado pt-BR / Brazilian Pt",
        ]

        self.assertEqual(self._kept(names), names)

    def test_generic_portuguese_and_dub_tags_do_not_prove_brazilian_audio(self):
        names = [
            "Vingadores Ultimato dublado hd 720p 2019",
            "Cidade de Deus (2002) BDrip 720p Nacional dat2014",
            "Homem-Aranha.2023.DUBLADO-LAPUMiA.mkv",
            "Batman Ninja 2018 [1080p] DUBLADO WWW.BLUDV.COM",
            "Vingadores Ultimato 2019 720p Português Inglês",
            "O Diabo Veste Prada 1080P (2006) Dublada",
            "Example Audio Portuguese",
            "Example DUBLADO LEGENDADO",
            "Example Brasileiro 1080p",
        ]
        self.assertEqual(self._kept(names), [])

    def test_recognizes_explicit_brazilian_language_variants(self):
        names = [
            "Example 1080p PTBR",
            "Example 1080p PT.BR",
            "Example 1080p Português Brasileiro",
            "Example 1080p Português do Brasil",
            "Example 1080p Brazilian Portuguese",
            "Example 1080p Audio Brasileiro",
            "Example 1080p Dublagem Brasileira",
            "Example 1080p POB",
        ]
        self.assertEqual(self._kept(names), names)

    def test_drops_english_only_releases(self):
        names = [
            "Oppenheimer.2023.1080p.BluRay.DD5.1.x264-GalaxyRG[TGx]",
            "Interstellar.2014.PROPER.IMAX.1080p.UHD.BluRay.x265.HDR.DV.DD+5.1",
            "Breaking Bad S01 Complete - 1080p ENG-ITA Multisub x264 BluRay",
            "Hot Wheels AcceleRacers 1-4 + Micro-series",
        ]

        self.assertEqual(self._kept(names), [])

    def test_dual_audio_alone_is_not_portuguese(self):
        """On these indexers "Dual Audio" is overwhelmingly Hindi/Tamil/Telugu."""
        names = [
            "Interstellar (2014) IMAX 1080p [Hindi ORG 2.0 + English 5.1] Dual Audio Bluray",
            "Interstellar.2014.720p.BRRip.Hindi.Dub.Dual-Audio.x264.mkv",
            "Interstellar (2014) 720p BRRip [Telugu-Dub] Dual-Audio x264",
        ]

        self.assertEqual(self._kept(names), [])

    def test_nacional_does_not_match_internacional(self):
        self.assertEqual(
            self._kept(["Aeroporto Internacional 1970 1080p BluRay"]), []
        )

    def test_accented_spelling_matches_via_accent_folding(self):
        self.assertEqual(
            self._kept(["Divertida Mente 2015 1080p Português Brasileiro"]),
            ["Divertida Mente 2015 1080p Português Brasileiro"],
        )

    def test_polish_dub_is_not_mistaken_for_portuguese(self):
        self.assertEqual(
            self._kept(
                ["Hot Wheels Acceleracers Breaking Point - Punkt zwrotny DUB PL.avi"]
            ),
            [],
        )

    def test_subtitle_tags_and_release_groups_do_not_prove_audio(self):
        names = [
            "Example 2024 English Audio SUB PT-BR",
            "Example 2024 LEGENDADO WWW.BLUDV.COM",
            "Example 2024 Portuguese subtitles LAPUMiA",
            "Example 2024 PT_BR legendado",
            "Example 2024 1080p COMANDOTORRENTS",
            "Example 2024 Brazilian Portuguese subs",
            "Example 2024 Audio English Legendas em Português",
            "Example 2024 Dublado Audio PT-PT Subs PT-BR",
            "Example 2024 Audio Portuguese Subs Brazilian Portuguese",
            "Example 2024 Dublado Subs POB",
        ]
        self.assertEqual(self._kept(names), [])

    def test_european_audio_is_not_brazilian_audio(self):
        names = [
            "Example 2024 Dublado PT-PT",
            "Example 2024 Português de Portugal",
            "Example 2024 European Portuguese Audio",
            "Example 2024 Dublado PT-PT SUB PT-BR",
        ]
        self.assertEqual(self._kept(names), [])

    def test_dubbed_releases_can_also_have_subtitles(self):
        names = [
            "Example 2024 DUBLADO PT-BR LEGENDADO",
            "Example 2024 Audio PT-BR Subs English",
            "Example 2024 Áudio Português Brasileiro Legendas Inglês",
            "Example 2024 Dual Audio PT-BR English",
            "Example 2024 PT_BR 1080p",
            "Example 2024 Dublado Audio PT-BR PT-PT",
            "Example 2024 Brazilian Portuguese Dubbed English subtitles",
            "Example 2024 Dub PT-BR Subs English",
        ]
        self.assertEqual(self._kept(names), names)

    def test_source_name_is_not_audio_evidence(self):
        row = _row("Example 2024 1080p", source="PT-BR Dublado")
        self.assertEqual(apply_filters([row], self.config), [])


class PortugueseSubtitleMatchingTests(unittest.TestCase):
    def setUp(self):
        self.config = _preset(MovieProvider(), "Legendado (PT subs)").config

    def _kept(self, names: list[str]) -> list[str]:
        rows = [_row(name) for name in names]
        return [r.name for r in apply_filters(rows, self.config)]

    def test_keeps_subtitled_releases(self):
        names = [
            "Duna.2021.1080p.WEB-DL.LEGENDADO",
            "The Godfather 1972 1080p BluRay SUB PT",
        ]

        self.assertEqual(self._kept(names), names)

    def test_bare_leg_substring_does_not_leak(self):
        names = [
            "I Am Legend 2007 1080p BluRay x264",
            "Monsters University 2013 College Cut 720p",
        ]

        self.assertEqual(self._kept(names), [])

    def test_audio_language_alone_does_not_prove_subtitles(self):
        names = [
            "Example 2024 Dublado PT-BR",
            "Example 2024 Português Inglês Dual Audio",
            "Example 2024 Audio PT-BR SUB English",
        ]
        self.assertEqual(self._kept(names), [])

    def test_recognizes_subtitle_language_in_both_orders(self):
        names = [
            "Example 2024 Portuguese subtitles",
            "Example 2024 Legendas em Português",
            "Example 2024 PT_BR Subs",
            "Example 2024 Subs: [pt-BR]",
        ]
        self.assertEqual(self._kept(names), names)


class QueryExpansionTests(unittest.TestCase):
    def test_plain_search_sends_one_query(self):
        provider = MovieProvider()

        self.assertEqual(provider.expand_queries("Toy Story"), ["Toy Story"])

    def test_dub_preset_fans_the_query_out_over_its_terms(self):
        provider = MovieProvider()
        provider.active_presets = [_preset(provider, "Dublado (PT-BR)")]

        self.assertEqual(
            provider.expand_queries("Toy Story"),
            ["Toy Story", "Toy Story pt-br", "Toy Story dublado"],
        )

    def test_expansion_is_capped_when_presets_stack(self):
        provider = MovieProvider()
        provider.active_presets = [
            _preset(provider, "Dublado (PT-BR)"),
            _preset(provider, "Legendado (PT subs)"),
            FilterPreset("noisy", FilterConfig(), query_terms=("a", "b", "c")),
        ]

        self.assertEqual(len(provider.expand_queries("Toy Story")), 4)

    def test_quality_presets_do_not_expand_the_query(self):
        provider = MovieProvider()
        provider.active_presets = [_preset(provider, "1080p")]

        self.assertEqual(provider.expand_queries("Toy Story"), ["Toy Story"])


class _RecordingProvider(BaseProvider):
    name = "Recorder"
    slug = "recorder"
    icon = "🎬"
    categories = [201]

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        super().__init__()

    def _init_engines(self):
        return [
            SearchEngine("On", "1", self._record("On"), enabled=True),
            SearchEngine("Off", "2", self._record("Off"), enabled=False),
        ]

    def _record(self, engine_name: str):
        def search(query: str):
            self.calls.append((engine_name, query))
            return [_row(f"{engine_name} {query} dublado", source=engine_name)]
        return search


class RequiredEngineTests(unittest.TestCase):
    def test_engine_left_off_stays_out_of_a_normal_search(self):
        provider = _RecordingProvider()

        provider.search("nemo")

        self.assertEqual(provider.calls, [("On", "nemo")])

    def test_preset_forces_its_required_engine_on_for_the_search(self):
        provider = _RecordingProvider()
        provider.active_presets = [
            FilterPreset("pt", FilterConfig(), require_engines=("Off",))
        ]

        provider.search("nemo")

        self.assertEqual(sorted(provider.calls), [("Off", "nemo"), ("On", "nemo")])

    def test_forcing_an_engine_does_not_rewrite_its_saved_mode(self):
        provider = _RecordingProvider()
        provider.active_presets = [
            FilterPreset("pt", FilterConfig(), require_engines=("Off",))
        ]

        provider.search("nemo")

        off_engine = next(e for e in provider.engines if e.name == "Off")
        self.assertEqual(off_engine.mode, "off")

    def test_untoggling_a_preset_restores_the_original_search_engines(self):
        provider = _RecordingProvider()
        provider.active_presets = [
            FilterPreset("pt", FilterConfig(), require_engines=("Off",))
        ]
        self.assertEqual({e.name for e in provider.effective_engines}, {"On", "Off"})
        provider.search("nemo")
        provider.active_presets.clear()
        provider.calls.clear()

        provider.search("nemo")

        self.assertEqual(provider.calls, [("On", "nemo")])
        self.assertEqual([e.name for e in provider.effective_engines], ["On"])

    def test_every_engine_runs_every_expanded_query(self):
        provider = _RecordingProvider()
        provider.active_presets = [
            FilterPreset(
                "pt", FilterConfig(),
                query_terms=("dublado",), require_engines=("Off",),
            )
        ]

        provider.search("nemo")

        self.assertEqual(
            sorted(provider.calls),
            [
                ("Off", "nemo"),
                ("Off", "nemo dublado"),
                ("On", "nemo"),
                ("On", "nemo dublado"),
            ],
        )

    def test_rows_repeated_across_expanded_queries_are_deduped(self):
        provider = _RecordingProvider()
        same = _row("Toy Story dublado")

        def always_same(_query: str):
            return [same]

        for engine in provider.engines:
            engine.search_fn = always_same
        provider.active_presets = [
            FilterPreset("pt", FilterConfig(), query_terms=("dublado", "nacional"))
        ]

        results = provider.search("Toy Story")

        self.assertEqual(len(results), 1)


class _AutoEngineProvider(BaseProvider):
    name = "Auto"
    slug = "auto-recorder"
    icon = "🎬"
    categories = [201]

    def __init__(self):
        self.calls: list[str] = []
        super().__init__()

    def _init_engines(self):
        def empty(query: str):
            self.calls.append(query)
            return []

        return [
            SearchEngine(
                "Knaben", "🧭", empty, enabled=False, emergency_fallback=True
            ),
        ]


class ForcedAutoEngineTests(unittest.TestCase):
    def test_a_forced_auto_engine_is_not_re_run_as_an_emergency(self):
        provider = _AutoEngineProvider()
        provider.active_presets = [
            FilterPreset("pt", FilterConfig(), require_engines=("Knaben",))
        ]

        provider.search("nemo")

        self.assertEqual(provider.calls, ["nemo"])

    def test_an_unforced_auto_engine_still_runs_as_an_emergency(self):
        provider = _AutoEngineProvider()

        provider.search("nemo")

        self.assertEqual(provider.calls, ["nemo"])


class MoviePresetWiringTests(unittest.TestCase):
    def test_dub_preset_pulls_in_the_engines_that_index_brazilian_releases(self):
        preset = _preset(MovieProvider(), "Dublado (PT-BR)")

        self.assertEqual(
            set(preset.require_engines), {"Knaben", "SolidTorrents"}
        )

    def test_required_engine_names_exist_on_the_provider(self):
        provider = MovieProvider()
        known = {engine.name for engine in provider.engines}

        for preset in provider.presets:
            for name in preset.require_engines:
                self.assertIn(name, known)


class LanguageSearchRegressionTests(unittest.TestCase):
    def test_combined_presets_and_cli_filters_apply_to_actual_search_results(self):
        provider = MovieProvider()
        provider.active_presets = [
            _preset(provider, "Dublado (PT-BR)"),
            _preset(provider, "Legendado (PT subs)"),
            _preset(provider, "1080p"),
        ]
        keep = _row("Example 1080p Dublado PT-BR Legendado", seeders=5)
        provider.engines = [SearchEngine("Fixture", "", lambda query: [
            keep,
            _row("Example 1080p Dublado PT-BR"),
            _row("Example 1080p Legendado"),
            _row("Example 720p Dublado PT-BR Legendado"),
            _row("Example 1080p Dublado PT-BR Legendado Low Seeds", seeders=1),
        ])]

        results = provider.search("Example", cli_filters=FilterConfig(min_seeds=3))

        self.assertEqual(results, [keep])

    def test_apibay_retries_keep_the_title_with_language_terms(self):
        for preset_name, title in [
            ("Dublado (PT-BR)", "Nemo"),
            ("Dublado (PT-BR)", "Toy Story"),
            ("Legendado (PT subs)", "Up"),
        ]:
            with self.subTest(preset=preset_name, title=title):
                provider = MovieProvider()
                provider.apibay_cache_enabled = False
                provider.active_presets = [_preset(provider, preset_name)]
                for engine in provider.engines:
                    if engine.name != "Apibay":
                        engine.search_fn = lambda query: []
                queries = []

                def respond(_url, **kwargs):
                    query = parse_qs(kwargs["params"])["q"][0]
                    queries.append(query)
                    response = Mock()
                    response.raise_for_status.return_value = None
                    response.json.return_value = (
                        [{"id": "1", "category": "201", "info_hash": "a" * 40,
                          "name": "Unrelated Movie Dublado PT-BR Legendado", "seeders": 10}]
                        if query.casefold() in {"dublado", "pt-br", "pt br", "legendado"}
                        else [{"id": "0", "name": "No results returned"}]
                    )
                    return response

                with (
                    patch("torrent_finder.providers.base.requests.get", side_effect=respond),
                    patch("torrent_finder.providers.movie_provider._fetch_yts_movies", return_value=[]),
                ):
                    results = provider.search(title)

                self.assertEqual(results, [])
                for query in queries:
                    self.assertTrue(set(title.casefold().split()) & set(query.casefold().split()), query)

    def test_matching_duplicate_survives_regardless_of_arrival_order(self):
        plain = _row("Example 2024 1080p")
        dubbed = _row("Example 2024 1080p Dublado PT-BR")
        dubbed.info_hash = plain.info_hash
        for rows in ([plain, dubbed], [dubbed, plain]):
            with self.subTest(first=rows[0].name):
                provider = MovieProvider()
                provider.active_presets = [_preset(provider, "Dublado (PT-BR)")]
                provider.engines = [SearchEngine("Fixture", "", lambda query: rows)]
                self.assertEqual([r.name for r in provider.search("Example")], [dubbed.name])

    def test_filter_menu_saves_and_restores_preset_without_changing_engine_modes(self):
        from torrent_finder import state
        from torrent_finder.ui import prompts

        provider = MovieProvider()
        modes = {e.name: e.mode for e in provider.engines}
        persisted = {}

        def select(items, **kwargs):
            for item in items:
                if item.label == "Dublado (PT-BR)":
                    self.assertIn("Knaben + SolidTorrents", item.description)
                    item.toggled = True
            return next(i for i, item in enumerate(items) if item.value == "confirm")

        with (
            patch.object(prompts, "PROVIDERS", [provider]),
            patch.object(prompts, "arrow_select", side_effect=select),
            patch.object(state.store, "read", return_value=persisted),
            patch.object(state.store, "write", side_effect=lambda data: persisted.update(data)),
            patch.object(state.store, "flush"),
        ):
            prompts.filter_menu(provider)
            restored = MovieProvider()
            state.load_state([restored])

        self.assertEqual([p.name for p in restored.active_presets], ["Dublado (PT-BR)"])
        self.assertEqual({e.name: e.mode for e in restored.engines}, modes)
        self.assertIn("Example dublado", restored.expand_queries("Example"))


if __name__ == "__main__":
    unittest.main()
