"""torrent-finder-cli — terminal torrent search across multiple sources.

See ``torrent_finder.main:main`` for the entry point (also exposed as the
``torrent-finder`` console script and ``python -m torrent_finder``).
"""

try:
    # Written by setuptools-scm at build time (installed / frozen copies).
    from torrent_finder._version import __version__
except Exception:
    # Running from a source checkout that was never built — fall back to the
    # installed dist metadata, then to a sentinel.
    try:
        from importlib.metadata import PackageNotFoundError, version

        __version__ = version("torrent-finder-cli")
    except Exception:
        __version__ = "0+unknown"
