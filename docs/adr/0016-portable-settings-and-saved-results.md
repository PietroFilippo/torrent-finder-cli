# Portable settings, saved results, and explicit name/source scopes

Status: Accepted (2026-10-02)

## Decision

Release-name rules have a small serializable contract separate from provider
presets: all words, any word, consecutive-word phrase, excluded words. They use
the shared Unicode normalization in `result_view.words` and apply before alias
deduplication. Provider presets retain source matching where it already carries
meaning (for example, FitGirl repacks). Profile and solo snapshots persist the
rules. New controls are transactional with their existing parent filter editor.

Nyaa Anime categories are an explicit source-specific setting. Other enabled
engines remain outside that scope, which the menu explains. Manga's existing
EN/Raw switches are retained, a non-English switch is added, and the Raw adapter
uses the source's actual `3_3` category. `3_2` means non-English-translated.
PT-BR audio and subtitle presets are independent conservative name checks.

Inline details use listing metadata before filename hints and require no new
network requests. Expansion retains the selected original index and prior
scroll offset. Its bounded detail viewport is scrollable in narrow terminals.

Bookmarks store copied result mappings, including lazy/direct acquisition
handles, or queries with copied search settings. They keep saved/fetched times
and stable entry IDs. A refresh reruns the saved search and updates only the
same canonical result identity. An unreturned listing keeps its original
metadata and records the unsuccessful lookup. Reopening and comparison use
the existing table and acquisition seam; saved data is not availability proof.

Settings transfer uses a versioned, allowlisted JSON document. Optional history
is explicit. Merge matches profile names while retaining local IDs and active
selection; replace resets portable provider/preferences. Stats, bookmarks and
machine-specific state stay on the current machine. Omitted history is retained.
Legacy combined settings import as Default. Import validates nested snapshots
and presents a detached candidate before a single atomic commit.

Credential transfer is a separate file type and UI action. It copies only saved
file values, never environment variables. Both normal and credential imports
preserve existing bytes on failed writes. Exports require a new filename.

`store.commit` replaces a complete fsynced JSON file before updating the cache.
The ordinary flush path shares this atomic writer. An unreadable authoritative
file is preserved rather than replaced with a legacy/default reconstruction.

## Validation

Deterministic tests cover import validation, merge/replace, cancellation, failed
replacement, credential separation, bookmark acquisition handles and refresh
identity, per-provider name matching, category routing, and compact rendering.
Real Windows ConPTY checks exercise persistence, result details, bookmarks,
search replay, comparison, import preview/application and malformed-file errors.
A targeted live Nyaa non-English Anime search validates the selected source
scope; it does not establish general provider or language coverage.
