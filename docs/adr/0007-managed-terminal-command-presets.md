# ADR-0007: Managed terminal-command presets

Status: accepted (2026-07-15)

## Context

The canonical `torrent-finder` command is created by pip/pipx from
`[project.scripts]`. Source checkouts and standalone binaries have different
launch targets, and an application setting alone cannot create a command that
a shell can resolve. Arbitrary alias text would also introduce command
injection, quoting, collision, and cleanup risks.

## Decision

The startup provider menu exposes a Terminal Command screen with a fixed set of
presets: `torrent-finder`, `tf`, `torrent`, `find-torrent`, and `tfind`.
`torrent-finder` remains canonical. `torrent` is also a package entry point for
pip/pipx installations.

Selecting another preset creates at most one forwarding launcher:

- Windows uses a `.cmd` file and POSIX uses an executable shell script.
- The target is install-aware: the frozen executable, the package console
  script, or `python -m torrent_finder` from the source root.
- Every CLI argument is forwarded unchanged.
- The launcher is placed beside the canonical command when available;
  otherwise a user bin directory already on `PATH` is preferred.
- Adding a missing launcher directory to the Windows user `PATH` requires an
  explicit confirmation. POSIX shell profiles are never edited automatically.

Generated files contain an ownership marker. The app refuses unrelated command
or file collisions and removes a prior launcher only when that marker is
present. The selected preset and generated path are stored under the
`terminal_command` setting.

## Consequences

- Users get short commands without editing shell profiles by hand in the
  common pip/pipx case.
- The original `torrent-finder` command remains usable after selecting an
  alias; the setting expresses the preferred quick command, not an exclusive
  rename.
- The fixed preset list keeps shell input out of generated scripts.
- A POSIX user whose `~/.local/bin` is not on `PATH` receives the exact
  directory to add; supporting automatic edits for every shell is deliberately
  out of scope.
