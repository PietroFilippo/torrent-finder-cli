"""Anime torrent provider — searches video and TV categories."""

import xml.etree.ElementTree as ET
from typing import Callable

import requests

from filters import FilterConfig, FilterPreset
from providers.base import BaseProvider


class AnimeProvider(BaseProvider):
    name = "Anime"
    icon = "🍙"
    categories = [201, 205, 207, 208]  # Movies, TV, HD Movies, HD TV
    solidtorrents_category = "Anime"

    presets = [
        FilterPreset("HD Quality", FilterConfig(quality=["1080p", "720p"])),
        FilterPreset("Dual Audio", FilterConfig(include_keywords=["dual audio"])),
        FilterPreset("Subbed", FilterConfig(include_keywords=["sub"])),
    ]

    def search_engines(self) -> list[Callable[[str], list[dict]]]:
        """Return a list of engine search methods to run concurrently."""
        return [self._search_apibay, self._search_solidtorrents, self._search_nyaa]

    def _parse_nyaa_size(self, size_str: str) -> int:
        """Parse Nyaa size string (e.g. '1.5 GiB') into bytes."""
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

    def _search_nyaa(self, query: str) -> list[dict]:
        """Search Nyaa.si RSS feed for the query."""
        results = []
        try:
            # c=1_2 limits to Anime - English-translated
            response = requests.get(
                "https://nyaa.si/",
                params={"page": "rss", "q": query, "c": "1_2"},
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
                
                if title is not None and info_hash is not None:
                    size_bytes = 0
                    if size is not None and size.text:
                        size_bytes = self._parse_nyaa_size(size.text)
                        
                    results.append({
                        "name": title.text,
                        "info_hash": info_hash.text.lower(),
                        "seeders": seeders.text if seeders is not None else "0",
                        "leechers": leechers.text if leechers is not None else "0",
                        "size": str(size_bytes),
                        "source": "Nyaa"
                    })
        except Exception:
            pass
        return results
