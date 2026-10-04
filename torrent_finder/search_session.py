"""Bounded, resumable search attempts shared by solo and combined searches.

Only the coordinator commits completed attempts. Abandoned workers cannot
change returned rows, pagination cursors or a subsequent retry.
"""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import threading
import time

from torrent_finder.filters import apply_filters
from torrent_finder.search_control import SearchControl, SearchInterrupted
from torrent_finder.search_diagnostics import ACCESS_STATUSES, Diagnostic, RequestTrace
from torrent_finder.search_errors import SearchError
from torrent_finder.search_result import SearchResult, normalize_result
from torrent_finder.result_view import release_tag_hits, title_score
import requests

# Once the searches finish, wait at most this long for the Books author lookup.
_AUTHOR_LOOKUP_WAIT = 1.5
MAX_PAGE = 10
MAX_PAGE_TASKS = 24


class PageRows(list):
    def __init__(self, rows=(), *, has_more=True):
        super().__init__(rows)
        self.has_more = has_more


class SearchResults(list):
    def __init__(self, rows=(), notices=(), *, session=None):
        super().__init__(rows)
        self.notices = tuple(notices)
        self.session = session


@dataclass
class _Task:
    group: int
    engine: object
    query: str
    page: int
    diagnostic: Diagnostic
    rows: list = field(default_factory=list)
    has_more: bool = True


class SearchSession:
    def __init__(self, providers, queries, cli_filters=None, *, combined=False,
                 result_filter=None, workers=6, work_titles=None, shared_summary="", work_authors=None):
        from torrent_finder.providers.combined_provider import provider_label
        self.providers = list(providers)
        self.queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))
        self.cli_filters = deepcopy(cli_filters)
        self.combined = combined
        self.result_filter = result_filter
        self.work_titles = work_titles or {}
        # query -> the requested work's authors (author search, Identify title,
        # or a lookup for plain searches); used to rank listings.
        self.work_authors = dict(work_authors or {})
        self.shared_summary = shared_summary
        self.workers = workers
        self._slots = threading.BoundedSemaphore(workers)
        self.tasks = []
        self.groups = []
        # Other names searched because a title found nothing: alias -> typed query.
        self.alias_of = {}
        self.notes = []
        self._busy = threading.Lock()
        # Interleave providers before queries so a slow first provider doesn't
        # own the entire queue. On engines always precede their Auto fallbacks.
        for query in self.queries:
            for provider in self.providers:
                self._add_group(provider, query)

    def _add_group(self, provider, query):
        from torrent_finder.providers.combined_provider import provider_label
        group = len(self.groups)
        self.groups.append((provider, query))
        typed = provider.typed_preset(query)
        active = {e.name for e in provider.effective_engines} | set(typed.require_engines if typed else ())
        for engine in provider.engines:
            status = "pending" if engine.name in active else "auto" if engine.mode == "auto" else "off"
            for expanded in provider.expand_queries(query):
                self.tasks.append(_Task(group, engine, expanded, engine.initial_page,
                                        Diagnostic(provider_label(provider), engine.name, expanded,
                                                   engine.initial_page, status)))
        return group

    @property
    def diagnostics(self):
        return tuple(t.diagnostic for t in self.tasks)

    @property
    def can_retry(self):
        return any(d.retryable for d in self.diagnostics)

    def _latest_pages(self):
        latest = {}
        for task in self.tasks:
            latest[task.group, task.engine.name, task.query] = task
        return list(latest.values())

    def page_status(self):
        lines = []
        for task in self._latest_pages():
            d = task.diagnostic
            if d.status == "off":
                continue
            if not task.engine.page_fn:
                status = "deeper retrieval unavailable"
            elif d.status in {"auto", "skipped"}:
                status = "Auto not needed; no pages requested"
            elif d.retryable:
                status = "page incomplete; retry failed sources first"
            elif task.page >= MAX_PAGE:
                status = f"page limit reached ({MAX_PAGE})"
            elif not task.has_more:
                status = "exhausted for this query"
            else:
                status = f"next page: {task.page + 1}"
            lines.append(f"{d.provider} / {d.engine} · {task.query}: {status}")
        return lines

    def _page_candidates(self):
        return [t for t in self._latest_pages() if t.engine.page_fn and t.has_more
                and t.page < MAX_PAGE and t.diagnostic.status in {"results", "empty", "filtered"}]

    @property
    def can_load_more(self):
        return bool(self._page_candidates())

    def _auto_ready(self):
        ready = []
        for group in range(len(self.groups)):
            tasks = [t for t in self.tasks if t.group == group]
            primary = [t for t in tasks if t.diagnostic.status not in {"auto", "off", "skipped"}]
            if any(t.diagnostic.status == "pending" for t in primary):
                continue
            provider, query = self.groups[group]
            if provider.prefer_title_matches and provider.auto_needs_relevant_rows:
                authors = self.work_authors.get(query, ())
                answered = any(provider.title_relevance(row, query, authors) >= 1 for t in primary for row in t.rows)
                reason = "On engines returned rows matching the title; Auto was not needed."
            else:
                answered = any(t.rows for t in primary)
                reason = "On engines returned rows before local filters; Auto was not needed."
            for task in tasks:
                if task.diagnostic.status != "auto":
                    continue
                if answered:
                    task.diagnostic = replace(task.diagnostic, status="skipped", message=reason)
                else:
                    task.diagnostic = replace(task.diagnostic, status="pending")
                    ready.append(task)
        return ready

    def _execute(self, task, control, slots):
        provider, _query = self.groups[task.group]
        started = time.monotonic()
        status, message, rows, more = "empty", "", [], True
        with RequestTrace() as trace:
            try:
                # Retrying the initial request repeats that request, including
                # its bounded source-specific fallback behavior.
                if task.page == task.engine.initial_page:
                    operation = lambda: task.engine.search_fn(task.query)
                else:
                    operation = lambda: task.engine.page_fn(task.query, task.page)
                raw = control.run_engine(provider.slug, task.engine.name, operation, slots)
                more = getattr(raw, "has_more", True)
                rows = [SearchResult.from_mapping(dict(normalize_result(r))) for r in raw or []]
                rows = [r for r in rows if r.info_hash]
                fetched = datetime.now(timezone.utc).isoformat()
                for row in rows:
                    row.setdefault("fetched_at", row.get("apibay_cached_at") or fetched)
                status = "results" if rows else "empty"
                if trace.failures:
                    status, message = trace.failures[-1]
                    if rows:
                        message += " Received rows are retained; this search may be incomplete."
            except SearchInterrupted:
                status = "interrupted" if control.stopped() else "timeout"
                message = "Stopped waiting; received results are retained."
            except SearchError as error:
                message = str(error)
                low = message.casefold()
                status = error.status or (
                    "missing_login" if "not logged in" in low else "rejected_login" if "rejected" in low
                    else "login_error" if "login" in low or "log in" in low else "error")
            except requests.Timeout:
                status, message = "timeout", "Source request timed out."
            except Exception:
                status, message = trace.failures[-1] if trace.failures else ("error", "Source search failed; try again later.")
        kept, removed = provider.filter_with_reasons(rows, self.cli_filters, self.result_filter)
        if rows and not kept and status == "results":
            status = "filtered"
        hint = ""
        if not rows and status == "empty":
            message = "No matching rows returned by this search; source coverage is not established."
            hint = task.engine.empty_hint(task.query) if task.engine.empty_hint else ""
        descriptions = [provider.filter_summary()]
        for label, config in (("Defaults", provider.default_filters), ("CLI", self.cli_filters)):
            if config:
                parts = [f"{name}: {value}" for name, value in vars(config).items() if value and not callable(value)]
                if parts:
                    descriptions.append(label + ": " + ", ".join(parts))
        if self.shared_summary:
            descriptions.append(self.shared_summary)
        diagnostic = replace(task.diagnostic, status=status, raw=len(rows), kept=len(kept),
                             removed=tuple(removed), seconds=time.monotonic() - started, message=message,
                             cached=sum(bool(r.get("apibay_cached_at")) for r in rows),
                             requests=trace.requests, attempt=task.diagnostic.attempt + 1,
                             filters="; ".join(descriptions), hint=hint)
        return rows, more, diagnostic

    def _commit(self, task, outcome):
        rows, more, diagnostic = outcome
        if task.page > task.engine.initial_page and not rows and not diagnostic.retryable:
            more = False
        # Only identical consecutive catalog pages signal a stuck cursor. RSS
        # overlap with the first catalog page is normal and not exhaustion.
        previous = next((t for t in reversed(self.tasks) if t is not task and
                         (t.group, t.engine.name, t.query, t.page) ==
                         (task.group, task.engine.name, task.query, task.page - 1)), None)
        if previous and previous.page > task.engine.initial_page and rows and not diagnostic.retryable:
            if {(r.info_hash, r.name) for r in previous.rows} == {(r.info_hash, r.name) for r in rows}:
                more = False
                diagnostic = replace(diagnostic, message="Source repeated the previous page; pagination stopped.")
        # Keep earlier rows even when a repeat attempt is partial or empty.
        seen = {(r.info_hash, r.name) for r in rows}
        task.rows = rows + [r for r in task.rows if (r.info_hash, r.name) not in seen]
        task.has_more, task.diagnostic = more, diagnostic

    def snapshot(self):
        from torrent_finder.providers.combined_provider import provider_label, result_identity
        merged = {}
        provider_order = {p.slug: i for i, p in enumerate(self.providers)}
        groups = sorted(enumerate(self.groups), key=lambda item: (provider_order[item[1][0].slug], item[0]))
        for group, (provider, query) in groups:
            candidates = [r for t in self.tasks if t.group == group for r in t.rows]
            rows = provider._filter_search_results(candidates, query, self.cli_filters, self.result_filter)
            for raw in rows:
                row = SearchResult.from_mapping(dict(raw))
                key = result_identity(row)
                if key in merged:
                    existing = merged[key]
                    if (provider.slug in existing.get("matched_providers", [provider.slug])
                            and provider.preference_score(row) > provider.preference_score(existing)):
                        origins = {field: existing[field] for field in ("matched_providers", "matched_queries", "provider_slug", "provider_label", "from_work") if field in existing}
                        existing.update(dict(row))
                        existing.update(origins)
                        if self.combined:
                            existing["preference_score"] = provider.preference_score(row)
                    for field, value in (("matched_providers", provider.slug), ("matched_queries", query)):
                        if field in existing and value not in existing[field]:
                            existing[field].append(value)
                    continue
                if self.combined or len(self.queries) > 1 or self.work_titles:
                    row["matched_queries"] = [query]
                    row["matched_providers"] = [provider.slug]
                if self.combined:
                    row["provider_slug"] = provider.slug
                    row["provider_label"] = provider_label(provider)
                    row["preference_score"] = provider.preference_score(row)
                if len(self.queries) > 1 or self.work_titles:
                    row["from_work"] = self.work_titles.get(query, query)
                merged[key] = row
        ordered = list(merged.values())
        if not self.combined and self.providers:
            ordered = self.providers[0].rank_preferences(self.providers[0]._sort_results(ordered))
        typed = {p.slug: [t for t in (p.typed_preset(q) for q in self.queries) if t] for p in self.providers}

        def typed_hits(row):
            """Presets typed after the title ("Berserk português") that the row matches."""
            presets = typed.get(row.get("provider_slug") or self.providers[0].slug, ())
            return sum(bool(apply_filters([row], preset.config)) for preset in presets)

        if self.queries and self.providers and (self.combined or self.providers[0].prefer_title_matches):
            relevance = {p.slug: p.title_relevance for p in self.providers}
            fallback = (self.providers[0].title_relevance if not self.combined
                        else lambda row, query, authors=(): title_score(row.name, query))
            # Equally good titles: releases carrying the tags typed with the
            # title first ("Finding Nemo pt-br"), then preferred presets.
            ordered.sort(key=lambda r: (max(relevance.get(r.get("provider_slug"), fallback)(
                                                r, q, self.work_authors.get(q, ())) for q in self.queries),
                                        max(release_tag_hits(r.name, q) for q in self.queries) + typed_hits(r),
                                        r.get("preference_score", 0)), reverse=True)
        elif any(typed.values()):
            ordered.sort(key=typed_hits, reverse=True)
        notices = list(dict.fromkeys(d.message if d.status in ACCESS_STATUSES
                                    else f"{d.provider} / {d.engine}: {d.message}"
                                    for d in self.diagnostics if d.retryable or d.status in ACCESS_STATUSES))
        notices += self.notes
        for presets in typed.values():
            for preset in presets:
                count = sum(bool(apply_filters([row], preset.config)) for row in ordered)
                notices.append(f"{count} result(s) carry a {preset.name} tag and are listed first; the title "
                               "alone was searched too." if count else
                               f"No result carries a {preset.name} tag; the title alone was searched too, "
                               "so other releases are shown.")
        if not ordered:  # source advice only when nothing at all was found
            notices += list(dict.fromkeys(d.hint for d in self.diagnostics if d.hint))
        return SearchResults(ordered, notices, session=self)

    def run(self, action="initial", *, cancel_event=None, finish_event=None,
            on_progress=None, on_results=None, timeout=30):
        if not self._busy.acquire(blocking=False):
            raise SearchError("This search is still running.")
        try:
            return self._run(action, cancel_event=cancel_event, finish_event=finish_event,
                             on_progress=on_progress, on_results=on_results, timeout=timeout)
        finally:
            self._busy.release()

    def _run(self, action, *, cancel_event, finish_event, on_progress, on_results, timeout):
        from torrent_finder.providers.combined_provider import SearchProgress, provider_label
        action_started = time.monotonic()
        control = SearchControl(timeout, cancel_event, finish_event)
        author_lookup = self._start_author_lookup() if action == "initial" else None
        # Reuse slots across actions: requests still finishing after a stop
        # continue to count against this session's concurrency allowance.
        slots = self._slots
        if action == "retry":
            selected = [t for t in self.tasks if t.diagnostic.retryable]
        elif action == "more":
            candidates = self._page_candidates()
            # A click never expands an unbounded number of query/engine pairs.
            candidates.sort(key=lambda t: (t.page, t.group, t.engine.name, t.query))
            selected = []
            for old in candidates[:MAX_PAGE_TASKS]:
                task = _Task(old.group, old.engine, old.query, old.page + 1,
                             replace(old.diagnostic, page=old.page + 1, status="pending", attempt=0,
                                     raw=0, kept=0, removed=(), seconds=0, cached=0, requests=0, message=""))
                self.tasks.append(task)
                selected.append(task)
        elif action == "initial":
            selected = [t for t in self.tasks if t.diagnostic.status == "pending"]
        else:
            raise ValueError("Unknown search action")
        for task in selected:
            task.diagnostic = replace(task.diagnostic, status="pending")
        selected += self._auto_ready()

        def publish():
            results = self.snapshot()
            if on_results is not None:
                on_results(results)
            if on_progress is not None:
                waiting = {self.groups[t.group][0].slug for t in self.tasks if t.diagnostic.status in {"pending", "auto"}}
                on_progress(SearchProgress(len(self.providers) - len(waiting), len(self.providers), len(results),
                                           tuple(provider_label(p) for p in self.providers if p.slug in waiting)))

        publish()
        executor = ThreadPoolExecutor(max_workers=self.workers)
        pending = {}
        try:
            if not control.stopped():
                # Give each provider/query one slot before a provider's extra
                # engines or preset spellings can monopolize the worker queue.
                positions = {}
                def fair_order(task):
                    position = positions.get(task.group, 0)
                    positions[task.group] = position + 1
                    return position
                selected.sort(key=fair_order)
                pending = {executor.submit(self._execute, t, control, slots): t for t in selected}
            alias_round = action == "initial" and any(p.looks_up_aliases for p in self.providers)
            while not control.stopped():
                if not pending:
                    if not alias_round:
                        break
                    alias_round = False  # one round: aliases are not looked up again
                    for task in self._alias_tasks(control):
                        pending[executor.submit(self._execute, task, control, slots)] = task
                    if not pending:
                        break
                    publish()
                    continue
                done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                for future in done:
                    self._commit(pending.pop(future), future.result())
                for task in self._auto_ready():
                    if not control.stopped():
                        pending[executor.submit(self._execute, task, control, slots)] = task
                if done:
                    publish()
        finally:
            # Freeze this action before an abandoned worker can finish. No
            # worker mutates tasks, and callbacks only run on this coordinator.
            executor.shutdown(wait=False, cancel_futures=True)
            for task in self.tasks:
                if task.diagnostic.status == "pending":
                    reason = "Stopped waiting" if control.finish.is_set() or control.cancel.is_set() else "Search time limit reached"
                    task.diagnostic = replace(task.diagnostic, status="interrupted", requests=None,
                                              seconds=time.monotonic() - action_started,
                                              attempt=task.diagnostic.attempt + 1,
                                              message=reason.lower() + "; showing results received so far.")
        if author_lookup is not None and not control.stopped():
            author_lookup.join(timeout=_AUTHOR_LOOKUP_WAIT)  # usually already done: it ran alongside
        publish()
        return self.snapshot()

    def _alias_tasks(self, control):
        """Searches for other names of titles that found nothing matching.

        For providers that look up aliases (General Manga): when a title's
        sources answered but no row matches it, the catalog's names for the work
        are searched too ("Yokohama Shopping Log" → "Yokohama Kaidashi Kikou").
        At most three titles are looked up, with one catalog request each.
        """
        wanted = []
        for group, (provider, query) in enumerate(list(self.groups)):
            if not provider.looks_up_aliases or query in self.alias_of:
                continue
            tasks = [t for t in self.tasks if t.group == group]
            if not any(t.diagnostic.status in {"results", "empty", "filtered"} for t in tasks):
                continue  # the sources failed; other names would not help
            if any(provider.title_relevance(row, query) >= 1 for t in tasks for row in t.rows):
                continue
            wanted.append((provider, query))
        wanted = wanted[:3]
        if not wanted:
            return []
        found = {}

        def look_up():
            for provider, query in wanted:
                try:
                    found[provider.slug, query] = tuple(provider.lookup_aliases(query))
                except Exception:
                    continue  # the search simply ends without other names

        thread = threading.Thread(target=look_up, daemon=True)
        thread.start()
        while thread.is_alive() and not control.stopped():
            thread.join(0.05)
        if control.stopped():
            return []
        added = []
        for provider, query in wanted:
            aliases = [a for a in found.get((provider.slug, query), ()) if a not in self.queries]
            for alias in aliases:
                self.queries.append(alias)
                self.alias_of[alias] = query
                group = self._add_group(provider, alias)
                added += [t for t in self.tasks if t.group == group and t.diagnostic.status == "pending"]
            if aliases:
                self.notes.append(f"Nothing matched “{query}”, so its catalog title was searched too: "
                                  + ", ".join(f"“{alias}”" for alias in aliases) + ".")
        return added

    def _start_author_lookup(self):
        """Find the requested work's authors for plain queries (Books), in parallel
        with the searches; rankings use them once known."""
        provider = next((p for p in self.providers if p.looks_up_authors), None)
        wanted = [q for q in self.queries if not self.work_authors.get(q)][:3]
        if provider is None or not wanted:
            return None

        def look_up():
            for query in wanted:
                try:
                    authors = provider.lookup_authors(query)
                except Exception:
                    continue  # ranking simply proceeds without authors
                if authors:
                    self.work_authors.setdefault(query, tuple(authors))

        thread = threading.Thread(target=look_up, daemon=True)
        thread.start()
        return thread


def search_many(provider, queries, cli_filters=None, *, cancel_event=None, finish_event=None,
                on_progress=None, timeout=30, work_titles=None, work_authors=None):
    """UI entry point: isolate settings before starting any source requests."""
    from torrent_finder.state import apply_provider_state, provider_snapshot
    if getattr(provider, "is_combined", False):
        return provider.search_many(queries, cli_filters, cancel_event, finish_event=finish_event,
                                    on_progress=on_progress, timeout=timeout, work_titles=work_titles,
                                    work_authors=work_authors)
    child = type(provider)()
    apply_provider_state(child, provider_snapshot(provider))
    return SearchSession([child], queries, cli_filters, work_titles=work_titles, work_authors=work_authors).run(
        cancel_event=cancel_event, finish_event=finish_event, on_progress=on_progress, timeout=timeout)
