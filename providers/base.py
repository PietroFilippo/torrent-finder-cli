"""Abstract base class for torrent search providers."""

from abc import ABC, abstractmethod

import concurrent.futures
from dataclasses import dataclass
from typing import Callable

import requests

from constants import API_URL, console
from filters import FilterConfig, FilterPreset, apply_filters


@dataclass
class SearchEngine:
    """A toggleable search engine backend."""
    name: str
    icon: str
    search_fn: Callable[[object, str], list[dict]]  # bound method reference
    enabled: bool = True


class BaseProvider(ABC):
    """Base class that all providers inherit from.

    Each provider defines:
      - name: display label (e.g. "Movies")
      - icon: emoji (e.g. "🎬")
      - categories: list of apibay numeric category IDs to search
    """

    name: str  # display label, free to change
    slug: str  # immutable identity used for persistence keys (history, stats, settings)
    icon: str
    categories: list[int]
    solidtorrents_category: str = "all"

    # Capabilities — gate UI rows in download_method_prompt.
    # Opt-in: subclasses override to True when applicable.
    supports_subtitles: bool = False
    supports_episode_picker: bool = False

    default_filters: FilterConfig | None = None
    presets: list[FilterPreset] = []
    
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

    def _search_apibay(self, query: str) -> list[dict]:
        """Search Apibay API for the query."""
        results = []
        for cat in self.categories:
            try:
                response = requests.get(
                    API_URL, params={"q": query, "cat": cat}, timeout=10
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException:
                # Silently fail on network/DNS/Cloudflare blocks
                continue
            except ValueError:
                # Silently fail on malformed JSON
                continue

            if not data or (len(data) == 1 and data[0].get("id") == "0"):
                continue

            for item in data:
                item["source"] = "Apibay"
            results.extend(data)
        return results

    def _search_solidtorrents(self, query: str) -> list[dict]:
        """Search SolidTorrents API for the query."""
        results = []
        try:
            response = requests.get(
                "https://solidtorrents.to/api/v1/search",
                params={"q": query, "category": self.solidtorrents_category},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            for r in data.get("results", []):
                results.append({
                    "name": r.get("title", "Unknown"),
                    "info_hash": r.get("infohash", "").lower(),
                    "seeders": str(r.get("swarm", {}).get("seeders", 0)),
                    "leechers": str(r.get("swarm", {}).get("leechers", 0)),
                    "size": str(r.get("size", 0)),
                    "source": "SolidTorrents"
                })
        except Exception:
            pass
        return results

    def search(self, query: str, cli_filters: FilterConfig | None = None) -> list[dict]:
        """Search all enabled engines concurrently, merge, dedupe, and sort by seeds."""
        seen_hashes: set[str] = set()
        merged: list[dict] = []

        active_engines = [e for e in self.engines if e.enabled]
        if not active_engines:
            return []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(active_engines)) as executor:
            future_to_engine = {
                executor.submit(e.search_fn, query): e for e in active_engines
            }
            for future in concurrent.futures.as_completed(future_to_engine):
                try:
                    data = future.result()
                    for item in data:
                        h = item.get("info_hash", "").lower()
                        if h and h not in seen_hashes:
                            seen_hashes.add(h)
                            merged.append(item)
                except Exception:
                    pass

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

        # Sort by seeders descending
        merged.sort(key=lambda x: int(x.get("seeders", 0)), reverse=True)
        return merged
