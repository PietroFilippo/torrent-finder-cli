"""Typed search result contract.

Search producers historically returned plain dicts with a shared loose shape
plus source-specific handle keys. ``SearchResult`` makes the common fields
explicit while still behaving like a mapping for the existing UI and acquisition
code. Source-specific identifiers live in ``handle`` but remain readable through
their legacy keys during the migration.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any


HANDLE_KEYS = frozenset({
    "rt_topic_id",
    "fg_post_url",
    "of_post_url",
    "mdk_path",
    "lg_md5",
})

_FIELD_KEYS = {
    "name": "name",
    "info_hash": "info_hash",
    "seeders": "seeders",
    "leechers": "leechers",
    "size": "size",
    "source": "source",
    "page_url": "page_url",
    "from_work": "from_work",
}

_FIELD_DEFAULTS = {
    "name": "Unknown",
    "info_hash": "",
    "seeders": 0,
    "leechers": 0,
    "size": 0,
    "source": "",
    "page_url": "",
    "from_work": "",
}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return text if text else default


@dataclass
class SearchResult(MutableMapping[str, Any]):
    name: str = "Unknown"
    info_hash: str = ""
    seeders: int = 0
    leechers: int = 0
    size: int = 0
    source: str = ""
    page_url: str = ""
    from_work: str = ""
    handle: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = _as_str(self.name, "Unknown")
        self.info_hash = _as_str(self.info_hash)
        self.seeders = _as_int(self.seeders)
        self.leechers = _as_int(self.leechers)
        self.size = _as_int(self.size)
        self.source = _as_str(self.source)
        self.page_url = _as_str(self.page_url)
        self.from_work = _as_str(self.from_work)
        self.handle = dict(self.handle or {})
        self.extra = dict(self.extra or {})

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any] | "SearchResult") -> "SearchResult":
        if isinstance(row, SearchResult):
            return row

        fields: dict[str, Any] = {}
        handle: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for key, value in row.items():
            if key in _FIELD_KEYS:
                fields[key] = value
            elif key == "handle" and isinstance(value, Mapping):
                handle.update(dict(value))
            elif key == "extra" and isinstance(value, Mapping):
                extra.update(dict(value))
            elif key in HANDLE_KEYS:
                handle[key] = value
            else:
                extra[key] = value

        return cls(**fields, handle=handle, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        data = {key: getattr(self, attr) for key, attr in _FIELD_KEYS.items()}
        data["handle"] = dict(self.handle)
        data.update(self.handle)
        data.update(self.extra)
        return data

    def __getitem__(self, key: str) -> Any:
        if key in _FIELD_KEYS:
            return getattr(self, _FIELD_KEYS[key])
        if key == "handle":
            return self.handle
        if key == "extra":
            return self.extra
        if key in self.handle:
            return self.handle[key]
        if key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in _FIELD_KEYS:
            if key in ("seeders", "leechers", "size"):
                value = _as_int(value)
            elif key == "name":
                value = _as_str(value, "Unknown")
            else:
                value = _as_str(value)
            setattr(self, _FIELD_KEYS[key], value)
            return
        if key == "handle":
            self.handle = dict(value or {})
            return
        if key == "extra":
            self.extra = dict(value or {})
            return
        if key in HANDLE_KEYS:
            self.handle[key] = value
            return
        self.extra[key] = value

    def __delitem__(self, key: str) -> None:
        if key in _FIELD_KEYS:
            self[key] = _FIELD_DEFAULTS[key]
            return
        if key == "handle":
            self.handle.clear()
            return
        if key == "extra":
            self.extra.clear()
            return
        if key in self.handle:
            del self.handle[key]
            return
        if key in self.extra:
            del self.extra[key]
            return
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        yield from _FIELD_KEYS
        if self.handle:
            yield "handle"
        for key in self.handle:
            if key not in _FIELD_KEYS:
                yield key
        for key in self.extra:
            if key not in _FIELD_KEYS and key not in self.handle:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key == "from_work" and not self.from_work:
            self.from_work = _as_str(default)
            return self.from_work
        try:
            return self[key]
        except KeyError:
            self[key] = default
            return default


def normalize_result(row: Mapping[str, Any] | SearchResult) -> SearchResult:
    return SearchResult.from_mapping(row)


def normalize_results(rows: list[Mapping[str, Any] | SearchResult]) -> list[SearchResult]:
    return [normalize_result(row) for row in rows]
