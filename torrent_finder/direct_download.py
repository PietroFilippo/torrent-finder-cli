"""File writing shared by the direct-download sources (Madokami, Libgen).

A transfer streams into a temporary ``.part`` sibling and appears under its
final name only once complete. Cancelling (Esc), a network or disk error, or
Ctrl+C removes just that temporary file, so an interrupted download never looks
finished and never touches an existing file. When the name is already taken
the new file is saved as ``Name (1).ext``: two different books can share a
filename, and replacing one would silently lose it.
"""

import os
import tempfile
import time


class Cancelled(Exception):
    """The caller's cancel_event fired mid-transfer."""


# Windows: antivirus briefly holds a file that was just closed.
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


def save_response(resp, dest_dir: str, filename: str, cancel_event=None, progress_cb=None) -> str:
    """Stream a ``requests`` response body into a new file in *dest_dir*; return its path.

    ``cancel_event`` is checked between chunks and ``progress_cb(bytes_done,
    total_or_None)`` runs per chunk, the total coming from Content-Length when
    the server sends one. Raises ``Cancelled`` or the underlying error.
    """
    try:
        total = int(resp.headers.get("Content-Length", "")) or None
    except ValueError:
        total = None
    # Keep room for the random suffix within the 255-character name limit.
    fd, temporary = tempfile.mkstemp(prefix=filename[:200] + ".", suffix=".part", dir=dest_dir)
    try:
        with os.fdopen(fd, "wb") as fh:
            done = 0
            if progress_cb:
                progress_cb(0, total)
            for chunk in resp.iter_content(chunk_size=65536):
                if cancel_event is not None and cancel_event.is_set():
                    raise Cancelled()
                if chunk:
                    fh.write(chunk)
                    done += len(chunk)
                    if progress_cb:
                        progress_cb(done, total)
        return _promote(temporary, os.path.join(dest_dir, filename))
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def _promote(temporary: str, dest: str) -> str:
    """Give a finished transfer the first free name among *dest*, ``dest (1)``, …"""
    root, extension = os.path.splitext(dest)
    for number in range(1000):
        candidate = f"{root} ({number}){extension}" if number else dest
        try:
            _rename_new(temporary, candidate)
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(f"No free filename for {dest}")


def _rename_new(source: str, target: str) -> None:
    """Rename *source* to *target*, raising ``FileExistsError`` instead of replacing it."""
    for delay in (*_RETRY_DELAYS, None):
        try:
            if os.name == "nt":
                os.rename(source, target)  # never replaces on Windows
            else:
                _link_rename(source, target)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def _link_rename(source: str, target: str) -> None:
    try:
        os.link(source, target)  # fails when target exists, unlike os.rename
    except FileExistsError:
        raise
    except OSError:
        # A filesystem without hard links (FAT, some network shares).
        if os.path.lexists(target):
            raise FileExistsError(target) from None
        os.rename(source, target)
        return
    os.remove(source)
