"""Creator-mode fan-out: run the normal provider search across resolved works.

The resolver layer (``resolvers/``) turns a creator name into a list of Works;
this runs ``provider.search`` for each one concurrently and merges the results
the same way ``BaseProvider.search`` merges engines — dedupe by info hash, sort
by seeders. Provider presets + CLI filters still apply (they live inside
``provider.search``), so creator results obey the same filtering as a normal
search.
"""

import concurrent.futures

from torrent_finder.search_result import SearchResult, normalize_result


def fan_out(provider, works, cli_filters=None, cancel_event=None, max_workers=6) -> list[SearchResult]:
    """Search every Work's title(s) and return one merged, sorted result list.

    Each result is tagged with ``from_work`` (the originating title) for any
    later grouping; existing keys are untouched.
    """
    # One search task per distinct query string (primary title + alt titles).
    tasks: list[tuple[object, str]] = []
    for w in works:
        seen_q: list[str] = []
        for q in (w.title, *w.alt_titles):
            q = (q or "").strip()
            if q and q not in seen_q:
                seen_q.append(q)
                tasks.append((w, q))
    if not tasks:
        return []

    seen_hashes: set = set()
    merged: list[SearchResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_work = {
            executor.submit(provider.search, q, cli_filters): w for (w, q) in tasks
        }
        for future in concurrent.futures.as_completed(future_to_work):
            if cancel_event is not None and cancel_event.is_set():
                break
            work = future_to_work[future]
            try:
                rows = future.result() or []
            except Exception:
                rows = []
            for raw_row in rows:
                r = normalize_result(raw_row)
                h = r.info_hash.lower()
                if h and h in seen_hashes:
                    continue
                if h:
                    seen_hashes.add(h)
                r.setdefault("from_work", work.title)
                merged.append(r)

    merged.sort(key=lambda x: x.seeders, reverse=True)
    return merged
