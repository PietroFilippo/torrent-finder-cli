"""Reading a key on Windows without losing "à".

readchar reads keys with ``msvcrt.getwch()``, which answers a special key (an
arrow, Home, F1…) with a prefix, 0xE0 or 0x00, and then the key's code. But
0xE0 is also "à" (U+00E0): readchar took a typed "à" for a prefix, waited for
the next key and returned neither ("Amor à Primeira Vista" lost two letters).
The key event in the console tells the two apart, so ``readkey`` reads it the
way getwch does (raw mode, key-down events only) and returns readchar's own
strings: a character as itself, a special key as ``"\\x00" + code``.

``install()`` puts it in readchar's place on Windows; every screen reads keys
through ``readchar.readkey()`` at call time, so all of them get it, and tests
that patch ``readchar.readkey`` are unaffected. Elsewhere it does nothing.
"""

from __future__ import annotations

import sys

import readchar

# getwch's codes for special keys (the byte after the prefix), by virtual-key
# code: (alone or with Shift, with Ctrl, with Alt). Function keys differ with
# Shift too: F1-F10 and F11/F12 have their own Shift row below.
_NAVIGATION = {
    0x26: ("\x48", "\x8d", "\x98"),  # Up
    0x28: ("\x50", "\x91", "\xa0"),  # Down
    0x25: ("\x4b", "\x73", "\x9b"),  # Left
    0x27: ("\x4d", "\x74", "\x9d"),  # Right
    0x24: ("\x47", "\x77", "\x97"),  # Home
    0x23: ("\x4f", "\x75", "\x9f"),  # End
    0x21: ("\x49", "\x86", "\x99"),  # Page Up
    0x22: ("\x51", "\x76", "\xa1"),  # Page Down
    0x2D: ("\x52", "\x92", "\xa2"),  # Insert
    0x2E: ("\x53", "\x93", "\xa3"),  # Delete
}
# F1-F10 (VK 0x70-0x79): alone 0x3B.., Shift 0x54.., Ctrl 0x5E.., Alt 0x68..
_FUNCTION = {0x70 + n: tuple(chr(base + n) for base in (0x3B, 0x54, 0x5E, 0x68)) for n in range(10)}
_FUNCTION[0x7A] = ("\x85", "\x87", "\x89", "\x8b")  # F11
_FUNCTION[0x7B] = ("\x86", "\x88", "\x8a", "\x8c")  # F12

_ALT = 0x0001 | 0x0002     # RIGHT_ALT_PRESSED | LEFT_ALT_PRESSED
_CTRL = 0x0004 | 0x0008    # RIGHT_CTRL_PRESSED | LEFT_CTRL_PRESSED
_SHIFT = 0x0010

_original = readchar.readkey
_console = None  # (kernel32, handle, record type) once opened; False when there is no console


def special_code(vk: int, state: int) -> "str | None":
    """getwch's code for a special key with these modifiers, or None (Shift, Ctrl, Caps Lock alone…)."""
    if vk in _NAVIGATION:
        alone, ctrl, alt = _NAVIGATION[vk]
        return alt if state & _ALT else ctrl if state & _CTRL else alone
    if vk in _FUNCTION:
        alone, shift, ctrl, alt = _FUNCTION[vk]
        return alt if state & _ALT else ctrl if state & _CTRL else shift if state & _SHIFT else alone
    return None


def _open_console():
    """The console's input handle, as getwch uses it (CONIN$, whatever stdin is)."""
    global _console
    if _console is None:
        _console = False
        try:
            import ctypes
            from ctypes import wintypes

            class KeyEvent(ctypes.Structure):
                _fields_ = [("down", wintypes.BOOL), ("repeat", wintypes.WORD), ("vk", wintypes.WORD),
                            ("scan", wintypes.WORD), ("char", wintypes.WCHAR), ("state", wintypes.DWORD)]

            class Event(ctypes.Union):
                _fields_ = [("key", KeyEvent), ("_size", ctypes.c_byte * 16)]

            class InputRecord(ctypes.Structure):
                _fields_ = [("type", wintypes.WORD), ("event", Event)]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.restype = wintypes.HANDLE
            handle = kernel32.CreateFileW("CONIN$", 0x80000000 | 0x40000000, 0x1 | 0x2, None, 3, 0, None)
            mode = wintypes.DWORD()
            if handle not in (None, wintypes.HANDLE(-1).value) and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                _console = (kernel32, handle, InputRecord)
        except (OSError, AttributeError, ValueError):
            pass
    return _console


def read_key_event() -> "tuple[str, str | None]":
    """The next key press as (character, None) or ("", special code), in raw mode as getwch reads it."""
    import ctypes
    from ctypes import wintypes
    kernel32, handle, InputRecord = _console
    mode = wintypes.DWORD()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    kernel32.SetConsoleMode(handle, 0)  # raw: Ctrl+C arrives as a key, like getwch
    try:
        record, count = InputRecord(), wintypes.DWORD()
        while True:
            if not kernel32.ReadConsoleInputW(handle, ctypes.byref(record), 1, ctypes.byref(count)):
                raise OSError(ctypes.get_last_error(), "ReadConsoleInputW failed")
            if record.type != 0x0001 or not record.event.key.down:
                continue  # mouse, focus, resize, key-up
            key = record.event.key
            if key.char != "\0":
                return key.char, None
            code = special_code(key.vk, key.state)
            if code is not None:
                return "", code
    finally:
        kernel32.SetConsoleMode(handle, mode.value)


def readkey() -> str:
    """readchar.readkey with a typed "à" kept: the key's event, not getwch's prefix, says what it is."""
    if not _open_console():
        return _original()
    char, code = read_key_event()
    if code is not None:
        return "\x00" + code
    if char in readchar.config.INTERRUPT_KEYS:
        raise KeyboardInterrupt
    if "\ud800" <= char <= "\udbff":  # the first half of a character beyond U+FFFF
        low, _code = read_key_event()
        char = (char + low).encode("utf-16", errors="surrogatepass").decode("utf-16")
    return char


def install() -> None:
    """Read keys this way on Windows (a no-op elsewhere and when already installed)."""
    if sys.platform == "win32" and readchar.readkey is _original:
        readchar.readkey = readkey
