"""Bounded follow-up metadata probes for the 2026-10-03 audit; opt-in only."""
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import re
import time

import requests

from scripts import provider_audit as audit

OUT = audit.DEFAULT_OUT
CASES = json.loads(Path("docs/audits/2026-10-03/cases.json").read_text(encoding="utf-8"))["cases"]


def save(name, records):
    (OUT / name).write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def request(url, **kwargs):
    started = time.monotonic()
    item = {"url": url, "started_at": audit.now()}
    try:
        response = requests.get(url, timeout=25, headers={"User-Agent": "torrent-finder-cli-audit/1.0 (gpt-6-astra)"}, **kwargs)
        item.update(status=response.status_code, bytes=len(response.content), seconds=round(time.monotonic()-started, 3))
        response.raise_for_status()
        return response, item
    except requests.RequestException as error:
        item.update(error_type=type(error).__name__, seconds=round(time.monotonic()-started, 3))
        return None, item


def candidates():
    records = []
    for case in [c for c in CASES if c["provider"] == "mobile" and int(c["id"].split("-")[-1]) <= 24]:
        response, item = request("https://search.f-droid.org/api/search_apps", params={"q": case["query"]})
        item.update(source="F-Droid", case_id=case["id"], query=case["query"])
        if response is not None:
            try:
                item["payload"] = response.json()
            except ValueError:
                item["error_type"] = "invalid_json"
        records.append(item)
        save("candidate-probes.json", records)
        time.sleep(1)
    response, meta = request("https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv.gz")
    meta["source"] = "Project Gutenberg"
    if response is not None:
        data = list(csv.DictReader(io.StringIO(gzip.decompress(response.content).decode("utf-8-sig"))))
        meta["catalog_rows"] = len(data)
        for case in [c for c in CASES if c["provider"] == "books"]:
            matches = [r for r in data if audit.candidate({"name": r.get("Title", "")}, case)[0]]
            records.append(dict(meta, case_id=case["id"], query=case["query"], matches=matches))
    else:
        records.append(meta)
    save("candidate-probes.json", records)
    # These are catalog matches only; access and downloadable files must be
    # checked per item before a future adapter could offer an acquisition.
    for query in ("Metropolis", "Night of the Living Dead", "Dom Casmurro", "The Left Hand of Darkness"):
        expression = 'title:("' + query + '") AND (mediatype:movies OR mediatype:texts)'
        response, item = request("https://archive.org/advancedsearch.php", params={
            "q": expression, "output": "json", "rows": 10,
            "fl[]": ["identifier", "title", "mediatype", "language", "access-restricted-item"]})
        item.update(source="Internet Archive", query=query)
        if response is not None:
            try:
                item["payload"] = response.json()
            except ValueError:
                item["error_type"] = "invalid_json"
        records.append(item)
        save("candidate-probes.json", records)
        time.sleep(1)


def extensions():
    factories = audit.environment(OUT)
    audit.install_http_observer()
    records = []
    lookup = {c["id"]: c for c in CASES}
    # First titles + concrete Saki/manga/book controls, selected before looking
    # at these follow-up responses. Repeats never establish catalog absence.
    selected = [(slug, engine) for slug, engine in (
        ("movies", "YTS"), ("movies", "Nyaa"), ("games", "FitGirl"),
        ("anime", "Nyaa"), ("anime", "Knaben"), ("books", "Libgen"),
        ("madokami", "Madokami"), ("software", "Apibay"), ("movies", "SolidTorrents"))]
    for slug, engine in selected:
        record = audit.measure(factories[slug], lookup[f"{slug}-01"], engine, repeat=3)
        records.append(record)
        save("extension-probes.json", records)
        print(record["id"], record["status"], record["kept_count"], flush=True)
    for slug, query, engine in (("anime", "Saki", "Nyaa"), ("anime", "Saki", "Knaben"),
                               ("manga", "One Piece", "Nyaa (EN)"), ("books", "Dune", "Knaben")):
        case = next(c for c in CASES if c["provider"] == slug and c["query"] == query)
        for page in (2, 3):
            record = audit.measure(factories[slug], case, engine, page=page, repeat=3)
            records.append(record)
            save("extension-probes.json", records)
    for query in ("Saki", "Naruto"):
        case = next(c for c in CASES if c["provider"] == "anime" and c["query"] == query)
        for category in ("1_3", "1_4", "1_0"):
            records.append(audit.measure(factories["anime"], case, "Nyaa", nyaa_category=category, repeat=3))
            save("extension-probes.json", records)


def knaben_v2():
    factories = audit.environment(OUT)
    records = []
    for slug, query in (("anime", "Saki"), ("movies", "Dune"), ("games", "Elden Ring"),
                       ("software", "Blender"), ("mobile", "OsmAnd"), ("manga", "One Piece"), ("books", "Dune")):
        cats = factories[slug]().knaben_categories
        for include_dead in (False, True):
            params = {"q": query, "sf": "title", "c": ",".join(map(str, cats)), "o": "seeders", "d": "desc", "s": 50}
            if include_dead:
                params["dead"] = ""
            response, item = request("https://api.knaben.org/v2/search", params=params)
            item.update(source="Knaben v2", provider=slug, query=query, include_dead=include_dead)
            if response is not None:
                try:
                    data = response.json()
                    item["top_keys"] = list(data) if isinstance(data, dict) else []
                    item["payload"] = data
                except ValueError:
                    item["error_type"] = "invalid_json"
            records.append(item)
            save("knaben-v2-probes.json", records)
            time.sleep(1)


def combined():
    from dataclasses import asdict
    from torrent_finder.search_session import SearchSession
    factories = audit.environment(OUT)
    audit.install_http_observer()
    records = []
    for query, slugs in (("Saki", ["anime", "manga", "madokami", "rutracker"]),
                         ("Elden Ring", ["games", "fitgirl", "online-fix"]),
                         ("Dune", ["movies", "books"]), ("VLC", ["software", "mobile"])):
        providers = [factories[slug]() for slug in slugs]
        traffic = []
        for provider in providers:
            provider.apibay_cache_enabled = False
            for engine in provider.engines:
                operation = engine.search_fn
                def observed(q, fn=operation):
                    token = audit.TRACE.set(traffic)
                    try:
                        return fn(q)
                    finally:
                        audit.TRACE.reset(token)
                engine.search_fn = observed
        session = SearchSession(providers, [query], combined=True)
        started = time.monotonic()
        stamp = audit.now()
        rows = session.run(timeout=30)
        records.append(dict(query=query, providers=slugs, started_at=stamp, seconds=round(time.monotonic()-started,3),
                            diagnostics=[asdict(d) for d in session.diagnostics], http=traffic,
                            rows=[dict(audit.serial_row(r), matched_providers=r.get("matched_providers"),
                                       matched_queries=r.get("matched_queries")) for r in rows]))
        save("combined-live.json", records)


def source_comparisons():
    from torrent_finder import online_fix
    session = online_fix._anon_http()
    records = []
    for query, page in (("Raft",1),("Raft",2),("\"Raft\"",1),("Lethal Company",1)):
        time.sleep(11)
        params={"do":"search","subaction":"search","story":query}
        if page>1:
            params.update(search_start=page,result_from=(page-1)*21+1,full_search=0)
        start=time.monotonic()
        response=session.get("https://online-fix.me/index.php",params=params,headers=online_fix._REFERER,timeout=20)
        body=response.text
        main=re.search(r"<div id=['\"]dle-content['\"]>(.*?)<aside",body,re.S)
        ids=sorted(set(re.findall(r"/games/[a-z0-9_-]+/(\d+)-",main.group(1)))) if main else []
        # Only metadata and the cooldown sentence; never persist whole pages.
        records.append(dict(source="Online-Fix own search",query=query,page=page,params=params,
            checked_at=audit.now(),status=response.status_code,seconds=round(time.monotonic()-start,3),
            main_listing_ids=ids,raft_present="16179" in ids,
            cooldown="воспользоваться поиском" in body,
            declared_results=re.findall(r"найдено[^<]{0,100}",body,re.I)))
        save("source-comparisons.json",records)
    response=session.get("https://online-fix.me/games/survival/16179-raft-po-seti.html",headers=online_fix._REFERER,timeout=20)
    records.append(dict(source="Online-Fix exact listing",url=response.url,status=response.status_code,
                        checked_at=audit.now(),title=re.findall(r"<h1[^>]*>(.*?)</h1>",response.text,re.S)))
    save("source-comparisons.json",records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("kind", choices=["candidates", "extensions", "knaben-v2", "combined", "source-comparisons"])
    args = parser.parse_args()
    if not args.run:
        parser.error("Live metadata requests require --run")
    OUT.mkdir(parents=True, exist_ok=True)
    {"candidates": candidates, "extensions": extensions, "knaben-v2": knaben_v2,
     "combined": combined, "source-comparisons":source_comparisons}[args.kind]()
