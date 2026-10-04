"""File writing shared by the direct-download sources (Madokami, Libgen,
F-Droid, Online-Fix and Jimaku).

A transfer streams into a temporary ``.part`` sibling and appears under its
final name only once complete. Cancelling (Esc), a network or disk error, or
Ctrl+C removes just that temporary file, so an interrupted download never looks
finished and never touches an existing file. When the name is already taken
the new file is saved as ``Name (1).ext``: two different books can share a
filename, and replacing one would silently lose it.

Names come from servers, so ``safe_filename`` reduces each to one ordinary
file name inside the download folder before anything is written.
"""

import os
import re
import tempfile
import time


class Cancelled(Exception):
    """The caller's cancel_event fired mid-transfer."""


# Windows: antivirus briefly holds a file that was just closed.
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
# Characters Windows refuses in names (":" would also open a hidden stream),
# plus control characters.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", re.I)
# Room for " (999)" and the temporary ".part" suffix within 255 characters.
_MAX_NAME = 180


def safe_filename(name: str, fallback: str = "download") -> str:
    """One ordinary file name from a server-provided name: only its last path
    part (either slash), Windows-invalid characters replaced, no trailing dots
    or spaces, no reserved device names, at most ``_MAX_NAME`` characters with
    the extension kept. *fallback* when nothing usable remains."""
    name = re.split(r"[/\\]", str(name or ""))[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip().rstrip(". ")
    if not name or set(name) <= {"."}:
        name = fallback
    if _RESERVED.fullmatch(name):
        name = "_" + name
    if len(name) > _MAX_NAME:
        root, extension = os.path.splitext(name)
        extension = extension if len(extension) <= 16 else ""
        name = root[:_MAX_NAME - len(extension)].rstrip(". ") + extension
    return name


def save_response(resp, dest_dir: str, filename: str, cancel_event=None, progress_cb=None) -> str:
    """Stream a ``requests`` response body into a new file in *dest_dir*; return its path.

    ``cancel_event`` is checked between chunks and ``progress_cb(bytes_done,
    total_or_None)`` runs per chunk, the total coming from Content-Length when
    the server sends one. *filename* is made safe first (``safe_filename``).
    Raises ``Cancelled`` or the underlying error.
    """
    filename = safe_filename(filename)
    dest = os.path.join(dest_dir, filename)
    if os.path.dirname(os.path.abspath(dest)) != os.path.abspath(dest_dir):
        raise OSError(f"Refusing to save outside the download folder: {filename}")
    try:
        total = int(resp.headers.get("Content-Length", "")) or None
    except ValueError:
        total = None
    fd, temporary = tempfile.mkstemp(prefix=filename + ".", suffix=".part", dir=dest_dir)
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
        # A cancel that arrives after the last chunk still wins: the partial
        # file is removed below instead of being published under its name.
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled()
        return _promote(temporary, dest, cancel_event)
    except BaseException:
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def _promote(temporary: str, dest: str, cancel_event=None) -> str:
    """Give a finished transfer the first free name among *dest*, ``dest (1)``, …"""
    root, extension = os.path.splitext(dest)
    for number in range(1000):
        candidate = f"{root} ({number}){extension}" if number else dest
        try:
            _rename_new(temporary, candidate, cancel_event)
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(f"No free filename for {dest}")


def _rename_new(source: str, target: str, cancel_event=None) -> None:
    """Rename *source* to *target*, raising ``FileExistsError`` instead of replacing it.

    A cancel that arrives while a locked file is being retried stops the
    rename; the caller then removes the temporary file.
    """
    for delay in (*_RETRY_DELAYS, None):
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled()
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
