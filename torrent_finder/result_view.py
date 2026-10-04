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
_ROMAN_VALUES = dict(zip(_ROMAN, (2, 3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20)))
_NUMBERS = {**{str(n): word for n, word in enumerate(_NUMBER_WORDS)},
            **{roman: _NUMBER_WORDS[value] for roman, value in _ROMAN_VALUES.items()}}
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


# Source and platform words people add to a game title; dedicated game sites
# search their own catalog, where these words only hide the game.
_GAME_EXTRAS = re.compile(r"\b(?:fit\s?girl|dodi|elamigos|online[- ]?fix|repacks?|linux|windows|win(?:32|64)?"
                          r"|macos|mac|osx|pc)\b", re.I)


def game_title_query(query: str) -> str:
    """The game title in a query, without source/platform words:
    "Cyberpunk 2077 fitgirl" → "Cyberpunk 2077", "Stardew Valley linux" → "Stardew Valley"."""
    return " ".join(_GAME_EXTRAS.sub(" ", query).split()) or query


_DIGIT_ROMANS = {**{value: roman.upper() for roman, value in _ROMAN_VALUES.items()}, 5: "V", 10: "X"}


def number_variant(query: str) -> "str | None":
    """The query with its final number written the other common way: Roman
    numerals as digits ("Civilization VI" → "Civilization 6"), digits as Roman
    numerals ("Final Fantasy 7" → "Final Fantasy VII", "Grand Theft Auto 5" →
    "Grand Theft Auto V"). None when the query does not end in such a number.
    Lone "V"/"X" stay as typed: they are often letters ("Mega Man X")."""
    parts = query.split()
    if len(parts) < 2:
        return None
    last = parts[-1].casefold()
    if last in _ROMAN_VALUES:
        swapped = str(_ROMAN_VALUES[last])
    elif last.isdigit() and int(last) in _DIGIT_ROMANS:
        swapped = _DIGIT_ROMANS[int(last)]
    else:
        return None
    return " ".join([*parts[:-1], swapped])


_POSSESSIVE = re.compile(r"\b([^\W\d_]{3,})(?:['’]s|s)\b")


def possessive_variant(query: str) -> "str | None":
    """The query with possessive and plural endings dropped ("Baldur's Gate 3",
    "Baldurs Gate 3" → "Baldur Gate 3"), or None when nothing changes. A site that
    matches text fragments then finds "Baldur’s" however the apostrophe was typed."""
    stem = _POSSESSIVE.sub(r"\1", query)
    return stem if stem != query else None


def _compact_words(text: str) -> tuple[str, ...]:
    """``words`` that ignore apostrophes: "Baldur’s" and "Baldurs" are one word."""
    return words(re.sub(r"['’`´]", "", text))


# What may follow a program's name without making it another program: versions,
# years, editions, platforms, languages and packaging ("Photoshop 2024 (x64)",
# "OBS Studio", "MATLAB R2024a"). Another name word means another product
# ("Photoshop Lightroom", "Photoshop Elements", "Ableton Live Packs").
_PRODUCT_DETAIL = re.compile(
    r"\d.*|v\d.*|r\d{4}\w*|cs\d*|x64|x86|amd64|arm64|aarch64|universal"
    r"|win|windows|mac|macos|osx|linux|android|ios|apk|obb|mod|modded|unlocked"
    r"|cc|pro|plus|premium|ultimate|enterprise|professional|business|home|standard|studio|suite"
    r"|producer|signature|deluxe|complete|x|pe|hd|lite|free|paid|prime|vip|gold"
    r"|portable|repack|repacked|multilingual|multilang|multi"
    r"|multilanguage|english|eng|en|ru|rus|pt|br|ptbr|portugues|portuguese|brasil|espanol|spanish|french"
    r"|francais|german|deutsch|italian|italiano|russian|final|full|retail|stable|lts|beta|build|release"
    r"|latest|edition"
    r"|version|ver|update|updated|setup|installer|offline|crack|cracked|keygen|patch|patched|activated"
    r"|preactivated|pre|activator|incl|including|with|for|and|by|iso|dmg|exe|msi|zip|rar|appimage|deb|rpm"
)


# Before a product name, these make the listing an add-on for it ("Lucky Block
# Mod for Minecraft", "Actions for Photoshop").
_ADDON_LINKS = frozenset({"for", "to", "into", "with"})
_ASIDES = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}")


def product_title_score(name: str, query: str) -> int:
    """How well a program listing matches the searched product (3, 1 or 0).

    The query is a product name, then optional details ("Photoshop 2024").
    3: outside brackets, the name is followed by details only (version,
    edition, platform…), is not an add-on "for" it, and the typed details
    appear anywhere; 1: a longer product contains the name ("Photoshop" in
    "Photoshop Lightroom", "Pocket Minecraft Edition" in parentheses), or every
    word appears apart; 0: words are missing.
    """
    wanted, have = _compact_words(query), _compact_words(name)
    if not wanted:
        return 0
    span = next((i for i, word in enumerate(wanted) if i and _PRODUCT_DETAIL.fullmatch(word)), len(wanted))
    product, details = wanted[:span], wanted[span:]
    title = _compact_words(_ASIDES.sub(" ", name))
    if all(word in have for word in details):
        for start in range(len(title) - span + 1):
            if title[start:start + span] == product and (start == 0 or title[start - 1] not in _ADDON_LINKS):
                after = title[start + span] if start + span < len(title) else None
                if after is None or _PRODUCT_DETAIL.fullmatch(after):
                    return 3
    return 1 if all(word in have for word in wanted) else 0


_UNIT_WORDS = {word: n for n, word in enumerate(_NUMBER_WORDS[:20])}
_TEN_WORDS = {word: 10 * n for n, word in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
_UNIT_ORDINALS = {word: n for n, word in enumerate(
    ("zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
     "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth").split())}
_TEN_ORDINALS = {word: 10 * n for n, word in enumerate(
    "twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth".split(), 2)}
_LARGE_NUMBERS = {"thousand", "million", "billion"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _number_at(words, i):
    """(digits, length) of a spelled-out number starting at words[i], or None."""
    value, j = 0, i

    def word(k):
        return words[k] if k < len(words) else ""

    if word(j) in _UNIT_WORDS and 0 < _UNIT_WORDS[word(j)] < 10 and word(j + 1) in ("hundred", "hundredth"):
        value, j = _UNIT_WORDS[word(j)] * 100, j + 1
    if word(j) == "hundredth":
        return _ordinal(value or 100), j + 1 - i
    if word(j) == "hundred":
        value, j = value or 100, j + 1
        later = word(j + 1)
        if word(j) == "and" and (later in _UNIT_WORDS or later in _TEN_WORDS
                                 or later in _UNIT_ORDINALS or later in _TEN_ORDINALS):
            j += 1
    if word(j) in _TEN_WORDS:
        value, j = value + _TEN_WORDS[word(j)], j + 1
        if word(j) in _UNIT_WORDS and 0 < _UNIT_WORDS[word(j)] < 10:
            return str(value + _UNIT_WORDS[word(j)]), j + 1 - i
        if word(j) in _UNIT_ORDINALS and 0 < _UNIT_ORDINALS[word(j)] < 10:
            return _ordinal(value + _UNIT_ORDINALS[word(j)]), j + 1 - i
        return str(value), j - i
    if word(j) in _TEN_ORDINALS:
        return _ordinal(value + _TEN_ORDINALS[word(j)]), j + 1 - i
    if word(j) in _UNIT_WORDS:
        return str(value + _UNIT_WORDS[word(j)]), j + 1 - i
    if word(j) in _UNIT_ORDINALS:
        return _ordinal(value + _UNIT_ORDINALS[word(j)]), j + 1 - i
    return (str(value), j - i) if j > i else None


def digit_spelling(query: str) -> "str | None":
    """The query with spelled-out numbers in digits ("Twenty First Century Boys"
    → "21st Century Boys", "Mob Psycho Hundred" → "Mob Psycho 100", "Catch-
    Twenty-Two" → "Catch-22"), or None when it has none. A number before
    "thousand" or "million" stays as typed."""
    pieces = re.findall(r"(^|\s+|-)([^\s-]+)", query)  # (separator, token), hyphens split too
    words = [token.casefold().strip(".,:;!?()[]") for _sep, token in pieces]
    out, i, changed = [], 0, False
    while i < len(pieces):
        found = _number_at(words, i)
        if found and i + found[1] < len(words) and words[i + found[1]] in _LARGE_NUMBERS:
            found = None
        if found:
            digits, length = found
            last = pieces[i + length - 1][1]
            tail = last[len(last.rstrip(".,:;!?)]")):]
            out.append(pieces[i][0] + digits + tail)
            i, changed = i + length, True
        else:
            out.append(pieces[i][0] + pieces[i][1])
            i += 1
    return "".join(out).strip() if changed else None


def same_title(first: str, second: str) -> bool:
    """Equal titles, ignoring case, accents, punctuation and apostrophes."""
    return bool(_compact_words(first)) and _compact_words(first) == _compact_words(second)


def matches_name(name: str, query: str, mode: str = "contains") -> bool:
    if not query.strip():
        return True
    if mode == "title":
        return words(media_title(name)) == words(query)
    if mode == "filename":
        return name.strip().casefold() == query.strip().casefold()
    # "Baldurs" finds "Baldur’s", and "Baldur's" still finds "Baldur.s".
    found = set(words(name)) | set(_compact_words(name))
    return (all(word in found for word in _compact_words(query))
            or all(word in found for word in words(query)))


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
