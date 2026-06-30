"""Entry for ``python -m torrent_finder`` (torrent.bat / clone runs) and the
frozen PyInstaller binary. The ``__name__`` guard keeps PyInstaller's build-time
analysis from launching the app; ``python -m`` and the frozen exe both run it."""
from torrent_finder.main import main

if __name__ == "__main__":
    main()
