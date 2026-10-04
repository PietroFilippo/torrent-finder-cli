"""Terminal-UX primitives for the streaming flow.

Pinned-header rendering, scroll-region pinning, terminal-title escape codes,
and screen-clear helpers used by ``stream_with_webtorrent`` and
``stream_with_peerflix`` in ``downloader.py``. Stream-flow shaped: the
header knows about episode index, VLC URL, and attached sub paths — not a
generic terminal toolkit.
"""

import os
import sys

from rich.console import Group
from rich.markup import escape
from rich.text import Text

from torrent_finder.constants import console
from torrent_finder.ui import theme
from torrent_finder.ui.layout import ellipsize_cells
from torrent_finder.torrent_meta import format_size


# Minimum header height keeps the normal-width stream header stable (header
# line, file, size, subtitles, VLC hint, keys, spacer). Narrow terminals may
# wrap it taller; the scroll region then starts below the actual rendered
# header instead of overlapping child-process output.
_STREAM_HEADER_LINES = 7


def _clear_terminal() -> None:
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def _set_terminal_title(title: str) -> None:
    """Set the terminal window title via OSC escape."""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def _truncate(text: str, max_len: int) -> str:
    """Truncate *text* to *max_len* terminal cells."""
    return ellipsize_cells(text, max_len)


def _print_stream_header(
    ep_idx: int,
    total: int,
    file_idx: int | None,
    multi: bool,
    vlc_url: str | None = None,
    use_scroll_region: bool = True,
    sub_paths: list[str] | None = None,
    backend: str = "",
    filename: str = "",
    filesize_bytes: int = 0,
) -> None:
    """Pin a summary at the top of the terminal for this stream session.

    The Quiet header shows the file name, size, backend, subtitle status, the
    VLC retry hint and the keys under the shared header line. The normal header
    keeps a stable minimum height; wrapped narrow headers reserve their actual
    rendered height before the child-process scroll region begins.

    When *use_scroll_region* is True (peerflix), a scroll region is set below
    the panel so child output flows in the lower zone. When False (webtorrent),
    only the terminal **window title** is pinned (webtorrent's full-screen
    ANSI clears through scroll regions, so we can't rely on them).
    """
    # Reset any previous scroll region so clear works on the full screen
    sys.stdout.write("\033[r")
    sys.stdout.flush()
    _clear_terminal()

    n = ep_idx + 1

    # Terminal title — persists in OS title bar regardless of screen content
    if multi:
        _set_terminal_title(f"Episode {n}/{total} — file {file_idx} | n: next  b: back  v: VLC  Ctrl+C: cancel")
    elif file_idx is not None:
        _set_terminal_title(f"Streaming file {file_idx} | v: VLC  Ctrl+C: cancel")

    # Content sits inside the two-cell margins.
    inner_width = theme.inner_width(console.size.width)

    # Escape user-supplied strings — torrent filenames often contain bracketed
    # tags like ``[x265]`` that Rich's markup parser would interpret as styles.
    file_display = escape(_truncate(filename or "(unknown file)", inner_width))

    size_str = format_size(filesize_bytes) if filesize_bytes else "size unknown"
    backend_str = f" · via {escape(backend)}" if backend else ""
    idx_str = f" · file index {file_idx}" if file_idx is not None else ""

    if sub_paths:
        primary = escape(
            _truncate(os.path.basename(sub_paths[0]), max(4, inner_width - 20))
        )
        extras = f"  (+{len(sub_paths) - 1} more)" if len(sub_paths) > 1 else ""
        sub_line = f"[success]Subtitles:[/success] [highlight]{primary}[/highlight]{extras}"
    else:
        sub_line = "[muted]No subtitles attached[/muted]"

    binds: list[str] = ["Ctrl+C cancel"]
    if vlc_url:
        binds.append("v reopen VLC")
    if multi:
        binds.append("n next")
        if ep_idx > 0:
            binds.append("b previous")

    # Persistent warning row — surfaces the VLC "cannot open MRL" race that
    # can hit multi-file webtorrent streams (the HTTP server may need a moment
    # to register the file route after the TCP port comes up). Always shown
    # so the user knows the recovery key without having to remember it.
    warning_line = (
        '[muted]If VLC errors with "cannot open MRL": press [/muted][key]v[/key] '
        '[muted]to retry (stream route may still be warming up)[/muted]'
    )

    width = console.size.width
    title_text = f"Streaming — Episode {n}/{total}" if multi else "Streaming"
    lines: list[Text] = list(theme.header_lines(title_text, "", width))
    for markup in (f"[highlight]{file_display}[/highlight]",
                   f"[muted]{size_str}{backend_str}{idx_str}[/muted]",
                   sub_line,
                   warning_line):
        lines.extend(theme.wrap_block(Text.from_markup(markup), width, console))
    lines.extend(theme.wrap_keys(theme.parse_footer("  •  ".join(binds)).keys, width))
    panel = Group(*lines)
    rendered_lines = len(
        console.render_lines(
            panel,
            console.options.update(width=max(1, console.size.width)),
            pad=False,
        )
    )
    console.print(panel)
    # Reset SGR + flush so any child subprocess starts writing into a clean
    # terminal state. Mitigates a class of "child output appears line-by-line
    # instead of redrawing in place" issues where the child inherits residual
    # ANSI state from Rich's render.
    sys.stdout.write("\033[0m")
    sys.stdout.flush()

    if use_scroll_region:
        header_lines = max(_STREAM_HEADER_LINES, rendered_lines)
        for _ in range(rendered_lines, header_lines):
            console.print()
        # Child output begins below the actual wrapped panel height.
        term_h = console.size.height
        top = header_lines + 1
        if top < term_h:
            sys.stdout.write(f"\033[{top};{term_h}r")
            sys.stdout.write(f"\033[{top};1H")
            sys.stdout.write("\033[J")  # erase from cursor to end of region
            sys.stdout.flush()
    else:
        console.print()  # blank separator line


def _reset_scroll_region() -> None:
    """Remove the scroll region so the full terminal is usable again."""
    sys.stdout.write("\033[r")
    sys.stdout.flush()


def _reset_terminal_title() -> None:
    """Restore the terminal title to the default."""
    _set_terminal_title("Torrent Search CLI")
