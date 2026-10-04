"""The Quiet look shared by every screen: palette, header line and key bar.

Screens draw no boxes. A header line names the app and the current screen,
content sits under a two-cell margin, and one key bar lists the keys as
``key action`` pairs. The terminal's own bright blue carries focus, keys and
the brand; three fixed shades of blue give headings, secondary text and rules
their own weight. See docs/adr/0020-quiet-terminal-design.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.text import Text

APP_NAME = "torrent-finder"
MARGIN = "  "
CURSOR = "▍"
CHECK = "✓"
UNCHECKED = "•"
MARKER = "◆"
CRUMB = " › "
KEY_GAP = "   "

# One blue scale, each shade with one job. The accent is the terminal's own
# bright blue so it matches the user's palette; the three fixed shades sit
# around it (tuned to Windows Terminal's Campbell blue) and degrade to the
# nearest named colour on terminals without true colour.
ACCENT = "bright_blue"    # focus: the cursor bar, the focused row, keys, the brand
SKY = "#7DAEFF"           # light: section and column headings, the subject of a screen
STEEL = "#6A86B3"         # blue-grey: labels, hints, separators, Off, disabled rows
DEEP = "#3A5A8C"          # dark: rules
KEY = f"bold {ACCENT}"
MUTED = STEEL
GOOD = "green"
WARN = "yellow"
BAD = "red"
SECTION = f"bold {SKY}"   # uppercase section headers and table column headers
FOCUS = f"bold {ACCENT}"
BRAND = f"bold {ACCENT}"  # the app name in every header
SCREEN = "bold"           # the screen name after it
SUBJECT = f"not bold {SKY}"  # what the screen is about: the query, torrent or provider after the name
RULE = "─"
RULE_STYLE = DEEP

# Rich theme entries; constants.custom_theme registers these so markup such as
# "[muted]…[/muted]" works in every console that renders the app.
STYLES = {
    "accent": ACCENT,
    "key": KEY,
    "muted": MUTED,
    "sky": SKY,
    "good": GOOD,
    "warn": WARN,
    "bad": BAD,
    "section": SECTION,
    # Message styles used by console output across the app.
    "title": "bold",
    "info": MUTED,
    "success": GOOD,
    "warning": WARN,
    "error": f"bold {BAD}",
    "highlight": "bold",
    # Rich's own spinners and progress bars follow the palette.
    "status.spinner": ACCENT,
    "bar.complete": ACCENT,
    "bar.finished": GOOD,
    "bar.pulse": ACCENT,
    "progress.percentage": ACCENT,
    "progress.remaining": MUTED,
    "progress.elapsed": MUTED,
}

_STATE_STYLES = {
    "on": GOOD,
    "auto": WARN,
    "off": MUTED,
    "require": f"bold {ACCENT}",
    "prefer": ACCENT,
}


def state_style(state: str) -> str:
    """Colour for a named toggle state (engine On/Auto/Off, preset Require/Prefer)."""
    return _STATE_STYLES.get(state.strip().casefold(), "")


def inner_width(width: int) -> int:
    """Cells left for content once both margins are taken."""
    return max(8, width - 2 * len(MARGIN))


def _as_text(value: str | Text) -> Text:
    return value.copy() if isinstance(value, Text) else Text.from_markup(value)


def _title_text(title: str | Text) -> Text:
    """``Screen › subject``: the screen name bold, what it is about in the light blue.

    Later crumbs (a query, a torrent name, a provider, a folder path) are the
    subject; the separators between them are muted like the one after the app
    name.
    """
    crumb = _as_text(title)
    styled = Text(style=SCREEN)  # base style; the title's own markup still wins
    styled.append_text(crumb)
    first = crumb.plain.find(CRUMB)
    if first >= 0:
        styled.stylize(SUBJECT, first + len(CRUMB))
        for match in re.finditer(re.escape(CRUMB), crumb.plain):
            styled.stylize(f"not bold {MUTED}", match.start(), match.end())
    return styled


def _header_left(title: str | Text) -> Text:
    left = Text(MARGIN)
    left.append(APP_NAME, style=BRAND)
    if title:
        crumb = _as_text(title)
        if crumb.plain.strip():
            left.append(CRUMB, style=MUTED)
            left.append_text(_title_text(crumb))
    return left


def rule(width: int, margin: str = MARGIN) -> Text:
    """A thin dark-blue line across the content width: under headers, above key bars."""
    return Text(margin + RULE * max(1, width - 2 * len(margin)), style=RULE_STYLE, no_wrap=True)


def _cut_index(plain: str, limit: int, floor: int) -> int:
    """Index to break *plain* within *limit* cells, at a space after *floor* if possible."""
    end, cells = 0, 0
    for end, char in enumerate(plain):
        cells += cell_len(char)
        if cells > limit:
            break
    else:
        return len(plain)
    space = plain.rfind(" ", floor, end + 1)
    return space if space > floor else max(1, end)


def header_lines(title: str | Text = "", status: str | Text = "", width: int = 80) -> list[Text]:
    """The header line; a long title continues on a second, indented line.

    Narrow windows keep the whole screen name instead of cutting it. The
    status sits at the right of the last line.
    """
    left = _header_left(title)
    right = _as_text(status) if status else Text()
    usable = max(1, width - len(MARGIN))
    needed = cell_len(left.plain) + (cell_len(right.plain) + 2 if right.plain else 0)
    if needed <= usable or width < 24:
        return [header(title, status, width)]
    right.stylize(MUTED)
    if cell_len(left.plain) <= usable:
        first, rest = left, Text()
    else:
        floor = len(MARGIN) + len(APP_NAME) + len(CRUMB)
        cut = _cut_index(left.plain, usable, floor)
        first, rest = left[:cut], strip_text(left[cut:])
    first.no_wrap, first.overflow = True, "ellipsis"
    if cell_len(first.plain) > usable:
        first.truncate(usable, overflow="ellipsis")
    second = Text(MARGIN + "  ", no_wrap=True, overflow="ellipsis")
    second.append_text(rest)
    if right.plain:
        # The screen name keeps up to two thirds of the line; the status gets
        # the rest, cut from its end, and gives way entirely when tiny.
        title_need = min(cell_len(second.plain), max(len(MARGIN) + 3, usable * 2 // 3))
        status_room = usable - title_need - 2
        if status_room < min(cell_len(right.plain), 6):
            right = Text()
        elif cell_len(right.plain) > status_room:
            right.truncate(status_room, overflow="ellipsis")
    room = usable - (cell_len(right.plain) + 2 if right.plain else 0)
    if cell_len(second.plain) > room:
        second.truncate(max(len(MARGIN) + 3, room), overflow="ellipsis")
    if right.plain:
        second.append(" " * max(2, usable - cell_len(second.plain) - cell_len(right.plain)))
        second.append_text(right)
    return [first, second] if second.plain.strip() else [first]


def header(title: str | Text = "", status: str | Text = "", width: int = 80) -> Text:
    """``  torrent-finder › Title ......... status  `` fitted to one line of *width* cells."""
    left = _header_left(title)
    right = _as_text(status) if status else Text()
    if right.plain:
        right.stylize(MUTED)
    usable = max(1, width - len(MARGIN))
    if right.plain:
        room = usable - cell_len(left.plain) - 2
        if room < min(cell_len(right.plain), 12):
            # Not enough room: the screen name matters more than the status.
            right.truncate(max(0, min(cell_len(right.plain), usable // 3)), overflow="ellipsis")
        elif cell_len(right.plain) > room:
            right.truncate(room, overflow="ellipsis")
    left_room = usable - (cell_len(right.plain) + 2 if right.plain else 0)
    if cell_len(left.plain) > left_room:
        left.truncate(max(1, left_room), overflow="ellipsis")
    line = Text(no_wrap=True, overflow="ellipsis")
    line.append_text(left)
    if right.plain:
        gap = usable - cell_len(left.plain) - cell_len(right.plain)
        line.append(" " * max(1, gap))
        line.append_text(right)
    return line


# --- key bar ---------------------------------------------------------------

_ATOM = (
    r"(?:(?:Ctrl|Shift|Alt)\s?\+\s?(?:[A-Za-z0-9]+|[↑↓←→])"
    r"|PgUp|PgDn|Home|End|Enter|Esc|Space|Tab|Backspace|Delete|Del"
    r"|F\d{1,2}(?![A-Za-z0-9])"
    r"|↑↓|←→|[↑↓←→]"
    r"|[A-Za-z0-9](?![A-Za-z0-9])"
    r"|[\[\]/?,.;:<>+*-](?![A-Za-z0-9]))"
)
_KEY_SEGMENT = re.compile(
    rf"^(?P<key>{_ATOM}(?:\s?/\s?{_ATOM})*)\s+(?P<action>[A-Za-z0-9(].*)$"
)
_SEPARATOR = re.compile(r"\s*•\s*|\s+\|\s+")


@dataclass
class Footer:
    """A footer split into prose lines and ``key action`` segments."""

    context: list[Text] = field(default_factory=list)
    keys: list[Text] = field(default_factory=list)


def key_segment(key: str, action: str) -> Text:
    segment = Text(no_wrap=True)
    segment.append(key, style=KEY)
    segment.append(" ")
    segment.append(action)  # the terminal's normal text colour: readable, not grey
    return segment


_KEY_ONLY = None


def is_key(text: str) -> bool:
    """True when *text* is just a key name (``U``, ``Tab``, ``Ctrl+F``, ``a/i``)."""
    global _KEY_ONLY
    if _KEY_ONLY is None:
        _KEY_ONLY = re.compile(rf"^{_ATOM}(?:\s?/\s?{_ATOM})*$")
    return bool(text) and bool(_KEY_ONLY.match(text.strip()))


_LABEL = re.compile(r"(?:(?<=^)|(?<=· )|(?<=• ))([A-Z][A-Za-z ]{0,24}:)(?= )")
_SEPARATOR_MARK = re.compile(r" [·•] ")


def labelled(line: str, margin: str = "", wrap: bool = False) -> Text:
    """``Label: value · Label: value`` with steel-blue labels and separators, values in normal text.

    One line cut with "…" unless *wrap* is set.
    """
    text = Text(margin + line, no_wrap=not wrap, overflow="fold" if wrap else "ellipsis")
    offset = len(margin)
    for match in _LABEL.finditer(line):
        text.stylize(MUTED, offset + match.start(1), offset + match.end(1))
    for match in _SEPARATOR_MARK.finditer(line):
        text.stylize(MUTED, offset + match.start(), offset + match.end())
    return text


def strip_text(text: Text) -> Text:
    """*text* without leading or trailing whitespace, styles kept."""
    plain = text.plain
    start = len(plain) - len(plain.lstrip())
    end = len(plain.rstrip())
    return text[start:end] if end > start else Text()


def _split(line: Text) -> list[Text]:
    pieces, position = [], 0
    for match in _SEPARATOR.finditer(line.plain):
        pieces.append(line[position:match.start()])
        position = match.end()
    pieces.append(line[position:])
    return [piece for piece in (strip_text(p) for p in pieces) if piece.plain]


def parse_footer(footer: str | Text | None) -> Footer:
    """Turn a footer into context lines and key segments, in their original order.

    A segment reads as a key when it starts with a key name (``Enter``,
    ``Ctrl+F``, ``↑/↓``, a single letter…) followed by its action. Anything
    else is prose; prose keeps its own markup on a muted base.
    """
    parsed = Footer()
    if not footer:
        return parsed
    text = footer.copy() if isinstance(footer, Text) else Text.from_markup(footer)
    for line in text.split("\n", allow_blank=True):
        prose = []
        for piece in _split(line):
            match = _KEY_SEGMENT.match(piece.plain)
            if match:
                key = re.sub(r"\s*([/+])\s*", r"\1", match.group("key"))
                parsed.keys.append(key_segment(key, match.group("action").strip()))
            else:
                prose.append(piece)
        if prose:
            joined = Text(style=MUTED)
            for i, piece in enumerate(prose):
                if i:
                    joined.append(" · ")
                joined.append_text(piece)
            parsed.context.append(joined)
    return parsed


def has_key(segments: list[Text], key: str) -> bool:
    return any(segment.plain.split(" ", 1)[0] == key for segment in segments)


def wrap_keys(segments: list[Text], width: int, margin: str = MARGIN) -> list[Text]:
    """Lay key segments out in as few lines as fit; never split a segment.

    *margin* is the left margin: frames use two cells, main-screen logs none.
    """
    room = max(8, width - len(margin) - len(MARGIN))
    lines: list[Text] = []
    current: Text | None = None
    for segment in segments:
        if current is not None and cell_len(current.plain) + len(KEY_GAP) + cell_len(segment.plain) <= room:
            current.append(KEY_GAP)
            current.append_text(segment)
            continue
        if current is not None:
            lines.append(current)
        current = Text(no_wrap=True, overflow="ellipsis")
        current.append_text(segment)
    if current is not None:
        lines.append(current)
    framed = []
    for line in lines:
        out = Text(margin, no_wrap=True, overflow="ellipsis")
        out.append_text(line)
        if cell_len(out.plain) > width:
            out.truncate(width, overflow="ellipsis")
        framed.append(out)
    return framed


def wrap_block(text: Text, width: int, console, margin: str = MARGIN) -> list[Text]:
    """Wrap a prose block under the left margin; returns one Text per line."""
    room = max(8, width - len(margin) - len(MARGIN))
    lines = []
    for line in text.wrap(console, room, overflow="fold"):
        out = Text(margin, no_wrap=True)
        out.append_text(line)
        lines.append(out)
    return lines or [Text(margin)]


# --- main-screen logs ------------------------------------------------------
# Download, stream and acquisition output shares the main screen with the
# tools' own output, which starts at column 0, so these blocks use no margin.

def log_header(title: str | Text = "", width: int = 80) -> Text:
    """``torrent-finder › Title`` at column 0, for screens that print a log."""
    line = Text(no_wrap=True, overflow="ellipsis")
    line.append(APP_NAME, style=BRAND)
    if title:
        crumb = _as_text(title)
        if crumb.plain.strip():
            line.append(CRUMB, style=MUTED)
            line.append_text(_title_text(crumb))
    if cell_len(line.plain) > width:
        line.truncate(max(1, width), overflow="ellipsis")
    return line


def report(title: str, body: str, tone: str = "") -> Text:
    """A titled result block for the main-screen log: bold title, then Rich-markup body.

    Blank lines before and after set it apart from the log around it.
    """
    block = Text("\n")
    block.append(title + "\n", style=f"bold {tone}".strip())
    block.append_text(Text.from_markup(body))
    block.append("\n")
    return block


def any_key(action: str = "continue") -> str:
    """Markup for the pause line that ends a main-screen log."""
    return f"[muted]Press [key]any key[/key] to {action}…[/muted]"


def section_label(label: str) -> str:
    """Display text for a section header: decoration and leading icons removed."""
    cleaned = label.strip().strip("─—-").strip()
    return cleaned.upper()
