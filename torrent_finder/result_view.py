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


def _surname(author: str) -> str:
    """"austen" from "Jane Austen" or "Austen, Jane"."""
    found = words(author.split(",")[0] if "," in author else author)
    return found[-1] if found else ""


def _latin(tokens) -> bool:
    return any(re.search(r"[a-z]", token) for token in tokens)


def _author_check(authors, listing_author, others) -> int:
    """Score for an exact title once the requested work's *authors* are known."""
    surnames = {surname for surname in map(_surname, authors) if surname}
    if not surnames:
        return 3
    if listing_author is not None:  # an explicit author field (Libgen)
        listed = set(words(listing_author))
        if surnames & listed:
            return 4
        # Only a comparable, clearly different author demotes: another script
        # ("Остин") or a missing author stays neutral.
        return 2 if listed and _latin(listed) and _latin(surnames) else 3
    return 4 if surnames & set(others) else 3  # torrent names: only a match counts


def book_title_score(name: str, query: str, authors: tuple = (), listing_author: "str | None" = None) -> int:
    """``title_score`` for book listings, 0-4.

    Each part of a name can be its title, the rest author or extra details.
    Word counts matter ("Tomorrow and Tomorrow" is a different book from
    "Tomorrow, and Tomorrow, and Tomorrow"), and author words in the query may
    sit beside an exact title, so the original work outranks titles that merely
    contain it ("A Pride and Prejudice Variation"). Format words ("Dune
    audiobook", "... epub") are filters, not part of the title.

    With the requested work's *authors* known, an exact title naming a
    matching author scores 4, and one whose *listing_author* field names a
    clearly different author 2 ("The Name of the Rosé" by Christine Blum).
    """
    wanted_list = tuple(word for word in words(query) if word not in _BOOK_FORMATS) or words(query)
    wanted = Counter(wanted_list)
    if not wanted:
        return 0
    text = media_title(_BOOK_NOISE.sub(" ", name))  # parentheses first: media_title trims a trailing ")"
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
            # Exactly this title, plus any author words the query names.
            return _author_check(authors, listing_author, every - title) if authors else 3
        if part[:len(wanted_list)] == wanted_list:
            best = 2  # the title with a subtitle or edition after it
    if best or wanted - every:
        return best
    return 1  # every query word, counting repeats, appears somewhere


# Release details people type after a title: "Finding Nemo 1080p", "... pt-br", "Dark S02".
_RELEASE_TAGS = re.compile(
    r"\b(?:\d{3,4}p|4k|uhd|x26[45]|h\.?26[45]|hevc|av1|blu-?ray|web-?(?:dl|rip)|remux|hdtv"
    r"|bdrip|dvdrip|hdr(?:10)?|dolby vision|dual[- ]audio|multi[- ]audio|pt-?br|dublado|legendado"
    r"|dubbed|subbed|s\d{1,2}(?:e\d{1,3})?)\b", re.I)
_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                 "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
_ROMAN = ("ii iii iv vi vii viii ix xi xii xiii xiv xv xvi xvii xviii xix xx").split()
_NUMBERS = {**{str(n): word for n, word in enumerate(_NUMBER_WORDS)},
            **{roman: _NUMBER_WORDS[value] for roman, value in zip(_ROMAN, (2, 3, 4, 6, 7, 8, 9, 11, 12, 13,
                                                                             14, 15, 16, 17, 18, 19, 20))}}
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def split_release_tags(query: str) -> tuple[str, tuple[str, ...]]:
    """The title part of a query and the release tags typed with it:
    "Finding Nemo 1080p" → ("Finding Nemo", ("1080p",))."""
    tags = tuple(match.group(0) for match in _RELEASE_TAGS.finditer(query))
    title = " ".join(_RELEASE_TAGS.sub(" ", query).split())
    return (title or query), tags


def release_tag_hits(name: str, query: str) -> int:
    """How many of the release tags typed in *query* the listing *name* carries."""
    name_words = words(name)
    hits = 0
    for tag in split_release_tags(query)[1]:
        tag_words = words(tag)
        span = len(tag_words)
        hits += any(name_words[i:i + span] == tag_words for i in range(len(name_words) - span + 1))
    return hits


def movie_title_score(name: str, query: str) -> int:
    """``title_score`` for movie and TV listings, 0-3.

    Release tags typed with the title don't count against it ("Finding Nemo
    1080p"), numbers match their word or roman form ("Dune Part 2" = "Dune Part
    Two"), and a year in the query must match the listing's year: a remake or
    another film with the same title scores one lower. The original outranks its
    sequels ("The Matrix" over "The Matrix Reloaded").
    """
    title_query = split_release_tags(query)[0]
    wanted_year = next((y for y in _YEAR.findall(title_query) if words(title_query)[:1] != (y,)), None)
    if wanted_year:
        title_query = " ".join(title_query.replace(wanted_year, " ").split()) or title_query
    wanted = tuple(_NUMBERS.get(word, word) for word in words(title_query))
    if not wanted:
        return 0
    title = tuple(_NUMBERS.get(word, word) for word in words(media_title(name)))
    if title == wanted:
        score = 3
    elif title[:len(wanted)] == wanted:
        score = 2
    else:
        score = int(all(word in title for word in wanted))
    years = _YEAR.findall(name)
    if wanted_year and score and years and wanted_year not in years:
        score -= 1
    return score


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
