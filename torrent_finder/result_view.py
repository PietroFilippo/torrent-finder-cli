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


_YEAR_TOKEN = re.compile(r"\b(?:19|20)\d{2}\b")


def media_title(name: str, keep=()) -> str:
    """Strip common release tags, preserving sequel/subtitle words.

    Numbers the searched title has (*keep*, its words: "Cyberpunk 2077",
    "1984") are title words, not years or episodes. Of several bare years only
    the last is the release year: "Blade Runner 2049 (2017)" keeps "2049"."""
    keep = set(keep)
    name = re.sub(r"\[[^\]]*\]", " ", name)
    name = re.sub(r"\.(?:mkv|mp4|avi|torrent)$", "", name, flags=re.I)
    years = [match.start() for match in _YEAR_TOKEN.finditer(name)]
    boundaries = re.finditer(
        r"(?:\b(?:19|20)\d{2}\b|\b\d{3,4}p\b|\bS\d{1,2}(?:E\d+)?\b"
        r"|\b(?:blu[- .]?ray|web[- .]?(?:dl|rip)|bdrip|hdtv|x26[45]|hevc|repack)\b"
        r"|\s+-\s+\d+(?:\b|\s)|\b(?:v\d+\.\d+|build\s+\d+))", name, re.I
    )
    # A title may itself be a year (1917, 1984). Only strip tags after a title.
    for boundary in boundaries:
        text = boundary.group(0)
        if keep and words(text) and set(words(text)) <= keep:
            continue  # the searched title's own number
        if _YEAR_TOKEN.fullmatch(text) and any(start > boundary.start() for start in years):
            ranged = re.match(r"\s*[-–]\s*(?:19|20)\d{2}\b", name[boundary.end():])
            if not ranged and not name[:boundary.start()].rstrip().endswith(("(", "[")):
                continue  # a later year is the release year
        if words(name[:boundary.start()]):
            return name[:boundary.start()].strip(" ._-()")
    return name.strip(" ._-()")


def title_score(name: str, query: str) -> int:
    wanted = words(query)
    title = words(media_title(name, wanted))
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


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _surname(author: str) -> str:
    """"austen" from "Jane Austen" or "Austen, Jane"; "miller" from "Walter M. Miller Jr."."""
    found = [word for word in words(author.split(",")[0] if "," in author else author)
             if word not in _NAME_SUFFIXES]
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
        requested = {word for author in authors for word in words(author)}
        # Either name order: "Cervantes, Miguel de" for "Miguel de Cervantes Saavedra".
        if surnames & listed or _surname(listing_author) in requested:
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
    text = media_title(_BOOK_NOISE.sub(" ", name), wanted_list)  # parentheses first: media_title trims a trailing ")"
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
        compact = "".join(words(tag))  # "ptbr" = "PT-BR", "h264" = "H.264", "bluray" = "Blu-Ray"
        hits += any("".join(name_words[i:i + span]) == compact
                    for span in (1, 2, 3) for i in range(len(name_words) - span + 1))
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
    keep = words(title_query)
    score = 0
    # "Город бога / Cidade de Deus / City of God [2002, …]": each part is a title.
    # Release details follow the first bracket there: "… [1999, …] Dub + Sub".
    parts = [re.split(r"\s\[", part, maxsplit=1)[0] for part in re.split(r"\s+/\s+", name)]
    for part in [name, *parts] if len(parts) > 1 else [name]:
        title = tuple(_NUMBERS.get(word, word) for word in words(media_title(part, keep)))
        if title == wanted:
            score = max(score, 3)
        elif title[:len(wanted)] == wanted:
            score = max(score, 2)
        else:
            score = max(score, int(all(word in title for word in wanted)))
    years = _YEAR.findall(name)
    if wanted_year and score and years and wanted_year not in years:
        score -= 1
    return score


# Source and platform words people add to a game title; dedicated game sites
# search their own catalog, where these words only hide the game. Platform
# words count only at the end: "PC Building Simulator" is a title.
_GAME_SOURCES = re.compile(r"\b(?:fit\s?girl|dodi|elamigos|online[- ]?fix|repacks?)\b", re.I)
_GAME_PLATFORMS = re.compile(r"(?:\s+(?:linux|windows|win(?:32|64)?|macos|mac|osx|pc))+\s*$", re.I)


def game_title_query(query: str) -> str:
    """The game title in a query, without source/platform words:
    "Cyberpunk 2077 fitgirl" → "Cyberpunk 2077", "Stardew Valley linux" → "Stardew Valley"."""
    title = " ".join(_GAME_SOURCES.sub(" ", query).split())
    return _GAME_PLATFORMS.sub("", " " + title).strip() or title or query


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


_POSSESSIVE = re.compile(r"\b([^\W\d_]{3,})(?:['’\u02bc]s|s)\b")


def possessive_variant(query: str) -> "str | None":
    """The query with possessive and plural endings dropped ("Baldur's Gate 3",
    "Baldurs Gate 3" → "Baldur Gate 3"), or None when nothing changes. A site that
    matches text fragments then finds "Baldur’s" however the apostrophe was typed."""
    stem = _POSSESSIVE.sub(r"\1", query)
    return stem if stem != query else None


def _compact_words(text: str) -> tuple[str, ...]:
    """``words`` that ignore apostrophes: "Baldur’s" and "Baldurs" are one word."""
    return words(re.sub(r"['’`´\u02bc]", "", text))


# What may follow a program's name without making it another program: versions,
# years, editions, platforms, languages and packaging ("Photoshop 2024 (x64)",
# "OBS Studio", "MATLAB R2024a"). Another name word means another product
# ("Photoshop Lightroom", "Photoshop Elements", "Ableton Live Packs").
_PRODUCT_DETAIL = re.compile(
    r"\d.*|v\d.*|v|r\d{4}\w*|cs\d*|x64|x86|amd64|arm64|aarch64|universal"
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
    appear anywhere; 2: the listing starts with the name and continues with
    another word ("Minecraft Pocket Edition", "VLC Media Player"); 1: the name
    sits inside another product ("Adobe Photoshop Lightroom", "Pixel Gun 3D
    (Pocket Minecraft Edition)", "Mod for Minecraft"), or every word appears
    apart; 0: words are missing.
    """
    wanted, have = _compact_words(query), _compact_words(name)
    if not wanted:
        return 0
    span = next((i for i, word in enumerate(wanted) if i and _PRODUCT_DETAIL.fullmatch(word)), len(wanted))
    if all(word.isdigit() for word in wanted[:span]):
        span = min(len(wanted), span + 1)  # "7 Zip": the number is part of the name
    product, details = wanted[:span], wanted[span:]
    joined = "".join(product)  # "7zip" for "7-Zip"
    title = _compact_words(_ASIDES.sub(" ", name))
    best = 0
    if all(word in have for word in details):
        for start in range(len(title)):
            if title[start:start + span] == product:
                length = span
            elif span > 1 and title[start] == joined:
                length = 1
            else:
                continue
            if any(word in _ADDON_LINKS for word in title[max(0, start - 2):start]):
                continue  # an add-on: "Plugins for Adobe Photoshop"
            after = title[start + length] if start + length < len(title) else None
            if after is None or _PRODUCT_DETAIL.fullmatch(after):
                return 3
            if start == 0:
                best = 2
    if best:
        return best
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
    Twenty-Two" → "Catch-22", "Nineteen Eighty-Four" → "1984"), or None when it
    has none. Titles with "thousand" or "million" stay as typed ("One Thousand
    and One Nights")."""
    pieces = re.findall(r"(^|\s+|-)([^\s-]+)", query)  # (separator, token), hyphens split too
    words = [token.casefold().strip(".,:;!?()[]") for _sep, token in pieces]
    if _LARGE_NUMBERS & set(words):
        return None
    out, i, changed = [], 0, False
    while i < len(pieces):
        found = _number_at(words, i)
        if found:
            digits, length = found
            pair = _number_at(words, i + length) if digits.isdigit() and 10 <= int(digits) <= 99 else None
            if pair and pair[0].isdigit() and int(pair[0]) <= 99:
                digits, length = f"{digits}{int(pair[0]):02d}", length + pair[1]  # a year: "Nineteen Eighty-Four"
            first, last = pieces[i][1], pieces[i + length - 1][1]
            lead = first[:len(first) - len(first.lstrip("([{"))]
            tail = last[len(last.rstrip(".,:;!?)]}")):]
            out.append(pieces[i][0] + lead + digits + tail)
            i, changed = i + length, True
        else:
            out.append(pieces[i][0] + pieces[i][1])
            i += 1
    return "".join(out).strip() if changed else None


# Hepburn syllables: a word made only of them is romanized Japanese.
_ROMAJI_WORD = re.compile(r"(?:(?:ky|gy|sh|ch|ny|hy|by|py|my|ry|ts|j|[kgsztdnhbpmyrwf])?[aiueo]|n)+")


def _long_vowel_word(word: str) -> bool:
    """A romanized word whose ou/oo/uu is most likely a long vowel: "Hishouden",
    "Kyoujin", "Ryuu", "Shoujo"; not English words such as "house" or "you"."""
    low = word.casefold()
    return (bool(_ROMAJI_WORD.fullmatch(low)) and re.search(r"ou|oo|uu", low) is not None
            and (len(low) >= 6 or (len(low) >= 4 and low.endswith(("ou", "uu")))))


def _shorten(word: str) -> str:
    return re.sub(r"(?i)(o)[ou]|(u)u", lambda m: m.group(1) or m.group(2), word) if _long_vowel_word(word) else word


def short_vowel_spelling(query: str) -> "str | None":
    """The query with romanized long vowels written short ("Shingeki no Kyoujin"
    → "Shingeki no Kyojin", "Mahjong Hishouden" → "Mahjong Hishoden"). Sources
    use either spelling and match only their own. None when nothing changes."""
    spelled = re.sub(r"[A-Za-z]+", lambda m: _shorten(m.group(0)), query)
    return spelled if spelled != query else None


def _spelling_words(text: str) -> tuple[str, ...]:
    """Words as spelled, apostrophes ignored and hyphens inside words joined."""
    return _compact_words(re.sub(r"(?<=[^\W\d_])-(?=[^\W\d_])", "", text))


def _name_words(text: str) -> tuple[str, ...]:
    """Words for comparing names across spellings: apostrophes ignored, hyphens
    inside words joined ("Hishou-den"), romanized long vowels written short."""
    return tuple(_shorten(word) for word in _spelling_words(text))


def same_spelling(first: str, second: str) -> bool:
    """Equal as searched: case, accents, punctuation, apostrophes and hyphens
    inside words aside, but "Hishouden" and "Hishoden" differ (a source finds
    only one of them)."""
    return bool(_spelling_words(first)) and _spelling_words(first) == _spelling_words(second)


def same_title(first: str, second: str) -> bool:
    """Equal titles, ignoring case, accents, punctuation, apostrophes, hyphens
    inside words and romanized long vowels ("Mahjong Hishouden: Naki no Ryuu" =
    "Mahjong Hishou-den Naki no Ryuu" = "Mahjong Hishoden Naki no Ryuu")."""
    words_first = _name_words(first)
    return bool(words_first) and words_first == _name_words(second)


def title_starts_with(title: str, query: str) -> bool:
    """*title* begins with the words of *query* (at least two) and goes on
    before any subtitle, compared like ``same_title``: "Mahjong Hishoden" starts
    "Mahjong Hishoden Naki no Ryuu". A franchise name before a subtitle doesn't
    count: "Koukaku Kidoutai" names more than "Koukaku Kidoutai: Stand Alone …"."""
    head = re.split(r"\s*:\s*|\s+[-–—]\s+", title, maxsplit=1)[0]
    wanted, have = _name_words(query), _name_words(head)
    return len(wanted) >= 2 and len(have) > len(wanted) and have[:len(wanted)] == wanted


def contains_title(title: str, part: str) -> bool:
    """*part* is a run of consecutive words of *title*, compared like ``same_title``."""
    wanted, have = _name_words(part), _name_words(title)
    return bool(wanted) and any(have[i:i + len(wanted)] == wanted for i in range(len(have) - len(wanted) + 1))


def reduced_title(query: str) -> "str | None":
    """The query without the romanized words that may hide a long vowel, and
    without particles ("Tate no Yusha no Nariagari" → "Tate Nariagari"), for a
    catalog search when the full spelling found nothing. None when too little
    or nothing would be removed."""
    kept = [word for word in query.split()
            if not (_ROMAJI_WORD.fullmatch(word.casefold().strip(".,:;!?")) and
                    (len(word.strip(".,:;!?")) <= 2 or re.search(r"[ou]", word, re.I)))]
    reduced = " ".join(kept)
    return reduced if reduced != query and len(re.sub(r"\W", "", reduced)) >= 4 else None


def matches_name(name: str, query: str, mode: str = "contains") -> bool:
    if not query.strip():
        return True
    if mode == "title":
        return words(media_title(name, words(query))) == words(query)
    if mode == "filename":
        return name.strip().casefold() == query.strip().casefold()
    # "Baldurs" finds "Baldur’s", and "Baldur's" still finds "Baldur.s".
    found = set(words(name)) | set(_compact_words(name))
    return (all(word in found for word in _compact_words(query))
            or all(word in found for word in words(query)))


def timestamp(value) -> int:
    """UTC upload time, or 0 when absent/invalid; never guess from last-seen.

    A time this platform cannot turn back into a date (Windows stops at the
    year 3000) is invalid too, so every screen can show what this accepts.
    """
    try:
        number = max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        try:
            try:
                date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                date = parsedate_to_datetime(str(value))
            number = max(0, int(date.replace(tzinfo=date.tzinfo or timezone.utc).timestamp()))
        except (ValueError, TypeError, OverflowError, OSError):
            return 0
    try:
        datetime.fromtimestamp(number, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return 0
    return number


# What a title score means, for the "Ranked:" note under a focused result.
TITLE_REASONS = {4: "exact title and author", 3: "exact title", 2: "title starts with the search",
                 1: "every searched word", 0: "title differs from the search"}


def ranking_notes(provider, queries):
    """``describe(row) -> (reason, preferred preset names)`` for the results table.

    The reason names how well the row's title matches the searched one (only
    for providers ranked by title, scored by the row's own provider) and the
    preferred presets it matches, which also break ties.
    """
    from torrent_finder.filters import apply_filters
    queries = [query for query in queries or () if query and query.strip()]
    combined = getattr(provider, "is_combined", False)
    children = {child.slug: child for child in provider.children} if combined else {}

    def describe(row):
        owner = children.get(row.get("provider_slug"), provider) if combined else provider
        preferred = tuple(preset.name for preset in getattr(owner, "preferred_presets", ())
                          if preset not in getattr(owner, "active_presets", ())
                          and apply_filters([row], preset.config))
        reason = ""
        if queries and (combined or getattr(owner, "prefer_title_matches", False)):
            try:
                reason = TITLE_REASONS.get(max(owner.title_relevance(row, query) for query in queries), "")
            except Exception:  # a dict row (a saved bookmark) or a scorer problem: no title note
                reason = ""
        if preferred:
            reason = ", ".join(filter(None, (reason, "prefers " + ", ".join(preferred))))
        return reason, preferred

    return describe


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
