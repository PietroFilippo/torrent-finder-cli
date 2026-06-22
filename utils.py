"""Utility functions for formatting, styling, and magnet link building."""

import re
import threading
import time

from constants import TRACKERS


def start_esc_listener(cancel_event: "threading.Event") -> "threading.Event":
    """Watch for Esc on a daemon thread and set ``cancel_event`` when pressed.

    Lets a blocking, non-interactive wait (search fan-out, DHT metadata fetch,
    creator lookups) be aborted with Esc instead of Ctrl+C — which would kill
    the whole program. Returns a ``stop`` event the caller sets to tear the
    listener down once the wait completes.
    """
    import platform

    stop = threading.Event()

    def listen() -> None:
        if platform.system() == "Windows":
            import msvcrt
            while not stop.is_set():
                if msvcrt.kbhit():
                    if msvcrt.getch() == b"\x1b":  # Esc
                        cancel_event.set()
                        return
                time.sleep(0.1)
        else:
            import select
            import sys
            import termios
            import tty
            fd = sys.stdin.fileno()
            try:
                old = termios.tcgetattr(fd)
            except Exception:
                return  # not a real tty — no key cancel available
            try:
                tty.setcbreak(fd)
                while not stop.is_set():
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        if sys.stdin.read(1) == "\x1b":  # Esc
                            cancel_event.set()
                            return
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    threading.Thread(target=listen, daemon=True).start()
    return stop


def format_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    if size_bytes <= 0:
        return "N/A"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    size = float(size_bytes)
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {units[idx]}"


def parse_size_to_bytes(size_str: str) -> int:
    """Parse a human-readable size string like '5.0 MB' or '2.6 GB' to bytes."""
    match = re.match(r"([\d.]+)\s*(B|KB|MB|GB|TB)", size_str.strip(), re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(value * multipliers.get(unit, 1))


def seed_style(seeds: int) -> str:
    """Return a rich color tag based on seed count."""
    if seeds >= 50:
        return "bold green"
    elif seeds >= 10:
        return "green"
    elif seeds >= 1:
        return "yellow"
    return "red"


def leech_style(leeches: int) -> str:
    """Return a rich color tag based on leech count."""
    if leeches <= 5:
        return "dim white"
    elif leeches <= 50:
        return "yellow"
    return "red"


def marquee(text: str, width: int, tick: int, sep: str = "   •   ") -> str:
    """Return a `width`-char window into `text`, shifted left by `tick` chars.

    For text shorter than `width`, returns it unchanged. Otherwise wraps
    around with `sep` between repetitions so the scroll loops smoothly.
    """
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    period = len(text) + len(sep)
    offset = tick % period
    full = text + sep + text + sep
    return full[offset:offset + width]


def build_magnet(info_hash: str, name: str) -> str:
    """Build a magnet URI from an info hash."""
    trackers = "&".join(f"tr={t}" for t in TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={name}&{trackers}"
