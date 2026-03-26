"""Abstract base class for torrent search providers."""

from abc import ABC, abstractmethod

import requests

from constants import API_URL, console


class BaseProvider(ABC):
    """Base class that all providers inherit from.

    Each provider defines:
      - name: display label (e.g. "Movies")
      - icon: emoji (e.g. "🎬")
      - categories: list of apibay numeric category IDs to search
    """

    name: str
    icon: str
    categories: list[int]

    @property
    def label(self) -> str:
        return f"{self.icon} {self.name}"

    def search(self, query: str) -> list[dict]:
        """Search apibay across all provider categories, merge, dedupe, and sort by seeds."""
        seen_hashes: set[str] = set()
        merged: list[dict] = []

        for cat in self.categories:
            try:
                response = requests.get(
                    API_URL, params={"q": query, "cat": cat}, timeout=10
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                console.print(f"[error] API request failed: {e}[/error]")
                continue
            except ValueError:
                console.print("[error] Invalid response from API.[/error]")
                continue

            # apibay returns [{"id": "0", ...}] when nothing is found
            if not data or (len(data) == 1 and data[0].get("id") == "0"):
                continue

            for item in data:
                h = item.get("info_hash", "")
                if h and h not in seen_hashes:
                    seen_hashes.add(h)
                    merged.append(item)

        # Sort by seeders descending
        merged.sort(key=lambda x: int(x.get("seeders", 0)), reverse=True)
        return merged
