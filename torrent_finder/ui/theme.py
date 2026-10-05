"""The Quiet look shared by every screen: palette, header line and key bar.

Screens draw no boxes. A header line names the app and the current screen,
content sits under a two-cell margin, and one key bar lists the keys as
``key action`` pairs. Colours come from a palette with one job per colour:
an accent for focus, keys and the brand, three shades for headings,
secondary text and rules, and the state colours. Themes swap the palette,
never the roles. See docs/adr/0020-quiet-terminal-design.md and
docs/adr/0021-themes.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.text import Text

APP_NAME = "torrent-finder"
MARGIN = "  "
KEY_GAP = "   "


@dataclass(frozen=True)
class Glyphs:
    """The symbols a design draws with; screens read them from this module at render time."""

    cursor: str      # marks the focused row
    check: str       # a ticked checkbox
    unchecked: str   # an unticked checkbox
    marker: str      # a range-select anchor
    crumb: str       # between the parts of a screen name
    bar: str         # one cell of a bar in a chart row
    spinner: str     # a Rich spinner name
    rule: str = "─"


@dataclass(frozen=True)
class Design:
    """A whole look: its glyphs and whether frames get the Athanor chrome (frame, message and status lines)."""

    key: str
    name: str
    glyphs: Glyphs
    framed: bool
    note: str


DESIGNS: dict[str, Design] = {design.key: design for design in (
    Design("athanor", "Athanor", Glyphs("@", "√", "∙", "♦", " » ", "▓", "line"), True,
           "A roguelike scriptorium: a double-line frame, a message line, a status line, "
           "glyphs from the IBM PC character set, and a painting behind the terminal."),
    Design("simple", "Simple", Glyphs("▍", "✓", "•", "◆", " › ", "▇", "dots"), False,
           "The quiet look: a header line, thin rules and a key bar; no frame."),
)}


@dataclass(frozen=True)
class Palette:
    """A theme: one colour for every role, nothing else.

    *accent* carries focus (the brand, cursor bar, focused row, keys and
    Prefer); *sky* section and column headings and the subject of a screen;
    *steel* labels, hints, separators, Off and disabled rows; *deep* rules and
    bars; *fill* the focused row's background when focus is "fill". *good*,
    *warn* and *bad* are the state colours (On / Auto / failures, seed health).

    Every palette belongs to a *design*. The terminal colours describe the page
    it is made for: *page* (background), *text* (foreground) and *ink* (the
    painting's lines); Athanor colourways draw their text in *text* and their
    frame and bars in *frame* and *bar_bg*.
    """

    key: str
    name: str
    accent: str
    sky: str
    steel: str
    deep: str
    fill: str
    good: str = "green"
    warn: str = "yellow"
    bad: str = "red"
    note: str = ""
    light: bool = False
    design: str = "simple"
    page: str = "#0C0C0C"
    text: str = ""
    ink: str = ""
    frame: str = ""
    bar_bg: str = ""


def _colourway(key, name, accent, sky, steel, deep, fill, good, warn, bad, *, page, text, ink, frame, bar_bg, note):
    return Palette(key, name, accent, sky, steel, deep, fill, good, warn, bad, note=note, design="athanor",
                   page=page, text=text, ink=ink, frame=frame, bar_bg=bar_bg)


# Dark Simple palettes leave the state colours to the terminal's own green,
# yellow and red. Hex shades degrade to the nearest named colour without true
# colour. Athanor colourways are named for the stages of the alchemical work.
THEMES: dict[str, Palette] = {palette.key: palette for palette in (
    _colourway("citrinitas", "Citrinitas", "#D49A3A", "#E3C27A", "#83745E", "#5C4C39", "#2B2117",
               "#8F9A5A", "#C8742E", "#C2452D", page="#16120E", text="#CFC1A3", ink="#3A3026",
               frame="#AC7D31", bar_bg="#0D0B08",
               note="Lamplight amber on parchment: the scriptorium as first seen."),
    _colourway("rubedo", "Rubedo", "#D86A45", "#EBA987", "#8D6F65", "#5A3A33", "#2C1714",
               "#8F9A5A", "#D9A441", "#C23A3A", page="#150E0D", text="#D9C6B8", ink="#3A2420",
               frame="#A8472F", bar_bg="#0C0807",
               note="Vermilion and rust: the reddening, the work's last stage."),
    _colourway("albedo", "Albedo", "#E6E1D6", "#B9C6D2", "#7C8088", "#43474E", "#24272C",
               "#8FA68A", "#D3A955", "#C9675A", page="#121315", text="#D2CEC6", ink="#2E3237",
               frame="#9AA0A8", bar_bg="#0B0C0E",
               note="Bone and silver: the whitening, cool and quiet."),
    _colourway("viriditas", "Viriditas", "#5FB3A1", "#A7D8C8", "#6E8577", "#3A4D42", "#16241F",
               "#A3C25E", "#D9A441", "#CF5D4B", page="#0F1412", text="#C6D1C3", ink="#26342D",
               frame="#4E8F7F", bar_bg="#090C0B",
               note="Verdigris on copper: the greening of old metal."),
    _colourway("nigredo", "Nigredo", "#C8643C", "#D8CFC3", "#6E6A64", "#3A3835", "#1E1C1B",
               "#8F9A5A", "#D9A441", "#B83A3A", page="#0E0E0E", text="#BDB6AD", ink="#2B2928",
               frame="#6E6A64", bar_bg="#080808",
               note="Ash and a single ember: the blackening."),
    Palette("quiet", "Quiet Blue", "bright_blue", "#7DAEFF", "#6A86B3", "#3A5A8C", "#16233D",
            note="Your terminal's bright blue with three fixed shades of blue."),
    Palette("iris", "Iris", "#A78BFA", "#C9B8FF", "#8F86B5", "#4B3F86", "#231B3F",
            note="Violet; green, yellow and red stay free for states."),
    Palette("lagoon", "Lagoon", "#2DD4BF", "#9FF2E4", "#6E9CA3", "#1E5C66", "#0E2A2E",
            note="Teal; as cool as Quiet Blue, further from the blue of links."),
    Palette("ember", "Ember", "#FFB454", "#FFD9A0", "#A89378", "#6F4A2A", "#30220F", warn="#FF8A3D",
            note="Warm amber; Auto turns orange so it never looks like the accent."),
    Palette("mono", "Mono", "#F2F2F2", "#D9D9D9", "#8C8C8C", "#474747", "#262626",
            note="No hue: weight carries the structure, states keep their colours."),
    Palette("paper", "Paper", "#1F5FD6", "#2B4C8C", "#6B7A99", "#B9C6DC", "#DCE6F7",
            good="#1A7F37", warn="#9A6700", bad="#CF222E", light=True, page="#FAFAFA",
            note="For light terminals: switch your terminal to a light colour scheme first."),
)}
DEFAULT_THEME = "citrinitas"
DEFAULT_THEMES = {"athanor": "citrinitas", "simple": "quiet"}  # what choosing a design starts on
FOCUS_STYLES = {"bar": "Cursor bar", "fill": "Filled row"}
DENSITIES = {"comfortable": "Comfortable", "compact": "Compact"}


def palettes(design: str) -> list[Palette]:
    """The palettes of one design, in their registry order."""
    return [palette for palette in THEMES.values() if palette.design == design]


# The active palette's roles and the active design's glyphs, rebound by
# apply(). Screens read these at render time (``theme.ACCENT``,
# ``theme.CURSOR``), so a theme change reaches the next frame.
PALETTE: Palette = THEMES[DEFAULT_THEME]
DESIGN: Design = DESIGNS[PALETTE.design]
ACCENT = SKY = STEEL = DEEP = FILL = GOOD = WARN = BAD = TEXT = FRAME = BAR_BG = ""
KEY = MUTED = SECTION = FOCUS = BRAND = SUBJECT = RULE_STYLE = ""
CURSOR = CHECK = UNCHECKED = MARKER = CRUMB = BAR = SPINNER = RULE = ""
FRAMED = False            # the Athanor chrome: a frame, a message line and a status line
SCREEN = "bold"           # the screen name after the app name
FILL_FOCUS = False        # focus style "fill": the focused row on a tinted background
COMPACT = False           # density "compact": the short-window layout at every size

# Rich theme entries; constants.custom_theme registers these so markup such as
# "[muted]…[/muted]" works in every console that renders the app. Updated in
# place by apply().
STYLES: dict[str, str] = {}
_STATE_STYLES: dict[str, str] = {}


def _bind(palette: Palette) -> None:
    global PALETTE, DESIGN, ACCENT, SKY, STEEL, DEEP, FILL, GOOD, WARN, BAD, TEXT, FRAME, BAR_BG
    global KEY, MUTED, SECTION, FOCUS, BRAND, SUBJECT, RULE_STYLE, FRAMED
    global CURSOR, CHECK, UNCHECKED, MARKER, CRUMB, BAR, SPINNER, RULE
    PALETTE = palette
    DESIGN = DESIGNS[palette.design]
    glyphs = DESIGN.glyphs
    CURSOR, CHECK, UNCHECKED, MARKER = glyphs.cursor, glyphs.check, glyphs.unchecked, glyphs.marker
    CRUMB, BAR, SPINNER, RULE = glyphs.crumb, glyphs.bar, glyphs.spinner, glyphs.rule
    FRAMED = DESIGN.framed
    ACCENT, SKY, STEEL, DEEP, FILL = palette.accent, palette.sky, palette.steel, palette.deep, palette.fill
    GOOD, WARN, BAD = palette.good, palette.warn, palette.bad
    TEXT = palette.text                      # "" leaves body text to the terminal's foreground
    FRAME = palette.frame or palette.deep
    BAR_BG = palette.bar_bg
    KEY = f"bold {ACCENT}"
    MUTED = STEEL
    SECTION = f"bold {SKY}"     # uppercase section headers and table column headers
    FOCUS = f"bold {ACCENT}"
    BRAND = f"bold {ACCENT}"    # the app name in every header
    SUBJECT = f"not bold {SKY}"  # what the screen is about: the query, torrent or provider after the name
    RULE_STYLE = DEEP
    STYLES.clear()
    STYLES.update({
        "accent": ACCENT,
        "key": KEY,
        "muted": MUTED,
        "steel": STEEL,
        "sky": SKY,
        "deep": DEEP,
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
        # A transient line that needs attention (the quit guard) and the update
        # banner. "not dim" keeps them bright inside dimmed footers; the banner's
        # headline is not bold because bold black reads as grey on many terminals.
        "alert": f"not dim bold {WARN}",
        "banner": f"not dim black on {WARN}",
        "banner.action": f"not dim bold {WARN}",
        # Rich's own spinners and progress bars follow the palette.
        "status.spinner": ACCENT,
        "bar.complete": ACCENT,
        "bar.finished": GOOD,
        "bar.pulse": ACCENT,
        "progress.percentage": ACCENT,
        "progress.remaining": MUTED,
        "progress.elapsed": MUTED,
    })
    _STATE_STYLES.clear()
    _STATE_STYLES.update({
        "on": GOOD,
        "auto": WARN,
        "off": MUTED,
        "require": f"bold {ACCENT}",
        "prefer": ACCENT,
    })


_bind(PALETTE)
_pushed_theme = False


def apply(palette: "Palette | str | None" = None, *, focus: str | None = None,
          density: str | None = None) -> Palette:
    """Switch the active palette and/or the focus and density settings.

    Every role name in this module is rebound, the Rich markup styles follow,
    and the app's consoles pick them up for the next frame. Unknown names
    raise ``KeyError``/``ValueError``; callers resolve user input first.
    """
    global FILL_FOCUS, COMPACT, _pushed_theme
    if isinstance(palette, str):
        palette = THEMES[palette]
    if focus is not None:
        if focus not in FOCUS_STYLES:
            raise ValueError(f"Unknown focus style {focus!r}")
        FILL_FOCUS = focus == "fill"
    if density is not None:
        if density not in DENSITIES:
            raise ValueError(f"Unknown density {density!r}")
        COMPACT = density == "compact"
    if palette is not None:
        _bind(palette)
        from rich.theme import Theme

        from torrent_finder import constants
        constants.custom_theme = Theme(dict(STYLES))
        if _pushed_theme:
            constants.console.pop_theme()
        constants.console.push_theme(constants.custom_theme)
        _pushed_theme = True
    return PALETTE


def current() -> tuple[Palette, str, str]:
    """The active palette, focus style and density."""
    return PALETTE, "fill" if FILL_FOCUS else "bar", "compact" if COMPACT else "comfortable"


def framed(width: int, height: int) -> bool:
    """True when frames of this size get the Athanor frame (never in tiny windows)."""
    return FRAMED and width >= 40 and height >= 12


def bars(width: int, height: int) -> bool:
    """True when a framed screen also gets its message and status lines (comfortable density, 24+ rows)."""
    return framed(width, height) and not COMPACT and height >= 24


def view_height(height: int, width: int) -> int:
    """Rows a frame's content may use: the Athanor frame and its two lines take theirs first.

    In framed windows the screen name sits in the frame's top edge, so screens
    leave their header out (see ``frame_header``).
    """
    if not framed(width, height):
        return height
    return height - 2 - (2 if bars(width, height) else 0)


def frame_header(title: "str | Text" = "", status: "str | Text" = "", width: int = 80,
                 height: int = 24) -> list[Text]:
    """A screen's header lines, or none when the Athanor frame carries the screen name."""
    return [] if framed(width, height) else header_lines(title, status, width)


def frame_rule(width: int, height: int) -> list[Text]:
    """The rule under a header, or none under the Athanor frame's top edge."""
    return [] if framed(width, height) else [rule(width)]


def roomy(height: int, threshold: int) -> bool:
    """True when a window *height* rows tall has room for spacing and rules.

    Every frame asks this before adding a rule or spacer line; the compact
    density answers no at any size, so lists get those rows instead.
    """
    return not COMPACT and height >= threshold


def state_style(state: str) -> str:
    """Colour for a named toggle state (engine On/Auto/Off, preset Require/Prefer)."""
    return _STATE_STYLES.get(state.strip().casefold(), "")


def seed_style(seeds: int) -> str:
    """Seed health: good from 10 seeds, warn below, bad at none."""
    return GOOD if seeds >= 10 else WARN if seeds >= 1 else BAD


def leech_style(leeches: int) -> str:
    """Leeches: muted when few, then warn, then bad."""
    return MUTED if leeches <= 5 else WARN if leeches <= 50 else BAD


def bar(value: float, largest: float, width: int) -> str:
    """A run of bar cells scaled so *largest* fills *width*; at least one cell for any value."""
    if width <= 0 or value <= 0 or largest <= 0:
        return ""
    return BAR * max(1, min(width, round(width * value / largest)))


def inner_width(width: int) -> int:
    """Cells left for content once both margins are taken."""
    return max(8, width - 2 * len(MARGIN))


INSPECTOR_MIN_WIDTH = 150  # narrower windows keep one column


def inspector_width(width: int) -> int:
    """Cells for the inspector pane beside a list in a window this wide; 0 when it stays one column."""
    if width < INSPECTOR_MIN_WIDTH:
        return 0
    return max(56, min(90, round(width * 0.4)))


def _as_text(value: str | Text) -> Text:
    return value.copy() if isinstance(value, Text) else Text.from_markup(value)


def _title_text(title: str | Text) -> Text:
    """``Screen › subject``: the screen name bold, what it is about in the light blue.

    Later crumbs (a query, a torrent name, a provider, a folder path) are the
    subject; the separators between them are muted like the one after the app
    name.
    """
    crumb = _as_text(title)
    # Titles are written with " › "; each design draws its own crumb (same width, so spans still fit).
    plain = crumb.plain.replace(" › ", CRUMB)
    styled = Text(plain, style=SCREEN)
    first = plain.find(CRUMB)
    if first >= 0:
        styled.stylize(SUBJECT, first + len(CRUMB))
        for match in re.finditer(re.escape(CRUMB), plain):
            styled.stylize(f"not bold {MUTED}", match.start(), match.end())
    styled.spans.extend(crumb.spans)  # last wins: the title's own markup beats these defaults
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
    right.stylize_before(MUTED)  # the status's own colours win
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
        right.stylize_before(MUTED)  # the status's own colours win
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


def with_help(segments: list[Text], width: int) -> list[Text]:
    """*segments* plus "? keys" when it fits on the lines the keys already take."""
    if has_key(segments, "?"):
        return segments
    candidate = segments + [key_segment("?", "keys")]
    return candidate if len(wrap_keys(candidate, width)) == len(wrap_keys(segments, width)) else segments


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
