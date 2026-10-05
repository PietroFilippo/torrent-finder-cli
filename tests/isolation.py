"""Keep tests away from the user's saved settings; not a test module itself.

Importing this module redirects saved settings, credentials, the Apibay cache
and the default download folder to a temporary directory for the whole run.
Test discovery imports every test module before any test runs, so one import
protects the full suite; each module that reaches persistence imports it too,
so running it alone is safe.

It also starts every test, under unittest or pytest alike, from one
appearance: the Simple design with the default painting, the Windows
Terminal profile out of reach, and no full-screen view left open after it.
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from torrent_finder import apibay_cache, constants, credentials, store

_RUN_DIRECTORY = tempfile.mkdtemp(prefix="torrent-finder-tests-")
atexit.register(shutil.rmtree, _RUN_DIRECTORY, ignore_errors=True)
store.STATE_PATH = os.path.join(_RUN_DIRECTORY, "filter_state.json")
store.LEGACY_STATE_PATHS = []
store._atexit_registered = True  # never save leftover test changes at exit
store.SAVE_DELAY = None  # no background saves racing a later test; tests flush explicitly
credentials._CRED_FILE = Path(_RUN_DIRECTORY) / "credentials.json"
credentials._LEGACY_CRED_PATHS = []
credentials._file_cache = None
apibay_cache.CACHE_PATH = os.path.join(_RUN_DIRECTORY, "apibay_cache.json")
constants.DOWNLOADS_DIR = os.path.join(_RUN_DIRECTORY, "downloads")

# Books searches look up the requested work's author on Open Library, and Manga
# searches that find nothing look up other titles on AniList; tests that cover
# them switch these back on with a stubbed lookup.
from torrent_finder.providers.anime_provider import AnimeProvider  # noqa: E402
from torrent_finder.providers.book_provider import BookProvider  # noqa: E402
from torrent_finder.providers.madokami_provider import MadokamiProvider  # noqa: E402
from torrent_finder.providers.manga_provider import MangaProvider  # noqa: E402
BookProvider.looks_up_authors = False
MangaProvider.looks_up_aliases = False
AnimeProvider.looks_up_aliases = False
MadokamiProvider.looks_up_aliases = False

# Rich takes a console that writes to a file on Windows for the legacy console
# and draws it one column narrower; terminals (Windows Terminal, and CI's
# Linux) use the full width, so tests do too, on every platform.
import rich.console  # noqa: E402

rich.console.detect_legacy_windows = lambda: False

# Athanor is the app's default design, but most layout tests describe the
# Simple design's frames, and tests that start the app apply its startup
# appearance: every test starts and ends on this baseline. Tests of Athanor
# or of the Windows Terminal profile opt in themselves.
from torrent_finder import paintings, terminal_profile  # noqa: E402
from torrent_finder.ui import appearance, display, theme  # noqa: E402

BASELINE = ("quiet", "bar", "comfortable")


def restore_baseline() -> None:
    palette, focus, density = theme.current()
    if (palette.key, focus, density) != BASELINE:
        theme.apply(BASELINE[0], focus=BASELINE[1], density=BASELINE[2])
    appearance._session["painting"] = paintings.DEFAULT
    appearance._session["fonts"] = appearance.DEFAULT_FONTS


def _screens_closed() -> None:
    left_open = display.depth()
    display._views.clear()
    if left_open:
        raise AssertionError(f"{left_open} full-screen view(s) left open")


_run = unittest.TestCase.run


def _run_from_baseline(self, result=None):
    restore_baseline()
    self.addCleanup(_screens_closed)  # runs after the test's own cleanups, reported like them
    # The real Windows Terminal folder and the Store Python's cmd calls stay out of reach.
    with patch.object(terminal_profile, "supported", lambda environ=None: False), \
         patch.object(terminal_profile, "_package_family", lambda: ""):
        try:
            return _run(self, result)
        finally:
            restore_baseline()


if not getattr(unittest.TestCase.run, "from_baseline", False):  # once, even if imported twice
    _run_from_baseline.from_baseline = True
    unittest.TestCase.run = _run_from_baseline
restore_baseline()


def isolate_store(case, data=None, path=None) -> Path:
    """Give one test a fresh store backed by its own settings file; undone on cleanup.

    *data*, when given, is written as the saved file before the first read.
    *path* places that file in a directory the test already owns.
    """
    if path is None:
        directory = tempfile.TemporaryDirectory()
        case.addCleanup(directory.cleanup)
        path = Path(directory.name) / "filter_state.json"
    if data is not None:
        path.write_text(json.dumps(data), encoding="utf-8")
    for name, value in (("STATE_PATH", str(path)), ("LEGACY_STATE_PATHS", []),
                        ("_cache", None), ("_pending", []), ("_signature", None),
                        ("_problem", None), ("_save_scheduled", False)):
        patcher = patch.object(store, name, value)
        patcher.start()
        case.addCleanup(patcher.stop)
    return path


def restart_store() -> None:
    """Forget the in-memory view, like a new app session reading the same file."""
    store._cache, store._signature, store._problem = None, None, None
    store._pending.clear()
