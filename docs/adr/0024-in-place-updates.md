# ADR-0024: Updates run in the app's own terminal, with download progress

Status: accepted (2026-10-05). Supersedes the update half of
[ADR-0012](0012-stable-credentials-and-safe-updates.md): the hidden helper, the
separate progress window and reopening in a new console.

## Context

An update from v0.8.x on a Windows laptop opened another Windows Terminal tab
that stayed blank for the whole update. The helper ADR-0012 introduced ran
without a console (`CREATE_NO_WINDOW | DETACHED_PROCESS`), so the console
program it started, pipx, got a console of its own: with Windows Terminal as
the default terminal, a new tab, empty because pipx's output went to
update.log. The progress viewer was another console, and reopening the app a
third. The display could not show a percentage either: it only knew the
helper's waiting/installing/finished states.

The helper existed because Windows will not let pip or pipx replace the
running launcher (`torrent-finder.exe`). Windows does let a running program's
file be renamed, and pip ≥ 24.1 reports download bytes
(`--progress-bar raw`: `Progress <done> of <total>` lines).

Trying it showed two traps. The launcher is also a zip that Python keeps on
`sys.path`; every `importlib.metadata` lookup leaves it open without sharing
rename access, until that cache is cleared and garbage collected. And pip,
when moving an installed file aside fails partway through an uninstall, does
not put back the files it already moved: the package is gone and the app no
longer starts.

## Decision

Updates run in the app's terminal, under the same update screen:

- **Installer commands run hidden.** Each runs with its output piped into
  update.log and parsed line by line, on Windows with `CREATE_NO_WINDOW` (a
  hidden console of its own: no window or tab, and Ctrl+C in the app cannot
  reach it), elsewhere in a new session. While a command runs, Ctrl+C only
  shows that an update cannot be stopped halfway. Each command is stopped
  after 15 minutes.
- **pip does the update, with progress.** pip and pipx installs run this
  Python's pip: `pip install --upgrade --progress-bar raw torrent-finder-cli`
  (`off` before pip 24.1). The screen moves through Preparing, Downloading,
  Installing and Finishing; while pip downloads, the bar fills with its
  percentage and the bytes; other steps pulse; Elapsed counts throughout.
  A pipx install then runs `pipx upgrade`, which finds the update installed
  and refreshes pipx's records and its copy of the command; if only that
  fails, the update stands with a note. pipx does the whole update when pip
  is missing from its venv or pipx tracks a file, URL or git source.
- **The launcher is moved aside first (Windows).** The update reads every
  piece of metadata it needs, clears Python's metadata cache, renames each
  in-use launcher of this app to `<name>.exe.<8 hex>.old`, and checks that no
  installed file is held open in a way that forbids moving it. If one is
  (normally another Torrent Finder window), nothing is installed and the
  screen says so. After the update, launchers the installer did not replace
  are put back; moved ones still running are recorded in the
  `moved_launchers` setting and deleted at a later startup.
- **Restart in place.** After a successful package or checkout update, a key
  press restarts the app the way it was started (its launcher, or
  `python -m torrent_finder`), keeping `--skip-warning` and `--theme` but not
  the first search. `main()` records the session and flushes the store first,
  so the old process writes nothing afterwards. POSIX replaces the process;
  Windows cannot, so the old process waits for the new one, leaving Ctrl+C to
  it, and exits with its code. Nothing new from pip or git means no restart.

Binaries still open the Releases page. Startup still reports a result that a
version before this one recorded in update-status.json.

## Consequences

- No update opens a window or tab, and the screen shows what is happening.
  The download percentage is pip's own; steps without a measurable length
  pulse instead of showing an estimate.
- Another open Torrent Finder window stops the update before anything
  changes, instead of failing halfway. Other windows running from a launcher
  that could be moved keep running the old code, as with git updates.
- The installed version draws the update screen: updating from v0.9.0 or
  earlier still uses the old helper once.
- While the restarted app runs, the old process waits in memory on Windows.
- `tests/test_update_install.py` covers output parsing, the command order,
  hidden installers (a real one has no console window), held files,
  launchers on disk and restarting; the update was also checked end to end
  with pipx 1.17 and pip 26, with the launchers both linked and copied.
