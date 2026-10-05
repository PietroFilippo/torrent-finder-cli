"""The inspector pane's details for the main menu's rows.

Wide windows show an inspector beside a selector list (see
``selector._build_panel``): the focused row's name, hint and description,
then the lines a row's ``SelectItem.inspect`` returns. These functions build
those lines for the main menu: what a provider will search and what it found
before, the search Continue would reopen and the ones before it, which logins
are set, the download folder's free space, and the current settings. Each
reads saved state once, when its row is first focused, and shows nothing it
cannot read. See docs/adr/0020-quiet-terminal-design.md.
"""

from __future__ import annotations

import os
import shutil

from rich.cells import cell_len
from rich.text import Text

from torrent_finder.ui import theme

_LABEL = 12   # the label column of a "label  value" line
_RECENT = 5   # recent searches listed under Continue


def heading(label: str) -> Text:
    return Text(label.upper(), style=theme.SECTION)


def pair(label: str, value: "str | Text", style: str = "", width: int = _LABEL) -> Text:
    """``  Label       value``: a dim label in a *width* column (two spaces at least), then the value."""
    line = Text("  ")
    line.append(label + " " * max(2, width - cell_len(label)), style=theme.MUTED)
    if isinstance(value, Text):
        line.append_text(value)
    else:
        line.append(value, style=style)
    return line


def _column(value: str, width: int) -> str:
    """*value* in a column *width* cells wide: cut with "…" or padded."""
    if cell_len(value) > width:
        while value and cell_len(value) > width - 1:
            value = value[:-1]
        value += "…"
    return value + " " * (width - cell_len(value))


def _state(word: str) -> Text:
    return Text(word, style=theme.state_style(word) or theme.MUTED)


def _recent(slug: str | None = None, skip: int = 0, limit: int = 3) -> list[dict]:
    """The newest history entries (of one provider when *slug* is given), one per query."""
    from torrent_finder.state import load_history
    seen, entries = set(), []
    for entry in load_history()[skip:]:
        if not isinstance(entry, dict):
            continue
        query = str(entry.get("query", "")).strip()
        if not query or (slug and entry.get("provider") != slug) or query.casefold() in seen:
            continue
        seen.add(query.casefold())
        entries.append(entry)
        if len(entries) == limit:
            break
    return entries


def _when(entry: dict) -> str:
    from torrent_finder.utils import relative_time
    return relative_time(entry.get("timestamp")) or ""


def _counts(slug: str) -> list[Text]:
    from torrent_finder.stats import get_all_stats
    stats = get_all_stats()
    searches = int(stats.get("searches_by_provider", {}).get(slug, 0) or 0)
    picked = int(stats.get("torrents_picked_by_provider", {}).get(slug, 0) or 0)
    if not searches and not picked:
        return []
    line = Text("  ")
    line.append(str(searches))
    line.append(" searches · " if searches != 1 else " search · ", style=theme.MUTED)
    line.append(str(picked))
    line.append(" picked", style=theme.MUTED)
    return [Text(""), heading("This shelf"), line]


def _recent_here(slug: str) -> list[Text]:
    entries = _recent(slug)
    if not entries:
        return []
    lines = [Text(""), heading("Recent here")]
    for entry in entries:
        line = Text("  " + _column(str(entry["query"]).strip(), 30))
        line.append(_when(entry), style=theme.MUTED)
        lines.append(line)
    return lines


# --- rows --------------------------------------------------------------------------------

def provider(target) -> list[Text]:
    """A provider: its engines and their modes, its presets, recent searches and counts.

    A group lists its sources; Search across providers lists the providers
    its profile selects.
    """
    from torrent_finder.providers import ProviderGroup
    from torrent_finder.ui.prompts import provider_hint
    if getattr(target, "is_combined", False):
        from torrent_finder.providers.combined_provider import provider_label
        lines = [heading("Providers")]
        for child in target.children:
            if child.slug in target.selected_slugs:
                lines.append(pair(provider_label(child).split(" · ")[0], provider_hint(child)))
        return lines + _recent_here(target.slug) + _counts(target.slug)
    if isinstance(target, ProviderGroup):
        lines = [heading("Sources")]
        for child in target.children:
            lines.append(pair(child.label, provider_hint(child) if hasattr(child, "engines") else ""))
        return lines

    lines = [heading("Engines")]
    names = max((cell_len(engine.name) for engine in target.engines), default=0) + 2
    for engine in target.engines:
        mode = {"on": "On", "auto": "Auto"}.get(engine.mode, "Off")
        line = Text("  " + _column(engine.name, max(_LABEL, names)))
        line.append_text(_state(mode))
        note = (engine.description or "").split(". ")[0].rstrip(".")
        if note:
            line.append(" " * (6 - len(mode)))
            line.append(note, style=theme.MUTED)
        lines.append(line)
    presets = [(word, chosen) for word, chosen in (("Require", target.active_presets),
                                                   ("Prefer", target.preferred_presets)) if chosen]
    if presets:
        lines += [Text(""), heading("Filters")]
        lines += [pair(word, ", ".join(preset.name for preset in chosen)) for word, chosen in presets]
    return lines + _recent_here(target.slug) + _counts(target.slug)


def continue_search(entry: dict) -> list[Text]:
    """The search Continue reopens (its names, presets, author), then the searches before it."""
    from torrent_finder.providers import display_name_for
    lines = []
    if entry.get("kind") == "creator" and entry.get("name"):
        lines.append(pair(str(entry.get("facet") or "Creator").capitalize(), str(entry["name"])))
    queries = [str(query) for query in entry.get("queries") or [] if str(query).strip()]
    if queries:
        lines.append(pair("Names", ", ".join(queries)))
    presets = [str(preset) for preset in entry.get("presets") or []]
    if presets:
        lines.append(pair("Presets", ", ".join(presets)))
    before = _recent(skip=1, limit=_RECENT)
    if before:
        lines += ([Text("")] if lines else []) + [heading("Recent searches")]
        for item in before:
            line = Text("  " + _column(str(item["query"]).strip(), 24))
            line.append(_column(display_name_for(str(item.get("provider", ""))), 26), style=theme.MUTED)
            line.append(_when(item), style=theme.MUTED)
            lines.append(line)
        hint = Text("  ")
        hint.append("H", style=theme.KEY)
        hint.append(" opens the whole history", style=theme.MUTED)
        lines.append(hint)
    return lines


def credentials() -> list[Text]:
    """Every login and key, set or not."""
    from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
    lines = [heading("Logins and keys")]
    width = max((cell_len(spec.name) for spec in CREDENTIAL_REGISTRY), default=0) + 2
    for spec in CREDENTIAL_REGISTRY:
        status = spec.status()
        lines.append(pair(spec.name, status, theme.GOOD if status != "not set" else theme.MUTED, width))
    return lines


def download_folder(path: str) -> list[Text]:
    """The folder's free space and the unpack setting."""
    from torrent_finder import unpack
    from torrent_finder.utils import format_size
    lines = []
    existing = path
    while existing and not os.path.isdir(existing):
        parent = os.path.dirname(existing)
        existing = "" if parent == existing else parent
    if existing:
        try:
            usage = shutil.disk_usage(existing)
            lines.append(pair("Free", f"{format_size(usage.free)} of {format_size(usage.total)}"))
        except OSError:
            pass
    lines.append(pair("Unpack", _state("On" if unpack.enabled() else "Off")))
    return lines


def settings() -> list[Text]:
    """The appearance in use, the terminal command and the network check."""
    from torrent_finder import paintings, terminal_profile
    from torrent_finder.launcher_alias import current_status
    from torrent_finder.security import exposure_label
    from torrent_finder.ui import appearance
    palette, focus, density = theme.current()
    lines = [heading("Appearance"),
             pair("Design", f"{theme.DESIGNS[palette.design].name} · {palette.name}")]
    if palette.design == "athanor":
        shown = paintings.catalog().get(appearance.painting())
        lines.append(pair("Painting", shown.title if shown else "none"))
    lines += [pair("Focus", theme.FOCUS_STYLES[focus]), pair("Density", theme.DENSITIES[density])]
    if terminal_profile.supported():
        lines.append(pair("Terminal", "torrent-finder profile" if terminal_profile.installed() else "no profile"))
    command = current_status()
    lines += [Text(""), heading("Command and network"),
              pair("Command", command.name if command.available else f"{command.name} (setup needed)")]
    network = exposure_label()
    if network:
        lines.append(pair("Network", Text.from_markup(network)))
    return lines
