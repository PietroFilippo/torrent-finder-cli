"""Abstract base class for torrent search providers."""

from abc import ABC, abstractmethod

import concurrent.futures
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from typing import Callable, Iterator
from urllib.parse import quote, quote_plus, urlencode

import requests

from torrent_finder import apibay_cache
from torrent_finder.constants import API_URL, console
from torrent_finder.filters import FilterConfig, FilterPreset, apply_filters
from torrent_finder.search_result import SearchResult, normalize_result


_APIBAY_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
_APIBAY_FALLBACK_IGNORED = {
    "a",
    "an",
    "and",
    "at",
    "film",
    "for",
    "in",
    "movie",
    "of",
    "on",
    "or",
    "part",
    "the",
    "to",
}


def _apibay_title_case(query: str) -> str:
    """Return a stable title-cased spelling, including all-uppercase input."""
    return " ".join(word.capitalize() for word in query.casefold().split())


def _apibay_fallback_query(query: str) -> str | None:
    """Return one conservative retry for Apibay's brittle phrase search."""
    tokens = re.findall(r"[a-z0-9]+", query.casefold())
    if len(tokens) < 2:
        return None

    normalized = [_APIBAY_NUMBER_WORDS.get(token, token) for token in tokens]
    normalized_query = " ".join(normalized)
    canonical_query = " ".join(tokens)
    if (
        normalized_query != canonical_query
        or canonical_query != query.casefold().strip()
    ):
        return normalized_query

    meaningful = [
        token
        for token in normalized
        if token not in _APIBAY_FALLBACK_IGNORED and not token.isdigit()
    ]
    return max(meaningful, key=len) if meaningful else None


@dataclass
class SearchEngine:
    """A toggleable search engine backend."""
    name: str
    icon: str
    search_fn: Callable[[object, str], list[dict | SearchResult]]  # bound method reference
    enabled: bool = True
    emergency_fallback: bool = False
    explicitly_disabled: bool = False


class BaseProvider(ABC):
    """Base class that all providers inherit from.

    Each provider defines:
      - name: display label (e.g. "Movies")
      - slug: canonical identity used by persistence and the CLI
      - cli_aliases: optional backwards-compatible CLI spellings
      - icon: emoji (e.g. "🎬")
      - categories: list of apibay numeric category IDs to search
    """

    name: str  # display label, free to change
    slug: str  # immutable identity used for persistence keys (history, stats, settings)
    cli_aliases: tuple[str, ...] = ()  # backwards-compatible -t names; slug is always accepted
    icon: str
    categories: list[int]
    apibay_fallback_categories: tuple[int, ...] = ()
    solidtorrents_category: str = "all"
    nyaa_category: str = "1_2"  # Nyaa "c" filter; e.g. "1_2" anime EngSub, "4_1" live-action EngSub

    # Capabilities — gate UI rows in download_method_prompt.
    # Opt-in: subclasses override to True when applicable.
    supports_subtitles: bool = False
    supports_episode_picker: bool = False
    # Opt-out: True by default; set False for non-video providers (e.g. Manga)
    # to hide the "Stream to VLC" section.
    supports_streaming: bool = True

    default_filters: FilterConfig | None = None
    presets: list[FilterPreset] = []

    # Optional "search by creator" facets (director/studio/author/…). Empty
    # disables the by-creator quick action for this provider. Populated by
    # subclasses with resolvers.CreatorFacet instances.
    creator_facets: list = []
    apibay_cache_enabled: bool = True

    # Optional one-line caveat shown when this provider is selected/searched
    # (e.g. Mobile noting it's Android-only). Empty = no note.
    search_note: str = ""
    
    def __init__(self):
        self.active_presets: list[FilterPreset] = []
        self.engines: list[SearchEngine] = self._init_engines()

    def _init_engines(self) -> list[SearchEngine]:
        """Define available search engines. Override in subclasses to customize."""
        return [
            SearchEngine("Apibay", "🏴‍☠️", self._search_apibay, enabled=True),
            SearchEngine("SolidTorrents", "🔗", self._search_solidtorrents, enabled=True),
        ]

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}"

    def _apibay_retry_queries(self, query: str) -> Iterator[str]:
        # APIBay's query cache is case-sensitive. Preserve the user's spelling
        # for the first request, then retry the complete normalized phrase in
        # lowercase and title case before degrading it. In particular,
        # FINDING NEMO must be able to become finding nemo.
        normalized = " ".join(query.split())
        yield normalized.casefold()
        yield _apibay_title_case(normalized)
        fallback = _apibay_fallback_query(query)
        if fallback:
            yield fallback
            yield _apibay_title_case(fallback)

    def _search_apibay(self, query: str) -> list[SearchResult]:
        """Search APIBay live, then use its last successful rows on empties."""
        results = self._search_apibay_live(query)
        if not self.apibay_cache_enabled:
            return results
        if results:
            apibay_cache.store(self.slug, query, results)
            return results
        return apibay_cache.load(self.slug, query)

    def _search_apibay_live(self, query: str) -> list[SearchResult]:
        """Search Apibay with conservative provider-specific query retries.

        Apibay's phrase matching can return either a no-results sentinel or
        unrelated categories for valid titles. Retry normalized queries only
        after filtering leaves no provider results. Network failures stop the
        retry chain.
        """
        def fetch(
            search_query: str, category: str | int | None = None
        ) -> list[dict] | None:
            # The documented all-category request omits cat. APIBay's cache
            # does not treat that as equivalent to cat=0: during the July
            # 2026 incident, finding nemo&cat=0 returned the empty sentinel
            # while omitting cat returned 100 rows.
            query_params: dict[str, str | int] = {"q": search_query}
            if category is not None:
                query_params["cat"] = category

            # Edge nodes have disagreed on %20 versus "+" space decoding.
            # Keep both deterministic encodings, but do not mutate the query
            # or add random cache keys: that multiplied one search into more
            # than twenty requests without fixing poisoned queries.
            tried: set[str] = set()
            answered = False
            for quoter in (quote, quote_plus):
                params = urlencode(query_params, quote_via=quoter)
                if params in tried:
                    continue
                try:
                    response = requests.get(
                        API_URL,
                        params=params,
                        timeout=45,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    response.raise_for_status()
                    data = response.json()
                except (requests.RequestException, ValueError):
                    # Do not mark a failed encoding as tried. For a one-word
                    # query, the second encoder then provides one transport
                    # retry even though its query string is identical.
                    continue
                tried.add(params)
                if not isinstance(data, list):
                    continue
                answered = True
                rows = [item for item in data if isinstance(item, dict)]
                if not rows:
                    continue
                if len(rows) == 1 and str(rows[0].get("id")) == "0":
                    continue
                return rows
            return [] if answered else None

        wanted = {str(category) for category in self.categories}

        def matching_results(data: list[dict]) -> list[SearchResult]:
            results: list[SearchResult] = []
            for item in data:
                if str(item.get("category", "")) not in wanted:
                    continue
                tid = item.get("id")
                raw_name = item.get("name")
                name = (
                    raw_name
                    if isinstance(raw_name, str) and raw_name
                    else "Unknown"
                )
                results.append(SearchResult(
                    # Apibay HTML-escapes quotes in names (&quot;) to keep its
                    # JSON valid — undo that for display.
                    name=unescape(name),
                    info_hash=item.get("info_hash", ""),
                    seeders=item.get("seeders", 0),
                    leechers=item.get("leechers", 0),
                    size=item.get("size", 0),
                    source="Apibay",
                    page_url=(
                        f"https://thepiratebay.org/description.php?id={tid}"
                        if tid
                        else ""
                    ),
                ))
            return results

        normalized_query = " ".join(query.split())
        if not normalized_query:
            return []

        data = fetch(normalized_query)
        if data is None:
            return []

        results = matching_results(data)
        if results:
            return results

        if self.apibay_fallback_categories:
            # APIBay accepts comma-separated categories (the same form used
            # by TPB indexer clients). One scoped fallback is both broader and
            # gentler on the service than one request per category.
            category_filter = ",".join(
                str(category) for category in self.apibay_fallback_categories
            )
            category_data = fetch(normalized_query, category_filter)
            if category_data is not None:
                results = matching_results(category_data)
            if results:
                return results

        # Dedupe retries by exact string: Apibay treats differently-cased
        # spellings of the same words as distinct queries (see above).
        tried = {normalized_query}
        for fallback in self._apibay_retry_queries(normalized_query):
            if fallback in tried:
                continue
            tried.add(fallback)
            fallback_data = fetch(fallback)
            if fallback_data is None:
                break
            results = matching_results(fallback_data)
            if results:
                break
        return results

    def _search_solidtorrents(self, query: str) -> list[SearchResult]:
        """Search SolidTorrents API for the query."""
        results: list[SearchResult] = []
        try:
            response = requests.get(
                "https://solidtorrents.to/api/v1/search",
                params={"q": query, "category": self.solidtorrents_category},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            for r in data.get("results", []):
                # The slug segment is ignored by the site; only the id matters.
                rid = r.get("_id") or r.get("id")
                results.append(SearchResult(
                    name=r.get("title", "Unknown"),
                    info_hash=r.get("infohash", "").lower(),
                    seeders=r.get("swarm", {}).get("seeders", 0),
                    leechers=r.get("swarm", {}).get("leechers", 0),
                    size=r.get("size", 0),
                    source="SolidTorrents",
                    page_url=f"https://solidtorrents.to/torrents/t/{rid}" if rid else "",
                ))
        except Exception:
            pass
        return results

    def _parse_nyaa_size(self, size_str: str) -> int:
        """Parse a Nyaa size string (e.g. '1.5 GiB') into bytes."""
        size_str = size_str.lower().strip()
        try:
            val, unit = size_str.split(" ", 1)
            num = float(val)
            if "kib" in unit: return int(num * 1024)
            if "mib" in unit: return int(num * 1024**2)
            if "gib" in unit: return int(num * 1024**3)
            if "tib" in unit: return int(num * 1024**4)
            return int(num)
        except Exception:
            return 0

    def _search_nyaa(self, query: str) -> list[SearchResult]:
        """Search Nyaa scoped to ``self.nyaa_category`` (the provider default)."""
        return self._search_nyaa_in(query, self.nyaa_category)

    def _search_nyaa_in(self, query: str, category: str) -> list[SearchResult]:
        """Search the Nyaa.si RSS feed scoped to a specific ``c`` category.

        Split out from ``_search_nyaa`` so one provider can register multiple
        Nyaa engines on different categories (e.g. Manga's English-translated
        ``3_1`` + Raw ``3_2``).
        """
        results: list[SearchResult] = []
        try:
            response = requests.get(
                "https://nyaa.si/",
                params={"page": "rss", "q": query, "c": category},
                timeout=10
            )
            response.raise_for_status()

            root = ET.fromstring(response.text)
            nyaa_ns = "{https://nyaa.si/xmlns/nyaa}"

            for item in root.findall(".//item"):
                title = item.find("title")
                info_hash = item.find(f"{nyaa_ns}infoHash")
                seeders = item.find(f"{nyaa_ns}seeders")
                leechers = item.find(f"{nyaa_ns}leechers")
                size = item.find(f"{nyaa_ns}size")
                guid = item.find("guid")  # permalink to the nyaa.si view page

                if title is not None and info_hash is not None:
                    size_bytes = 0
                    if size is not None and size.text:
                        size_bytes = self._parse_nyaa_size(size.text)

                    results.append(SearchResult(
                        name=title.text,
                        info_hash=info_hash.text.lower(),
                        seeders=seeders.text if seeders is not None else 0,
                        leechers=leechers.text if leechers is not None else 0,
                        size=size_bytes,
                        source="Nyaa",
                        page_url=guid.text if guid is not None and guid.text else "",
                    ))
        except Exception:
            pass
        return results

    def search(self, query: str, cli_filters: FilterConfig | None = None) -> list[SearchResult]:
        """Search enabled engines, then safe emergency engines if all are empty."""
        seen_hashes: set[str] = set()
        merged: list[SearchResult] = []

        active_engines = [e for e in self.engines if e.enabled]
        if not active_engines:
            return []

        def run_engines(engines: list[SearchEngine]) -> None:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(engines)
            ) as executor:
                future_to_engine = {
                    executor.submit(engine.search_fn, query): engine
                    for engine in engines
                }
                for future in concurrent.futures.as_completed(future_to_engine):
                    try:
                        data = future.result()
                        for raw_item in data:
                            item = normalize_result(raw_item)
                            info_hash = item.info_hash.lower()
                            if info_hash and info_hash not in seen_hashes:
                                seen_hashes.add(info_hash)
                                merged.append(item)
                    except Exception:
                        pass

        run_engines(active_engines)

        if not merged:
            emergency_engines = [
                engine
                for engine in self.engines
                if (
                    not engine.enabled
                    and engine.emergency_fallback
                    and not engine.explicitly_disabled
                )
            ]
            if emergency_engines:
                run_engines(emergency_engines)

        # Apply filters
        # 1. Default provider filters
        if self.default_filters:
            merged = apply_filters(merged, self.default_filters)
            
        # 2. Active preset filters
        for preset in self.active_presets:
            merged = apply_filters(merged, preset.config)

        # 3. CLI filters
        if cli_filters:
            merged = apply_filters(merged, cli_filters)

        return self._sort_results(merged)

    def _sort_results(self, results: list[SearchResult]) -> list[SearchResult]:
        """Order merged results for display. Default: seeders descending.

        Providers whose primary engine has no swarm stats (e.g. Books' Libgen
        direct downloads, always seeders=0) override this so their main source
        isn't buried under every torrent row.
        """
        results.sort(key=lambda x: x.seeders, reverse=True)
        return results
