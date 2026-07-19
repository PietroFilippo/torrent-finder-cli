# ADR-0009: APIBay last-known-good cache and emergency engines

Status: accepted (2026-07-18)

## Context

APIBay is not reliably truthful about search availability. Its endpoint can
return HTTP 200 with a one-row "No results returned" sentinel for a query that
worked moments earlier, while deterministic casing, encoding, or category
variants may disagree. Network and edge-node failures create the same
user-visible empty result.

Retry normalization improves the chance of a live hit but cannot guarantee
one. Unbounded or randomized retries amplify traffic and latency. A provider
may already have another public search engine, but some are default-off to
control noise and request volume. User-disabled engines must remain off.

## Decision

Successful APIBay rows are saved by normalized provider slug and query in a
versioned `apibay_cache.json`. The cache:

- lives in the machine-stable application-state directory but remains
  separate from settings and history;
- stores only successful rows with an info hash;
- is capped at 128 provider/query entries and evicts the oldest;
- writes through an atomic file replacement; and
- is disposable if unreadable or deleted.

Every search attempts APIBay live first. When its bounded live retry chain
produces no usable rows, the matching last-known-good rows are returned. Their
`source` remains `"Apibay"` so acquisition and torrent-info routing do not
change. Cache provenance lives in result metadata and is rendered as
`Apibay*`.

A `SearchEngine` can opt into `emergency_fallback` while remaining
default-off. After all enabled engines complete, the provider runs eligible
emergency engines only if there are zero merged raw rows. Filtering never
triggers emergency network traffic. An explicit user disable is persisted
separately and always wins. Legacy saved disabled states without that metadata
are treated conservatively as explicit.

## Consequences

- After one successful APIBay response for a provider/query, intermittent
  empty responses usually stop becoming empty screens.
- A first-time query can still fail, and all external engines can be down at
  once; this is higher availability, not a guarantee.
- Cached names, seeder counts, and page metadata may be stale. The info hash
  remains the stable acquisition identity.
- Emergency engines add traffic only on a total raw miss and do not silently
  override the user's engine choice.
- The cache can be deleted independently without affecting configuration,
  history, credentials, or statistics.
