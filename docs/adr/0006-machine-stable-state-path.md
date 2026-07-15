# ADR-0006: Machine-stable state path

Status: accepted (2026-07-15)

## Context

`filter_state.json` was stored under the platform user-data directory. On
Windows, Microsoft Store Python can virtualize `%LOCALAPPDATA%` into an
interpreter-package-specific `LocalCache`. The same apparent path could then
refer to different files when the app was launched through another Python
installation or as a packaged executable. This appeared to users as history,
stats, and settings resetting after an environment or network change.

Network properties such as public IP, interface, SSID, and MAC address are not
valid persistence identity. State belongs to the OS user on the current
machine and must remain stable when connectivity changes.

## Decision

On Windows, `filter_state.json` lives at
`%USERPROFILE%\.torrent-finder-cli\filter_state.json`, outside Store Python's
LocalAppData virtualization. Other platforms retain their existing per-user
platform data location. `store.py` remains the single owner of the file.

When the machine-stable file does not exist, the store discovers prior copies
from the old platform data directory, Store Python LocalCache directories, the
repository root, and the package directory. It consolidates them once:

- The newest file supplies settings, provider toggles, and other ordinary
  state.
- History is combined, deduplicated by search identity, sorted newest first,
  and capped at 50 entries.
- Cumulative stats use the maximum value for each counter and the earliest
  `first_use`. This avoids double-counting copies that share a common past.

The merged file is written immediately. Legacy copies remain untouched.

## Consequences

- Network changes and launch-method changes no longer select a different
  history/stats file.
- Existing stranded history is recovered without making migration UI-aware.
- Diverged stats are merged conservatively. A counter can be slightly low when
  separate copies contain disjoint activity, but it will not be inflated by
  adding overlapping cumulative totals.
- Credentials and the default downloads directory keep their existing
  platform-specific locations; this decision covers the shared application
  state owned by `store.py`.
