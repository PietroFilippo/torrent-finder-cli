"""Utility functions for formatting, styling, and magnet link building."""

import re
import threading
import time
from urllib.parse import quote

from torrent_finder.constants import TRACKERS
from torrent_finder.ui import theme


def start_esc_listener(cancel_event: "threading.Event", *, finish_event=None) -> "threading.Event":
    """Watch for Esc on a daemon thread and set ``cancel_event`` when pressed.

    Lets a blocking, non-interactive wait (search fan-out, DHT metadata fetch,
    creator lookups) be aborted with Esc instead of Ctrl+C — which would kill
    the whole program. Returns a ``stop`` event the caller sets to tear the
    listener down once the wait completes.
    With ``finish_event``, Enter ends the wait and keeps partial search results.
    """
    import platform

    stop = threading.Event()

    def listen() -> None:
        if platform.system() == "Windows":
            import msvcrt
            while not stop.is_set():
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key in (b"\x00", b"\xe0"):
                        msvcrt.getch()  # consume the second byte of a special key
                    elif key == b"\x1b":  # Esc
                        cancel_event.set()
                        return
                    elif finish_event is not None and key in (b"\r", b"\n"):
                        finish_event.set()
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
                        key = sys.stdin.read(1)
                        if key == "\x1b":  # Esc
                            cancel_event.set()
                            return
                        if finish_event is not None and key in ("\r", "\n"):
                            finish_event.set()
                            return
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    threading.Thread(target=listen, daemon=True).start()
    return stop


def parse_timestamp(iso_ts: object):
    """The moment an ISO-8601 timestamp names, or None when it is missing, malformed or has no timezone.

    Saved times are always recorded in UTC. A timezone-less value (hand-edited
    or from elsewhere) has no reliable moment, so callers treat it as unknown.
    """
    from datetime import datetime
    try:
        moment = datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return None
    return moment if moment.utcoffset() is not None else None


def relative_time(iso_ts: object, now=None) -> str:
    """``just now``, ``5m ago``, ``2h ago``, ``3d ago``, ``4mo ago``; empty when the time is unknown."""
    from datetime import datetime, timezone
    moment = parse_timestamp(iso_ts)
    if moment is None:
        return ""
    seconds = int(((now or datetime.now(timezone.utc)) - moment).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return f"{days // 30}mo ago"


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
    """Seed-health colour from the active theme: good from 10 seeds, warn below, bad at none."""
    return theme.seed_style(seeds)


def leech_style(leeches: int) -> str:
    """Leech colour from the active theme: muted when few, then warn, bad."""
    return theme.leech_style(leeches)


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
    """Build a magnet URI from an info hash.

    The name is percent-encoded: a raw "&", "#" or "+" in a torrent name would
    otherwise end or alter the display-name parameter for every client.
    """
    trackers = "&".join(f"tr={t}" for t in TRACKERS)
    # The hash is encoded too: a malformed one from an index must not end the
    # parameter or reach a client's command line with quotes.
    return f"magnet:?xt=urn:btih:{quote(info_hash, safe='')}&dn={quote(name, safe='')}&{trackers}"
