"""Offline export, scoring and real SearchSession replay of saved audit rows.

No source requests are permitted. Run after the live passes finish.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
from unittest.mock import patch

from scripts import provider_audit as audit

DEST = Path("docs/audits/2026-10-03")
HEALTHY = {"results", "empty", "filtered"}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def score(record, case):
    record = deepcopy(record)
    if record["measurement"] == "not_run":
        return record
    positions = [i+1 for i, row in enumerate(record["rows"]) if audit.candidate(row, case)[0]]
    record.update(candidate_count=len(positions),
                  variant_candidate_count=sum(audit.candidate(row, case)[1] for row in record["rows"]),
                  first_candidate_rank=positions[0] if positions else None,
                  scoring="final manifest lexical aliases/exclusions; not adjudicated recall")
    if record["engine"] == "Online-Fix" and not record["repeat"]:
        record["interpretation"] = "initial pass may include undetected HTTP-200 search cooldown; use paced repeat"
    return record


def quantiles(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {}
    return {"min": values[0], "median": round(statistics.median(values),3),
            "p95": values[math.ceil(.95*len(values))-1], "max": values[-1]}


def restore(row):
    item = dict(row)
    item["info_hash"] = item.pop("identity")
    return item


def replay(factory, case, records, *, all_on=False, filter_mode=None):
    from torrent_finder.search_session import SearchSession
    from torrent_finder.filters import FilterConfig, FilterPreset
    provider = factory()
    known = {r["engine"]: r for r in records}
    # A local-only literal probe does not expand requests or force engines.
    token = {"anime":"720p", "movies":"1080p", "manga":"digital", "books":"epub",
             "madokami":"c001", "games":"FitGirl", "fitgirl":"deluxe", "online-fix":"online",
             "software":"x64", "mobile":"apk", "rutracker":"FLAC"}[case["provider"]]
    if filter_mode:
        preset = FilterPreset("Audit literal " + token, FilterConfig(include_keywords=[token]))
        if filter_mode == "require":
            provider.active_presets = [preset]
        else:
            provider.preferred_presets = [preset]
    for engine in provider.engines:
        if all_on:
            engine.set_mode("on")
        engine.search_fn = lambda q, name=engine.name: [restore(r) for r in known.get(name, {}).get("raw_rows", [])]
    session = SearchSession([provider], [case["query"]])
    rows = session.run(timeout=5)
    called = [d.engine for d in session.diagnostics if d.status not in {"off","skipped","auto"}]
    unknown = [name for name in called if known.get(name, {}).get("status") not in HEALTHY]
    positions = [i+1 for i, row in enumerate(rows) if audit.candidate(row,case)[0]]
    return {"rows": [audit.serial_row(r) for r in rows], "count":len(rows),
            "candidate_count":len(positions), "first_candidate_rank":positions[0] if positions else None,
            "called":called, "unknown_sources":unknown,
            "filter_mode":filter_mode, "filter_literal":token if filter_mode else None}


def alias_replays(factories, cases, groups):
    from torrent_finder.search_session import SearchSession
    lookup={c["id"]:c for c in cases}
    pairs=[("movies-02","movies-26"),("anime-06","anime-30"),
           ("books-07","books-26"),("manga-12","manga-31"),
           ("games-03","games-26"),("online-fix-01","online-fix-25")]
    results=[]
    for first,second in pairs:
        samples={c["query"]:{r["engine"]:r for r in groups[c["id"]]} for c in (lookup[first],lookup[second])}
        provider=factories[lookup[first]["provider"]]()
        for engine in provider.engines:
            engine.search_fn=lambda q,name=engine.name:[restore(r) for r in samples.get(q,{}).get(name,{}).get("raw_rows",[])]
        session=SearchSession([provider],list(samples))
        rows=session.run(timeout=5)
        results.append(dict(case_ids=[first,second],queries=list(samples),count=len(rows),
                            candidate_count=sum(audit.candidate(row,lookup[first])[0] for row in rows),
                            matched_queries=[r.get("matched_queries",[]) for r in rows],
                            rows=[audit.serial_row(r) for r in rows]))
    return results


def run(source, dest):
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path=dest/"cases.json"
    if not manifest_path.exists():
        manifest_path=source/"cases.json" if (source/"cases.json").exists() else DEST/"cases.json"
        (dest/"cases.json").write_bytes(manifest_path.read_bytes())
    cases = json.loads(manifest_path.read_text(encoding="utf-8"))["cases"]
    lookup = {c["id"]:c for c in cases}
    if (source/"measurements.jsonl").exists():
        records = audit.load_records(source/"measurements.jsonl")
        ext = source/"extension-probes.json"
        if ext.exists():
            records += json.loads(ext.read_text(encoding="utf-8"))
    else:
        records=[json.loads(line) for line in gzip.decompress((source/"measurements.jsonl.gz").read_bytes()).decode("utf-8").splitlines()]
    records = [score(r,lookup[r["case_id"]]) for r in records]
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids)), "duplicate measurement IDs"
    records.sort(key=lambda r:r["id"])
    content = "".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in records).encode("utf-8")
    (dest/"measurements.jsonl.gz").write_bytes(gzip.compress(content,mtime=0))
    columns = ["id","case_id","provider","engine","query","scenario","default_mode","measurement",
               "status","raw_count","kept_count","candidate_count","variant_candidate_count",
               "first_candidate_rank","duplicate_count","seconds","first_result_seconds","repeat","page","nyaa_category"]
    with (dest/"measurements.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction="ignore",lineterminator="\n")
        writer.writeheader(); writer.writerows(records)
    baseline=[r for r in records if not r["repeat"]]
    assert len(baseline)==1056, f"incomplete initial matrix: {len(baseline)} / 1056"
    # Replace only the contaminated Online-Fix pass using its measured paced
    # rerun; share exactly identical queries with Games, with explicit provenance.
    paced={r["query"]:r for r in records if r["engine"]=="Online-Fix" and r["repeat"]==2}
    effective=[]
    for record in baseline:
        item=record
        if record["engine"]=="Online-Fix" and record["query"] in paced:
            replacement=paced[record["query"]]
            item=score(dict(replacement,case_id=record["case_id"],provider=record["provider"],
                            id=record["id"],evidence_id=replacement["id"]),lookup[record["case_id"]])
        effective.append(item)
    factories=audit.environment(source)
    groups=defaultdict(list)
    for r in effective: groups[r["case_id"]].append(r)
    replay_rows=[]; filters=[]
    with patch("requests.Session.send",side_effect=AssertionError("Offline replay attempted network")):
        for case in cases:
            samples=groups[case["id"]]
            default=replay(factories[case["provider"]],case,samples)
            all_on=replay(factories[case["provider"]],case,samples,all_on=True)
            contribution={}
            for sample in samples:
                identities={r["identity"].casefold() for r in sample["rows"] if audit.candidate(r,case)[0]}
                others={r["identity"].casefold() for s in samples if s["engine"]!=sample["engine"] for r in s["rows"] if audit.candidate(r,case)[0]}
                contribution[sample["engine"]]={"distinct_candidate_ids":len(identities),"unique_to_engine":len(identities-others)}
            replay_rows.append(dict(case_id=case["id"],provider=case["provider"],query=case["query"],scenario=case["scenario"],
                                    default=default,all_on=all_on,contribution=contribution,
                                    evidence_ids=[s.get("evidence_id",s["id"]) for s in samples]))
            if int(case["id"].split("-")[-1]) in (1,2):
                for mode in ("prefer","require"):
                    result=replay(factories[case["provider"]],case,samples,all_on=True,filter_mode=mode)
                    filters.append(dict(case_id=case["id"],mode=mode,before=all_on["count"],**result))
        aliases=alias_replays(factories,cases,groups)
    (dest/"replays.json.gz").write_bytes(gzip.compress(json.dumps(dict(cases=replay_rows,filters=filters,aliases=aliases),ensure_ascii=False,sort_keys=True).encode(),mtime=0))
    summary={"baseline":"v0.7.0 c35280d4f7976fa1265b857c6c045d257d5ca711", "case_count":len(cases),
             "initial_matrix_cells":len(baseline),"measurement_records":len(records),
             "initial_statuses":dict(Counter(r["status"] for r in baseline)),
             "initial_measurement_types":dict(Counter(r["measurement"] for r in baseline)),
             "live_http_events":sum(len(r["http"]) for r in records if r["measurement"]=="live"),
             "first_at":min(r["started_at"] for r in records),"last_at":max(r["finished_at"] for r in records),
             "providers":{},"engines":[],"scenario_groups":[]}
    for slug in factories:
        data=[r for r in replay_rows if r["provider"]==slug]
        nonnegative=[r for r in data if r["scenario"]!="negative_control"]
        summary["providers"][slug]={"queries":len(data),"nonnegative_queries":len(nonnegative),
            "default_title_candidate_queries":sum(bool(r["default"]["candidate_count"]) for r in nonnegative),
            "all_on_title_candidate_queries":sum(bool(r["all_on"]["candidate_count"]) for r in nonnegative),
            "all_on_no_candidate_queries":[r["case_id"] for r in nonnegative if not r["all_on"]["candidate_count"]],
            "all_on_unknown_queries":sum(bool(r["all_on"]["unknown_sources"]) for r in nonnegative),
            "candidate_gain_from_all_on":[r["case_id"] for r in nonnegative if r["all_on"]["candidate_count"] and not r["default"]["candidate_count"]],
            "default_non_candidate_rows":sum(r["default"]["count"]-r["default"]["candidate_count"] for r in nonnegative),
            "default_rows":sum(r["default"]["count"] for r in nonnegative)}
        for engine in factories[slug]().engines:
            cells=[r for r in effective if r["provider"]==slug and r["engine"]==engine.name]
            positive=[r for r in cells if r["scenario"]!="negative_control"]
            summary["engines"].append(dict(provider=slug,engine=engine.name,default_mode=engine.mode,cells=len(cells),
                statuses=dict(Counter(r["status"] for r in cells)),candidate_queries=sum(bool(r["candidate_count"]) for r in positive),
                raw_rows=sum(r["raw_count"] for r in cells),kept_rows=sum(r["kept_count"] for r in cells),
                candidate_rows=sum(r["candidate_count"] or 0 for r in cells),
                first_candidate_ranks=quantiles([r["first_candidate_rank"] for r in cells]),
                paced_seconds=quantiles([r["seconds"] for r in cells if r["measurement"]=="live"])))
    for scenario in sorted({c["scenario"] for c in cases}):
        data=[r for r in replay_rows if r["scenario"]==scenario]
        summary["scenario_groups"].append(dict(scenario=scenario,cases=len(data),
            default_candidates=sum(bool(r["default"]["candidate_count"]) for r in data),
            all_on_candidates=sum(bool(r["all_on"]["candidate_count"]) for r in data)))
    write_json(dest/"summary.json",summary)
    with (dest/"engine-results.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream,lineterminator="\n")
        writer.writerow(["provider","engine","default_mode","cells","candidate_queries","raw_rows","kept_rows",
                         "candidate_rows","statuses","latency_min","latency_median","latency_p95","latency_max"])
        for row in summary["engines"]:
            writer.writerow([row[k] for k in ("provider","engine","default_mode","cells","candidate_queries","raw_rows","kept_rows","candidate_rows")]+
                            [json.dumps(row["statuses"],sort_keys=True)]+[row["paced_seconds"].get(k) for k in ("min","median","p95","max")])
    for name in ("inventory.json","candidate-probes.json","knaben-v2-probes.json","combined-live.json","source-comparisons.json"):
        file=source/name
        zipped=source/(name+".gz")
        if file.exists() or zipped.exists():
            value=json.loads(file.read_text(encoding="utf-8") if file.exists() else gzip.decompress(zipped.read_bytes()))
            if name=="inventory.json":
                write_json(dest/name,value)
            else:
                (dest/(name+".gz")).write_bytes(gzip.compress(json.dumps(value,ensure_ascii=False,sort_keys=True).encode(),mtime=0))
    files=[p for p in dest.iterdir() if p.is_file() and p.name!="SHA256SUMS"]
    (dest/"SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n" for p in sorted(files)),encoding="ascii",newline="\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in {"engines","scenario_groups"}},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,default=audit.DEFAULT_OUT)
    parser.add_argument("--dest",type=Path,default=DEST)
    args=parser.parse_args()
    run(args.source,args.dest)
