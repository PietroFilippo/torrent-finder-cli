# ADR-0029: Session background downloads through aria2 JSON-RPC

Status: accepted (2026-10-13). Phase A: engine and tests; screens follow.

## Context

Foreground aria2 downloads occupy the download screen until they finish.
Users approved browsing while downloads run. Workers need structured
progress, exact selected paths, individual cancellation and safe shutdown,
without drawing into the terminal or sharing its Ctrl+C delivery.

## Decision

- One lazy `Aria2Engine` per `JobManager`, with two concurrent downloads.
  Authenticated RPC binds to loopback on a fresh port. Its requests session
  ignores environment proxies, uses a three-second timeout and refuses
  redirects. One poller sends a `system.multicall` once a second and follows
  the metadata GID to the payload GID before recognizing completion.
- On Windows, start aria2 and unpack tools with `CREATE_NO_WINDOW`, following
  ADR-0024; aria2 starts in a new session elsewhere. All aria2 streams go to
  DEVNULL. Disable user aria2 configuration and put its log and DHT files in
  machine state, so a user's aria2 setup cannot change this engine.
- Jobs live in memory behind an RLock. Snapshots copy jobs; revision changes
  immediately for states and at most once a second for progress. Hooks only
  signal redraws, outside the job lock; workers never print or draw spinners.
  Duplicate active info hash, folder and selection combinations are refused.
- A separate finisher uses selected paths from RPC, removes the aria2 result,
  then optionally unpacks. Archive access retries brief permission locks;
  notes hold unpack status and results. A standalone success counts once in
  method statistics; a batch counts once after every member succeeds. Use a
  fresh group ID and `with jobs.batch():` around enrollment to prevent a fast
  first download finishing before the last member is added. Removing finished
  rows does not erase a group's failed or stopped outcome.
- Stop calls `aria2.remove`, keeping partial files resumable. Shutdown stops
  jobs and joins workers; aria2 escalates from shutdown to forceShutdown to a
  process-tree kill and reaping. An unpack already executing is allowed to
  return; cancellation prevents more archives or completion statistics.
  `--stop-with-process` covers parent crashes. `downloads.busy()` supplies the
  future update/quit guard, including queued, paused and unpacking jobs and a
  stopped finisher that has not returned yet.
- State identities remain English; labels and diagnostics use `t()` and the
  Brazilian Portuguese catalogue. Notifications reach the later UI through
  `on_change`, rather than calling chrome from the engine.

## Rejected

- Parsing foreground output: progress and file selection already have a
  structured RPC interface, and stdout belongs to the terminal UI.
- `DETACHED_PROCESS`: it can open a blank Windows Terminal tab (ADR-0024).
- Keeping jobs after app exit, persistence, direct downloads and other torrent
  backends: later phases; the current process owns all background work.

## Consequences

The UI can read immutable summary values and independent job copies while
RPC or unpack work runs. The next phase must subscribe to changes, enroll
batches together, call shutdown in its finally block, and refuse in-app
updates while busy: a POSIX exec restart keeps the watched parent PID.
Fake-RPC tests cover the lifecycle; a real aria2 test downloads from a local
HTTP server into temporary storage and asserts that no child remains.
