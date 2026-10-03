"""Opt-in, resumable live search audit. Never invoked by normal tests or CI.

Run from the repository root: python -m scripts.provider_audit --run
Only searches listing metadata. Does not resolve payloads or start downloads.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.parse import urlsplit, urlunsplit


DEFAULT_OUT = Path("dist/provider-audit-2026-10-03")
TRACE = ContextVar("audit_http", default=None)
WRITE_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
LAST_REQUEST = {}
HOST_INTERVAL = {"online-fix.me": 11.0}
STOP = threading.Event()


def now():
    return datetime.now(timezone.utc).isoformat()


def normalized(text):
    text = "".join(c for c in unicodedata.normalize("NFKD", str(text)).casefold()
                   if not unicodedata.combining(c))
    text = text.replace("'", "").replace("’", "")
    return " ".join(re.findall(r"\w+", text, re.UNICODE))


def candidate(row, case):
    """Conservative lexical proxy; never presented as adjudicated relevance."""
    name = " " + normalized(row.get("name", "")) + " "
    aliases = case.get("aliases", [])
    title = any(" " + normalized(alias) + " " in name for alias in aliases)
    excluded = any(" " + normalized(value) + " " in name for value in case.get("exclude_phrases", []))
    title = title and not excluded
    variant = title and all(token in name.split() for token in normalized(case.get("variant_tokens", "")).split())
    return title, variant


def safe_url(url):
    parts = urlsplit(str(url or ""))
    if parts.scheme not in {"http", "https"}:
        return ""
    # Retain public listing IDs; discard any authentication/token parameters.
    allowed = []
    from urllib.parse import parse_qsl, urlencode
    for key, value in parse_qsl(parts.query):
        if key in {"id", "t", "md5"}:
            allowed.append((key, value))
    return urlunsplit((parts.scheme, parts.hostname or "", parts.path, urlencode(allowed), ""))


def serial_row(row):
    return {"name": str(row.get("name", "")), "identity": str(row.get("info_hash", "")),
            "source": str(row.get("source", "")), "page_url": safe_url(row.get("page_url")),
            "size": row.get("size", 0), "seeders": row.get("seeders", 0),
            "leechers": row.get("leechers", 0), "uploaded_at": row.get("uploaded_at", ""),
            "cached": bool(row.get("apibay_cached_at"))}


def install_http_observer():
    import requests
    original = requests.Session.send

    def send(session, request, **kwargs):
        trace = TRACE.get()
        if trace is None:
            return original(session, request, **kwargs)
        host = urlsplit(request.url).hostname or "unknown"
        # One request start per second per hostname, also across engine groups.
        with RATE_LOCK:
            delay = max(0.0, LAST_REQUEST.get(host, 0) + HOST_INTERVAL.get(host, 1.0) - time.monotonic())
            LAST_REQUEST[host] = time.monotonic() + delay
        if STOP.wait(delay):
            raise requests.Timeout("Audit stopped")
        started = time.monotonic()
        entry = dict(host=host, method=request.method, status=None, seconds=None)
        try:
            response = original(session, request, **kwargs)
            entry.update(status=response.status_code,
                         content_type=response.headers.get("Content-Type", "").split(";")[0],
                         bytes=len(response.content), redirected=bool(response.history))
            if response.headers.get("Retry-After"):
                entry["retry_after"] = response.headers["Retry-After"]
            # Shape hints, not response bodies or authenticated HTML.
            if "html" in entry["content_type"]:
                text = response.text.casefold()
                entry["challenge"] = any(needle in text for needle in
                    ("cf-chl-", "just a moment", "verify you are human", "checking your browser"))
                if host == "online-fix.me":
                    entry["search_cooldown"] = "воспользоваться поиском" in text and "секунд" in text
                    main = re.search(r"<div id=['\"]dle-content['\"]>(.*?)<aside", response.text, re.S)
                    entry["main_listing_ids"] = sorted(set(re.findall(r"/games/[a-z0-9_-]+/(\d+)-", main.group(1)))) if main else []
            return response
        except requests.RequestException as error:
            entry["error_type"] = type(error).__name__
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - started, 3)
            trace.append(entry)
    requests.Session.send = send


def environment(out):
    # Fresh factory defaults; never borrow or write the user's provider profile.
    from torrent_finder import store, apibay_cache
    store.STATE_PATH = str(out / "isolated-state.json")
    store.LEGACY_STATE_PATHS = []
    store._cache, store._dirty = {}, False
    apibay_cache.CACHE_PATH = str(out / "isolated-cache.json")
    from torrent_finder.providers import PROVIDERS
    return {p.slug: type(p) for p in PROVIDERS if p.slug != "all"}


def source_key(provider, engine):
    family = "Nyaa" if engine.name.startswith("Nyaa") else engine.name
    if family == "Apibay":
        scope = [provider.categories, provider.apibay_fallback_categories]
    elif family == "Knaben":
        scope = provider.knaben_categories
    elif family == "Nyaa":
        scope = {"Nyaa (Raw)": "3_3", "Nyaa (Non-English)": "3_2"}.get(engine.name, provider.nyaa_category)
        scope = [scope, provider.prefer_title_matches]
    elif family == "SolidTorrents":
        scope = provider.solidtorrents_category
    else:
        scope = "shared"
    return family, json.dumps(scope, sort_keys=True)


def measure(factory, case, engine_name, *, page=None, repeat=0, nyaa_category=None):
    from torrent_finder.search_session import SearchSession
    provider = factory()
    provider.apibay_cache_enabled = False
    if nyaa_category:
        provider.nyaa_category = nyaa_category
    engine = next(e for e in provider.engines if e.name == engine_name)
    default_mode = engine.mode
    for e in provider.engines:
        e.set_mode("on" if e is engine else "off")
    traffic = []
    operation = engine.search_fn if page is None else lambda q: engine.page_fn(q, page)

    def observed(query):
        token = TRACE.set(traffic)
        try:
            return operation(query)
        finally:
            TRACE.reset(token)
    engine.search_fn = observed
    session = SearchSession([provider], [case["query"]], workers=1)
    started = time.monotonic()
    stamp = now()
    rows = session.run(timeout=20, cancel_event=STOP)
    elapsed = time.monotonic() - started
    task = next(t for t in session.tasks if t.engine.name == engine_name)
    diagnostic = asdict(task.diagnostic)
    raw = [serial_row(row) for row in task.rows]
    kept = [serial_row(row) for row in rows]
    matches = [i + 1 for i, row in enumerate(kept) if candidate(row, case)[0]]
    qualified = [i + 1 for i, row in enumerate(kept) if candidate(row, case)[1]]
    if any(event.get("search_cooldown") for event in traffic):
        audit_status = "search_cooldown"
    elif any(event.get("status") == 429 for event in traffic):
        audit_status = "rate_limited"
    elif any(event.get("challenge") for event in traffic):
        audit_status = "challenge"
    elif any(event.get("status") in {401, 403} for event in traffic) and not kept:
        audit_status = "rejected_login" if engine_name == "Madokami" else "access_blocked"
    else:
        audit_status = diagnostic["status"]
    return dict(id=f"{case['id']}::{engine_name}::{page or 0}::{nyaa_category or ''}::{repeat}",
                case_id=case["id"], provider=case["provider"], engine=engine_name,
                query=case["query"], scenario=case["scenario"], default_mode=default_mode,
                page=page, nyaa_category=nyaa_category, repeat=repeat, started_at=stamp,
                finished_at=now(), measurement="live", seconds=round(elapsed, 3),
                # Adapters return a complete list: this is first batch, not
                # time to first byte or to the first row inside the adapter.
                first_result_seconds=round(elapsed, 3) if kept else None,
                status=audit_status, diagnostic=diagnostic, http=traffic,
                raw_count=len(raw), kept_count=len(kept), candidate_count=len(matches),
                variant_candidate_count=len(qualified), first_candidate_rank=matches[0] if matches else None,
                duplicate_count=len(raw)-len({(r['identity'],r['source']) for r in raw}),
                raw_rows=raw, rows=kept)


def load_records(path):
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def run(args):
    from scripts.provider_audit_corpus import build
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest.exists() else build()
    factories = environment(args.out)
    install_http_observer()
    path = args.out / "measurements.jsonl"
    existing = load_records(path)
    done = {record["id"] for record in existing}
    groups = defaultdict(list)
    cases = manifest["cases"]
    # Interleave providers for source health checks instead of declaring a host
    # blocked from three spellings of the same title.
    cases = sorted(cases, key=lambda c: (int(c["id"].rsplit("-", 1)[1]), c["provider"]))
    for case in cases:
        if args.providers and case["provider"] not in args.providers:
            continue
        provider = factories[case["provider"]]()
        for engine in provider.engines:
            if args.engines and engine.name not in args.engines:
                continue
            family, scope = source_key(provider, engine)
            rid = f"{case['id']}::{engine.name}::0::::{args.repeat}"
            if rid not in done:
                groups[family].append((case, engine.name, scope))
    if args.limit:
        # Use only for pilot runs; limits apply per independent backend.
        groups = {key: tasks[:args.limit] for key, tasks in groups.items()}
    budget = time.monotonic() + args.minutes * 60
    progress = {"completed": len(existing)}

    def save(record):
        with WRITE_LOCK:
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
            progress["completed"] += 1
            if record["measurement"] == "live" or progress["completed"] % 100 == 0:
                print(f"{progress['completed']}: {record['case_id']} / {record['engine']}: "
                      f"{record['status']} {record['kept_count']} rows ({record['measurement']})", flush=True)

    def backend(family, tasks):
        failures, circuit, evidence = 0, None, []
        cache = {}
        for case, engine_name, scope in tasks:
            if STOP.is_set() or time.monotonic() > budget:
                STOP.set()
                return
            key = (scope, case["query"])
            rid = f"{case['id']}::{engine_name}::0::::{args.repeat}"
            if circuit and not args.repeat:
                record = dict(id=rid, case_id=case["id"], provider=case["provider"], engine=engine_name,
                              query=case["query"], scenario=case["scenario"], repeat=args.repeat,
                              measurement="not_run", status="unknown_circuit_open", reason=circuit,
                              evidence_ids=evidence[-3:], started_at=now(), finished_at=now(),
                              raw_count=0, kept_count=0, candidate_count=None, variant_candidate_count=None,
                              seconds=None, first_result_seconds=None, first_candidate_rank=None,
                              raw_rows=[], rows=[], http=[])
            elif key in cache:
                original = cache[key]
                record = dict(original, id=rid, case_id=case["id"], provider=case["provider"],
                              engine=engine_name, scenario=case["scenario"], measurement="reused_shared_source",
                              reused_from=original["id"], seconds=None, first_result_seconds=None)
            else:
                record = measure(factories[case["provider"]], case, engine_name, repeat=args.repeat)
                cache[key] = record
                evidence.append(record["id"])
                if record["status"] in {"missing_login", "rejected_login", "rate_limited"}:
                    circuit = record["status"]
                elif record["status"] in {"error", "timeout", "access_blocked", "challenge", "login_error"} and not record["raw_count"]:
                    failures += 1
                    if failures >= 3:
                        circuit = "three consecutive unavailable searches; remaining cells unknown"
                else:
                    failures = 0
            save(record)

    print(f"Starting {sum(map(len, groups.values()))} cells across {len(groups)} backends", flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        try:
            futures = [pool.submit(backend, family, tasks) for family, tasks in groups.items()]
            for future in as_completed(futures):
                future.result()
        except KeyboardInterrupt:
            STOP.set()
            raise
    print("Stopped at audit time budget; rerun to resume." if STOP.is_set() else "Audit pass complete.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="explicitly enable live requests")
    parser.add_argument("--manifest", type=Path, default=Path("docs/audits/2026-10-03/cases.json"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--providers", nargs="+")
    parser.add_argument("--engines", nargs="+")
    parser.add_argument("--limit", type=int, default=0, help="pilot cells per backend")
    parser.add_argument("--repeat", type=int, default=0, help="separate pass ID; bypasses circuit breaker")
    parser.add_argument("--minutes", type=float, default=40)
    args = parser.parse_args()
    if not args.run:
        parser.error("Live network requests require --run. See docs/audits before running.")
    run(args)


if __name__ == "__main__":
    main()
