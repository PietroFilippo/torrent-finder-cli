"""User-facing prompts: banner, download method selection."""

# i18n: converted
import io
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass

import readchar
from rich.cells import cell_len
from rich.console import Console
from rich.markup import escape
from rich.text import Span, Text

from torrent_finder.constants import buffer_console, console
from torrent_finder.downloader import (
    detect_torrent_client,
    download_with_webtorrent,
    has_aria2,
    has_webtorrent,
    has_peerflix,
    open_magnet,
    torrent_client_label,
)
from torrent_finder.i18n import N_, current, t, tn
from torrent_finder.providers import PROVIDER_MENU, PROVIDERS, ProviderGroup
from torrent_finder.ui import chrome as frames, display, inspector, theme
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.ui.selection import MultiSelection, SelectionPolicy

@dataclass
class QuitGuard:
    """The main menu's double-press quit: Esc arms it, a second Esc quits, any other choice disarms it."""

    armed: bool = False

    def hint(self) -> str:
        return t("[alert]Press Esc or Ctrl+C again to quit[/alert]") if self.armed else ""

_ARIA2_INSTALL_URL = "https://aria2.github.io/"
_WEBTORRENT_INSTALL_URL = "https://www.npmjs.com/package/webtorrent-cli"
_PEERFLIX_INSTALL_URL = "https://www.npmjs.com/package/peerflix"

# "Add another title" trigger for multi-line search entry. Ctrl+N on every
# platform: it's distinct from Enter everywhere, whereas Ctrl+J is LF ('\n') and
# would collide with Enter on POSIX — readchar leaves ICRNL set, so the Enter key
# arrives as '\n' there (see readchar's _posix_key.py: ENTER = LF).
_ADD_LINE_KEYS = {readchar.key.CTRL_N}
MULTI_ADD_KEY_LABEL = "Ctrl+N"

def search_shortcuts_line(has_history: bool) -> str:
    """Build the search-screen key line in display-priority order."""
    if has_history:
        return t("Enter search  •  Ctrl+F filters  •  Ctrl+N add another title  •  Tab actions  •  ↑/↓ recent  •  Esc back / undo title")
    return t("Enter search  •  Ctrl+F filters  •  Ctrl+N add another title  •  Tab actions  •  Esc back / undo title")

# The prompt marker every text field uses.
PROMPT = "[accent]›[/accent] "

def _print_lines(target: Console, block: Text) -> None:
    for line in theme.wrap_block(block, target.size.width, target):
        target.print(line)

def _print_keys(target: Console, footer: str) -> None:
    for line in theme.wrap_keys(theme.parse_footer(footer).keys, target.size.width):
        target.print(line)

def _keybar_wraps(footer: str, width: int, items: list[SelectItem] | None = None) -> bool:
    """Measure the translated key segments using the renderer's spacing and margins."""
    if items is not None and any(item.description or item.inspect for item in items):
        from torrent_finder.ui.selector import _PANE_GAP
        pane = theme.inspector_width(width)
        if pane:
            width -= pane + _PANE_GAP
    keys = theme.parse_footer(footer).keys
    cells = sum(cell_len(key.plain) for key in keys)
    cells += max(0, len(keys) - 1) * cell_len(theme.KEY_GAP)
    return cells > max(8, width - 2 * cell_len(theme.MARGIN))

def input_screen(
    title: str,
    *lines: str,
    keys: str = N_("Enter confirm  •  Esc cancel"),
    status: str = "",
) -> Callable[[Console], None]:
    """Renderer for a text field in the Quiet layout: header, help, field, keys.

    *lines* are help or error lines (Rich markup) shown above the field. The
    returned renderer draws the part above the field; its ``footer`` draws the
    key bar below it.
    """

    if keys == "Enter confirm  •  Esc cancel":
        keys = t("Enter confirm  •  Esc cancel")

    def render(target: Console) -> None:
        width, height = target.size.width, target.size.height
        rows = theme.view_height(height, width)
        for line in theme.frame_header(title, status, width, height):
            target.print(line)
        if theme.roomy(rows, 12):
            for line in theme.frame_rule(width, height):
                target.print(line)
        for line in lines:
            if line:
                _print_lines(target, Text.from_markup(line))
        if lines and any(lines) and theme.roomy(rows, 12):
            target.print()

    def footer(target: Console) -> None:
        if theme.roomy(theme.view_height(target.size.height, target.size.width), 12):
            target.print(theme.rule(target.size.width))
        _print_keys(target, keys)

    render.footer = footer
    render.title, render.status = title, status  # for the Athanor frame's top edge
    return render

_LABEL_GAP = "  "
_RECENT_ROWS = 5
_FOCUS_LABELS = {"bar": N_("Cursor bar"), "fill": N_("Filled row")}
_DENSITY_LABELS = {"comfortable": N_("comfortable"), "compact": N_("compact")}

def _change_shortcut() -> Text:
    text = Text.from_markup(t("[key]Ctrl+F[/key] to change"), style=theme.MUTED)
    text.spans = [Span(span.start, span.end, theme.KEY if span.style == "key" else span.style)
                  for span in text.spans]
    return text

def _join(parts: list[Text], separator: str = " · ") -> Text:
    joined = Text()
    for index, part in enumerate(parts):
        if index:
            joined.append(separator, style=theme.MUTED)
        joined.append_text(part)
    return joined

def engines_line(provider) -> Text:
    """``Engines  Apibay On · Knaben Auto · Nyaa On · YTS, SolidTorrents off``, states in their colours.

    Engines a preset turns On for its searches count as On here, as they do in
    the search itself.
    """
    effective = {engine.name for engine in provider.effective_engines}
    parts, off = [], []
    for engine in provider.engines:
        state = "On" if engine.name in effective else "Auto" if engine.mode == "auto" else ""  # i18n: ignore — engine identity
        if state:
            parts.append(Text.assemble(engine.name + " ", (t(state, ctx="engine mode"), theme.state_style(state))))
        else:
            off.append(engine.name)
    if off:
        parts.append(Text(t("{engines} off", engines=", ".join(off)), style=theme.MUTED))
    line = Text.assemble((t("Engines") + _LABEL_GAP, theme.MUTED))
    line.append_text(_join(parts) if parts else Text(t("none"), style=theme.MUTED))
    return line

def filters_line(provider) -> Text:
    """``Filters  Require x · Prefer y · Names: … · Ctrl+F to change``; "no presets" when none apply."""
    parts = []
    for word, presets in (("Require", provider.active_presets), ("Prefer", provider.preferred_presets)):  # i18n: ignore — preset identity
        if presets:
            parts.append(Text.assemble((t(word, ctx="preset state"), theme.state_style(word)), " " + ", ".join(p.label for p in presets)))
    if provider.name_rules.summary():
        parts.append(Text.assemble((t("Names "), theme.MUTED), provider.name_rules.summary_label()))
    categories = getattr(provider, "nyaa_categories", None)
    if categories:
        parts.append(Text.assemble(("Nyaa ", theme.MUTED), t(categories[provider.nyaa_category])))  # i18n: ignore — engine name
    parts.append(_change_shortcut())
    if len(parts) == 1:
        parts.insert(0, Text(t("no presets"), style=theme.MUTED))
    line = Text.assemble((t("Filters") + _LABEL_GAP, theme.MUTED))
    line.append_text(_join(parts))
    return line

def combined_lines(provider) -> list[Text]:
    """``Providers  …`` and ``Profile  …`` for Search across providers."""
    selection, details = provider.summary_label()
    first = Text.assemble((t("Providers") + _LABEL_GAP, theme.MUTED), selection)
    second = Text.assemble((t("Profile") + _LABEL_GAP, theme.MUTED), details, (" · ", theme.MUTED))
    second.append_text(_change_shortcut())
    return [first, second]

def matching_history(history: list[str], typed: str) -> list[str]:
    """Past searches containing *typed* (any case), newest first; all of them when nothing is typed."""
    needle = typed.strip().casefold()
    return [entry for entry in history if needle in entry.casefold()] if needle else list(history)

def _recent_row(text: str, needle: str, selected: bool, label_width: int, hint: str) -> Text:
    row = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
    row.append(theme.CURSOR if selected else " ", style=theme.ACCENT)
    row.append(" ")
    label = Text(text, style=theme.FOCUS if selected else "")
    start = text.casefold().find(needle) if needle else -1
    if start >= 0:
        label.stylize(theme.ACCENT, start, start + len(needle))
    row.append_text(label)
    if hint:
        row.append(" " * (label_width - cell_len(text) + 2))
        row.append(hint, style=theme.MUTED)
    return row

def make_search_screen_renderer(
    engine_names: str,
    active_filters: str,
    has_history: bool,
    notice: str = "",
    scope_label: str = N_("Engines"),
    title: str = N_("Search"),
    provider=None,
    recent_hints: "dict[str, str] | None" = None,
) -> Callable[[Console], None]:
    """Return the responsive renderer used by the search editor.

    The header names the provider. With *provider*, the lines under it show
    each engine's mode and the presets in their state colours (providers and
    profile for Search across providers); without it, *engine_names* and
    *active_filters* are shown as plain labelled text. Below the field, a
    RECENT list shows past searches matching what is typed (*recent_hints*
    maps a search to a note such as when it ran); ↑/↓ walks it. Keys go last.
    """
    from rich.markup import escape
    if title == "Search":
        title = t("Search")
    elif provider is not None and title == provider.name:
        title = provider.label
    if provider is not None and getattr(provider, "is_combined", False):
        info = combined_lines(provider)
    elif provider is not None:
        info = [engines_line(provider), filters_line(provider)]
    else:
        info = [theme.labelled(t('{scope}: {engines} · Filters: {filters}', scope=t(scope_label), engines=escape(engine_names), filters=escape(active_filters)),
                               wrap=True)]
    hints = recent_hints or {}
    compact_shortcuts = (
        t('Enter search  •  Ctrl+F filters  •  Ctrl+N add title  •  Tab actions  •  Esc back')
    )
    full_shortcuts = search_shortcuts_line(has_history)

    def render(target: Console) -> None:
        width, full_height = target.size.width, target.size.height
        height = theme.view_height(full_height, width)
        from torrent_finder.ui import downloads as downloads_ui
        status = downloads_ui.badge() if not theme.FRAMED else ""
        for line in theme.frame_header(title, status, width, full_height):
            target.print(line)
        if theme.roomy(height, 14):
            for line in theme.frame_rule(width, full_height):
                target.print(line)
        if height >= 12:
            for block in info:
                for line in theme.wrap_block(block, width, target):
                    target.print(line)
        if notice:
            _print_lines(target, theme.strip_text(Text.from_markup(notice)))
        if theme.roomy(height, 12):
            target.print()

    def recent(target: Console, typed: str, candidates: list[str], selected: int) -> None:
        """The RECENT list under the field; the cursor bar marks the search ↑/↓ put in it."""
        if not candidates:
            return
        needle = typed.strip().casefold()
        first = max(0, selected - _RECENT_ROWS + 1)
        shown = candidates[first:first + _RECENT_ROWS]
        if theme.roomy(theme.view_height(target.size.height, target.size.width), 12):
            target.print()
        heading = Text(theme.MARGIN, no_wrap=True, overflow="ellipsis")
        heading.append(t("RECENT"), style=theme.SECTION)
        if needle:
            heading.append(t("  matching {query}", query=typed.strip()), style=theme.MUTED)
        if len(candidates) > len(shown):
            heading.append(t('  {first}–{last} of {total}', first=first + 1, last=first + len(shown), total=len(candidates)), style=theme.MUTED)
        target.print(heading)
        label_width = max(cell_len(text) for text in shown)
        for index, text in enumerate(shown, first):
            target.print(_recent_row(text, needle, index == selected, label_width, hints.get(text, "")))

    def footer(target: Console) -> None:
        rows = theme.view_height(target.size.height, target.size.width)
        if theme.roomy(rows, 12):
            target.print(theme.rule(target.size.width))
        _print_keys(target, compact_shortcuts if rows < 18 or _keybar_wraps(full_shortcuts, target.size.width) else full_shortcuts)

    render.footer = footer
    render.recent = recent
    render.title, render.status = title, ""  # for the Athanor frame's top edge
    return render

def _capture_lines(render: Callable[[Console], None], width: int, height: int) -> list[str]:
    """Run *render* against an off-screen console; return its ANSI lines."""
    buffer = io.StringIO()
    target = buffer_console(buffer, width, height)
    render(target)
    lines = buffer.getvalue().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines

def _fold(line: Text, width: int) -> tuple[list[Text], list[int]]:
    """Cut *line* into rows of *width* cells at character boundaries.

    Returns the rows and the character offset each row starts at. Folding by
    characters (not words) keeps the cursor arithmetic exact for any text.
    """
    plain = line.plain
    rows, starts = [], []
    start, cells = 0, 0
    for index, char in enumerate(plain):
        char_cells = cell_len(char)
        if cells + char_cells > width and index > start:
            rows.append(line[start:index])
            starts.append(start)
            start, cells = index, 0
        cells += char_cells
    rows.append(line[start:])
    starts.append(start)
    return rows, starts

def _ansi(row: Text, width: int) -> str:
    buffer = io.StringIO()
    buffer_console(buffer, width).print(row, no_wrap=True, overflow="crop", end="")
    return buffer.getvalue()

def _render_query_frame(
    screen_renderer: Callable[[Console], None],
    prompt_str: str,
    committed: list[str],
    buffer: list[str],
    pos: int,
    width: int,
    height: int,
    recall: "tuple[str, list[str], int] | None" = None,
    message: str = "",
) -> tuple[str, int, int]:
    """Pre-render one complete text-field frame and its absolute cursor position.

    The frame never exceeds *height*: when it would, the list of past searches
    under the field goes first (*recall* is what was typed, the matching
    searches and the one ↑/↓ chose), then help lines above the field (the
    header line stays), then the oldest queued titles, then key lines. The row
    being edited always stays on screen, and the cursor is computed on the
    same character-folded rows that are drawn.
    """
    width, height = max(1, width), max(1, height)
    if frames.too_small(width, height):
        return "\n".join(_ansi(line, width) for line in frames.enlarge_notice(width, height)), height, 1
    # A renderer that names its screen gets the Athanor frame: it lays out for
    # the rows inside it, and the frame and its lines are added at the end.
    title = getattr(screen_renderer, "title", None)
    framed = title is not None and theme.framed(width, height)
    full_height = height
    if framed:
        height = theme.view_height(full_height, width)
    top = _capture_lines(screen_renderer, width, full_height)
    render_footer = getattr(screen_renderer, "footer", None)
    footer = _capture_lines(render_footer, width, full_height) if render_footer is not None else []
    render_recent = getattr(screen_renderer, "recent", None)
    below = (_capture_lines(lambda target: render_recent(target, *recall), width, full_height)
             if render_recent is not None and recall is not None else [])

    # Inside the Athanor frame each side takes a cell: rows fold to the room
    # between them, and continuation rows start with the space a side
    # replaces (the first row starts with the margin already).
    fold_width = max(1, width - 2) if framed else width

    def sided(folded: list[Text]) -> list[Text]:
        return folded[:1] + [Text(" ") + row for row in folded[1:]] if framed else folded

    prompt = Text.from_markup(theme.MARGIN + prompt_str)
    queued: list[Text] = []
    for query in committed:
        line = prompt.copy()
        line.append(query)
        queued.extend(sided(_fold(line, fold_width)[0]))
    field = prompt.copy()
    field.append("".join(buffer))
    rows, starts = _fold(field, fold_width)
    cursor_index = len(prompt.plain) + pos
    cursor_row = max(k for k, start in enumerate(starts) if start <= cursor_index)
    cursor_col = cell_len(field.plain[starts[cursor_row]:cursor_index])
    if cursor_col >= fold_width:  # the cursor sits just past a full row
        cursor_row, cursor_col = cursor_row + 1, 0
        if cursor_row == len(rows):
            rows.append(Text(""))
    rows = sided(rows)
    if framed and cursor_row:
        cursor_col += 1  # a continuation row starts one cell further in

    # Simple shows the announcement on a notice line above the keys; Athanor on its message line.
    notice = [_ansi(frames.notice_line(message, width), width)] if message and not theme.FRAMED else []
    if notice and theme.roomy(height, 12):
        notice.insert(0, "")  # a row between the field (or the past searches) and the notice

    def total() -> int:
        return len(top) + len(queued) + len(rows) + len(below) + len(notice) + len(footer)

    if total() > height:  # the past searches give way first, all of them below a heading and a row
        room = height - (len(top) + len(queued) + len(rows) + len(notice) + len(footer))
        blank = 1 if below and not Text.from_ansi(below[0]).plain.strip() else 0
        below = below[:room] if room - blank >= 2 else []
    if total() > height:
        top = top[:max(1, height - (len(queued) + len(rows) + len(notice) + len(footer)))]
    if total() > height:  # keep the newest queued titles
        room = height - len(top) - len(rows) - len(notice) - len(footer)
        queued = queued[-room:] if room > 0 else []
    if total() > height:  # then the notice
        notice = []
    if total() > height:  # keep the key lines, losing the spacer above them first
        room = height - len(top) - len(queued) - len(rows)
        footer = footer[-room:] if room > 0 else []
    first_row = 0
    if total() > height:  # the text itself is taller than the window
        visible = max(1, height - len(top))
        first_row = min(max(0, cursor_row - visible + 1), max(0, len(rows) - visible))
        rows = rows[first_row:first_row + visible]
        top = top[:max(0, height - len(rows))]

    lines = top + [_ansi(row, width) for row in queued + rows] + below + notice + footer
    row_number = len(top) + len(queued) + (cursor_row - first_row) + 1
    if framed:
        texts = [Text.from_ansi(line) for line in lines]
        composed = frames.compose(texts, title, getattr(screen_renderer, "status", ""), width, full_height, message)
        lines = [_ansi(text, width) for text in composed]
        row_number += 1 + (1 if theme.bars(width, full_height) else 0)  # the top edge and the message line
        height = full_height
    return (
        "\n".join(lines),
        max(1, min(height, row_number)),
        max(1, min(width, cursor_col + 1)),
    )

def _write_query_frame(
    content: str,
    cursor_row: int,
    cursor_col: int,
    expected_size: object,
) -> bool:
    """Atomically replace the search screen if its render size is still current."""
    if console.size != expected_size:
        return False
    sys.stdout.write(display.paint(content, expected_size.width, expected_size.height,
                                   after=f"\033[{cursor_row};{cursor_col}H"))
    sys.stdout.flush()
    return True

def get_query_with_shortcut(
    prompt_str: str,
    initial: str = "",
    history=None,
    filters_shortcut: bool = False,
    multi: bool = False,
    screen_renderer: Callable[[Console], None] | None = None,
    propagate_interrupt: bool = False,
    initial_committed: list[str] | None = None,
) -> "str | tuple | list | None":
    """Read a search query with inline editing.

    With ``multi=True``, Ctrl+N commits the current line and starts another;
    Enter then returns the full ``list[str]`` of titles. Ctrl+F / Tab carry
    committed titles as a third tuple entry, restored via ``initial_committed``.
    Esc backs out progressively — it clears the line being typed,
    then restores the last committed title for editing, and only returns
    "GO_BACK" once nothing is left. Without ``multi`` the return is a single
    string and Esc leaves immediately, exactly as before.

    Returns the typed text, "GO_BACK" on Esc, or ``("ACTIONS", typed)`` when Tab
    is pressed. Ctrl+C cancels the field like Esc, returning "GO_BACK", so a
    nested editor never exits the app. Only ``propagate_interrupt=True`` (the
    main search prompt and its quit guard) raises ``KeyboardInterrupt`` instead. With ``filters_shortcut=True``, Ctrl+F returns
    ``("FILTERS", typed)``. ``history`` enables Up/Down search recall.

    When ``screen_renderer`` is provided, the editor owns an alternate-screen
    frame and redraws it atomically whenever the terminal size changes.
    """
    buffer: list[str] = list(initial)
    pos = len(buffer)
    committed = list(initial_committed or []) if multi else []

    hist = history or []
    from torrent_finder.ui import downloads as downloads_ui
    watched = downloads_ui.watch() if screen_renderer is not None else {}
    # Taken only when this screen has a message line to show it on; otherwise it waits for one.
    announcement = (frames.take_message()
                    if screen_renderer is not None and frames.shows_message(console.size.width, console.size.height)
                    else "")
    hpos = -1          # the chosen past search in `matches`, -1 while typing
    stash = ""         # what was typed before ↑ started walking past searches
    matches: list[str] = []

    stop_event = threading.Event()
    render_lock = threading.Lock()
    watcher_thread: threading.Thread | None = None
    observed_size = console.size

    def draw() -> bool:
        with render_lock:
            for _ in range(3):
                frame_size = console.size
                content, cursor_row, cursor_col = _render_query_frame(
                    screen_renderer,
                    prompt_str,
                    committed,
                    buffer,
                    pos,
                    frame_size.width,
                    frame_size.height,
                    recall=recall_state(),
                    message=announcement,
                )
                if _write_query_frame(
                    content,
                    cursor_row,
                    cursor_col,
                    frame_size,
                ):
                    return True
            return False

    def recall_state() -> "tuple[str, list[str], int] | None":
        if not hist:
            return None
        if hpos >= 0:
            return stash, matches, hpos
        typed = "".join(buffer)
        return typed, matching_history(hist, typed), -1

    def watcher() -> None:
        nonlocal observed_size, announcement
        while not stop_event.wait(0.05):
            current_size = console.size
            downloads_changed = downloads_ui.poll(watched)
            if current_size != observed_size or downloads_changed:
                observed_size = current_size
                if frames.shows_message(*current_size):
                    announcement = frames.take_message() or announcement
                draw()

    def repaint(prev_col: int, prev_len: int) -> None:
        """Redraw an edit and leave the physical cursor at ``pos``."""
        if screen_renderer is not None:
            draw()
            return

        out = ['\b' * prev_col, ''.join(buffer)]
        extra = prev_len - len(buffer)
        if extra > 0:
            out.append(' ' * extra)
            out.append('\b' * extra)
        out.append('\b' * (len(buffer) - pos))
        sys.stdout.write(''.join(out))
        sys.stdout.flush()

    def recall(text: str) -> None:
        nonlocal pos
        prev_col, prev_len = pos, len(buffer)
        buffer[:] = list(text)
        pos = len(buffer)
        repaint(prev_col, prev_len)

    if screen_renderer is not None:
        display.enter_screen(cursor=True)
        try:
            draw()
        except BaseException:  # Ctrl+C or a failure in the first frame: leave the screen it opened
            display.leave_screen()
            raise
        watcher_thread = threading.Thread(target=watcher, daemon=True)
        watcher_thread.start()
    else:
        console.print(prompt_str, end="")
        if buffer:
            sys.stdout.write(''.join(buffer))
        sys.stdout.flush()

    try:
        while True:
            key = readchar.readkey()
            frames.turn()

            if multi and key in _ADD_LINE_KEYS:
                text = "".join(buffer).strip()
                if text:
                    committed.append(text)
                    buffer[:] = []
                    pos = 0
                    hpos = -1
                    stash = ""
                    if screen_renderer is not None:
                        draw()
                    else:
                        print()
                        console.print(prompt_str, end="")
                        sys.stdout.flush()
                continue

            if key in (readchar.key.ENTER, readchar.key.CR, readchar.key.LF):
                if screen_renderer is None:
                    print()
                if multi:
                    text = "".join(buffer).strip()
                    if text:
                        committed.append(text)
                    return list(committed)
                return "".join(buffer)

            if key == readchar.key.ESC:
                if multi and (buffer or committed):
                    # Progressive back-out: clear the in-progress line first,
                    # then pop the last committed title back into the line for
                    # editing. Leaving the screen takes one more Esc when empty.
                    prev_col, prev_len = pos, len(buffer)
                    restoring = not buffer
                    if restoring:
                        buffer[:] = list(committed.pop())
                    else:
                        buffer[:] = []
                    pos = len(buffer)
                    hpos = -1
                    stash = ""
                    if screen_renderer is not None:
                        draw()
                    elif restoring:
                        # Erase the empty prompt line, move up over the printed
                        # committed line, and re-render it as the edit line.
                        sys.stdout.write("\r\033[K\033[F\r\033[K")
                        sys.stdout.flush()
                        console.print(prompt_str, end="")
                        sys.stdout.write("".join(buffer))
                        sys.stdout.flush()
                    else:
                        repaint(prev_col, prev_len)
                    continue
                if screen_renderer is None:
                    print()
                return "GO_BACK"

            if key in (readchar.key.TAB, '\t'):
                if screen_renderer is None:
                    print()
                if committed:
                    return ("ACTIONS", "".join(buffer), list(committed))
                return ("ACTIONS", "".join(buffer))

            if key == readchar.key.CTRL_F:
                if filters_shortcut:
                    if screen_renderer is None:
                        print()
                    if committed:
                        return ("FILTERS", "".join(buffer), list(committed))
                    return ("FILTERS", "".join(buffer))
                continue

            if key == readchar.key.LEFT:
                if pos > 0:
                    if screen_renderer is not None:
                        prev_col = pos
                        pos -= 1
                        repaint(prev_col, len(buffer))
                    else:
                        pos -= 1
                        sys.stdout.write('\b')
                        sys.stdout.flush()
                continue

            if key == readchar.key.RIGHT:
                if pos < len(buffer):
                    if screen_renderer is not None:
                        prev_col = pos
                        pos += 1
                        repaint(prev_col, len(buffer))
                    else:
                        sys.stdout.write(buffer[pos])
                        pos += 1
                        sys.stdout.flush()
                continue

            if key == readchar.key.UP:
                # Walk the past searches that contain what was typed, newest first.
                if hpos == -1:
                    stash = "".join(buffer)
                    matches = matching_history(hist, stash)
                if hpos < len(matches) - 1:
                    hpos += 1
                    recall(matches[hpos])
                continue

            if key == readchar.key.DOWN:
                if hpos >= 0:
                    hpos -= 1
                    recall(matches[hpos] if hpos >= 0 else stash)
                continue

            if key == readchar.key.HOME or key == readchar.key.CTRL_A:
                if pos > 0:
                    if screen_renderer is not None:
                        prev_col = pos
                        pos = 0
                        repaint(prev_col, len(buffer))
                    else:
                        sys.stdout.write('\b' * pos)
                        pos = 0
                        sys.stdout.flush()
                continue

            if key == readchar.key.END or key == readchar.key.CTRL_E:
                if pos < len(buffer):
                    if screen_renderer is not None:
                        prev_col = pos
                        pos = len(buffer)
                        repaint(prev_col, len(buffer))
                    else:
                        sys.stdout.write(''.join(buffer[pos:]))
                        pos = len(buffer)
                        sys.stdout.flush()
                continue

            if key in (readchar.key.BACKSPACE, '\x08', '\x7f'):
                if pos > 0:
                    prev_col, prev_len = pos, len(buffer)
                    del buffer[pos - 1]
                    pos -= 1
                    hpos = -1  # editing ends the walk; the list matches the new text
                    repaint(prev_col, prev_len)
                continue

            if key in (readchar.key.DELETE, readchar.key.SUPR):
                if pos < len(buffer):
                    prev_col, prev_len = pos, len(buffer)
                    del buffer[pos]
                    hpos = -1
                    repaint(prev_col, prev_len)
                continue

            if key in (readchar.key.CTRL_C, '\x03'):
                raise KeyboardInterrupt

            if key in (readchar.key.CTRL_D, '\x04'):
                raise EOFError

            if (
                len(key) == 1
                and key >= ' '
            ):
                prev_col, prev_len = pos, len(buffer)
                buffer.insert(pos, key)
                pos += 1
                hpos = -1
                repaint(prev_col, prev_len)
    except (KeyboardInterrupt, EOFError):  # typed Ctrl+C / Ctrl+D (raised above) or readkey's
        if propagate_interrupt:
            raise
        if screen_renderer is None:
            print()
        return "GO_BACK"
    finally:
        if screen_renderer is not None:
            stop_event.set()
            if watcher_thread is not None:
                watcher_thread.join(timeout=0.25)
            display.leave_screen()

def quick_actions_menu(update_available: bool = False, provider=None) -> "str | None":
    """Search-prompt quick actions, opened with Tab.

    Returns "update" (only when ``update_available``), "filter", "history",
    "stats", "tips", or None if cancelled. The familiar U/F/H/S/T letters jump
    straight to each action; arrows + Enter also work. Lives behind Tab so it
    never clashes with typing a query.
    """
    items: list[SelectItem] = []
    if update_available:
        items.append(SelectItem(label=t("Install update"), value="update", is_action=True, hint="U"))
    base = [
        (t("Filters & engines"), "filter", "F"),
        (t("Alternate-title search"), "titles", "A"),
        (t("Discover by topic / genre"), "discover", "D"),
        (t("Search history"), "history", "H"),
        (t("Bookmarks / download later"), "bookmarks", "B"),
        (t("Bookmark current search"), "save_search", "L"),
        (t("Settings backup / import"), "backup", "E"),
        (t("qBittorrent connection / progress"), "qbittorrent", "Q"),
        (t("Background downloads"), "downloads", "G"),  # D is Discover here
        (t("Usage stats"), "stats", "S"),
        (t("Tips & shortcuts"), "tips", "T"),
    ]
    for label, value, key in base:
        items.append(SelectItem(label=label, value=value, is_action=True, hint=key))
    items.append(SelectItem(label=t("Back"), value=None, is_action=True))

    def _pick(index: int):
        return lambda cursor, items_list: index

    key_actions: dict = {}
    offset = 0
    if update_available:
        key_actions["U"] = _pick(0)
        key_actions["u"] = _pick(0)
        offset = 1
    for i, (_label, _value, key) in enumerate(base):
        key_actions[key] = _pick(i + offset)
        key_actions[key.lower()] = _pick(i + offset)

    jump = " / ".join((["U"] if update_available else []) + [key for _, _, key in base])
    idx = arrow_select(
        items,
        title=t("Quick actions › {provider}", provider=provider.label) if provider else t("Quick actions"),
        intro=lambda: "" if provider or console.size.height < 20 else t("Search actions ask for a provider first."),
        banner=_make_banner_panel(),
        footer=t('↑/↓ select  •  Enter select  •  {jump} jump  •  Esc back', jump=jump),
        key_actions=key_actions,
    )
    if idx is None:
        return None
    return items[idx].value

def action_provider_prompt(action):
    """A global search action chooses its scope without opening another menu."""
    from torrent_finder.providers import PROVIDERS
    from torrent_finder.providers.combined_provider import provider_display_label
    items = [SelectItem(provider_display_label(p), value=p,
                        description=_provider_note(p)) for p in PROVIDERS]
    items.append(SelectItem(t("Back"), value=None, is_action=True))
    index = arrow_select(items, title=action, intro=lambda: t("Choose a provider.") if console.size.height >= 20 else "",
                         banner=_make_banner_panel(),
                         footer=t("All / selected providers uses its current profile.\n"
                                "↑/↓ navigate  •  Enter select  •  Esc back"))
    return None if index is None else items[index].value

def filter_menu(provider, on_save=None) -> None:
    """Show engine toggles and filter presets in a single menu."""
    if getattr(provider, "is_combined", False):
        from torrent_finder.ui.combined import combined_filter_menu
        combined_filter_menu(provider)
        return
    from rich.markup import escape
    has_engines = hasattr(provider, 'engines') and provider.engines
    has_presets = bool(provider.presets)
    from torrent_finder.result_view import sort_label
    from torrent_finder.ui.result_filters import choose_result_sort
    draft_sort = provider.result_sort
    draft_rules = provider.name_rules
    draft_category = provider.nyaa_category

    items = []
    # Badge values are English identities. Never recover a mode from display text.
    engine_badges = {"on": "On", "auto": "Auto", "off": "Off"}  # i18n: ignore — engine identities
    engine_modes = {badge: mode for mode, badge in engine_badges.items()}

    # --- Section 1: Search Engines ---
    engine_indices = []
    if has_engines:
        items.append(SelectItem(
            label=t("─── Search Engines ───"),
            value="section_header",
            enabled=False,
            is_action=True,
        ))
        for engine in provider.engines:
            items.append(SelectItem(
                label=engine.name,
                value=("engine", engine),
                toggle_states=tuple(
                    engine_badges[mode] for mode in engine.available_modes
                ),
                toggle_state=engine_badges[engine.mode],
                description=escape(t(engine.description)),
            ))
            engine_indices.append(len(items) - 1)

    # --- Section 2: Filter Presets ---
    preset_indices = []
    if has_presets:
        items.append(SelectItem(
            label=t("─── Filter Presets ───"),
            value="section_header",
            enabled=False,
            is_action=True,
        ))
        for p in provider.presets:
            items.append(SelectItem(
                label=p.label,
                value=("preset", p),
                toggle_states=("Off", "Require", "Prefer"),  # i18n: ignore — preset identities
                toggle_state="Require" if p in provider.active_presets else "Prefer" if p in provider.preferred_presets else "Off",  # i18n: ignore — preset identities
                description=t("Require excludes others; Prefer ranks similar matches higher. {description}",
                              description=t(p.description)),
            ))
            preset_indices.append(len(items) - 1)

    # --- Action buttons ---
    items.append(SelectItem(t("Literal release-name rules…"), "rules", is_action=True,
                            description=t("All words / any word / exact phrase / exclusions. Release names only.")))
    rules_idx = len(items) - 1
    categories = getattr(provider, "nyaa_categories", {})
    category_idx = None
    if categories:
        items.append(SelectItem(t("Nyaa category: {category}", category=t(categories[draft_category])), "category", is_action=True,
                                description=t("Nyaa only; other engines cannot enforce this language category. Category labels do not verify audio or subtitle tracks.")))
        category_idx = len(items) - 1
    if provider.slug == "manga":
        for idx in engine_indices:
            if items[idx].value[1].name.startswith("Nyaa"):
                items[idx].description = (t("EN = English-translated; Raw = untranslated; Non-English = other translations, "
                                          "including Portuguese. Other engines do not enforce these scopes. Language "
                                          "presets below turn the matching one on for their searches."))
    items.append(SelectItem(label=t('Result order: {sort}', sort=sort_label(draft_sort)), value="sort", is_action=True,
                            description=t("Saved for this provider. In a combined profile, its overall result order takes precedence.")))
    sort_idx = len(items) - 1
    items.append(SelectItem(label=t("Clear preset filters"), value="clear", is_action=True, hint="c"))
    items.append(SelectItem(label=t("Confirm"), value="confirm", is_action=True, hint="w"))
    items.append(SelectItem(label=t("Back"), value="back", is_action=True))

    # Index of Confirm action — returned when `w` is pressed
    confirm_idx = len(items) - 2

    # All toggleable rows (engines + presets)
    toggle_indexes = engine_indices + preset_indices

    def _is_active(index, item):
        return (item.toggle_state == "On" if index in engine_indices
                else item.toggle_state != "Off")

    def _set_active(index, item, active):
        if item.toggle_states:
            item.toggle_state = ("On" if index in engine_indices else "Require") if active else "Off"  # i18n: ignore — toggle identity
        else:
            item.toggled = active

    def _clear_item(index, item):
        # Clear preset toggles only — leave engine toggles alone, including Auto.
        if index in preset_indices:
            item.toggle_state = "Off"  # i18n: ignore — toggle identity

    def _invert_item(index, item):
        if item.toggle_states:
            _set_active(index, item, not _is_active(index, item))
        else:
            item.toggled = not item.toggled

    selection = MultiSelection(toggle_indexes, confirm_idx, SelectionPolicy(
        is_active=_is_active,
        set_active=_set_active,
        invert=_invert_item,
        toggle=lambda index, item: item.cycle_toggle(),
        clear=_clear_item,
    ))

    def handle_filter_action(idx, items):
        if items[idx].value == "clear":
            return selection.clear(idx, items)
        return False  # Exit for Confirm / Go Back

    key_actions = selection.key_actions

    # Start cursor on first enabled item (skip header)
    start = 1 if has_engines else 0

    def filter_status() -> str:
        """``3 on · 1 auto · 1 required · 2 preferred`` for the draft as it stands."""
        states = [items[i].toggle_state for i in engine_indices + preset_indices]
        parts = []
        if engine_indices:
            parts.append(t('{count} on', count=states.count('On')))
            if "Auto" in states:
                parts.append(t('{count} auto', count=states.count('Auto')))
        if "Require" in states:
            parts.append(tn("{n} required", "{n} required", states.count("Require")))
        if "Prefer" in states:
            parts.append(tn("{n} preferred", "{n} preferred", states.count("Prefer")))
        return " · ".join(parts)

    legend_text = Text.from_markup(t("[good]On[/good] searches every time · [warn]Auto[/warn] only when On finds nothing · [muted]Off[/muted] is skipped"))

    def legend():
        # Tall windows only: each engine row's own description explains its mode too.
        return legend_text if has_engines and console.size.height >= 28 else ""

    while True:
        result_idx = arrow_select(
            items,
            title=t('Filters › {label}', label=provider.label),
            status=filter_status,
            intro=legend,
            multi=True,
            banner=_make_banner_panel(),
            on_action=handle_filter_action,
            start_index=start,
            key_actions=key_actions,
            footer=t("↑/↓ nav • Space/Enter cycle • a all • i invert • c clear • v/V range • w save • Esc cancel"),
        )
        if result_idx == rules_idx:
            from torrent_finder.ui.name_rules import edit_name_rules
            draft_rules = edit_name_rules(draft_rules)
            start = rules_idx
            continue
        if category_idx is not None and result_idx == category_idx:
            choices = [SelectItem(t(label), key) for key, label in categories.items()]
            pick = arrow_select(choices, title=t("Nyaa Anime category"), footer=t("Nyaa only • Esc keep current category"))
            if pick is not None:
                draft_category = choices[pick].value
                items[category_idx].label = t("Nyaa category: {category}", category=t(categories[draft_category]))
            start = category_idx
            continue
        if result_idx != sort_idx:
            break
        # The selector's redraw thread must stop before another menu opens.
        draft_sort = choose_result_sort(draft_sort)
        items[sort_idx].label = t('Result order: {sort}', sort=sort_label(draft_sort))
        start = sort_idx

    if result_idx is None:
        return

    action = items[result_idx].value

    if action == "confirm":
        # Apply engine modes
        for idx in engine_indices:
            item = items[idx]
            _type, engine = item.value
            engine.set_mode(engine_modes[item.toggle_state])

        # Apply preset toggles
        provider.active_presets.clear()
        provider.preferred_presets.clear()
        for idx in preset_indices:
            item = items[idx]
            _type, preset = item.value
            if item.toggle_state == "Require":
                provider.active_presets.append(preset)
            elif item.toggle_state == "Prefer":
                provider.preferred_presets.append(preset)
        provider.result_sort = draft_sort
        provider.name_rules = draft_rules
        provider.nyaa_category = draft_category

        if on_save is not None:
            on_save()
        else:
            from torrent_finder.state import save_state
            try:
                save_state([provider])
            except (OSError, ValueError) as error:
                from rich.markup import escape
                console.print(t("[warning] Filters apply to this session, but couldn't be saved: {value}[/warning]", value=escape(str(error))))
                console.print(t("[muted]Press [key]any key[/key] to continue…[/muted]"))
                readchar.readkey()
    # "back" — just return

def episode_select_prompt(files: list, preselected: list[int] | None = None) -> list[int] | None:
    """Multi-select menu for picking episodes from a torrent's file list.

    Takes a list of TorrentFile. ``preselected`` is a list of 1-based file
    indexes to pre-toggle (so re-entering the picker shows current selection).

    Returns:
        - ``None`` if cancelled (Esc / Cancel button) — caller keeps prior selection.
        - ``list[int]`` (possibly empty) on Confirm — caller replaces prior selection.
          Empty list means "clear selection".
    """
    import os
    from torrent_finder.torrent_meta import extract_episode_number, format_size
    from torrent_finder.stats import record_episode_picker_used

    if not files:
        console.print(t("[warning] No files in torrent.[/warning]"))
        return None

    record_episode_picker_used()

    pre_set = set(preselected or [])

    items: list[SelectItem] = []
    file_item_indexes: list[int] = []
    sizes = [format_size(f.size_bytes) if f.size_bytes else "" for f in files]  # unknown, not "0 B"
    size_width = max((cell_len(size) for size in sizes), default=0)
    episode_width = cell_len(t("Ep {episode}", episode="000"))
    for f, size in zip(files, sizes):
        ep = extract_episode_number(f.name)
        ep_label = t('Ep {episode}', episode=ep.rjust(3, '0') if ep.isdigit() else ep) if ep else " " * episode_width
        label = f"{ep_label}  {os.path.basename(f.name)}"
        items.append(SelectItem(
            label=label,
            value=("file", f),
            toggled=(f.index in pre_set),
            hint=" " * (size_width - cell_len(size)) + size if size else "",  # sizes right-aligned
        ))
        file_item_indexes.append(len(items) - 1)

    items.append(SelectItem(label=t("Select all"), value="all", is_action=True, hint="a"))
    items.append(SelectItem(label=t("Invert selection"), value="invert", is_action=True, hint="i"))
    items.append(SelectItem(label=t("Clear"), value="clear", is_action=True, hint="c"))
    items.append(SelectItem(label=t("Confirm"), value="confirm", is_action=True, hint="w"))
    items.append(SelectItem(label=t("Cancel"), value="cancel", is_action=True))

    # Index of the Confirm action — returned when `w` is pressed
    confirm_idx = len(items) - 2

    selection = MultiSelection(file_item_indexes, confirm_idx, SelectionPolicy(
        is_active=lambda index, item: item.toggled,
        set_active=lambda index, item, active: setattr(item, "toggled", active),
        invert=lambda index, item: setattr(item, "toggled", not item.toggled),
        toggle=lambda index, item: setattr(item, "toggled", not item.toggled),
        clear=lambda index, item: setattr(item, "toggled", False),
    ))

    def on_action(idx, items):
        val = items[idx].value
        if val == "all":
            return selection.select_all(idx, items)
        if val == "invert":
            return selection.invert(idx, items)
        if val == "clear":
            return selection.clear(idx, items)
        return False

    key_actions = selection.key_actions

    result = arrow_select(
        items,
        title=t("Select Episodes"),
        status=tn('{n} file', '{n} files', len(files)),
        multi=True,
        banner=_make_banner_panel(),
        on_action=on_action,
        key_actions=key_actions,
        footer=(
            t("↑/↓ nav  •  Space/Enter toggle  •  v anchor  •  Shift+V range  •  "
            "a all  •  i invert  •  c clear  •  w save  •  Esc cancel")
        ),
    )

    if result is None:
        return None
    action = items[result].value
    if action != "confirm":
        return None

    return [items[i].value[1].index for i in file_item_indexes if items[i].toggled]

def _make_banner_panel() -> Text:
    """The app's one-line header (kept under its old name for existing callers)."""
    return theme.header(width=console.size.width)

def subtitle_source_prompt(current: dict | None = None) -> dict:
    """Pick the subtitle source for the next stream.

    Returns a dict ``{"mode": "auto"|"off"|"external", "path": str | None}``.
    Falls back to *current* (or auto-detect) when cancelled.
    """
    import os
    from torrent_finder.constants import get_download_dir

    current = current or {"mode": "auto", "path": None}

    items = [
        SelectItem(
            label=t("Auto-detect from torrent"),
            value="auto",
            description=t("Scan the torrent for .srt/.ass files alongside each video and attach them automatically."),
        ),
        SelectItem(
            label=t("Use external subtitle file…"),
            value="external",
            description=t("Pick a .srt/.ass file from your downloads folder or type a custom path."),
            is_action=True,
        ),
        SelectItem(
            label=t("No subtitles"),
            value="off",
            description=t("Stream without attaching any subtitles."),
        ),
        SelectItem(label=t("Back"), value="back", is_action=True),
    ]

    mode_to_index = {"auto": 0, "external": 1, "off": 2}
    start = mode_to_index.get(current.get("mode", "auto"), 0)

    result = arrow_select(
        items,
        title=t("Subtitle Source"),
        banner=_make_banner_panel(),
        start_index=start,
    )

    if result is None:
        return current
    val = items[result].value
    if val == "back":
        return current
    if val in ("auto", "off"):
        return {"mode": val, "path": None}

    # external — open file picker, listing recent subs from the effective
    # download dir (which may have been overridden by the user via the
    # "📁 Save to:" menu).
    dl_dir = get_download_dir()
    sub_files: list[tuple[str, str]] = []  # (label, abs_path)
    if os.path.isdir(dl_dir):
        try:
            entries = [
                (n, os.path.getmtime(os.path.join(dl_dir, n)))
                for n in os.listdir(dl_dir)
                if n.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx"))
            ]
            entries.sort(key=lambda t: -t[1])
            for fname, _ in entries[:15]:
                sub_files.append((fname, os.path.join(dl_dir, fname)))
        except OSError:
            pass

    picker_items: list[SelectItem] = []
    for label, path in sub_files:
        picker_items.append(SelectItem(label=label, value=path))
    if not sub_files:
        picker_items.append(SelectItem(
            label=t("[{message}]", message=t("no .srt/.ass files found in downloads folder")),
            value="__none__",
            enabled=False,
            is_action=True,
        ))
    picker_items.append(SelectItem(
        label=t("Type custom path…"),
        value="__type__",
        is_action=True,
        description=t("Type or paste the absolute path to a subtitle file."),
    ))
    picker_items.append(SelectItem(label=t("Back"), value="back", is_action=True))

    pick = arrow_select(
        picker_items,
        title=t("External Subtitle File"),
        banner=_make_banner_panel(),
    )

    if pick is None:
        return current
    chosen = picker_items[pick].value
    if chosen == "back" or chosen == "__none__":
        return current
    if chosen == "__type__":
        path = get_query_with_shortcut(PROMPT, screen_renderer=input_screen(
            t("External subtitle file"), t("Path to a .srt, .ass, .ssa, .vtt, .sub or .idx file.")))
        if not isinstance(path, str) or path == "GO_BACK":
            return current
        path = path.strip().strip('"').strip("'")
        if not path:
            return current
        if not os.path.exists(path):
            console.print(t('[warning] File not found: {value}[/warning]', value=escape(path)))
            console.print(t("[muted]Press [key]any key[/key] to continue…[/muted]"))
            readchar.readkey()
            return current
        return {"mode": "external", "path": os.path.abspath(path)}
    return {"mode": "external", "path": chosen}

def download_dir_ready() -> bool:
    """Confirm the download folder is usable before a transfer starts.

    When it isn't (e.g. a disconnected drive), say why and offer to choose
    another folder; the caller keeps its torrent and file selection. False
    means the user went back without a usable folder.
    """
    from rich.markup import escape
    from torrent_finder.constants import get_download_dir, prepare_download_dir

    while True:
        try:
            prepare_download_dir()
            return True
        except OSError as error:
            reason = error.strerror or str(error)
        items = [SelectItem(t("Choose another folder"), "choose"), SelectItem(t("Back"), "back")]
        pick = arrow_select(
            items,
            title=t("Download folder unavailable"),
            banner=_make_banner_panel(),
            footer=t("Can't save to {value}: {value_other}\nNothing was downloaded.\nEnter choose  •  Esc back", value=escape(get_download_dir()), value_other=escape(reason)),
        )
        if pick is None or items[pick].value == "back":
            return False
        download_dir_prompt()

def _unpack_label(on: bool) -> str:
    return t("Unpack page archives: ON") if on else t("Unpack page archives: OFF")

_UNPACK_DESCRIPTION = (
    N_("Unpack downloaded manga/comic archives (.zip, .cbz, .rar, .cbr, .7z holding only images) into a "
    "folder of pages beside them, then delete the archive. Applies to Madokami files and to aria2c / "
    "webtorrent / peerflix downloads, not to your torrent client. Other archives are left alone.")
)

def _toggle_unpack(item) -> None:
    from torrent_finder.state import load_setting, save_setting
    from torrent_finder.unpack import SETTING
    on = not bool(load_setting(SETTING, False))
    save_setting(SETTING, on)
    item.label = _unpack_label(on)

def download_dir_prompt() -> None:
    """Pick the default download directory. Persists via ``save_setting`` and
    returns to the caller — no return value. Applies to aria2, webtorrent /
    peerflix downloads, subtitle saves, and Online-Fix / Madokami file saves
    (not streams or magnet handoff). Reachable from the download-method menu
    and the provider screen."""
    import os
    from torrent_finder.constants import DOWNLOADS_DIR
    from torrent_finder.state import load_setting, save_setting

    from torrent_finder.unpack import SETTING as UNPACK_SETTING

    home_downloads = os.path.expanduser("~/Downloads")
    current = load_setting("download_dir", None)

    items = [
        SelectItem(
            label=t('Default ({value}/)', value=os.path.basename(DOWNLOADS_DIR)),
            value="__default__",
            description=t("Save into the downloads folder in the app's user data directory.\nPath: {value}", value=escape(DOWNLOADS_DIR)),
        ),
        SelectItem(
            label="~/Downloads",
            value=home_downloads,
            description=t('Save into your user Downloads folder.\nPath: {value}', value=escape(home_downloads)),
        ),
        SelectItem(
            label=t("Type custom path…"),
            value="__type__",
            is_action=True,
            description=t("Type or paste an absolute path. Will be created if it doesn't exist."),
        ),
        SelectItem(
            label=_unpack_label(bool(load_setting(UNPACK_SETTING, False))),
            value="__unpack__",
            is_action=True,
            description=t(_UNPACK_DESCRIPTION),
        ),
        SelectItem(label=t("Back"), value="back", is_action=True),
    ]

    def toggle(idx, items):
        if items[idx].value != "__unpack__":
            return False
        _toggle_unpack(items[idx])
        return True  # stay: it is a setting beside the folder choice

    # Start cursor on the current selection when possible.
    start = 0
    if current == home_downloads:
        start = 1
    elif isinstance(current, str) and current.strip() and current != DOWNLOADS_DIR:
        start = 2

    result = arrow_select(
        items,
        title=t("Download Folder"),
        banner=_make_banner_panel(),
        start_index=start,
        on_action=toggle,
    )

    if result is None:
        return
    chosen = items[result].value
    if chosen == "back":
        return

    if chosen == "__default__":
        save_setting("download_dir", None)
        return

    if chosen == "__type__":
        path = get_query_with_shortcut(PROMPT, screen_renderer=input_screen(
            t("Download folder"), t("Folder to save downloads in; it is created if missing.")))
        if not isinstance(path, str) or path == "GO_BACK":
            return
        path = path.strip().strip('"').strip("'")
        if not path:
            return
        path = os.path.abspath(os.path.expanduser(path))
    else:
        path = chosen

    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        console.print(t('[error] Could not create directory: {value}[/error]', value=escape(str(e))))
        console.print(t("[muted]Press [key]any key[/key] to continue…[/muted]"))
        readchar.readkey()
        return
    save_setting("download_dir", path)

def confirm_prompt(message: str, title: str = N_("Confirm")) -> bool:
    """Confirm with Y/yes in every language, or S/sim in Brazilian Portuguese."""
    from rich.console import Group

    from torrent_finder.ui.selector import _render
    if title == "Confirm":
        title = t("Confirm")
    width, height = console.size.width, console.size.height
    rows = theme.view_height(height, width)
    roomy = theme.roomy(rows, 12)
    head = list(theme.frame_header(title, "", width, height)) + (theme.frame_rule(width, height) if roomy else [])
    footer = t("S confirm  •  Esc cancel") if current() == "pt-BR" else t("Y confirm  •  Esc cancel")
    keys = theme.wrap_keys(theme.parse_footer(footer).keys, width)
    body = theme.wrap_block(Text.from_markup(message), width, console)
    rule = [theme.rule(width)] if roomy else []
    extra = [Text("")] + theme.wrap_block(Text(t("Any other key cancels too."), style=theme.MUTED), width, console)
    room = rows - len(head) - len(keys)
    # A small window keeps the keys: the cancel note and the rule go first, then the message's end.
    if len(body) + len(extra) + len(rule) > room:
        extra = []
    if len(body) + len(rule) > room:
        rule = []
    if len(body) > room:
        body = body[:max(1, room)]
        body[-1].truncate(max(1, width - 1))
        body[-1].append("…")
    lines = head + body + extra + rule + keys
    if frames.too_small(width, height):
        lines = frames.enlarge_notice(width, height)
    display.enter_screen()
    try:
        _render(None, Group(*frames.compose(lines, title, "", width, height)), width=width)
        try:
            key = readchar.readkey()
        except (EOFError, KeyboardInterrupt):
            return False
        return key.casefold() in (("y", "yes", "s", "sim") if current() == "pt-BR" else ("y", "yes"))
    finally:
        display.leave_screen(clear=True)

def print_banner() -> None:
    """Start a main-screen log: the app name at column 0, then a spacer."""
    console.print(theme.log_header(width=console.size.width))
    console.print()

import os


def clear_screen() -> None:
    """Clear the console and reprint the banner to reduce visual pollution."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print_banner()


def _wrap_info_paragraph(paragraph: str, width: int) -> list[str]:
    """Keep legacy single-cell word breaks; fold wide text at whole cell boundaries."""
    import textwrap

    if paragraph.isascii() or cell_len(paragraph) == len(paragraph):
        return textwrap.wrap(paragraph, width) or [""]
    return [line.plain.rstrip() for line in Text(paragraph).wrap(console, width, overflow="fold")] or [""]


def _torrent_info_rows(info, screen_width: int) -> list[SelectItem]:
    """Derive physical rows from source paragraphs using the current viewport."""
    from torrent_finder.torrent_info import description_label, info_label

    # Preserve the old description measure and the selector's margins/gutter.
    width = max(8, screen_width - 12)
    rows: list[SelectItem] = []

    def add(text: str = "") -> None:
        rows.append(SelectItem(label=text, value="__line__", passive=True))

    def add_wrapped(text: str, indent: str = "    ") -> None:
        for para in text.splitlines() or [""]:
            for line in _wrap_info_paragraph(para, width):
                add(indent + line)

    def field(lbl: str, val: str) -> None:
        if val:
            add(f"  {lbl}: {val}")

    field(t("Title"), info.title)
    field(t("Category"), info.category)
    field(t("Uploader"), info.uploader)
    field(t("Date"), info.date)
    if info.seeders or info.leechers:
        add(t('  Seeders / Leechers: {seeders} / {leechers}', seeders=info.seeders or '?', leechers=info.leechers or '?'))
    field(t("Size"), info.size)
    field(t("Info hash"), info.info_hash)
    field(t("Embedded subs"), info_label(info.embedded_subs))

    if info.description:
        add(); rows.append(SelectItem(t("Description"), value="section_header", enabled=False))
        add_wrapped(description_label(info.description), indent="  ")

    if info.files:
        add(); rows.append(SelectItem(t('Files ({count})', count=len(info.files)), value="section_header", enabled=False))
        for name, size in info.files:
            add_wrapped(f"{name}  ({size})" if size else name)

    return rows


class _TorrentInfoItems(list[SelectItem]):
    """Keep an old cursor on Back until the selector clamps it after a resize."""

    def __getitem__(self, index):
        # Rewrapping may remove the focused physical row between key presses.
        # The selector clamps during drawing/navigation, but Enter reads first.
        if isinstance(index, int) and index >= len(self):
            index = len(self) - 1
        return super().__getitem__(index)


def torrent_info_screen(result: dict) -> None:
    """Fetch and display origin details for a torrent in a scrollable view."""
    from torrent_finder.torrent_info import fetch_torrent_info, info_label

    try:
        with console.status(t("[accent]Fetching torrent info…[/accent]"), spinner=theme.SPINNER):
            info, err = fetch_torrent_info(result)
    except KeyboardInterrupt:
        console.print(t("[warning]Torrent info fetch cancelled.[/warning]"))
        return

    if info is None:
        console.print(f"[warning]{escape(info_label(str(err)))}[/warning]")
        console.print(t("[muted]Press [key]any key[/key] to continue…[/muted]"))
        readchar.readkey()
        return

    width = console.size.width
    back = SelectItem(label=t("Back"), value="back", is_action=True)
    items = _TorrentInfoItems(_torrent_info_rows(info, width) + [back])

    def refresh() -> bool:
        nonlocal width
        current_width = console.size.width
        if current_width == width:
            return False
        items[:] = _torrent_info_rows(info, current_width) + [back]
        width = current_width
        return True

    def title() -> str:
        # A resize can also discard a frame and retry within the same draw.
        refresh()
        return t('Torrent info › {source}', source=info.source)

    arrow_select(
        items,
        title=title,
        banner=_make_banner_panel(),
        footer=t("↑/↓ scroll  •  Esc back"),
        refresh=refresh,
    )


_INSTALL_HINTS = {"aria2c": N_("install: aria2.github.io"), "webtorrent": N_("install: npm i -g webtorrent-cli"),
                  "peerflix": N_("install: npm i -g peerflix")}


def _install_hint(tool: str, available: bool) -> str:
    return "" if available else t(_INSTALL_HINTS[tool])


def _tool_label(label: str, available: bool) -> "str | Text":
    """A tool's row label; steel when the tool is not installed (the row stays readable, Enter does nothing)."""
    return label if available else Text(label, style=theme.MUTED)


def torrent_summary(torrent: "dict | None", *, file_count: "int | None" = None, subtitles: str = "",
                    selected: "list[int] | None" = None) -> Text:
    """``Nyaa · 1.4 GB · 812 seeds · 140 leeches · 2026-09-14 · 12 files · subs auto``; seeds in their health colour."""
    from datetime import datetime, timezone

    from torrent_finder.result_view import timestamp
    from torrent_finder.utils import format_size
    parts: list[Text] = []
    if torrent:
        source = str(torrent.get("source") or "")
        if source:
            parts.append(Text(source + ("*" if torrent.get("apibay_cached_at") else "")))
        size = int(torrent.get("size", 0) or 0)
        if size:
            parts.append(Text(format_size(size)))
        seeds = int(torrent.get("seeders", 0) or 0)
        seed_text = Text(t("{seeds} seeds", seeds=seeds))
        seed_text.stylize(theme.seed_style(seeds), 0, len(str(seeds)))
        parts.append(seed_text)
        leeches = int(torrent.get("leechers", 0) or 0)
        parts.append(Text(t('{leeches} leeches', leeches=leeches)))
        uploaded = timestamp(torrent.get("uploaded_at"))
        if uploaded:
            parts.append(Text(datetime.fromtimestamp(uploaded, timezone.utc).strftime("%Y-%m-%d")))
    if file_count:
        parts.append(Text(tn('{n} file', '{n} files', file_count)))
    if selected:
        from torrent_finder.torrent_meta import compact_ranges
        parts.append(Text.assemble((tn('{n} picked', '{n} picked', len(selected)), theme.ACCENT), f" ({compact_ranges(selected)})"))
    if subtitles:
        if subtitles == "auto-detect from torrent":
            subtitle_label = t("auto", ctx="subtitle mode")
        elif subtitles == "disabled":
            subtitle_label = t("off", ctx="subtitle mode")
        else:
            subtitle_label = subtitles
        parts.append(Text(t("subs {subtitles}", subtitles=subtitle_label)))
    summary = Text()
    for index, part in enumerate(parts):
        if index:
            summary.append(" · ", style=theme.MUTED)
        summary.append_text(part)
    return summary


def header_shows(subject: str, title: str, width: int, height: int, rows: int = 0) -> bool:
    """True when the header of a screen named *title* shows the whole *subject* in a window this size.

    The Athanor frame's top edge cuts a long title; Simple's header continues
    it on a second line, which a narrow window cuts too. *rows* is the list's
    length: a list longer than the window gets a position in the header, which
    takes room from the title.
    """
    position = t('{first}–{last} of {total}', first=rows, last=rows, total=rows) if rows and theme.view_height(height, width) < rows + 8 else ""
    if theme.framed(width, height):
        return subject in frames.top_edge(title, position, width).plain
    return subject in "".join(line.plain for line in theme.header_lines(title, position, width))


def download_method_prompt(
    magnet: str = "",
    show_subtitles: bool = True,
    show_episode_picker: bool = False,
    selected_indexes: list[int] | None = None,
    sub_choice: dict | None = None,
    show_streaming: bool = True,
    page_url: str | None = None,
    info_source: str | None = None,
    focus: str | None = None,
    torrent: dict | None = None,
    file_count: int | None = None,
) -> str | None:
    """
    Prompt the user to choose a download method.

    *torrent* (the picked result) fills the summary line under the header:
    source, size, seeds, leeches, upload date, *file_count* once the file
    list is known, the subtitle choice and the picked files.
    Returns 't', 'd', 'p', 'aria', 'stream_w', 'stream_p', 's', 'pick_episodes',
    'torrent_info', 'set_subs', 'back', 'cancel', or None (Esc). 'back' and Esc
    step back to the results table; 'cancel' ("Done with this torrent") means
    the caller goes to what's next. 'l' (copy magnet) and 'open_page'
    (browser) are handled internally. *focus* is the value of the row to start
    on (the option chosen last time); otherwise "Open in client" is focused.
    """
    wt_available = has_webtorrent()
    pf_available = has_peerflix()
    aria_available = has_aria2()
    client_name = torrent_client_label(detect_torrent_client())
    has_selection = bool(selected_indexes)
    n_sel = len(selected_indexes) if selected_indexes else 0

    def _section(label: str) -> SelectItem:
        return SelectItem(
            label=f"─── {label} ───",
            value="section_header",
            enabled=False,
            is_action=True,
        )

    items: list[SelectItem] = []

    # --- Torrent & files ---
    _info_available = info_source in ("Nyaa", "Apibay", "YTS")
    if show_episode_picker or _info_available:
        items.append(_section(t("Torrent & files")))
        if show_episode_picker:
            ep_label = (
                tn('Change selection ({n} picked)', 'Change selection ({n} picked)', n_sel)
                if has_selection
                else t("Browse torrent files…")
            )
            items.append(SelectItem(
                label=ep_label,
                value="pick_episodes",
                is_action=True,
                hint=_install_hint("aria2c", aria_available) or ("" if has_selection else t("pick episodes or files")),
                passive=not aria_available,
                description=(
                    t("Browse every file in the torrent and pick any subset. "
                    "Downloads grab exactly what you pick; streams auto-skip non-video files.")
                    + ("" if aria_available else t('\nNeeds aria2c to read the file list: {ARIA2_INSTALL_URL}', ARIA2_INSTALL_URL=_ARIA2_INSTALL_URL))
                ),
            ))
        if _info_available:
            items.append(SelectItem(
                label=t('Torrent info (from {info_source})', info_source=info_source),
                value="torrent_info",
                is_action=True,
                description=(
                    t("Fetch details from the source page: category, description, file "
                    "list, comments, and whether subtitles are embedded in the video.")
                ),
            ))

    # --- Subtitle source (for streaming) ---
    if show_subtitles:
        import os as _os
        mode = (sub_choice or {}).get("mode", "auto")
        paths = (sub_choice or {}).get("paths")
        if not paths:
            _single = (sub_choice or {}).get("path")
            paths = [_single] if _single else []
        if mode == "auto":
            sub_label = N_("auto-detect from torrent")  # subtitle summary identity
        elif mode == "off":
            sub_label = N_("disabled")  # subtitle summary identity
        elif not paths:
            sub_label = t("file: ?")
        elif len(paths) == 1:
            sub_label = t('file: {value}', value=_os.path.basename(paths[0]))
        else:
            sub_label = t('{count} tracks: {value} +{value_other}', count=len(paths), value=_os.path.basename(paths[0]), value_other=len(paths) - 1)
        items.append(_section(t("Subtitles")))
        items.append(SelectItem(
            label=t('Subtitles: {subtitles}', subtitles=t(sub_label) if mode in ("auto", "off") else sub_label),
            value="set_subs",
            is_action=True,
            description=(
                t("Choose how VLC gets subtitles when streaming: auto-detect inside "
                "the torrent, use an external .srt/.ass file, or disable subtitles.")
            ),
        ))
        # Co-located with Source: searching downloads a .srt and auto-promotes it
        # to external source-mode, so the two subtitle rows belong together.
        items.append(SelectItem(
            label=t("Search & download subtitles"),
            value="s",
            description=t("Find a matching .srt via OpenSubtitles and save it next to the video"),
        ))

    # --- Stream to VLC (hidden for non-video providers, e.g. Manga) ---
    if show_streaming:
        items.append(_section(t("Stream to VLC")))
        items.append(SelectItem(
            label=_tool_label(t("Stream with webtorrent"), wt_available),
            value="stream_w",
            passive=not wt_available,
            hint=(
                _install_hint("webtorrent", False) if not wt_available
                else tn('plays {n} episode in order', 'plays {n} episodes in order', n_sel) if has_selection
                else t("needs VLC")
            ),
            description=t("Stream via webtorrent — good streaming default")
                        + ("" if wt_available else t('\nInstall: {WEBTORRENT_INSTALL_URL}', WEBTORRENT_INSTALL_URL=_WEBTORRENT_INSTALL_URL)),
        ))
        items.append(SelectItem(
            label=_tool_label(t("Stream with peerflix"), pf_available),
            value="stream_p",
            passive=not pf_available,
            hint=(
                _install_hint("peerflix", False) if not pf_available
                else tn('plays {n} episode in order', 'plays {n} episodes in order', n_sel) if has_selection
                else t("needs VLC")
            ),
            description=t("Watch while downloading via VLC (peerflix) — try if webtorrent stalls or finds no peers")
                        + ("" if pf_available else t('\nInstall: {PEERFLIX_INSTALL_URL}', PEERFLIX_INSTALL_URL=_PEERFLIX_INSTALL_URL)),
        ))

    # --- Download ---
    # "Open in client" leads the section and is the default-focused row (see
    # default_focus below): it's the only option that seeds and the natural
    # primary for non-streaming providers (games/software). The terminal
    # downloaders follow, aria2c first as the best of them.
    items.append(_section(t("Download")))
    default_focus = len(items)  # index of the row the cursor should start on
    items.append(SelectItem(
        label=t('Open in {client_name}', client_name=client_name),
        value="t",
        hint=(t("untick unwanted files in its dialog") if has_selection
              else Text.assemble((t("recommended"), theme.ACCENT), t(" · seeds · GUI"))),
        description=t("Hand the magnet to your desktop client — use to seed or manage in a GUI"),
    ))
    from torrent_finder.qbittorrent import configured
    if configured():
        items.append(SelectItem(t("Send to qBittorrent WebUI"), "qbittorrent",
                                description=t("Choose client folder/category and view real progress. Adds the full torrent; manage file selection in qBittorrent.")))
    items.append(SelectItem(
        label=_tool_label(t("Download with aria2c"), aria_available),
        value="aria",
        passive=not aria_available,
        hint=(
            _install_hint("aria2c", False) if not aria_available
            else t("fastest · picked files only") if has_selection
            else t("fastest · resumes · no seeding")
        ),
        description=t("Best downloader — native multi-file, resumes, fastest for batches")
                    + ("" if aria_available else t('\nInstall: {ARIA2_INSTALL_URL}', ARIA2_INSTALL_URL=_ARIA2_INSTALL_URL)),
    ))
    items.append(SelectItem(
        label=_tool_label(t("Download with webtorrent"), wt_available),
        value="d",
        passive=not wt_available,
        hint=(
            _install_hint("webtorrent", False) if not wt_available
            else t("may download the full torrent") if has_selection
            else t("slower · no seeding")
        ),
        description=(
            t("Plain download via webtorrent — one file per run, no seeding. "
            "--select is not strict; webtorrent-cli often downloads the whole torrent anyway. "
            "Use aria2c if you need strict file picking.")
            + ("" if wt_available else t('\nInstall: {WEBTORRENT_INSTALL_URL}', WEBTORRENT_INSTALL_URL=_WEBTORRENT_INSTALL_URL))
        ),
    ))
    items.append(SelectItem(
        label=_tool_label(t("Download with peerflix"), pf_available),
        value="p",
        passive=not pf_available,
        hint=(
            _install_hint("peerflix", False) if not pf_available
            else t("ignores the file selection") if has_selection
            else t("slower · no seeding")
        ),
        description=(
            t("Plain download via peerflix — slower than aria2, no seeding. "
            "Does NOT honor file selection: peerflix always downloads the whole torrent. "
            "Use aria2c if you need strict file picking.")
            + ("" if pf_available else t('\nInstall: {PEERFLIX_INSTALL_URL}', PEERFLIX_INSTALL_URL=_PEERFLIX_INSTALL_URL))
        ),
    ))

    # --- Other ---
    items.append(_section(t("Other")))
    items.append(SelectItem(
        label=t("Copy magnet link"),
        value="l",
        is_action=True,
        description=t("Copies the magnet URI to your clipboard"),
    ))
    if page_url:
        from urllib.parse import urlparse as _urlparse
        _page_domain = _urlparse(page_url).netloc or page_url
        items.append(SelectItem(
            label=t("Open torrent page"),
            value="open_page",
            is_action=True,
            hint=_page_domain,
            description=t("Open this torrent's page on its source site in your browser.\n{value}", value=escape(page_url)),
        ))

    # --- Settings (persistent across runs, unlike the one-shot actions above) ---
    items.append(_section(t("Settings")))

    # Persistent download-folder override. Applies to aria2/webtorrent/peerflix
    # downloads + subtitle saves (not streams, not magnet handoff).
    import os as _os_dir
    from torrent_finder.constants import get_download_dir
    _dl_dir = get_download_dir()
    _dl_basename = _os_dir.path.basename(_dl_dir.rstrip(_os_dir.sep)) or _dl_dir
    items.append(SelectItem(
        label=t('Save to: {dl_basename}', dl_basename=_dl_basename),
        value="set_download_dir",
        is_action=True,
        description=(
            t("Choose where to save downloads made by the app and subtitles. Default: the downloads folder in the app's user data directory.\nCurrent: {value}", value=escape(_dl_dir))
        ),
    ))

    # Persistent toggle: suppress subprocess UI (progress bars, peer lists) and
    # replace it with a single spinner line. Applies to all stream + download
    # paths on the next launch.
    from torrent_finder.state import load_setting
    quiet_on = bool(load_setting("hide_stream_output", False))

    def _quiet_label(on: bool) -> str:
        return t("Quiet mode: ON") if on else t("Quiet mode: OFF")

    items.append(SelectItem(
        label=_quiet_label(quiet_on),
        value="toggle_quiet",
        is_action=True,
        description=(
            t("Hide the native progress UI of webtorrent/peerflix/aria2 and show "
            "a minimal spinner instead. Persists across runs.")
        ),
    ))
    # Persistent toggle: aria2c downloads (single and batch) as background
    # jobs, followed from the Downloads screen, instead of taking this screen.
    from torrent_finder.ui import downloads as downloads_ui
    items.append(SelectItem(
        label=downloads_ui.setting_label(),
        value="toggle_background",
        is_action=True,
        description=t(downloads_ui.SETTING_HELP),
    ))
    from torrent_finder.unpack import SETTING as UNPACK_SETTING
    items.append(SelectItem(
        label=_unpack_label(bool(load_setting(UNPACK_SETTING, False))),
        value="toggle_unpack",
        is_action=True,
        description=t(_UNPACK_DESCRIPTION),
    ))

    # --- Trailing actions ---
    items.append(SelectItem(
        label=t("Back to results"),
        value="back",
        is_action=True,
        description=t("Return to the search results list"),
    ))
    items.append(SelectItem(label=t("Done with this torrent"), value="cancel", is_action=True,
                            description=t("Leave this torrent and choose what to do next.")))

    def handle_download_action(idx, items):
        if items[idx].value == "l" and magnet:
            try:
                import subprocess, platform
                if platform.system() == "Windows":
                    subprocess.run("clip", input=magnet.encode(), check=True)
                elif platform.system() == "Darwin":
                    subprocess.run("pbcopy", input=magnet.encode(), check=True)
                else:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=magnet.encode(), check=True)
                items[idx].hint = t("✓ copied")
            except Exception:
                items[idx].hint = t("could not copy")
            return True  # Stay in menu
        if items[idx].value == "open_page" and page_url:
            try:
                import webbrowser
                opened = webbrowser.open(page_url)
            except Exception:
                opened = False
            if opened:
                items[idx].hint = t("✓ opened")
            else:
                from torrent_finder.main import _copy_to_clipboard
                copied = _copy_to_clipboard(page_url)
                items[idx].hint = (t("could not open the browser · URL copied") if copied
                                   else t("could not open the browser · could not copy URL"))
            return True  # Stay in menu
        if items[idx].value == "toggle_unpack":
            _toggle_unpack(items[idx])
            return True
        if items[idx].value == "toggle_background":
            downloads_ui.toggle_setting(items[idx])
            return True
        if items[idx].value == "toggle_quiet":
            from torrent_finder.state import load_setting, save_setting
            new_state = not bool(load_setting("hide_stream_output", False))
            save_setting("hide_stream_output", new_state)
            items[idx].label = _quiet_label(new_state)
            return True  # Stay in menu — arrow_select redraws in place, no flicker
        return False

    # The header names the picked torrent; the summary under it says what it is.
    title = t("Download")
    name = str(torrent.get("name") or t("Unknown")) if torrent else ""
    if torrent:
        title += f" › {escape(name)}"
    summary = torrent_summary(torrent, file_count=file_count,
                              subtitles=sub_label if show_subtitles else "",
                              selected=selected_indexes if has_selection else None)

    def intro() -> "Text | list[Text]":
        """The summary, under the name when a narrow window's header cuts it to a stump.

        A short window keeps one intro line, so there the name stands alone.
        """
        width, height = console.size.width, console.size.height
        if torrent and not header_shows(name, title, width, height, len(items)):
            name_line = Text(name, style="bold")
            return [name_line, summary] if theme.roomy(theme.view_height(height, width), 20) else [name_line]
        return summary

    idx = arrow_select(
        items,
        title=title,
        intro=intro,
        banner=_make_banner_panel(),
        on_action=handle_download_action,
        footer=t("↑/↓ navigate  •  Enter select  •  Esc back to results"),
        # Return to the option chosen last time, else "Open in client" (the primary action).
        start_index=next((i for i, item in enumerate(items) if focus and item.value == focus), default_focus),
    )

    if idx is None:
        return None

    return items[idx].value


def batch_download_menu(count: int, copyable: int) -> "str | None":
    """Reduced download menu for a multi-torrent selection.

    Only the actions that generalise across many *different* torrents: hand them
    all to the system client (it queues and downloads in parallel), or copy
    their magnets. Per-torrent actions (browse files, info, subtitles, stream)
    don't apply to a batch and are omitted — pick a single torrent for those.

    ``copyable`` is how many of the selected items actually have a magnet
    (Online-Fix and Madokami have none); Copy is disabled when it's zero.
    Returns "open", "copy", "back", "cancel" ("Done with this selection"), or
    None (Esc — caller treats it as back).
    """
    from torrent_finder.downloader import detect_torrent_client

    client = torrent_client_label(detect_torrent_client())
    copy_label = t("Copy all magnet links")
    if copyable != count:
        copy_label += f" ({copyable})"
    aria_ok = has_aria2()
    aria_label = t("Download all with aria2c")
    if copyable != count:
        aria_label += f" ({copyable})"
    items = [
        SelectItem(
            label=t('Open all {count} in {client}', count=count, client=client),
            value="open",
            is_action=True,
            description=(
                t("Hand every selected torrent to your desktop client at once — it "
                "queues and downloads them in parallel. Press Esc mid-run to stop.")
            ),
        ),
        SelectItem(
            label=aria_label,
            value="aria",
            is_action=True,
            enabled=(aria_ok and copyable > 0),
            hint=(
                "" if (aria_ok and copyable > 0)
                else t('aria2c not installed — {ARIA2_INSTALL_URL}', ARIA2_INSTALL_URL=_ARIA2_INSTALL_URL) if not aria_ok
                else t("no magnet links in this selection")
            ),
            description=(
                t("Download every selected torrent with one aria2c process — parallel and "
                "no torrent client needed. Online-Fix / Madokami / Libgen / F-Droid entries have no magnet "
                "and are skipped.")
            ),
        ),
        SelectItem(
            label=copy_label,
            value="copy",
            is_action=True,
            enabled=copyable > 0,
            hint=("" if copyable > 0 else t("no magnet links in this selection")),
            description=(
                t("Copy the magnets to your clipboard. Online-Fix / Madokami / Libgen / F-Droid entries have "
                "no magnet and are skipped; RuTracker / FitGirl links are resolved on demand.")
            ),
        ),
        SelectItem(
            label=t("Back to results"),
            value="back",
            is_action=True,
            description=t("Return to the results list to change your selection."),
        ),
        SelectItem(label=t("Done with this selection"), value="cancel", is_action=True,
                   description=t("Leave these torrents and choose what to do next.")),
    ]

    from torrent_finder.qbittorrent import configured
    if configured():
        items.insert(1, SelectItem(t("Send selection to qBittorrent WebUI"), "qbittorrent",
                                   description=t("Magnets and Online-Fix torrent files. Direct downloads are skipped.")))
    idx = arrow_select(
        items,
        title=t("Batch download"),
        status=tn('{n} torrent', '{n} torrents', count),
        banner=_make_banner_panel(),
        start_index=0,
        footer=t("↑/↓ navigate  •  Enter select  •  Esc back to results"),
    )
    if idx is None:
        return None
    return items[idx].value


def credentials_menu() -> None:
    """Open the dedicated credentials UI module."""
    from torrent_finder.ui.credentials import credentials_menu as open_menu

    open_menu()


def _provider_note(provider) -> str:
    note = getattr(provider, "search_note", "")
    return t(note)


def _provider_group_menu(group) -> object | None:
    """Submenu for a provider group (e.g. Software → Desktop / Mobile / RuTracker).

    Returns the chosen child provider, or None to go back to the provider list.
    Mirrors the main screen: F opens a child's filter menu, Esc/Back returns None.
    """
    items = [
        SelectItem(label=p.label, value=p, description=_provider_note(p))
        for p in group.children
    ]
    items.append(SelectItem(label=t("Back"), value="__back__", is_action=True))

    _filter_request = {"target": None}

    def _handle_f(cursor, items_list):
        target = items_list[cursor].value
        if isinstance(target, str):
            return True  # the Back row — no filters
        _filter_request["target"] = target
        return cursor

    start = 0
    while True:
        _filter_request["target"] = None
        result = arrow_select(
            items,
            title=group.label,
            footer=t("↑/↓ navigate  •  Enter select  •  F filters  •  Esc back"),
            banner=_make_banner_panel(),
            start_index=start,
            key_actions={"F": _handle_f, "f": _handle_f},
        )

        if result is None:
            return None

        if _filter_request["target"] is not None:
            filter_menu(_filter_request["target"])
            start = result
            continue

        chosen = items[result].value
        if chosen == "__back__":
            return None
        return chosen


def _provider_source_menu(provider, facets=None) -> "str | object | None":
    """Choose how to search a creator-capable provider.

    Shows normal keyword search up top, then one row per creator facet
    (director/studio/author/…) under a "By <labels>" section header. ``facets``
    is the already-credential-filtered list (falls back to all when omitted).
    Returns:
      - ``"search"`` for the normal keyword search,
      - a ``CreatorFacet`` to search by that facet,
      - ``None`` to go back to the provider list.
    """
    if facets is None:
        facets = list(getattr(provider, "creator_facets", []) or [])
    if not facets:
        return "search"

    items = [
        SelectItem(label=t("─── Search ───"), value="section_header", enabled=False, is_action=True),
        SelectItem(
            label=t("Keyword search"),
            value="__search__",
            description=t("Type a query and search the enabled engines, as usual."),
        ),
    ]
    items.append(SelectItem(label=t("Alternate-title search"), value="__titles__",
                            description=t("Identify a work in a catalog, review its English/native/alternative names, then search them together.")))
    items.append(SelectItem(label=t("Discover by topic / genre"), value="__discover__",
                            description=t("Choose catalog topics, select matching works, then search their titles.")))
    header = t("By {facets}", facets=" / ".join(t(f.label) for f in facets))
    items.append(SelectItem(label=f"─── {header} ───", value="section_header", enabled=False, is_action=True))
    for f in facets:
        items.append(SelectItem(
            label=t('By {facet}', facet=t(f.label).lower()),
            value=("facet", f),
            description=t(f.note),
        ))
    items.append(SelectItem(label=t("Back"), value="__back__", is_action=True))

    idx = arrow_select(
        items,
        title=t('Search options › {provider}', provider=provider.label),
        banner=_make_banner_panel(),
        footer=t("↑/↓ navigate  •  Enter select  •  Esc back"),
        start_index=1,  # land on the keyword-search row, skipping the header
    )
    if idx is None:
        return None
    val = items[idx].value
    if val == "__search__":
        return "search"
    if val == "__titles__":
        return "titles"
    if val == "__discover__":
        return "discover"
    if isinstance(val, tuple) and val and val[0] == "facet":
        return val[1]
    return None  # __back__


def _presets_hint(provider) -> list[tuple[str, str]]:
    """``Prefer 1080p`` / ``Require Dublado (PT-BR) +1`` parts: the word in the accent, names in text."""
    parts: list[tuple[str, str]] = []
    for word, presets in (("Require", provider.active_presets), ("Prefer", provider.preferred_presets)):  # i18n: ignore — preset identity
        if presets:
            more = f" +{len(presets) - 1}" if len(presets) > 1 else ""
            parts += [(t(word, ctx="preset state"), theme.ACCENT), (f" {presets[0].label}{more}", "")]
    return parts


def provider_hint(provider) -> Text:
    """What a provider row will search: its On engines and its presets."""
    from torrent_finder.providers.combined_provider import provider_display_label
    if getattr(provider, "is_combined", False):
        selected = [p for p in provider.children if p.slug in provider.selected_slugs]

        def category_label(child):
            # Find the category by identity, before drawing; translated qualified
            # labels (and qps markers) must never be split to recover a name.
            group = next((group for group in PROVIDER_MENU if isinstance(group, ProviderGroup)
                          and any(member.slug == child.slug for member in group.children)), None)
            return group.label if group is not None else provider_display_label(child)

        names = ", ".join(category_label(p) for p in selected)
        names = names if len(selected) <= 3 else tn('{n} provider', '{n} providers', len(selected))
        hint = Text(names or t("no providers selected"))
        hint.append(t(' · profile {profile}', profile=provider.profile_label))
        return hint
    if isinstance(provider, ProviderGroup):
        return Text(", ".join(child.label for child in provider.children))
    engines = [engine.name for engine in provider.effective_engines]
    hint = Text(", ".join(engines) if engines else t("no engines On"))
    presets = _presets_hint(provider)
    if presets:
        hint.append(" · ")
        for value, style in presets:
            hint.append(value, style=style or "default")
    return hint


def _folder_hint(path: str, room: int = 28) -> str:
    """A download folder as ``~/Downloads``: the home folder shortened, long paths keep their end."""
    import os
    home = os.path.expanduser("~")
    shown = "~" + path[len(home):] if path.casefold().startswith(home.casefold()) else path
    shown = shown.replace("\\", "/")
    return shown if cell_len(shown) <= room else "…" + shown[-(room - 1):]


def _credentials_hint() -> str:
    from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
    ready = sum(spec.status() != "not set" for spec in CREDENTIAL_REGISTRY)
    return tn('{n} of {total} set', '{n} of {total} set', ready, total=len(CREDENTIAL_REGISTRY))


def _continue_item(entry: dict) -> "SelectItem | None":
    """The CONTINUE row for the newest history entry, or None when its provider is gone."""
    from torrent_finder.providers import display_name_for, get_provider_by_slug
    from torrent_finder.utils import relative_time
    if not isinstance(entry, dict) or not get_provider_by_slug(str(entry.get("provider", ""))):
        return None
    query = str(entry.get("query", "")).strip()
    if not query:
        return None
    when = relative_time(entry.get("timestamp"))
    hint = display_name_for(entry["provider"]) + (f" · {when}" if when else "")
    replays = entry.get("kind") == "creator" or entry.get("queries") or entry.get("search_profile")
    if entry.get("queries"):
        hint += tn(' · {n} name', ' · {n} names', len(entry['queries']))
    description = (t("Runs this search again with its saved names and settings.") if replays
                   else t("Opens the search field with this search; Enter runs it, or edit it first."))
    return SelectItem(label=query, value=("history" if replays else "continue", entry), hint=hint,
                      description=description, inspect=lambda: inspector.continue_search(entry))


def _section_row(label: str) -> SelectItem:
    return SelectItem(label=label, value="section_header", enabled=False)


def home_status(update_status: str = "") -> str:
    """The main menu's header status: version, a pending update, the network check's verdict.

    The Athanor status line already ends in the version and the network verdict,
    so under it the header keeps only the update.
    """
    from torrent_finder import __version__
    from torrent_finder.security import exposure_label
    from torrent_finder.ui.downloads import badge
    if theme.bars(console.size.width, console.size.height):
        return f"[warn]{escape(update_status)}[/warn]" if update_status else ""
    parts = [f"v{escape(str(__version__))}"]
    downloading = badge()
    if downloading:
        parts.insert(0, downloading)  # Simple has no status line: the downloads figure leads the header
    if update_status:
        parts.append(f"[warn]{escape(update_status)}[/warn]")
    network = exposure_label()
    if network:
        parts.append(network)
    return " · ".join(parts)


def settings_menu() -> None:
    """Appearance, the terminal command and the network check, behind one Settings row."""
    from torrent_finder.launcher_alias import current_status
    from torrent_finder.security import exposure_label, show_security_warning
    from torrent_finder.ui.appearance import appearance_menu
    start = 0
    while True:
        palette, focus, density = theme.current()
        command = current_status()
        items = [
            SelectItem(t("Appearance"), "appearance",
                       hint=f"{palette.name} · {t(_FOCUS_LABELS[focus]).lower()} · {t(_DENSITY_LABELS[density])}",
                       description=t("Theme colours, how the focused row is marked, and spacing."),
                       inspect=inspector.appearance_details),
            SelectItem(t("Language", ctx="setting"), "__language__", hint=_language_hint(),
                       description=(t("The language of menus and messages. Automatic follows the Windows display "
                                      "language.") if sys.platform == "win32" else
                                    t("The language of menus and messages. Automatic follows the system language.")),
                       inspect=inspector.language_details),
            SelectItem(t('Terminal command: {name}', name=command.name), "__terminal_command__",
                       hint=t("ready") if command.available else t("setup needed"),
                       description=(t("Choose a preferred quick-launch command for new terminal sessions. "
                                    "The canonical torrent-finder command always remains available.")),
                       inspect=inspector.command_details),
            SelectItem(t("Network exposure info"), "__network_info__",
                       hint=Text.from_markup(exposure_label()) if exposure_label() else "",
                       description=t("Check which IP address peers see before downloading."),
                       inspect=inspector.network_details),
            SelectItem(t("Back"), None, is_action=True),
        ]
        index = arrow_select(items, title=t("Settings"), banner=_make_banner_panel(), start_index=start,
                             footer=t("↑/↓ navigate  •  Enter select  •  Esc back"))
        if index is None or items[index].value is None:
            return
        start = index
        action = items[index].value
        if action == "appearance":
            appearance_menu()
        elif action == "__language__":
            language_menu()
        elif action == "__terminal_command__":
            from torrent_finder.ui.launcher import terminal_command_prompt
            terminal_command_prompt()
        elif action == "__network_info__":
            show_security_warning(force=True)


def _language_hint() -> str:
    """The language in use and what chose it: ``English (system)``, ``Português (Brasil)``."""
    from torrent_finder import i18n
    from torrent_finder.state import load_setting
    code = i18n.current()
    name = i18n.languages().get(code, code)
    source = i18n.source()
    if source == "system" or (source == "saved" and load_setting(i18n.SETTING) == i18n.AUTO):
        return t("{language} (system)", language=name)
    if source == "cli":
        return f"{name} (--lang)"
    if source == "env":
        return f"{name} ({i18n.ENV})"
    return name


def language_menu() -> None:
    """Settings › Language: Automatic (the system's display language) or a language the app speaks.

    The choice is saved and used at once; the menus a user returns to are
    built again, so they redraw in the new language.
    """
    from torrent_finder import i18n, store
    from torrent_finder.state import commit_setting, load_setting
    windows = sys.platform == "win32"
    system = i18n.languages().get(i18n.detect(), i18n.languages()[i18n.DEFAULT])
    items = [SelectItem(t("Automatic (system: {language})", language=system), i18n.AUTO,
                        hint=t("changes with Windows") if windows else t("follows the system"),
                        description=(t("Uses the Windows display language when the app has it; English otherwise.")
                                     if windows else
                                     t("Uses the system language when the app has it; English otherwise.")))]
    items += [SelectItem(name, code, hint=i18n.OWN_WORDS.get(code, ""),
                         description=t("Keys stay the same in every language."))
              for code, name in i18n.languages().items()]
    items.append(SelectItem(t("Back"), None, is_action=True))
    saved = load_setting(i18n.SETTING, None) or i18n.AUTO
    start = next((i for i, item in enumerate(items) if item.value == saved), 0)
    index = arrow_select(items, title=t("Settings › Language"), start_index=start,
                         footer=t("↑/↓ navigate  •  Enter apply  •  Esc back"))
    if index is None or items[index].value is None:
        return
    value, before = items[index].value, i18n.source()
    try:
        commit_setting(i18n.SETTING, value)
    except (ValueError, store.SaveError) as error:
        frames.announce(f"[warn]{escape(t('The language was not saved: {error}', error=str(error)))}[/warn]")
    code = i18n.choose(value)
    frames.announce(escape(t("Language: {language}.", language=i18n.languages().get(code, code))))
    if before in ("cli", "env"):
        frames.announce(escape(t("Saved; --lang and {variable} still choose the language at startup.",
                                 variable=i18n.ENV)))


def provider_select_prompt(
    notice: str = "", open_group=None, update_available: bool = False,
    quit_guard: "QuitGuard | None" = None, update_status: str = "", refresh_update=None,
) -> object | None:
    """The main menu: continue the last search, pick a provider, or open a tool.

    Rows come in three sections. CONTINUE holds the newest history entry;
    SEARCH the providers and groups, each hinting what it will search; TOOLS
    the update, quick actions, credentials, download folder and settings rows.
    The header's status names the version, a pending update and the network
    check's verdict.

    Press F on a highlighted provider to configure its filters without leaving the menu.
    Press H to browse search history, S for stats, T for all tips and shortcuts.

    ``notice`` is an optional Rich-markup line (e.g. an "update available"
    banner) prepended to the footer; pass "" to show nothing. ``quit_guard``
    draws "press again to quit" under the key bar while it is armed; any
    choice made here, a submenu included, disarms it.
    ``update_status`` is a few words for the header ("update 0.8.2 ready").

    ``update_available`` adds an "Install update" action row (and the U hotkey)
    so the update is reachable right here, not only via Tab → quick actions.

    ``open_group`` (a ProviderGroup) jumps straight into that group's submenu —
    used by back-navigation from a group child so Esc returns to the source
    submenu (Esc in the submenu then falls through to the full provider list).

    Returns:
        - A provider object for normal selection.
        - A ``("history", entry)`` tuple when the user picks a history entry
          (the raw entry dict; main routes keyword vs creator).
        - A ``("continue", entry)`` tuple for the CONTINUE row of a plain
          keyword search: main opens the search field with its query.
        - ``"__update__"`` when the user picks the update row / presses U.
        - ``"__actions__"`` for Quick actions / Tab.
        - ``None`` if cancelled.
    """
    if open_group is not None:
        chosen = _provider_group_menu(open_group)
        if chosen is not None:
            return chosen
        # backed out of the submenu → fall through to the full provider list

    start = None

    # Closure flag: set by key_action when F is pressed on a provider
    _filter_request = {"target": None}

    def _handle_f(cursor, items_list):
        target = items_list[cursor].value
        if not hasattr(target, "engines"):
            # Not a provider (a group, the continue row, a tool): groups have no
            # filters of their own — drill in with Enter instead. Ignore silently.
            return True  # stay in menu, no flicker
        _filter_request["target"] = target
        return cursor  # exit menu to open filter_menu outside

    from torrent_finder.ui.tips import random_tip

    while True:
        _filter_request["target"] = None

        # Rebuilt every pass so hints show what changed in a submenu (filters,
        # the download folder, credentials) without leaving the screen.
        from torrent_finder.constants import get_download_dir
        from torrent_finder.state import load_history

        try:
            history = load_history()
        except (OSError, ValueError):
            history = []
        continue_item = _continue_item(history[0]) if history else None
        room_exits = ([(t("continue"), continue_item.label)] if continue_item else []) + [
            (t("search"), tn('{n} shelf', '{n} shelves', len(PROVIDER_MENU))), (t("tools"), t("credentials, settings"))]

        def room(exits=room_exits):
            """The Athanor main menu's room description, in windows tall enough to keep every row."""
            if not theme.FRAMED or theme.view_height(console.size.height, console.size.width) < 30:
                return ""
            heading = Text(t("~ The Index ~"), style=f"bold {theme.ACCENT}", justify="center")
            words = Text(t("Lamplight pools over shelves of catalogued torrents. A terminal hums here."))
            paths = Text(t("Obvious exits: "), style=theme.MUTED)
            for index, (name, note) in enumerate(exits):
                if index:
                    paths.append("  ")
                paths.append(name)
                if note:
                    paths.append(f" ({note})", style=theme.MUTED)
            return [heading, words, paths]
        items: list[SelectItem] = []
        if continue_item is not None:
            items += [_section_row(t("Continue")), continue_item]
        items.append(_section_row(t("Search")))
        items += [
            SelectItem(label=p.label, value=p, hint=provider_hint(p), description=_provider_note(p),
                       inspect=lambda p=p: inspector.provider(p))
            for p in PROVIDER_MENU
        ]
        items.append(_section_row(t("Tools")))
        if update_available:
            items.append(SelectItem(label=t("Install update"), value="__update__", hint="U",
                                    description=t("Install the new version now; the app reopens when it is done.")))
        items += [
            SelectItem(t("Quick actions"), value="__actions__", hint="Tab",
                       description=t("Bookmarks, alternate titles, topic discovery, backup and more.")),
            SelectItem(t("Credentials"), value="__credentials__", hint=_credentials_hint(),
                       description=t("Manage subtitle logins (OpenSubtitles / Addic7ed / Jimaku), search-provider "
                                   "logins (RuTracker / Online-Fix / Madokami), and the optional TMDB / IGDB "
                                   "creator-search upgrades."),
                       inspect=inspector.credentials),
            SelectItem(t("Download folder"), value="__download_dir__", hint=_folder_hint(get_download_dir()),
                       description=(
                           t('Current: {value}\nThe default folder for aria2c / webtorrent / peerflix downloads, subtitle saves, and Online-Fix / Madokami / Libgen / F-Droid files.\nAlso here: unpack downloaded manga archives into folders of pages.', value=escape(get_download_dir()))),
                       inspect=lambda: inspector.download_folder(get_download_dir())),
        ]
        # Downloads, once a background download was started this session: a
        # live count beside the name, and D opens the screen.
        from torrent_finder.ui import downloads as downloads_ui
        downloads_row = downloads_ui.menu_row()
        if downloads_row is not None:
            items.append(downloads_row)
        items.append(
            SelectItem(t("Settings"), value="__settings__", hint=t("theme · command · network"),
                       description=t("Theme and spacing, the quick-launch terminal command, and the network check."),
                       inspect=inspector.settings))
        if start is None:
            start = 1  # the continue row when there is one, else the first provider

        # Fresh tip each time we enter the selector — but NOT on every render
        # (that would re-roll on every keypress and make the screen jitter).
        tip_line = random_tip()

        def footer(complete=False):
            # Re-evaluated on every render: resizing the open menu switches
            # between the full key bar and a compact one.
            if downloads_row is not None:
                full = t("↑/↓ navigate  •  Enter select  •  F filters  •  H history  •  S stats  •  T tips  •  Tab actions  •  D downloads  •  Esc quit")
                compact = t("↑/↓ move • Enter select • Tab actions • Esc quit\nF filters • H history • S stats • D downloads")
            else:
                full = t("↑/↓ navigate  •  Enter select  •  F filters  •  H history  •  S stats  •  T tips  •  Tab actions  •  Esc quit")
                compact = t("↑/↓ move • Enter select • Tab actions • Esc quit\nF filters • H history • S stats")
            if update_available:
                full += " • " + t("U update")
            if complete:
                return full
            keys = compact if console.size.height < 24 or _keybar_wraps(full, console.size.width, items) else full
            return (notice + "\n" if notice else "") + keys

        hotkeys = {"H": "history", "h": "history", "S": "stats", "s": "stats",
                   "T": "tips", "t": "tips", "\t": "actions"}
        if update_available:
            hotkeys.update({"U": "update", "u": "update"})
        if downloads_row is not None:
            hotkeys.update({"D": "downloads", "d": "downloads"})
        downloads_seen = {"revision": downloads_ui.revision()}

        def refresh_menu():
            nonlocal update_available, update_status, notice
            changed = False
            if downloads_row is not None and downloads_ui.poll(downloads_seen):
                downloads_ui.update_menu_row(downloads_row)
                changed = True
            if refresh_update is None:
                return changed
            from torrent_finder.updates import status_label
            info, message = refresh_update()
            if not info or update_available:
                return changed
            update_available, update_status = True, status_label(info)
            notice = "" if theme.FRAMED else message
            # Append within Tools so an idle refresh never shifts the focused row.
            items.append(SelectItem(label=t("Install update"), value="__update__", hint="U",
                                    description=t("Install the new version now; the app reopens when it is done.")))
            hotkeys.update({"U": "update", "u": "update"})
            return True

        result = arrow_select(
            items,
            title=t("Select Provider"),
            status=lambda: home_status(update_status),
            intro=room,
            footer=footer,
            help_footer=lambda: footer(complete=True),
            banner=_make_banner_panel(),
            start_index=start,
            alert=quit_guard.hint if quit_guard else "",
            tip=tip_line,
            hotkeys=hotkeys,
            refresh=refresh_menu if refresh_update is not None or downloads_row is not None else None,
            key_actions={"F": _handle_f, "f": _handle_f},
        )

        if result is None:
            return None
        if quit_guard:
            quit_guard.armed = False  # any other choice disarms it, a submenu included

        # F key pressed on a provider — open its filter menu
        if _filter_request["target"] is not None:
            filter_menu(_filter_request["target"])
            start = result  # result is the cursor index returned by key_action
            continue

        # H/S hotkeys — open history / stats
        if isinstance(result, tuple) and result[0] == "hotkey":
            _, action, cursor = result
            if action == "actions":
                return "__actions__"
            if action == "history":
                from torrent_finder.ui.history import history_select_prompt
                pick = history_select_prompt()
                if pick:
                    return ("history", pick)  # entry dict — main routes keyword vs creator
                start = cursor
                continue
            if action == "stats":
                from torrent_finder.ui.stats import stats_page
                stats_page()
                start = cursor
                continue
            if action == "tips":
                from torrent_finder.ui.tips_page import tips_page
                tips_page()
                start = cursor
                continue
            if action == "downloads":
                downloads_ui.downloads_screen()
                start = cursor
                continue
            if action == "update":
                return "__update__"

        value = items[result].value
        start = result
        if isinstance(value, tuple) and value[0] in ("history", "continue"):
            return value
        if value in ("__update__", "__actions__"):
            return value
        if value == "__downloads__":
            downloads_ui.downloads_screen()
            continue
        if value == "__credentials__":
            credentials_menu()
            continue
        if value == "__download_dir__":
            download_dir_prompt()
            continue
        if value == "__settings__":
            settings_menu()
            continue

        # A group row — drill into its submenu. Picking a child returns it to
        # the caller; backing out stays on the provider screen.
        if isinstance(value, ProviderGroup):
            chosen = _provider_group_menu(value)
            if chosen is None:
                continue
            return chosen

        return value


def download_complete_prompt(message: str = N_("Download action finished"), *, summary: str = "",
                             retry: str = "") -> str:
    """Leave a completed action or revisit its choices without repeating it.

    *retry*, a row label such as "Retry the 2 that failed", adds a row after a
    partial failure; choosing it returns ``"retry"``.
    """
    if message == "Download action finished":
        message = t("Download action finished")
    items = [
        SelectItem(t("Continue to What's Next"), value="next", description=summary),
    ]
    if retry:
        items.append(SelectItem(retry, value="retry",
                                description=(summary + "\n" if summary else "")
                                + t("Runs only those again. To run the whole selection again, "
                                  "go back to download options and open all.")))
    items.append(
        SelectItem(t("Back to download options"), value="back",
                   description=(summary + "\n" if summary else "")
                   + t("Keep this selection. Returning does not repeat the download or handoff.")),
    )
    index = arrow_select(items, title=message, banner=_make_banner_panel(),
                         footer=t("↑/↓ select • Enter confirm • Esc back to download options"))
    return "back" if index is None else items[index].value


def search_again_prompt() -> str | tuple | None:
    """Prompt the user for what to do next after a download.

    Returns:
        - ``'search'`` to search again with the same provider.
        - ``'provider'`` to change provider.
        - ``("history", entry)`` when the user picks a history entry (raw entry dict).
        - ``'exit'`` when the Exit row is chosen.
        - ``None`` when Esc or Ctrl+C cancels the menu.
    """
    from torrent_finder.ui import downloads as downloads_ui
    choices = [
        (t("Search again"), "search", "R"),
        (t("Change provider"), "provider", "P"),
        (t("Main menu"), "main", "M"),
        (t("Quick actions"), "actions", "Tab"),
        (t("Search history"), "history", "H"),
        (t("Usage stats"), "stats", "S"),
        (t("Tips & shortcuts"), "tips", "T"),
        (t("Credentials"), "credentials", "C"),
    ]
    with_downloads = downloads_ui.current() is not None  # once a background download was started
    if with_downloads:
        choices.append((t("Downloads"), "downloads", "D"))
    choices.append((t("Exit"), "exit", "Q"))
    items = [SelectItem(label=label, value=value, hint=key) for label, value, key in choices]
    hotkeys = {}
    for _label, value, key in choices:
        if key == "Tab":
            hotkeys["\t"] = value
        else:
            hotkeys[key] = hotkeys[key.lower()] = value

    from torrent_finder.ui.tips import random_tip

    start = 0
    while True:
        # Fresh tip per menu entry, fixed across the render loop; it takes the
        # bottom rows when the screen leaves them empty.
        tip_line = random_tip()

        def footer():
            if with_downloads:
                full = t("↑/↓ navigate • Enter select • R/P/M/Tab/H/S/T/C/D/Q jump • Esc request exit")
                compact = t("↑/↓ move • Enter select • Esc exit\nR/P/M/Tab/H/S/T/C/D/Q jump")
            else:
                full = t("↑/↓ navigate • Enter select • R/P/M/Tab/H/S/T/C/Q jump • Esc request exit")
                compact = t("↑/↓ move • Enter select • Esc exit\nR/P/M/Tab/H/S/T/C/Q jump")
            return compact if console.size.height < 24 or _keybar_wraps(full, console.size.width, items) else full

        idx = arrow_select(
            items,
            title=t("What's Next?"),
            banner=_make_banner_panel(),
            start_index=start,
            hotkeys=hotkeys,
            footer=footer,
            tip=tip_line,
        )

        if idx is None:
            return None

        if isinstance(idx, tuple) and idx[0] == "hotkey":
            idx = next(i for i, item in enumerate(items) if item.value == idx[1])

        selected = items[idx].value

        if selected == "history":
            from torrent_finder.ui.history import history_select_prompt
            pick = history_select_prompt()
            if pick:
                return ("history", pick)  # entry dict — main routes keyword vs creator
            start = idx
            continue

        if selected == "stats":
            from torrent_finder.ui.stats import stats_page
            stats_page()
            start = idx
            continue

        if selected == "tips":
            from torrent_finder.ui.tips_page import tips_page
            tips_page()
            start = idx
            continue

        if selected == "credentials":
            credentials_menu()
            start = idx
            continue

        if selected == "downloads":
            downloads_ui.downloads_screen()
            start = idx
            continue

        if selected == "exit":
            return "exit"

        return selected
