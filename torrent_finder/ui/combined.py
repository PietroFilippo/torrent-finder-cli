"""Transactional settings for search across providers."""

from torrent_finder.i18n import N_, t, tn

# i18n: converted

from torrent_finder.search_profiles import profile_label
from torrent_finder.providers.combined_provider import CombinedProvider, provider_display_label
from torrent_finder.ui.selector import SelectItem, arrow_select
from torrent_finder.result_view import SORT_ORDERS
from torrent_finder.ui.result_filters import choose_result_sort


_SHARED_HELP = {
    "include_keywords": N_(
        "Keep only results whose name contains at least one of these phrases, from ANY selected provider. "
        "Example: batch, volume keeps names containing batch OR volume. Matching ignores letter case. "
        "Empty means no include restriction."
    ),
    "exclude_keywords": N_(
        "Hide results whose name contains any of these phrases, from ANY selected provider. "
        "Example: sample, trailer hides either word. Matching ignores letter case. "
        "An exclusion wins even if an include phrase matches. Empty excludes nothing."
    ),
}


def _shared_filter_screen(action):
    from rich.markup import escape
    from torrent_finder.ui.prompts import input_screen
    return input_screen(
        t("Name filters for all selected providers"),
        escape(t(_SHARED_HELP[action])),
        t("These filter returned names; they do not add words to your search. "
        "Provider presets still apply. For Anime-only 1080p, use Provider engines and presets."),
        keys=t("Enter save this draft field  •  Esc cancel"),
    )


def _choose_providers(draft):
    from torrent_finder.ui.prompts import _make_banner_panel
    items = [
        SelectItem(provider_display_label(p), p.slug, toggled=p.slug in draft.selected_slugs,
                   description=t(p.search_note))
        for p in draft.children
    ]
    count = len(items)
    items += [SelectItem(t("Use this selection"), "save", is_action=True, hint="w"),
              SelectItem(t("Cancel"), "cancel", is_action=True)]

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
        items, title=t("Choose providers"), multi=True, banner=_make_banner_panel(),
        footer=t("Space/Enter toggle • a all • c none • w confirm • Esc cancel"),
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
            SelectItem(provider_display_label(p), p, is_action=True,
                       hint=(t("included") if p.slug in draft.selected_slugs else t("excluded"))
                       + " · " + p.filter_summary_label())
            for p in draft.children
        ]
        items.append(SelectItem(t("Back"), None, is_action=True))
        chosen = arrow_select(items, title=t("Provider engines and presets"),
                              banner=_make_banner_panel(), footer=t("Enter configure • Esc back"))
        if chosen is None or items[chosen].value is None:
            return
        # The outer menu owns persistence; Cancel discards every draft edit.
        filter_menu(items[chosen].value, on_save=lambda: None)


def _profile_name(library, *, rename=False):
    from rich.markup import escape
    from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut, input_screen
    error = ""
    initial = library.current["name"] if rename else ""
    while True:
        render = input_screen(
            t("Rename profile") if rename else t("Save a copy as a new profile"),
            t("Use a unique name (1–60 characters). Changes stay in the draft until Save and return."),
            f"[bad]{escape(error)}[/bad]" if error else "",
            keys=t("Enter confirm  •  Esc cancel"),
        )
        value = get_query_with_shortcut(PROMPT, initial=initial, screen_renderer=render)
        if not isinstance(value, str) or value == "GO_BACK":
            return None
        try:
            return library.validate_name(value, library.current["id"] if rename else None)
        except ValueError as problem:
            error, initial = str(problem), value


def _manage_profiles(draft, library):
    from rich.markup import escape
    from torrent_finder.ui.prompts import _make_banner_panel, confirm_prompt
    library.update(draft.snapshot())
    items = [SelectItem(profile_label(entry), ("select", entry["id"]),
                        hint=t("current") if entry["id"] == library.current["id"] else "",
                        description=t("Use this profile. Draft edits are kept until you save or cancel the settings menu."))
             for entry in library.entries]
    items.extend([
        SelectItem(t("Save a copy as a new profile…"), ("copy", None)),
        SelectItem(t("Rename current profile…"), ("rename", None)),
        SelectItem(t("Delete current profile…"), ("delete", None), enabled=len(library.entries) > 1,
                   description=t("Keep at least one profile. Deletion takes effect only after Save and return.")),
        SelectItem(t("Back"), ("back", None)),
    ])
    selected = arrow_select(items, title=t("Search profiles"), banner=_make_banner_panel(),
                            footer=t("Enter choose • Esc back • Changes remain a draft"))
    if selected is None:
        return
    action, identity = items[selected].value
    if action == "select":
        library.select(identity)
    elif action in ("copy", "rename"):
        name = _profile_name(library, rename=action == "rename")
        if name is None:
            return
        if action == "copy":
            library.create(name, draft.snapshot())
        else:
            library.rename(library.current["id"], name)
    elif action == "delete":
        if not confirm_prompt(t("Delete profile '{profile}'?", profile=escape(profile_label(library.current))), title=t("Delete profile")):
            return
        library.delete(library.current["id"])
    else:
        return
    draft.use_profile(library.current)


def combined_filter_menu(provider):
    from torrent_finder.ui.prompts import PROMPT, _make_banner_panel, get_query_with_shortcut
    from rich.markup import escape
    library = provider.profile_draft()
    draft = CombinedProvider(provider.templates)
    draft.use_profile(library.current)
    error = ""
    while True:
        items = [
            SelectItem(t("Profile: {profile}…", profile=draft.profile_label), "profiles", enabled=bool(draft.selected_slugs),
                       description=t("Switch, copy, rename or delete a saved setup. A profile can select one or several providers. Select at least one provider first.")),
            SelectItem(tn("Providers: {n} selected", "Providers: {n} selected", len(draft.selected_slugs)), "providers"),
            SelectItem(t("All providers: include name phrases…"), "include_keywords",
                       hint=", ".join(draft.shared_filters.include_keywords) or t("any name"),
                       description=t("Keep names matching any listed phrase. Enter for examples and editing. Empty allows any name.")),
            SelectItem(t("All providers: exclude name phrases…"), "exclude_keywords",
                       hint=", ".join(draft.shared_filters.exclude_keywords) or t("none", ctx="keywords"),
                       description=t("Hide names matching any listed phrase, even if included. Enter for examples and editing.")),
            SelectItem(t("Provider engines and presets…"), "configure",
                       description=t("Each provider keeps its own settings. Resolution and language presets stay scoped to that provider.")),
            SelectItem(t("All providers: literal name rules…"), "rules",
                       hint=draft.name_rules.summary_label() or t("off", ctx="name rule"),
                       description=t("All words / any word / exact phrase / exclusions. Applies together with existing phrase rules.")),
            SelectItem(t("Result order: {order}", order=t(SORT_ORDERS[draft.result_sort])), "sort",
                       description=t("Saved in this profile. Recommended uses title relevance, then preferences. Other sorts override ranking; required filters still apply.")),
            SelectItem(t("Save and return"), "save", enabled=bool(draft.selected_slugs), hint="w",
                       description=t("Select at least one provider to save.") if not draft.selected_slugs else ""),
            SelectItem(t("Cancel"), "cancel"),
        ]
        save_index = next(i for i, item in enumerate(items) if item.value == "save")
        chosen = arrow_select(
            items, title=t("Filters › Search across providers"), banner=_make_banner_panel(),
            footer=(escape(error) + "\n" if error else "") + t("Enter choose • w save all profiles • Esc discard changes"),
            key_actions={"w": lambda *_: save_index if draft.selected_slugs else True,
                         "W": lambda *_: save_index if draft.selected_slugs else True},
        )
        if chosen is None or items[chosen].value == "cancel":
            return
        action = items[chosen].value
        if action == "providers":
            _choose_providers(draft)
        elif action == "profiles":
            _manage_profiles(draft, library)
        elif action == "sort":
            draft.result_sort = choose_result_sort(draft.result_sort)
        elif action == "configure":
            _configure_provider(draft)
        elif action == "rules":
            from torrent_finder.ui.name_rules import edit_name_rules
            draft.name_rules = edit_name_rules(draft.name_rules)
        elif action == "save":
            try:
                draft.save_profile(library)
            except (OSError, ValueError) as problem:
                error = str(problem)  # the draft stays open; w retries
                continue
            provider.use_profile(library.current)
            return
        else:
            previous = ", ".join(getattr(draft.shared_filters, action))
            value = get_query_with_shortcut(PROMPT, initial=previous,
                                            screen_renderer=_shared_filter_screen(action))
            if isinstance(value, str) and value != "GO_BACK":
                setattr(draft.shared_filters, action, [v.strip() for v in value.split(",") if v.strip()])
