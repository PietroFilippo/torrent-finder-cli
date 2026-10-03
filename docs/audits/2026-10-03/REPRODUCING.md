# Audit methods and reproduction

## Files

| File | Contents |
|---|---|
| `cases.json` | All 352 query cases, intended titles, aliases, exclusions, strata and variant tokens. Years for Software/Mobile identify intended era, not first publication. |
| `inventory.json` | Eleven providers, 33 engine combinations, factory modes/categories, paging and credential-configured booleans. |
| `measurements.jsonl.gz` | All 1,135 initial/follow-up engine records, with sanitized raw and final rows, identities, source page URLs, status, diagnostics and HTTP shape/timing observations. |
| `measurements.csv` | Flat per-record counts, rank, time and status for spreadsheets. |
| `summary.json`, `engine-results.csv` | Provider/engine aggregates and scenario groups. Candidate counts exclude synthetic negatives; engine status/row/latency totals include them. |
| `replays.json.gz` | Default/all-On real-coordinator replays for every query; uncertainty, source contribution, deduplication, 44 filter controls and six alias pairs. |
| `manual-relevance.json` | 88 manually judged listing rows. A targeted sample, not a precision estimate. |
| `cooldown-evidence.json` | Online-Fix HTTP-200 cooldown text, original-page hashes and offline parser outcomes. |
| `source-comparisons.json.gz` | Source-side Online-Fix query/page/listing evidence. |
| `combined-live.json.gz` | Four live searches using multiple providers; per-task diagnostics and matched-provider provenance. |
| `candidate-probes.json.gz` | F-Droid responses, matching Gutenberg catalog metadata, Internet Archive results and request status/timing. |
| `knaben-v2-probes.json.gz` | Fourteen current API comparisons, including origin trackers and zero-seed behavior. |
| `validation.json` | Test results, environment, archive integrity and real private-file preservation checks. |
| `SHA256SUMS` | SHA-256 of the report/evidence files, excluding the checksum file itself. |

Gzip files contain UTF-8 JSON (or JSON Lines as named), not Python pickle.
They can be inspected without executing code. Saved rows retain discovery IDs;
they do not include account names, passwords, request headers/cookies, credential
form bodies or full authenticated HTML. `identity` can be a torrent hash, source
listing ID or namespaced direct-download/directory handle. It does not always
identify a downloadable torrent. Page URL query strings retain only public
`id`, `t` and `md5` fields; userinfo, fragments and other parameters are removed.

## Offline reproduction

Use Python 3.10+ and the project's installed dependencies. From the repository
root, regenerate aggregates/replays from the committed evidence, with **no live
source access**:

```powershell
python -m scripts.provider_audit_report --source docs/audits/2026-10-03 --dest dist/audit-rebuilt
python -m unittest discover -s tests -p test_provider_audit.py -v
```

The rebuilt `summary.json`, `engine-results.csv`, `measurements.csv`,
`measurements.jsonl.gz` and `replays.json.gz` should match the committed files.
The exporter does not recreate human judgments or prose from scratch. It uses
the installed project's search/filter code; for future changed behavior, compare
against the baseline commit before treating a different replay as data drift.

The full deterministic suite was run separately:

```powershell
python -m unittest discover -s tests -v
```

The live scripts are never called by normal tests or CI. The audit unit tests
only test manifest completeness, lexical grading boundaries, privacy-preserving
URL/row serialization and preservation of unknown measurements.

## New opt-in live run

The saved case manifest is authoritative. Regenerate it only when deliberately
changing the corpus:

```powershell
python -m scripts.provider_audit_corpus
python -m scripts.provider_audit --run --out dist/audit-new --minutes 40
```

Without `--run`, the live CLI refuses to make requests. The same command resumes
completed record IDs from that output directory after cancellation/time budget.
Do not run multiple writers against one output file. On Windows, use
`$env:PYTHONIOENCODING='utf-8'` for readable non-ASCII console output. Capture
`$LASTEXITCODE` explicitly when redirecting PowerShell output; dependency warnings
on stderr can otherwise make the shell wrapper look unsuccessful even when
Python produced complete data.

Use a small pilot or a bounded selected repeat:

```powershell
python -m scripts.provider_audit --run --out dist/audit-pilot --limit 2 --minutes 3
python -m scripts.provider_audit --run --out dist/audit-repeat --providers anime --engines Nyaa --limit 2 --repeat 1 --minutes 3
```

`--repeat` changes record IDs and deliberately rechecks source health, bypassing
the initial-pass circuit breaker. **Use it only with a bounded selection** and
after any advertised cooldown. Stop on persistent blocking; skipped cells are
unknown, not misses. `--limit` is per backend family, not per provider.

The runner uses fresh provider factory defaults and redirects settings/cache
paths before importing the registry. It can use existing configured credentials
for source search; only boolean configuration status belongs in the report.
It does not invoke acquisition, client handoff, streaming or downloads.

### Bounds and pacing

- Three backend-family queues run concurrently, with one search at a time inside
  each queue. Shared queries/scopes can reuse results within a pass.
- HTTP request starts are separated by at least one second per hostname within
  the process. Online-Fix now uses eleven seconds, reflecting the discovered
  source restriction. Its initial pass used one second; those observations stay
  archived with an explicit contamination note.
- SearchSession applies its existing engine/action limits (normally 12 seconds
  per engine; 20-second single-engine audit action). The 40-minute runner budget
  stops scheduling new cells. Ctrl+C sets cancellation before waiting for workers.
- A 429 or explicit missing/rejected login opens the source circuit immediately;
  three consecutive unavailable attempts open it for other access/network
  failures. The pilot and initial resumed process had separate circuit state,
  producing five total RuTracker challenges before all remaining cells were
  left unknown. No attempt was made to bypass anti-bot access controls.
- Supplemental scripts are short fixed lists, not an exhaustive crawler. Their
  host pacing is local to their process; do not launch overlapping scripts to
  evade a site's rate limits.

Supplemental probes, if deliberately repeating this dated experiment:

```powershell
python -m scripts.provider_audit_probes extensions --run
python -m scripts.provider_audit_probes candidates --run
python -m scripts.provider_audit_probes knaben-v2 --run
python -m scripts.provider_audit_probes combined --run
python -m scripts.provider_audit_probes source-comparisons --run
```

These dated helper commands write to `dist/provider-audit-2026-10-03`. Run them
sequentially. They include no automatic large-scale rerun or scheduled task.
The final `Starve` query control was a separately recorded repeat-4 measurement;
it can be reproduced with `provider_audit.measure` and the `online-fix-10`
intended-work case, replacing only its query with `Starve`.

## Measurement definitions and limitations

- `raw_count` is the adapter output **after the app's result normalization**,
  before provider/local filters. It is not the remote site's total result count
  or the number of entries before an adapter's own parsing/identity checks.
- `kept_count` is the coordinator's final eligible, sorted/deduplicated output.
  `duplicate_count` describes repeated `(identity, source)` pairs in raw rows.
  Cross-engine union and unique contributions are in the replay data.
- `candidate_count`, `variant_candidate_count` and `first_candidate_rank` are
  lexical proxies. Apostrophes/accents/case normalize, aliases are explicit,
  variants require literal tokens, and exclusions remove known false matches.
  They do not replace the manual listing relevance sample. Real relevance is
  unadjudicated for the other rows.
- `seconds` includes audit pacing, parsing, existing adapter fallback and local
  processing. `first_result_seconds` is **first complete adapter batch**, not
  first byte or a streamed first row; these adapters return lists. Reused and
  skipped cells have no new latency. Engine p95 uses nearest rank. HTTP events
  separately record send duration after pacing. These are one-environment
  measurements, not a controlled throughput or normal UI latency benchmark.
- Healthy `empty` means the bounded query returned no rows. A catalog-absence
  conclusion requires stronger source evidence and was not made here. APIBay
  HTTP 200 empties, source truncation, transliteration and title-only searches
  remain potential causes. Some source requests timed out; later controls show
  transient recovery but do not retroactively change the initial observation.
- Online-Fix's paced repeated results replace that engine only for the aggregate
  replays, with the exact repeat record retained as `evidence_id`. Other repeated
  controls remain separate from the initial matrix. All original observations
  remain in the archive. The corrected Online-Fix source is shared by its
  dedicated provider and General Games, not counted as two catalogs.
- Offline replays are deterministic counterfactuals using observed rows. They
  cannot reproduce source timing/concurrency or unseen catalog changes. An
  unavailable primary is treated as contributing no observed rows; an Auto hit
  in that situation is conditional, and `unknown_sources` retains that caveat.
- Local prefer/require probes have no query expansion. Existing deterministic
  tests cover preset expansion, forced engines and bounds; the audit does not
  claim every built-in preset was exercised live.
- Candidate API results are raw catalog matches. Package, author, medium,
  access-right and edition checks are needed before counting them as target
  originals. The report's verified subsets are deliberately smaller.

## Deterministic failure coverage

The full suite includes the following relevant controlled behaviors, separate
from live reach measurements:

| Scenario | Existing test modules |
|---|---|
| Missing/rejected credentials, session changes | `test_credentials_recovery`, `test_credential_registry`, `test_title_search` |
| Deadline, cancellation, late worker isolation | `test_search_sessions`, `test_combined_latency`, `test_cancel_navigation` |
| Partial results and source failure | `test_search_sessions`, `test_combined_search`, `test_combined_ui` |
| Empty results, fallback and On/Auto/Off rules | `test_search_sessions`, `test_result_contract_characterization`, `test_engine_fallback_state` |
| Stale last-known-good cache and provenance | `test_apibay_cache`, `test_apibay_resilience` |
| Pagination, repeat-page exhaustion and retry | `test_search_sessions` |
| Required/preferred/language filters and aliases | `test_preset_preferences`, `test_language_filters`, `test_title_search` |

Passing fixtures establish these controlled behaviors, not remote site health.
