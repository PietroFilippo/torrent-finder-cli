"""Transactional settings for search across providers."""

from torrent_finder.providers.combined_provider import CombinedProvider, provider_label
from torrent_finder.ui.selector import SelectItem, arrow_select


_SHARED_HELP = {
    "include_keywords": (
        "Keep only results whose name contains at least one of these phrases, from ANY selected provider. "
        "Example: batch, volume keeps names containing batch OR volume. Matching ignores letter case. "
        "Empty means no include restriction."
    ),
    "exclude_keywords": (
        "Hide results whose name contains any of these phrases, from ANY selected provider. "
        "Example: sample, trailer hides either word. Matching ignores letter case. "
        "An exclusion wins even if an include phrase matches. Empty excludes nothing."
    ),
}


def _shared_filter_screen(action):
    from rich.text import Text
    def render(target):
        target.print(Text("Name filters for all selected providers", style="bold cyan"))
        target.print(Text(_SHARED_HELP[action]))
        target.print(Text("These filter returned names; they do not add words to your search. "
                          "Provider presets still apply. For Anime-only 1080p, use Provider engines and presets.", style="dim"))
        target.print(Text("Enter saves this draft field • Esc cancels", style="dim"))
    return render


def _choose_providers(draft):
    from torrent_finder.ui.prompts import _make_banner_panel
    items = [
        SelectItem(provider_label(p), p.slug, toggled=p.slug in draft.selected_slugs,
                   description=p.search_note)
        for p in draft.children
    ]
    count = len(items)
    items += [SelectItem("Use this selection  [w]", "save", is_action=True),
              SelectItem("Cancel", "cancel", is_action=True)]

    def set_all(value):
        def update(cursor, rows):
            for row in rows[:count]:
                row.toggled = value
            return True
        return update

    def toggle(cursor, rows):
        if cursor < count:
            rows[cursor].toggled = not rows[cursor].toggled
        return True

    chosen = arrow_select(
        items, title="Choose providers", multi=True, banner=_make_banner_panel(),
        footer="Space/Enter toggle • a all • c none • w confirm • Esc cancel",
        key_actions={"a": set_all(True), "A": set_all(True),
                     "c": set_all(False), "C": set_all(False),
                     " ": toggle, "w": lambda *_: count, "W": lambda *_: count},
    )
    if chosen is not None and items[chosen].value == "save":
        draft.selected_slugs = {row.value for row in items[:count] if row.toggled}


def _configure_provider(draft):
    from torrent_finder.ui.prompts import _make_banner_panel, filter_menu
    while True:
        items = [
            SelectItem(provider_label(p), p, is_action=True,
                       hint=("included" if p.slug in draft.selected_slugs else "excluded")
                       + " · " + (", ".join(pr.name for pr in p.active_presets) or "no presets"))
            for p in draft.children
        ]
        items.append(SelectItem("Back", None, is_action=True))
        chosen = arrow_select(items, title="Provider engines and presets",
                              banner=_make_banner_panel(), footer="Enter configure • Esc back")
        if chosen is None or items[chosen].value is None:
            return
        # The outer menu owns persistence; Cancel discards every draft edit.
        filter_menu(items[chosen].value, on_save=lambda: None)


def combined_filter_menu(provider):
    from torrent_finder.ui.prompts import _make_banner_panel, get_query_with_shortcut
    draft = CombinedProvider(provider.templates)
    draft.restore(provider.snapshot())
    while True:
        items = [
            SelectItem(f"Providers: {len(draft.selected_slugs)} selected", "providers"),
            SelectItem("All providers: include name phrases…", "include_keywords",
                       hint=", ".join(draft.shared_filters.include_keywords) or "any name",
                       description=_SHARED_HELP["include_keywords"]),
            SelectItem("All providers: exclude name phrases…", "exclude_keywords",
                       hint=", ".join(draft.shared_filters.exclude_keywords) or "none",
                       description=_SHARED_HELP["exclude_keywords"]),
            SelectItem("Provider engines and presets…", "configure",
                       description="Each provider keeps its own settings. Resolution and language presets stay scoped to that provider."),
            SelectItem("Save and return  [w]", "save", enabled=bool(draft.selected_slugs),
                       description="Select at least one provider to save." if not draft.selected_slugs else ""),
            SelectItem("Cancel", "cancel"),
        ]
        chosen = arrow_select(
            items, title="Search across providers — filters", banner=_make_banner_panel(),
            footer="Enter choose • w save • Esc cancel (discard changes)",
            key_actions={"w": lambda *_: 4 if draft.selected_slugs else True,
                         "W": lambda *_: 4 if draft.selected_slugs else True},
        )
        if chosen is None or items[chosen].value == "cancel":
            return
        action = items[chosen].value
        if action == "providers":
            _choose_providers(draft)
        elif action == "configure":
            _configure_provider(draft)
        elif action == "save":
            provider.restore(draft.snapshot())
            provider.save_profile()
            return
        else:
            previous = ", ".join(getattr(draft.shared_filters, action))
            value = get_query_with_shortcut("Name phrases (comma separated; empty clears): ", initial=previous,
                                            screen_renderer=_shared_filter_screen(action))
            if isinstance(value, str) and value != "GO_BACK":
                setattr(draft.shared_filters, action, [v.strip() for v in value.split(",") if v.strip()])
