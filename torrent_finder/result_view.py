"""Title matching and stable result views shared by search and the table."""

import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


SORT_ORDERS = {
    "relevance": "Recommended",
    "seeds": "Most seeders",
    "newest": "Newest uploads (unknown dates last)",
    "name": "Name A–Z",
    "size": "Largest size",
}


def words(text: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKD", text).casefold()
    return tuple(re.findall(r"[^\W_]+", "".join(c for c in folded if not unicodedata.combining(c))))


def media_title(name: str) -> str:
    """Strip common release tags, preserving sequel/subtitle words."""
    name = re.sub(r"\[[^\]]*\]", " ", name)
    name = re.sub(r"\.(?:mkv|mp4|avi|torrent)$", "", name, flags=re.I)
    boundaries = re.finditer(
        r"(?:\b(?:19|20)\d{2}\b|\b\d{3,4}p\b|\bS\d{1,2}(?:E\d+)?\b"
        r"|\b(?:blu[- .]?ray|web[- .]?(?:dl|rip)|bdrip|hdtv|x26[45]|hevc|repack)\b"
        r"|\s+-\s+\d+(?:\b|\s)|\b(?:v\d+\.\d+|build\s+\d+))", name, re.I
    )
    # A title may itself be a year (1917, 1984). Only strip tags after a title.
    for boundary in boundaries:
        if words(name[:boundary.start()]):
            return name[:boundary.start()].strip(" ._-()")
    return name.strip(" ._-()")


def title_score(name: str, query: str) -> int:
    title, wanted = words(media_title(name)), words(query)
    if not wanted:
        return 0
    if title == wanted:
        return 3
    if title[:len(wanted)] == wanted:
        return 2
    return int(all(word in title for word in wanted))


# Book listings: "Title — Author [epub, English]", "Author - Title (Edition)",
# "Title by Author.epub", "Title / Translated title".
_BOOK_PARTS = re.compile(r"\s+(?:—|–|-|/)\s+")
_BOOK_BY = re.compile(r"\s+by\s+", re.I)  # "Title by Author", but also "Stand by Me"
_BOOK_FORMATS = ("epub", "mobi", "pdf", "azw", "azw3", "fb2", "djvu", "cbz", "cbr",
                 "audiobook", "unabridged", "ebook")
_BOOK_NOISE = re.compile(r"\([^()]*\)|\{[^{}]*\}|\.(?:" + "|".join(_BOOK_FORMATS) + r")$"
                         r"|\b(?:" + "|".join(_BOOK_FORMATS) + r")\b", re.I)


def book_title_score(name: str, query: str) -> int:
    """``title_score`` for book listings, 0-3.

    Each part of a name can be its title, the rest author or extra details.
    Word counts matter ("Tomorrow and Tomorrow" is a different book from
    "Tomorrow, and Tomorrow, and Tomorrow"), and author words in the query may
    sit beside an exact title, so the original work outranks titles that merely
    contain it ("A Pride and Prejudice Variation"). Format words ("Dune
    audiobook", "... epub") are filters, not part of the title.
    """
    wanted_list = tuple(word for word in words(query) if word not in _BOOK_FORMATS) or words(query)
    wanted = Counter(wanted_list)
    if not wanted:
        return 0
    text = _BOOK_NOISE.sub(" ", media_title(name))
    every = Counter(words(text))
    parts = []
    for part in _BOOK_PARTS.split(text):
        pieces = _BOOK_BY.split(part)
        parts += [words(part)] + ([words(piece) for piece in pieces] if len(pieces) > 1 else [])
    parts = [part for part in parts if part]
    best = 0
    for part in parts:
        title = Counter(part)
        if not title - wanted and not (wanted - title) - (every - title):
            return 3  # exactly this title, plus any author words the query names
        if part[:len(wanted_list)] == wanted_list:
            best = 2  # the title with a subtitle or edition after it
    if best or wanted - every:
        return best
    return 1  # every query word, counting repeats, appears somewhere


def matches_name(name: str, query: str, mode: str = "contains") -> bool:
    if not query.strip():
        return True
    if mode == "title":
        return words(media_title(name)) == words(query)
    if mode == "filename":
        return name.strip().casefold() == query.strip().casefold()
    return all(word in words(name) for word in words(query))


def timestamp(value) -> int:
    """UTC upload time, or 0 when absent/invalid; never guess from last-seen."""
    try:
        number = max(0, int(value or 0))
        return number if number <= 253402300799 else 0  # datetime's year 9999
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        try:
            date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            date = parsedate_to_datetime(str(value))
        return max(0, int(date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp()))
    except (ValueError, TypeError, OverflowError, OSError):
        return 0


def result_indices(results, query: str = "", mode: str = "contains", order: str = "relevance") -> list[int]:
    """Return original indexes, so sorting/filtering cannot change a picked row."""
    indexes = [i for i, row in enumerate(results) if matches_name(row.get("name", ""), query, mode)]
    if order == "name":
        indexes.sort(key=lambda i: results[i].get("name", "").casefold())
    elif order in ("newest", "seeds", "size"):
        field = {"newest": "uploaded_at", "seeds": "seeders", "size": "size"}[order]
        def numeric(i):
            value = results[i].get(field)
            if order == "newest":
                return timestamp(value)
            try:
                return max(0, int(value or 0))
            except (ValueError, TypeError, OverflowError):
                return 0
        indexes.sort(key=numeric, reverse=True)
    return indexes
