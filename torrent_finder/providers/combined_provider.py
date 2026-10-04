"""Keyword search across independently configured providers.

Profiles contain settings, never credentials or shared provider instances.
Each invocation gets its own provider copies, request budget and notices.
"""

from dataclasses import dataclass, replace
import re

from torrent_finder.filters import FilterConfig, apply_filters
from torrent_finder.providers.base import BaseProvider
from torrent_finder.result_view import SORT_ORDERS
from torrent_finder.search_profiles import ProfileLibrary
from torrent_finder.search_errors import SearchError
from torrent_finder.state import apply_provider_state, provider_snapshot

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
    """Only genuine torrent hashes share identity across different sources.

    A listing whose real hash was resolved on demand (RuTracker, FitGirl) keeps
    the identity it was listed with (``listing_hash``): saving it before and
    after picking it is one bookmark, and a refresh still finds the listing.
    """
    value = row.get("listing_hash") or row.get("info_hash", "")
    if re.fullmatch(r"[0-9a-fA-F]{40}", value):
        return ("torrent", value.lower())
    return (row.get("source", ""), row.get("page_url") or value or row.get("name"))


# Compatibility name for callers that inspect combined notices.
from torrent_finder.search_session import SearchResults as CombinedResults


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
        self.profile_id = "default"
        self.profile_name = "Default"

    def _init_engines(self):
        return []

    @property
    def children(self):
        if self._children is None:
            self.use_profile(ProfileLibrary.load().current)
        return self._children

    def use_profile(self, entry):
        self.restore(entry["settings"])
        self.profile_id, self.profile_name = entry["id"], entry["name"]

    def restore_history(self, profile):
        self.restore(profile)
        self.profile_id, self.profile_name = None, "History search (unsaved)"

    def restore(self, profile):
        from torrent_finder.name_rules import NameRules
        profile = profile if isinstance(profile, dict) else {}
        self.name_rules = NameRules.restore(profile.get("name_rules", {}))
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
        order = profile.get("result_sort", "relevance")
        self.result_sort = order if isinstance(order, str) and order in SORT_ORDERS else "relevance"

    def snapshot(self):
        children = self.children
        return {
            "name_rules": self.name_rules.snapshot(),
            "selected": [p.slug for p in children if p.slug in self.selected_slugs],
            "providers": {p.slug: provider_snapshot(p) for p in children},
            "shared": {
                "include_keywords": list(self.shared_filters.include_keywords),
                "exclude_keywords": list(self.shared_filters.exclude_keywords),
            },
            "result_sort": self.result_sort,
        }

    def profile_draft(self):
        snapshot = self.snapshot()
        library = ProfileLibrary.load()
        if any(entry["id"] == self.profile_id for entry in library.entries):
            library.select(self.profile_id)
            library.update(snapshot)
        else:
            name, number = "History search", 2
            while library.find(name):
                name, number = f"History search {number}", number + 1
            library.create(name, snapshot)
        return library

    def save_profile(self, library=None):
        library = library if library is not None else self.profile_draft()
        library.update(self.snapshot())
        library.save()
        self.profile_id, self.profile_name = library.current["id"], library.current["name"]

    def summary(self):
        selected = [p for p in self.children if p.slug in self.selected_slugs]
        names = ", ".join(provider_label(p) for p in selected)
        selection = names if len(selected) <= 3 else f"{len(selected)} providers selected"
        required = sum(len(p.active_presets) for p in selected)
        preferred = sum(len(p.preferred_presets) for p in selected)
        shared = (len(self.shared_filters.include_keywords) + len(self.shared_filters.exclude_keywords)
                  + sum(bool(value.strip()) for value in self.name_rules.snapshot().values()))
        return (selection or "No providers selected",
                f"{self.profile_name} · Require: {required}; Prefer: {preferred}; {shared} name rules"
                + (" · " + self.name_rules.summary() if self.name_rules.summary() else ""))

    def filter_summary(self):
        return self.summary()[1]

    def search(self, query, cli_filters=None):
        return self.search_many([query], cli_filters)

    def search_many(self, queries, cli_filters=None, cancel_event=None, *, finish_event=None,
                    on_progress=None, timeout=None, work_titles=None):
        from torrent_finder.search_session import SearchSession
        session = CombinedProvider(self.templates)
        session.restore(self.snapshot())
        providers = [p for p in session.children if p.slug in session.selected_slugs]
        if not providers:
            raise SearchError("No providers selected. Press Ctrl+F to choose at least one.")

        def matches_shared_rules(row):
            if not session.name_rules.matches(row.name):
                return False
            for config in (session.shared_filters, cli_filters):
                if config is None:
                    continue
                effective = config if row.source in _SEED_SOURCES else replace(config, min_seeds=0)
                if not apply_filters([{"name": row.name, "seeders": row.seeders}], effective):
                    return False
            return True

        return SearchSession(providers, queries, combined=True, result_filter=matches_shared_rules,
                             workers=_REQUEST_LIMIT, work_titles=work_titles,
                             shared_summary="Shared: " + session.name_rules.summary() +
                             f"; include {session.shared_filters.include_keywords}; exclude {session.shared_filters.exclude_keywords}"
                             + (f"; CLI {cli_filters}" if cli_filters else "")).run(
            cancel_event=cancel_event, finish_event=finish_event, on_progress=on_progress,
            timeout=SEARCH_SECONDS if timeout is None else timeout)
