"""Startup advisory for terminals that can't render the interface.

The UI drives the terminal with raw ANSI/VT sequences (alternate screen
buffer, cursor control) on top of Rich. Windows' legacy conhost ignores
those sequences when Virtual Terminal processing is unavailable, so the
screens come out garbled. Rich probes the console at startup and tries to
enable VT processing itself; ``console.legacy_windows`` is True exactly
when that failed — the case the user can fix by switching terminal or
flipping the VirtualTerminalLevel registry default.

The advisory is deliberately plain ASCII: it targets the one environment
where emoji and box-drawing output are already broken.
"""

# i18n: converted
import unicodedata

import readchar

from torrent_finder.constants import console
from torrent_finder.i18n import t

_WINGET_CMD = "winget install -e --id Microsoft.WindowsTerminal"  # i18n: ignore (command)
_REG_CMD = (
    "reg add HKCU\\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f"  # i18n: ignore (command)
)


def _ascii(message: str) -> str:
    """Keep this last-resort advisory readable even without Unicode support.

    main.py resolves the interface language before calling this module.
    Brazilian Portuguese keeps its words with accent marks folded to ASCII.
    """
    return unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode("ascii")


def advise_limited_terminal() -> None:
    """Warn (and pause) when the terminal can't render the UI; else no-op."""
    if not console.is_terminal:
        return  # piped/redirected output — nothing interactive to garble

    if console.legacy_windows:
        console.print(_ascii(t(
            "[warning]This console is running in legacy mode - the interface "
            "will not render correctly (garbled characters, broken layout)."
            "[/warning]\n\n"
            "Best fix - install Windows Terminal, then run this program inside it:\n\n"
            "    [highlight]{winget}[/highlight]\n\n"
            '(no winget? install "Windows Terminal" from the Microsoft Store)\n\n'
            "Alternative - keep this console but enable ANSI support, then "
            "open a new console window:\n\n"
            "    [highlight]{registry}[/highlight]\n",
            winget=_WINGET_CMD, registry=_REG_CMD,
        )))
    elif console.is_dumb_terminal:
        console.print(_ascii(t(
            "[warning]This terminal reports no cursor control (TERM=dumb) - "
            "the interface will not render correctly. Run this program inside "
            "a regular terminal emulator.[/warning]\n"
        )))
    else:
        return

    console.print(_ascii(t("Press any key to continue anyway...")))
    try:
        readchar.readkey()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0)
