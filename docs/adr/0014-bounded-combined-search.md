# Bounded combined search with partial results and progress

Status: Accepted; supersedes the scheduling and wait behavior in ADR-0013.

## Context

Selecting all eleven providers could appear to hang, although Anime + Manga
alone was quick. A deterministic reproduction blocked three early providers and
showed that later fast providers never started until a slot opened. The UI then
waited for every provider and offered no progress or access to completed results.
Simulated network failures also confirmed two 45-second APIBay attempts and
three 25-second Libgen mirror attempts under the original standalone timeouts.

The searching screen reused a selection-menu label and a filter shortcut hint,
producing "Searching Search across providers" and advertising unavailable input.

## Decision

Give every selected provider an independent coordinator and process its titles
sequentially. Keep the six-slot engine limit. Combined searches have a 30-second
wait budget, shared across their titles and providers. Each engine invocation
gets up to 12 seconds for requests/retries; connect/read timeouts are capped at
3/6 seconds and shrink with the remaining budget. Context-local request wrappers
cover search requests, mirror retries, supplemental pages, and required login or
session setup. Other operations retain their original timeout behavior.

Provider search publishes filtered/deduplicated rows after each engine finishes.
The combined coordinator copies these batches under a lock, reports progress,
and returns a stable snapshot when all providers finish, the budget expires, or
the user presses Enter. Stopping the wait does not clear useful rows from a
provider that still has another engine running. Notices identify incomplete
providers and request timeouts; late callbacks cannot modify returned results.
Esc keeps its existing meaning of cancelling back to the prompt.

Display "Searching N providers for...", completion/result counts, elapsed time,
and pending providers. Show only controls available during that wait. Explain
shared name rules with OR examples, exclusion precedence, empty-field behavior,
and the distinction between filtering names and changing the query or a single
provider's presets.

## Consequences

Fast providers are no longer queued behind whole-provider jobs. Users can see
that work is progressing and choose to open partial results; a slow site cannot
hold the combined results screen indefinitely. Time-limited searches may omit
slow-source results, and the notices direct users to retry that provider alone.

Cancellation is cooperative: Python cannot kill a running HTTP request. The UI
returns without waiting for it, request timeouts bound normal network waits, and
deadline checks stop subsequent retries and queued engine calls. Adapters that
silently return empty rows for non-timeout failures retain that behavior.
