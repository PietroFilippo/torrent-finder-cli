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

import readchar

from torrent_finder.constants import console

_WINGET_CMD = "winget install -e --id Microsoft.WindowsTerminal"
_REG_CMD = (
    "reg add HKCU\\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f"
)


def advise_limited_terminal() -> None:
    """Warn (and pause) when the terminal can't render the UI; else no-op."""
    if not console.is_terminal:
        return  # piped/redirected output — nothing interactive to garble

    if console.legacy_windows:
        console.print(
            "[warning]This console is running in legacy mode - the interface "
            "will not render correctly (garbled characters, broken layout)."
            "[/warning]\n\n"
            "Best fix - install Windows Terminal, then run this program inside it:\n\n"
            f"    [highlight]{_WINGET_CMD}[/highlight]\n\n"
            '(no winget? install "Windows Terminal" from the Microsoft Store)\n\n'
            "Alternative - keep this console but enable ANSI support, then "
            "open a new console window:\n\n"
            f"    [highlight]{_REG_CMD}[/highlight]\n"
        )
    elif console.is_dumb_terminal:
        console.print(
            "[warning]This terminal reports no cursor control (TERM=dumb) - "
            "the interface will not render correctly. Run this program inside "
            "a regular terminal emulator.[/warning]\n"
        )
    else:
        return

    console.print("Press any key to continue anyway...")
    try:
        readchar.readkey()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0)
