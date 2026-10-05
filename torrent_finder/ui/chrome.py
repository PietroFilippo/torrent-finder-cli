"""The Athanor chrome: a double-line frame, a message line above it and a status line below.

Screens build their content as usual (without a header line when framed, see
``theme.frame_header``) for ``theme.view_height`` rows, then pass it here:
``compose`` puts the screen name and status in the frame's top edge, draws
the sides in the two-cell margins (so content keeps its columns), and adds
the message line (the newest announcement) and the NetHack-style status
line. In the Simple design, or
in windows too small for a frame, content passes through unchanged.
See docs/adr/0022-athanor-design.md.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.text import Text

from torrent_finder.ui import theme

TOP_LEFT, TOP_RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT, HORIZONTAL, VERTICAL = "╔", "╗", "╚", "╝", "═", "║"


@dataclass
class _Session:
    turns: int = 0  # keys read this session, NetHack's T
    messages: list = field(default_factory=list)  # announcements waiting for the message line
    shown: str = ""


_session = _Session()


def turn() -> None:
    """Count one key read (the status line's T)."""
    _session.turns += 1


def announce(message: str) -> None:
    """Queue a message (Rich markup) for the message line of the next screens; repeats are dropped."""
    if message and message not in _session.messages and message != _session.shown:
        _session.messages.append(message)


def take_message() -> str:
    """The announcement a new screen shows on its message line, with --More-- when others wait."""
    if not _session.messages:
        return ""
    _session.shown = _session.messages.pop(0)
    return _session.shown + (" [reverse]--More--[/reverse]" if _session.messages else "")


def clear_messages() -> None:
    _session.messages.clear()
    _session.shown = ""


# --- the pieces ------------------------------------------------------------------------

def _fit(text: Text, cells: int) -> Text:
    text = text.copy()
    if cell_len(text.plain) > cells:
        text.truncate(max(0, cells), overflow="ellipsis")
    return text


def top_edge(title: "str | Text", status: "str | Text", width: int) -> Text:
    """``╔═ torrent-finder » Screen › subject ════════ status ═╗``."""
    left = theme._header_left(title)
    left = left[len(theme.MARGIN):]  # the frame corner takes the margin
    right = theme._as_text(status) if status else Text()
    if right.plain:
        right.stylize_before(theme.MUTED)
    room = width - 6  # corners, the first rule cell and the spaces around the title
    if right.plain:
        right_room = max(0, min(cell_len(right.plain), room - min(cell_len(left.plain), room * 2 // 3) - 3))
        # A status that fits whole is kept; one cut down to a stump is dropped.
        right = _fit(right, right_room) if right_room >= min(cell_len(right.plain), 6) else Text()
    left = _fit(left, room - (cell_len(right.plain) + 3 if right.plain else 0))
    line = Text(no_wrap=True, overflow="crop")
    line.append(TOP_LEFT + HORIZONTAL + " ", style=theme.FRAME)
    line.append_text(left)
    line.append(" ", style=theme.FRAME)
    used = cell_len(line.plain) + (cell_len(right.plain) + 3 if right.plain else 0) + 1
    line.append(HORIZONTAL * max(0, width - used), style=theme.FRAME)
    if right.plain:
        line.append(" ")
        line.append_text(right)
        line.append(" " + HORIZONTAL, style=theme.FRAME)
    line.append(TOP_RIGHT, style=theme.FRAME)
    return line


def bottom_edge(width: int) -> Text:
    return Text(BOTTOM_LEFT + HORIZONTAL * max(0, width - 2) + BOTTOM_RIGHT, style=theme.FRAME, no_wrap=True)


def sided(line: Text, width: int) -> Text:
    """A content line between the frame's sides: the borders take the outer margin cells."""
    body = line.copy()
    body.no_wrap, body.overflow = True, "crop"
    if body.plain[:1] == " ":
        body = body[1:]
    inner = width - 2
    if cell_len(body.plain) > inner:
        body.truncate(inner)
    else:
        body.append(" " * (inner - cell_len(body.plain)))
    if theme.TEXT:
        body.stylize_before(theme.TEXT)  # the colourway's text colour for anything the screen left plain
    row = Text(no_wrap=True, overflow="crop")
    row.append(VERTICAL, style=theme.FRAME)
    row.append_text(body)
    row.append(VERTICAL, style=theme.FRAME)
    return row


def message_line(message: "str | Text", width: int) -> Text:
    """The line above the frame: the newest message on the bar background."""
    text = theme._as_text(message) if message else Text()
    line = Text(" ", no_wrap=True, overflow="ellipsis")
    line.append_text(text)
    line.stylize_before(f"bold {theme.TEXT}" if theme.TEXT else "bold")
    line = _fit(line, width)
    line.append(" " * (width - cell_len(line.plain)))
    if theme.BAR_BG:
        line.stylize_before(f"on {theme.BAR_BG}")
    return line


def _figures() -> list[tuple[str, str]]:
    """``Searches 128``, ``Picked 37``, ``Bookmarks 3``, ``T 842``: what the status line counts."""
    figures = []
    try:
        from torrent_finder.stats import get_all_stats
        stats = get_all_stats()
        figures += [("Searches", str(stats.get("searches_total", 0))), ("Picked", str(stats.get("picked_count", 0)))]
    except Exception:  # an unreadable store never stops a frame
        pass
    try:
        from torrent_finder import bookmarks
        figures.append(("Bookmarks", str(bookmarks.count())))
    except Exception:
        pass
    figures.append(("T", str(_session.turns)))
    return figures


def status_line(width: int, now: "_dt.datetime | None" = None) -> Text:
    """The line under the frame: session figures on the left; date, network and version on the right."""
    from torrent_finder import __version__
    from torrent_finder.security import exposure
    left = Text(" ")
    for index, (label, value) in enumerate(_figures()):
        if index:
            left.append("  ")
        left.append(f"{label}:", style=theme.MUTED)
        left.append(value, style=theme.TEXT or "")
    now = now or _dt.datetime.now()
    right = Text(f"{now:%a} {now.day} {now:%b}", style=theme.TEXT or "")
    network = exposure()
    if network:
        right.append("  ")
        right.append("VPN" if network == "vpn" else "IP visible", style=theme.GOOD if network == "vpn" else theme.WARN)
    right.append(f"  v{__version__} ", style=theme.MUTED)
    if cell_len(left.plain) + cell_len(right.plain) + 2 > width:
        right = Text()  # a narrow window keeps the figures
    line = _fit(left, width - cell_len(right.plain))
    line.no_wrap = True
    line.append(" " * max(0, width - cell_len(line.plain) - cell_len(right.plain)))
    line.append_text(right)
    if theme.BAR_BG:
        line.stylize_before(f"on {theme.BAR_BG}")
    return line


# --- composing a frame -----------------------------------------------------------------

def compose(lines: list[Text], title: "str | Text", status: "str | Text", width: int, height: int,
            message: "str | Text" = "") -> list[Text]:
    """A screen's content inside the Athanor chrome, exactly *height* lines; unchanged when unframed."""
    if not theme.framed(width, height):
        return lines
    with_bars = theme.bars(width, height)
    body = height - 2 - (2 if with_bars else 0)
    content = list(lines[:body])
    content += [Text("")] * (body - len(content))
    out = [message_line(message, width)] if with_bars else []
    out.append(top_edge(title, status, width))
    out += [sided(line, width) for line in content]
    out.append(bottom_edge(width))
    if with_bars:
        out.append(status_line(width))
    return out


class Framed:
    """A Rich renderable shown inside the chrome (the results table's Live view)."""

    def __init__(self, renderable, title: "str | Text", status: "str | Text", message: "str | Text" = ""):
        self.renderable, self.title, self.status, self.message = renderable, title, status, message

    @property
    def renderables(self) -> list:
        """The framed content's parts, as a Group would list them."""
        return list(getattr(self.renderable, "renderables", [self.renderable]))

    def __rich_console__(self, console, options):
        width = options.max_width
        height = options.height or console.size.height
        if not theme.framed(width, height):
            yield self.renderable
            return
        rendered = console.render_lines(self.renderable, options.update(width=width, height=None), pad=False)
        lines = [Text.assemble(*((segment.text, segment.style) for segment in line if not segment.control))
                 for line in rendered]
        for text in compose(lines, self.title, self.status, width, height, self.message):
            text.end = "\n"
            yield text


# --- the room on the main menu ------------------------------------------------------------

def room(title: str, description: str, exits: list[tuple[str, str]]) -> list[Text]:
    """A MUD-style room: a centred title, a description and the obvious exits."""
    heading = Text(f"~ {title} ~", style=f"bold {theme.ACCENT}", justify="center")
    words = Text(description)
    paths = Text("Obvious exits: ", style=theme.MUTED)
    for index, (name, note) in enumerate(exits):
        if index:
            paths.append("  ")
        paths.append(name)
        if note:
            paths.append(f" ({note})", style=theme.MUTED)
    return [heading, words, paths]
