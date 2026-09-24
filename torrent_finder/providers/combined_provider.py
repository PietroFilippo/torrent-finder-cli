"""Keyword search across independently configured providers.

Profiles contain settings, never credentials or shared provider instances.
Each invocation gets its own provider copies, request budget and notices.
"""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, replace
import re
import threading

from torrent_finder.filters import FilterConfig, apply_filters
from torrent_finder.providers.base import BaseProvider
from torrent_finder.result_view import title_score
from torrent_finder.search_errors import SearchError
from torrent_finder.search_result import SearchResult
from torrent_finder.search_control import SearchControl
from torrent_finder.state import (
    apply_provider_state, load_setting, provider_snapshot, save_setting,
)

_PROFILE_KEY = "combined_search"
_REQUEST_LIMIT = 6
SEARCH_SECONDS = 30.0
_LABELS = {
    "games": "Games · General", "online-fix": "Games · Online-Fix",
    "fitgirl": "Games · FitGirl", "software": "Software · Desktop",
    "mobile": "Software · Mobile", "rutracker": "Software · RuTracker",
    "manga": "Manga · General", "madokami": "Manga · Madokami",
}
_SEED_SOURCES = {"Apibay", "Nyaa", "Knaben", "SolidTorrents", "YTS", "RuTracker"}


def provider_label(provider) -> str:
    return _LABELS.get(provider.slug, provider.name)


def result_identity(row) -> tuple:
    """Only genuine torrent hashes share identity across different sources."""
    value = row.get("info_hash", "")
    if re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return ("torrent", value.lower())
    return (row.get("source", ""), row.get("page_url") or value or row.get("name"))


class CombinedResults(list):
    def __init__(self, rows=(), notices=()):
        super().__init__(rows)
        self.notices = tuple(notices)


@dataclass(frozen=True)
class SearchProgress:
    completed: int
    total: int
    results: int
    waiting: tuple[str, ...]


class CombinedProvider(BaseProvider):
    name = "Search across providers"
    slug = "all"
    icon = "🌐"
    categories = []
    is_combined = True
    supports_subtitles = supports_episode_picker = supports_streaming = False
    search_note = "Search selected providers together; each keeps its own engines and filters."

    def __init__(self, templates):
        super().__init__()
        self.templates = tuple(templates)
        self._children = None
        self.selected_slugs = set()
        self.shared_filters = FilterConfig()

    def _init_engines(self):
        return []

    @property
    def children(self):
        if self._children is None:
            self.restore(load_setting(_PROFILE_KEY, {}))
        return self._children

    def restore(self, profile):
        profile = profile if isinstance(profile, dict) else {}
        saved = profile.get("providers", {})
        self._children = []
        for original in self.templates:
            child = type(original)()
            initial = provider_snapshot(original)
            if child.slug == "anime" and child.slug not in saved:
                # New combined profiles never inherit a resolution restriction.
                quality_names = {p.name for p in child.presets if p.config.quality}
                initial["active_presets"] = [n for n in initial["active_presets"] if n not in quality_names]
            apply_provider_state(child, saved.get(child.slug, initial))
            self._children.append(child)
        valid = {p.slug for p in self._children}
        self.selected_slugs = set(profile.get("selected", valid)) & valid
        shared = profile.get("shared", {})
        self.shared_filters = FilterConfig(
            include_keywords=list(shared.get("include_keywords", [])),
            exclude_keywords=list(shared.get("exclude_keywords", [])),
        )

    def snapshot(self):
        children = self.children
        return {
            "selected": [p.slug for p in children if p.slug in self.selected_slugs],
            "providers": {p.slug: provider_snapshot(p) for p in children},
            "shared": {
                "include_keywords": list(self.shared_filters.include_keywords),
                "exclude_keywords": list(self.shared_filters.exclude_keywords),
            },
        }

    def save_profile(self):
        from torrent_finder import store
        save_setting(_PROFILE_KEY, self.snapshot())
        store.flush()

    def summary(self):
        selected = [p for p in self.children if p.slug in self.selected_slugs]
        names = ", ".join(provider_label(p) for p in selected)
        selection = names if len(selected) <= 3 else f"{len(selected)} providers selected"
        presets = sum(len(p.active_presets) for p in selected)
        shared = len(self.shared_filters.include_keywords) + len(self.shared_filters.exclude_keywords)
        return selection or "No providers selected", f"{presets} provider presets; {shared} shared name rules"

    def search(self, query, cli_filters=None):
        return self.search_many([query], cli_filters)

    def search_many(self, queries, cli_filters=None, cancel_event=None, *, finish_event=None,
                    on_progress=None, timeout=None):
        # Snapshot before starting threads: changing a menu after cancellation
        # cannot alter an old request that is still finishing.
        session = CombinedProvider(self.templates)
        session.restore(self.snapshot())
        queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))
        providers = [p for p in session.children if p.slug in session.selected_slugs]
        if not providers:
            raise SearchError("No providers selected. Press Ctrl+F to choose at least one.")
        if not queries:
            return CombinedResults()
        control = SearchControl(SEARCH_SECONDS if timeout is None else timeout, cancel_event, finish_event)
        slots = threading.BoundedSemaphore(_REQUEST_LIMIT)
        for provider in providers:
            provider.search_slots, provider.cancel_event = slots, control.cancel
            provider.search_control = control

        def matches_shared_rules(row):
            # Name rules must not match source labels. Seed requirements only
            # apply where swarm statistics exist, never to direct downloads.
            for config in (session.shared_filters, cli_filters):
                if config is None:
                    continue
                effective = config if row.source in _SEED_SOURCES else replace(config, min_seeds=0)
                if not apply_filters([{"name": row.name, "seeders": row.seeders}], effective):
                    return False
            return True

        batches, notices = {}, {}
        finished = set()
        lock = threading.Lock()
        accepting = True

        def publish():
            if on_progress is None:
                return
            with lock:
                if not accepting:
                    return
                keys = {result_identity(row) for rows in batches.values() for row in rows}
                progress = SearchProgress(len(finished), len(providers), len(keys),
                                          tuple(provider_label(p) for i, p in enumerate(providers) if i not in finished))
                # Serialize callbacks so an older count cannot replace a newer one.
                on_progress(progress)

        def update_batch(i, j, rows):
            with lock:
                if not accepting:
                    return
                batches[i, j] = rows
            publish()

        def search_provider(i, provider):
            # One coordinator per provider prevents slow early entries from
            # blocking unrelated providers. Engine calls still share six slots.
            for j, query in enumerate(queries):
                if control.stopped():
                    return
                try:
                    rows = provider.search(query, result_filter=matches_shared_rules,
                                           on_results=lambda rows, j=j: update_batch(i, j, rows))
                    update_batch(i, j, rows)
                except SearchError as error:
                    with lock:
                        if accepting:
                            notices[i] = str(error)
                    break
                except Exception:
                    with lock:
                        if accepting:
                            notices[i] = f"{provider_label(provider)} could not be searched. Try again later."
                    break
            if not control.stopped():
                with lock:
                    if accepting:
                        finished.add(i)
                publish()

        publish()
        executor = ThreadPoolExecutor(max_workers=len(providers))
        pending = {executor.submit(search_provider, i, provider) for i, provider in enumerate(providers)}
        try:
            while pending and not control.stopped():
                _, pending = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            with lock:
                accepting = False
                batches = dict(batches)
                notices = dict(notices)
                incomplete = [i for i in range(len(providers)) if i not in finished]

        messages = [notices[i] for i in sorted(notices)]
        labels = {p.slug: provider_label(p) for p in providers}
        messages.extend(f"{labels[slug]}: {engine} timed out; results may be incomplete."
                        for slug, engine in sorted(control.timeouts()))
        for i in incomplete:
            reason = "Stopped waiting" if control.finish.is_set() else "Search time limit reached"
            messages.append(f"{provider_label(providers[i])}: {reason.lower()}; showing results received so far. Search this provider separately to try again.")

        merged = {}
        for (i, j), rows in sorted(batches.items()):
            provider, query = providers[i], queries[j]
            for raw in rows:
                row = SearchResult.from_mapping(dict(raw))
                key = result_identity(row)
                if key in merged:
                    existing = merged[key]
                    for field, value in (("matched_providers", provider.slug), ("matched_queries", query)):
                        if value not in existing[field]:
                            existing[field].append(value)
                    continue
                row["provider_slug"] = provider.slug
                row["provider_label"] = provider_label(provider)
                row["matched_providers"] = [provider.slug]
                row["matched_queries"] = [query]
                if len(queries) > 1:
                    row["from_work"] = query
                merged[key] = row
        # Preserve each provider's ordering among equally relevant rows. This
        # keeps direct downloads useful even without swarm statistics.
        ordered = sorted(merged.values(), key=lambda r: max(title_score(r.name, q) for q in queries), reverse=True)
        return CombinedResults(ordered, messages)
