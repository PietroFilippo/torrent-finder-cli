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
import threading

from rich.cells import cell_len
from rich.text import Text

from torrent_finder.i18n import N_, t, tn
from torrent_finder.ui import theme

# i18n: converted

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


def _pairs(rows: list[tuple]) -> list[Text]:
    """Size one block's label column from its already translated labels."""
    width = max(_LABEL, max((cell_len(row[0]) + 2 for row in rows), default=0))
    return [pair(*row, width=width) for row in rows]


def _column(value: str, width: int) -> str:
    """*value* in a column *width* cells wide: cut with "…" or padded."""
    if cell_len(value) > width:
        while value and cell_len(value) > width - 1:
            value = value[:-1]
        value += "…"
    return value + " " * (width - cell_len(value))


def _state(word: str) -> Text:
    return Text(t(word, ctx="engine mode"), style=theme.state_style(word) or theme.MUTED)


def _recent(slug: str | None = None, skip: int = 0, limit: int = 3) -> list[dict]:
    """The newest history entries (of one provider when *slug* is given), one per query."""
    from torrent_finder.state import recent_history
    return recent_history(slug, skip, limit)


def _one_line(value: object) -> str:
    """User text on one line: a query saved with line breaks keeps its words."""
    return " ".join(str(value).split())


def _within(seconds: float, probe):
    """*probe*'s result, or None when it fails or takes longer than *seconds* (a slow or unplugged drive)."""
    box = {}

    def run():
        try:
            box["value"] = probe()
        except Exception:
            pass

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    return box.get("value")


def _when(entry: dict) -> str:
    from torrent_finder.utils import relative_time
    return relative_time(entry.get("timestamp")) or ""


def _count(stats: dict, key: str, slug: str) -> int:
    """One saved counter, or 0 when that part of the stats is unreadable."""
    counts = stats.get(key)
    value = counts.get(slug, 0) if isinstance(counts, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _counts(slug: str) -> list[Text]:
    from torrent_finder.stats import get_all_stats
    stats = get_all_stats()
    stats = stats if isinstance(stats, dict) else {}
    searches = _count(stats, "searches_by_provider", slug)
    picked = _count(stats, "torrents_picked_by_provider", slug)
    if not searches and not picked:
        return []
    line = Text("  ")
    line.append(tn("{n} search · {picked} picked", "{n} searches · {picked} picked", searches, picked=picked),
                style=theme.MUTED)
    line.highlight_regex(r"\d+", theme.TEXT or "default")
    return [Text(""), heading(t("This shelf")), line]


def _recent_here(slug: str) -> list[Text]:
    entries = _recent(slug)
    if not entries:
        return []
    lines = [Text(""), heading(t("Recent here"))]
    for entry in entries:
        line = Text("  " + _column(_one_line(entry["query"]), 30))
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
        from torrent_finder.providers.combined_provider import provider_display_label
        lines = [heading(t("Providers"))]
        lines += _pairs([(provider_display_label(child).split(" · ")[0], provider_hint(child))
                         for child in target.children if child.slug in target.selected_slugs])
        return lines + _recent_here(target.slug) + _counts(target.slug)
    if isinstance(target, ProviderGroup):
        lines = [heading(t("Sources"))]
        lines += _pairs([(child.label, provider_hint(child) if hasattr(child, "engines") else "")
                         for child in target.children])
        return lines

    lines = [heading(t("Engines"))]
    names = max((cell_len(engine.name) for engine in target.engines), default=0) + 2
    modes_width = max(cell_len(t(word)) for word in (N_("On", ctx="engine mode"), N_("Auto", ctx="engine mode"),
                                                  N_("Off", ctx="engine mode"))) + 2
    for engine in target.engines:
        mode = {"on": "On", "auto": "Auto"}.get(engine.mode, "Off")  # i18n: ignore — state identities
        line = Text("  " + _column(engine.name, max(_LABEL, names)))
        line.append_text(_state(mode))
        description = engine.description or ""
        note = t(description).split(". ")[0].rstrip(".")
        if note:
            line.append(" " * (modes_width - cell_len(t(mode, ctx="engine mode"))))
            line.append(note, style=theme.MUTED)
        lines.append(line)
    presets = [(word, chosen) for word, chosen in ((N_("Require", ctx="preset state"), target.active_presets),
                                                   (N_("Prefer", ctx="preset state"), target.preferred_presets)) if chosen]
    if presets:
        lines += [Text(""), heading(t("Filters"))]
        lines += _pairs([(t(word), ", ".join(t(preset.name) for preset in chosen)) for word, chosen in presets])
    return lines + _recent_here(target.slug) + _counts(target.slug)


def continue_search(entry: dict) -> list[Text]:
    """The search Continue reopens (its names, presets, author), then the searches before it."""
    from torrent_finder.providers import display_name_for
    rows = []
    if entry.get("kind") == "creator" and entry.get("name"):
        facet = _one_line(entry.get("facet") or N_("Creator")).capitalize()
        rows.append((t(facet), _one_line(entry["name"])))
    queries = [_one_line(query) for query in entry.get("queries") or [] if str(query).strip()]
    if queries:
        rows.append((t("Names"), ", ".join(queries)))
    presets = [_one_line(t(preset)) for preset in entry.get("presets") or []]
    if presets:
        rows.append((t("Presets"), ", ".join(presets)))
    rows += _profile_rows(entry.get("search_profile"))
    lines = _pairs(rows)
    before = _recent(skip=1, limit=_RECENT)
    if before:
        lines += ([Text("")] if lines else []) + [heading(t("Recent searches"))]
        for item in before:
            line = Text("  " + _column(_one_line(item["query"]), 24))
            line.append(_column(_one_line(display_name_for(str(item.get("provider", "")))), 26), style=theme.MUTED)
            line.append(_when(item), style=theme.MUTED)
            lines.append(line)
        hint = Text.from_markup(t("[key]H[/key] opens the whole history"), style=theme.MUTED)
        hint = Text("  ") + hint
        lines.append(hint)
    return lines


def _profile_rows(profile: object) -> list[tuple]:
    """A combined search's saved profile: the providers it searched and its shared keyword rules."""
    from torrent_finder.providers import display_name_for
    if not isinstance(profile, dict):
        return []
    lines = []
    selected = [display_name_for(str(slug)) for slug in profile.get("selected") or [] if isinstance(slug, str)]
    if selected:
        lines.append((t("Providers"), ", ".join(_one_line(name) for name in selected)))
    shared = profile.get("shared") if isinstance(profile.get("shared"), dict) else {}
    for label, key in ((N_("Include"), "include_keywords"), (N_("Exclude"), "exclude_keywords")):
        words = [_one_line(word) for word in shared.get(key) or [] if isinstance(word, str) and word.strip()]
        if words:
            lines.append((t(label), ", ".join(words)))
    return lines


def _profile(profile: object) -> list[Text]:
    return _pairs(_profile_rows(profile))


def credentials() -> list[Text]:
    """Every login and key, set or not."""
    from torrent_finder.credential_registry import CREDENTIAL_REGISTRY
    lines = [heading(t("Logins and keys"))]
    width = max((cell_len(spec.display_name()) for spec in CREDENTIAL_REGISTRY), default=0) + 2
    for spec in CREDENTIAL_REGISTRY:
        status = spec.status()
        lines.append(pair(spec.display_name(), spec.status_label(),
                          theme.GOOD if status != "not set" else theme.MUTED, width))
    return lines


def download_folder(path: str) -> list[Text]:
    """The folder's free space and the unpack setting."""
    from torrent_finder import unpack
    from torrent_finder.utils import format_size
    def usage():
        existing = os.path.abspath(path) if path else ""  # a relative folder lives under the current one
        while existing and not os.path.isdir(existing):
            parent = os.path.dirname(existing)
            existing = "" if parent == existing else parent
        return shutil.disk_usage(existing) if existing else None

    rows = []
    # A network or unplugged drive can take seconds to answer: the menu does not wait for it.
    space = _within(0.25, usage)
    if space:
        rows.append((t("Free"), t("{free} of {total}", free=format_size(space.free), total=format_size(space.total))))
    rows.append((t("Unpack"), _state("On" if unpack.enabled() else "Off")))  # i18n: ignore — state identities
    return _pairs(rows)


def appearance_details() -> list[Text]:
    """The appearance in use: design and colours, painting, focus, density, the terminal profile."""
    from torrent_finder import paintings, terminal_profile
    from torrent_finder.ui import appearance
    palette, focus, density = theme.current()
    rows = [(t("Design"), f"{theme.DESIGNS[palette.design].name} · {palette.name}")]
    if palette.design == "athanor":
        shown = paintings.catalog().get(appearance.painting())
        side = appearance.placement()
        where = "" if side == "right" or not shown else f" · {t(paintings.PLACEMENTS[side]).lower()}"
        rows.append((t("Painting"), (shown.title if shown else t("none")) + where))
    rows += [(t("Focus"), t(theme.FOCUS_STYLES[focus])), (t("Density"), t(theme.DENSITIES[density]))]
    if terminal_profile.supported():
        plain = appearance.profile_look(palette.design) == "plain"
        profile = t("torrent-finder profile · plain look") if plain else t("torrent-finder profile")
        rows.append((t("Terminal"), profile if terminal_profile.installed() else t("no profile")))
        if not plain:
            font, size = appearance.font(palette.design)
            rows.append((t("Font"), f"{font.face} · {font.size_label(size)}"))
    return [heading(t("Appearance")), *_pairs(rows)]


def command_details() -> list[Text]:
    from torrent_finder.launcher_alias import current_status
    command = current_status()
    return _pairs([(t("Command"), command.name if command.available else t("{command} (setup needed)", command=command.name))])


def network_details() -> list[Text]:
    from torrent_finder.security import exposure_label
    network = exposure_label()
    return _pairs([(t("Network"), Text.from_markup(network) if network else t("not checked yet"))])


def settings() -> list[Text]:
    """The appearance in use, the terminal command and the network check."""
    from torrent_finder.security import exposure_label
    lines = appearance_details() + [Text(""), heading(t("Command and network"))] + command_details()
    return lines + (network_details() if exposure_label() else [])
