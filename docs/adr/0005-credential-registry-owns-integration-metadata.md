# ADR-0005: Credential registry owns integration metadata

Status: accepted (2026-07-15)

## Context

Credential values were stored by `credentials.py`, but the interface for each
credentialed integration lived as dictionaries inside `ui/prompts.py`.
Required fields were repeated separately from field definitions, and live
verification used an eight-arm conditional that imported every client by ID.
Adding a login required coordinated edits across storage metadata, prompt
metadata, and verifier dispatch.

The credentials screens also occupied roughly 480 lines in the general prompt
module, making both the feature and `prompts.py` difficult to navigate and test.

## Decision

`credential_registry.py` is the seam for credentialed integrations. Each typed
`CredentialSpec` owns its fields, required/optional rules, display metadata,
status/save/clear behavior, and one lazy verifier adapter. The registry rejects
duplicate IDs and environment keys during import and derives the JSON file-key
map consumed by storage.

`credentials.py` remains the generic value store: environment variables win
over the gitignored JSON file, writes remain atomic, and callers that consume
credentials keep their existing convenience functions.

`ui/credentials.py` owns terminal rendering and user interaction. The existing
`prompts.credentials_menu()` name remains as a lazy compatibility wrapper.

## Consequences

- Adding a credentialed integration requires one registry entry and its lazy
  verifier adapter; storage and UI dispatch do not change.
- Required fields cannot drift from form fields because requirement is a field
  property rather than a second list.
- Verification, status, save, and clear semantics are headless-testable through
  the same `CredentialSpec` interface used by the UI.
- Network clients are imported only when their verifier runs, avoiding startup
  cost and circular imports.
- Credential values remain plaintext in the existing gitignored JSON file;
  this refactor does not introduce encrypted storage.
