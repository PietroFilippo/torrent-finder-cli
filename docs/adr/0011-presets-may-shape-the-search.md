# ADR-0011: Presets may shape the search, not only filter it

Status: accepted (2026-08-05)

## Context

Every preset until now was a pure post-filter: engines ran, rows merged, then
`apply_filters` narrowed them. That works for attributes the English-language
release scene already puts in the name a query returns — resolution, codec,
uploader tag.

It does not work for language. Measured against the live Movies & Series
engines:

- English-title queries return effectively no Portuguese rows. `Oppenheimer`
  0/47, `Deadpool` 0/79, `Interstellar` 0/60, `Toy Story 3` 0/83.
- The rows exist, but the indexers file them under Portuguese release names.
  `Toy Story dublado` returned 20 rows, all Portuguese, top row 42 seeders.
- APIBay caps a response at roughly 100 seeder-ordered rows, so the low-seed
  tail where dubs live is cut off before any filter sees it.
- The engines carrying Brazilian releases are the ones users leave Off.
  Knaben (Auto by default) indexes the Pirate Bay's Portuguese corpus; only
  SolidTorrents surfaces the Brazilian sites (LAPUMiA, BluDV, Comando,
  TorrentDosFilmes, BaixeDeTudo).

A language preset built as a post-filter would therefore be honest-looking and
almost always empty.

## Decision

`FilterPreset` gains two optional search-time fields alongside its `config`:

- `query_terms` — extra spellings the search fans out over. One
  `Toy Story` search becomes `Toy Story`, `Toy Story pt-br`,
  `Toy Story dublado`. Total queries per search are capped
  (`_MAX_QUERY_EXPANSIONS`), and worker count is bounded
  (`_MAX_SEARCH_WORKERS`), so stacking presets cannot amplify one search into
  a request storm.
- `require_engines` — engines forced On for the duration of one search, by
  `SearchEngine.name`. This does not write `engine.enabled` and does not
  persist; an engine the user set Off is Off again the moment the preset is
  untoggled. An Auto engine forced this way is excluded from the emergency
  pass so it is never asked the same query twice.

Presets without these fields behave exactly as before. `FilterConfig` also
gains `include_regex` (+ `fold_accents`), because language tags need patterns
substrings cannot express: `\bnacional\b` must not match `internacional`,
`\bleg\b` must not match `legend`, and one pattern should cover `português`
and `portugues`.

Audio/subtitle disambiguation also needs context. `name_predicate` is an
optional additional check on the release name only; it cannot match a source
name accidentally. `language_tags.py` owns these predicates: labels bind to
their following language before reversed spellings are considered, preventing
`Audio PT-BR Subs English` from being classified as Portuguese subtitles.
Dub tags may coexist with subtitles, while subtitle-only tags and uploader
names alone do not prove audio. The Brazilian preset requires explicit
regional audio evidence (`PT-BR`, `Português Brasileiro`, etc.), excluding
generic `dublado`, `nacional`, `Português`, and PT-PT-only audio. A Brazilian
tag attached only to subtitles cannot qualify the audio. This intentionally
trades coverage of incompletely tagged releases for PT-BR precision.

APIBay's longest-token fallback is disabled for queries ending in active
preset terms. Only full-query spelling retries run for those queries, keeping
the title instead of degrading `Nemo dublado` to `dublado`. Rows are filtered
before hash deduplication so an untagged variant cannot hide a matching one.

Movies & Series ships two presets on this seam: **Dublado (PT-BR)** and
**Legendado (PT subs)**.

## Consequences

- A preset can now cost network requests. The bound is explicit in
  `base.py` rather than implied, and the filter menu is the only thing that
  turns it on.
- The engine-mode contract from [ADR-0010](0010-knaben-and-explicit-engine-modes.md)
  is preserved in spirit: an engine still cannot make a request while
  appearing Off *unless* the user toggled a preset that names it. That
  coupling is documented in the preset's context help and in the README;
  the search screen shows the effective engines, including preset requirements.
- Language matching is a name heuristic, not metadata. A release with no
  language tag is invisible to it, and a mistagged release passes. There is
  no language field on these APIs to do better.
- "Dual audio" is deliberately excluded from the Portuguese pattern: on these
  indexers it is overwhelmingly Hindi/Tamil/Telugu.
- The search seam is language-agnostic. Additional languages can declare
  terms and required engines as preset data, with name predicates when their
  audio/subtitle tags need contextual matching.
- SolidTorrents reports `seeders: 0` for every row, so its Portuguese rows
  sort last under the default seeder-descending order. That is a pre-existing
  API limitation, not a claim that those torrents are dead.
