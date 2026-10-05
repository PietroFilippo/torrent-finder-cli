"""Appearance: the theme, focus style, density and painting, saved per machine.

At startup the theme comes from ``--theme`` (this run only), then the
``TORRENT_FINDER_THEME`` environment variable, then the saved setting, then
Citrinitas (the Athanor design). A theme's design (Athanor or Simple) comes
with it. Focus style, density and the Athanor painting come from the saved
setting; the painting is chosen apart from the colours, which recolour it.
Each design also keeps the font and text size of the Windows Terminal
profile, so switching designs switches fonts that suit them.
The Settings › Appearance screen previews a theme in place and saves the
choice. See docs/adr/0021-themes.md and docs/adr/0022-athanor-design.md.
"""

from __future__ import annotations

import os
import sys

from rich.text import Text

from torrent_finder import paintings, terminal_profile
from torrent_finder.ui import theme

SETTING = "appearance"
ENV = "TORRENT_FINDER_THEME"
DEFAULT_FONTS = {design: {"font": terminal_profile.default_font(design).key,
                           "size": terminal_profile.default_font(design).default_size}
                 for design in theme.DESIGNS}
# The Windows Terminal profile: Athanor's full look (page, painting, pixel font) or a plain one (Windows
# Terminal's own page and font, as in any other tab), and whether the command opens the profile's tab.
LOOKS = ("full", "plain")
DEFAULT_PROFILE = {"look": "full", "open_from_tabs": False}
DEFAULTS = {"theme": theme.DEFAULT_THEME, "focus": "fill", "density": "comfortable", "painting": paintings.DEFAULT,
            "fonts": DEFAULT_FONTS, "profile": DEFAULT_PROFILE}


def theme_key(name: object) -> str | None:
    """The registered theme a user-typed *name* means: a key or a display name, any case or spacing."""
    if not isinstance(name, str):
        return None
    folded = "".join(name.split()).casefold().replace("-", "").replace("_", "")
    for key, palette in theme.THEMES.items():
        if folded in (key, "".join(palette.name.split()).casefold()):
            return key
    return None


def _font_choice(design: str, value: object) -> dict:
    """A valid {"font", "size"} for *design*: a font that suits it, at one of that font's sizes."""
    value = value if isinstance(value, dict) else {}
    font = terminal_profile.FONTS.get(value.get("font"))
    if font is None or font.design != design:
        font = terminal_profile.default_font(design)
    size = value.get("size")
    return {"font": font.key, "size": size if size in font.sizes else font.default_size}


def normalize(value: object) -> dict:
    """A complete, valid appearance dict; anything unknown falls back to its default."""
    value = value if isinstance(value, dict) else {}
    fonts = value.get("fonts") if isinstance(value.get("fonts"), dict) else {}
    profile = value.get("profile") if isinstance(value.get("profile"), dict) else {}
    return {
        "theme": theme_key(value.get("theme")) or DEFAULTS["theme"],
        "focus": value.get("focus") if value.get("focus") in theme.FOCUS_STYLES else DEFAULTS["focus"],
        "density": value.get("density") if value.get("density") in theme.DENSITIES else DEFAULTS["density"],
        "painting": paintings.painting_key(value.get("painting")) or DEFAULTS["painting"],
        "fonts": {design: _font_choice(design, fonts.get(design)) for design in theme.DESIGNS},
        "profile": {"look": profile.get("look") if profile.get("look") in LOOKS else DEFAULT_PROFILE["look"],
                    "open_from_tabs": profile.get("open_from_tabs") is True},
    }


def saved() -> dict:
    """The saved appearance, or the defaults when nothing (valid) is saved or settings are unreadable."""
    try:
        from torrent_finder.state import load_setting
        return normalize(load_setting(SETTING, None))
    except Exception:  # an unreadable store must never stop the app from drawing
        return dict(DEFAULTS)


def env_theme(environ=None) -> tuple[str | None, str]:
    """The theme the environment asks for, and a notice when its value names no theme."""
    raw = (os.environ if environ is None else environ).get(ENV, "")
    if not raw.strip():
        return None, ""
    key = theme_key(raw)
    if key is None:
        names = ", ".join(theme.THEMES)
        return None, f"{ENV}={raw.strip()} is not a theme ({names}); using the saved theme."
    return key, ""


def resolve(cli_theme: str | None = None, environ=None, base: dict | None = None) -> tuple[dict, str, str]:
    """The appearance to start with, where its theme came from, and any notice.

    The source is ``"cli"``, ``"env"`` or ``"saved"``. *base* replaces the
    saved appearance (which is then not read).
    """
    appearance = dict(base) if base is not None else saved()
    key, notice = env_theme(environ)
    source = "saved"
    if key:
        appearance["theme"], source = key, "env"
    cli_key = theme_key(cli_theme) if cli_theme else None
    if cli_key:
        appearance["theme"], source = cli_key, "cli"
    return appearance, source, notice


_session = {"source": "saved", "painting": DEFAULTS["painting"], "fonts": DEFAULT_FONTS, "profile": DEFAULT_PROFILE}


def apply_startup(cli_theme: str | None = None, environ=None, saved_settings: bool = True) -> str:
    """Apply the startup appearance; returns a notice for the first screen ("" when none).

    Without *saved_settings* the saved appearance is not read (the update
    preview must not load, and so migrate, the settings file).
    """
    appearance, source, notice = resolve(cli_theme, environ, None if saved_settings else DEFAULTS)
    _session["source"] = source
    _session["painting"] = appearance["painting"]
    _session["fonts"] = appearance["fonts"]
    _session["profile"] = appearance["profile"]
    theme.apply(appearance["theme"], focus=appearance["focus"], density=appearance["density"])
    return notice


def override_source() -> str:
    """``"cli"`` or ``"env"`` when this run's theme overrides the saved one, else ``"saved"``."""
    return _session["source"]


def painting() -> str:
    """The painting this run uses: a catalogue key or ``none``."""
    return _session["painting"]


def font(design: str | None = None) -> tuple["terminal_profile.Font", float]:
    """The Windows Terminal profile's font for *design* (the current one by default) and its size."""
    design = design or theme.PALETTE.design
    choice = _font_choice(design, _session["fonts"].get(design))
    return terminal_profile.FONTS[choice["font"]], choice["size"]


def profile_look(design: str | None = None) -> str:
    """``"plain"`` when the profile shows *design* (the current one) on Windows Terminal's own page and font."""
    design = design or theme.PALETTE.design
    return _session["profile"]["look"] if design == "athanor" else "full"


def open_from_tabs() -> bool:
    """Whether the command, typed in another Windows Terminal tab, opens the app in the profile's tab."""
    return _session["profile"]["open_from_tabs"]


def save(theme_name: str, focus: str, density: str, painting_name: str | None = None,
         fonts: dict | None = None, profile: dict | None = None) -> None:
    """Save an explicit appearance choice now; raises ``ValueError``/``OSError`` when that fails.

    Without *painting_name* the current painting is kept, without *fonts* and *profile* the current ones.
    """
    from torrent_finder.state import commit_setting
    value = normalize({"theme": theme_name, "focus": focus, "density": density,
                       "painting": painting_name or _session["painting"], "fonts": fonts or _session["fonts"],
                       "profile": profile or _session["profile"]})
    _session["painting"] = value["painting"]  # in use this session even if saving fails
    _session["fonts"] = value["fonts"]
    _session["profile"] = value["profile"]
    commit_setting(SETTING, value)
    _session["source"] = "saved"


def _swatches(palette) -> Text:
    """The palette's four shades as blocks, then sample words in its own colours."""
    hint = Text()
    for shade in (palette.accent, palette.sky, palette.steel, palette.deep):
        hint.append(theme.BAR * 2, style=shade)
        hint.append(" ")
    hint.append(" Heading", style=f"bold {palette.sky}")
    hint.append(" · ", style=palette.steel)
    hint.append("On", style=palette.good)
    hint.append(" ")
    hint.append("Auto", style=palette.warn)
    hint.append(" ")
    hint.append("Off", style=palette.steel)
    return hint


# Themes colour text, rules and the focused row; the page itself is the
# terminal's, and an app cannot change it, so a light theme needs a light
# terminal colour scheme.
BACKGROUND_NOTE = "Themes colour the text; the background is your terminal's own."


def light_scheme_help(platform: str | None = None) -> str:
    """Where to switch the terminal to a light colour scheme, for the light theme."""
    platform = platform or sys.platform
    if platform == "win32":
        return ("Windows Terminal: Ctrl+, › profile › Appearance › Color scheme. "
                "Classic window: title bar › Properties › Colors.")
    if platform == "darwin":
        return "Terminal: Settings › Profiles. iTerm2: Settings › Profiles › Colors."
    return "Your terminal's preferences hold its colour schemes."


def _theme_help(palette) -> str:
    """A theme row's description: its note, and for a light theme where to make the terminal light."""
    return f"{palette.note} {light_scheme_help()}" if palette.light else palette.note


def _focus_hint(key: str) -> str:
    return f"{theme.CURSOR} beside the focused row" if key == "bar" else "the focused row on a tint"


_FOCUS_HELP = {
    "bar": "A mark in the gutter and bold text show the focused row.",
    "fill": "The focused row also gets a tinted background across the screen; easier to follow in long lists.",
}
_DENSITY_HINTS = {"comfortable": "rules and spacing when there is room", "compact": "more rows in every window"}
_DENSITY_HELP = {
    "comfortable": "Rules, spacer lines and (in Athanor) the message and status lines whenever the window has room.",
    "compact": "The short-window layout at every size: no rules, spacer, message or status lines, so lists show more rows.",
}
_DESIGN_HINTS = {"athanor": "frame · message and status lines · painting", "simple": "header line · rules · no frame"}

# Where a painting shows: terminals draw background pictures, apps cannot.
PAINTING_HELP = "Set the saved image as your terminal's background picture to see it behind the app."
PROFILE_PAINTING_HELP = "The Windows Terminal profile (at the end of this list) shows it behind the app."
PROFILE_HELP = ("A torrent-finder profile in Windows Terminal opens the app on the theme's own page: its colours, "
                "the painting behind the text (Windows Terminal 1.24 or later), and the font and text size chosen "
                "above, with the pixel fonts installed for your account. It follows what you choose here.")
PROFILE_NOTE = "This tab is the torrent-finder profile: its page, painting and font follow what you choose here."
# What a change does to Windows Terminal: at once when a running one could be told, else at its next start.
FOLLOWS_NOW = "The Windows Terminal profile follows."
FOLLOWS_LATER = "The Windows Terminal profile follows; it changes when Windows Terminal restarts."
# An open tab only finds fonts installed before it first drew.
NEW_FONTS = "Installed the pixel fonts for your account: a tab opened before now shows them once you open a new one."
FONT_SAVED = "Saved. The torrent-finder profile uses it: add it at the end of this list."
FONT_HELP = "The torrent-finder profile in Windows Terminal draws the app in it; other terminals keep their own font."
LOOK_HINTS = {"full": "the colourway's page, the painting, a pixel font",
              "plain": "Windows Terminal's own page and font"}
LOOK_HELP = {
    "full": "The profile shows Athanor on its colourway's page, with the painting behind the text and the font "
            "and text size chosen above.",
    "plain": "The profile shows Athanor as any other tab does: the frame and colours on Windows Terminal's own "
             "page and font, without the painting.",
}
OPEN_HELP = ("When you type the command in another Windows Terminal tab, the app opens in a torrent-finder tab of "
             "the same window, with its look, and the other tab gets its prompt back. Windows Terminal keeps "
             "pictures and fonts in profiles, and a running program cannot change them in its own tab.")
SIZE_HELP = ("How large the profile draws text. Larger text fills a big window with fewer, bigger rows; "
             "whole multiples keep pixel letters sharp at 100% display scaling.")


def _font_hint(option) -> str:
    if option.pixel:
        return f"{option.cell[0]}×{option.cell[1]} pixels"
    return "Windows Terminal's" if option.face.startswith("Cascadia") else "Windows'"


def _font_help(option) -> str:
    install = " Installed for your account when chosen." if not terminal_profile.font_installed(option) else ""
    return f"{option.note} {FONT_HELP}{install}"


def _size_hint(option, size) -> str:
    if option.pixel:  # half sizes draw font pixels one and two screen pixels wide by turns
        return "sharp" if float(size).is_integer() else "uneven pixels"
    return "Windows Terminal's default" if size == 12 else ""


PLAIN_PAINTING_HELP = "The profile's plain look leaves it out; its full look (at the end of this list) shows it."


def _painting_help(plain: bool = False) -> str:
    if not terminal_profile.supported():
        return PAINTING_HELP
    return PLAIN_PAINTING_HELP if plain else PROFILE_PAINTING_HELP


def _painting_rows(chosen: str, plain: bool = False) -> list:
    """The Painting section's rows: every engraving, then none."""
    rows = []
    for key, entry in paintings.catalog().items():
        rows.append(_choice(entry.title, ("painting", key), key == chosen, f"{entry.artist}, {entry.year}",
                            f"{entry.credit}; public domain. Recoloured in the colourway's ink. {_painting_help(plain)}"))
    rows.append(_choice("None", ("painting", paintings.NONE), chosen == paintings.NONE, "a plain page",
                        "No painting behind the app."))
    return rows


def _choice(label, value, chosen: bool, hint="", description=""):
    from torrent_finder.ui.selector import SelectItem
    return SelectItem(label, value, hint=hint, is_action=True, description=description,
                      marker="●" if chosen else "○", marker_style="" if chosen else theme.MUTED)


def _section(label: str):
    from torrent_finder.ui.selector import SelectItem
    return SelectItem(f"─── {label} ───", "section_header", enabled=False, is_action=True)


def appearance_menu() -> None:
    """Settings › Appearance: the design, its colours, its painting, the focus style and the density.

    Athanor and Simple are designs; each has its own colours, and Athanor a
    painting chosen apart from them. Space previews a design or a colourway
    in place; Enter applies a choice and saves it for later runs; Esc leaves,
    putting back what was applied when the screen opened if a preview was
    showing.
    """
    from rich.markup import escape

    from torrent_finder.ui.selector import SelectItem, arrow_select

    palette, focus, density = theme.current()
    chosen = {"theme": palette.key, "focus": focus, "density": density, "painting": painting(),
              "fonts": {design: dict(choice) for design, choice in _session["fonts"].items()},
              "profile": dict(_session["profile"])}
    state = {"preview": palette.key, "notice": ""}

    def design_of(key: str) -> str:
        return theme.THEMES[key].design

    def chosen_font(design: str):
        choice = _font_choice(design, chosen["fonts"].get(design))
        return terminal_profile.FONTS[choice["font"]], choice["size"]

    def plain(design: str) -> bool:
        return design == "athanor" and chosen["profile"]["look"] == "plain"

    def build() -> list:
        design = design_of(state["preview"])
        items = [_section("Design")]
        for key, option in theme.DESIGNS.items():
            items.append(_choice(option.name, ("design", key), key == design_of(chosen["theme"]),
                                 _DESIGN_HINTS[key], option.note))
        items.append(_section(f"{theme.DESIGNS[design].name} colours"))
        for option in theme.palettes(design):
            items.append(_choice(option.name, ("theme", option.key), option.key == chosen["theme"],
                                 _swatches(option), _theme_help(option)))
        if design == "athanor" and paintings.catalog():
            items.append(_section("Painting"))
            items += _painting_rows(chosen["painting"], plain(design))
            if chosen["painting"] != paintings.NONE:
                items.append(SelectItem("Save the painting as an image", ("export", None), is_action=True,
                                        hint=f"a PNG in the {theme.THEMES[state['preview']].name} colours",
                                        description=f"Into {paintings.export_folder()}. {PAINTING_HELP}"))
        # The app sets a font only through the Windows Terminal profile, and the plain look keeps its own.
        if terminal_profile.supported() and not plain(design):
            current, size = chosen_font(design)
            items.append(_section("Font"))
            for option in terminal_profile.fonts(design):
                items.append(_choice(option.face, ("font", option.key), option.key == current.key,
                                     _font_hint(option), _font_help(option)))
            items.append(_section("Text size"))
            for value in current.sizes:
                items.append(_choice(current.size_label(value), ("size", value), value == size,
                                     _size_hint(current, value), SIZE_HELP))
        items.append(_section("Focus"))
        for key, label in theme.FOCUS_STYLES.items():
            items.append(_choice(label, ("focus", key), key == chosen["focus"], _focus_hint(key), _FOCUS_HELP[key]))
        items.append(_section("Density"))
        for key, label in theme.DENSITIES.items():
            items.append(_choice(label, ("density", key), key == chosen["density"], _DENSITY_HINTS[key],
                                 _DENSITY_HELP[key]))
        if terminal_profile.supported():
            items.append(_section("Windows Terminal"))
            if design == "athanor":
                for key in LOOKS:
                    items.append(_choice(f"{key.capitalize()} look", ("look", key), key == chosen["profile"]["look"],
                                         LOOK_HINTS[key], LOOK_HELP[key]))
            if terminal_profile.installed():
                opening = chosen["profile"]["open_from_tabs"]
                items.append(SelectItem("Open from other tabs", ("open", not opening), is_action=True,
                                        hint=Text("On" if opening else "Off",
                                                  style=theme.state_style("On" if opening else "Off")),
                                        description=OPEN_HELP))
                items.append(SelectItem("Remove the torrent-finder profile", ("profile", "remove"), is_action=True,
                                        hint="it follows the choices above",
                                        description=f"{PROFILE_HELP} Removing it deletes "
                                                    f"{terminal_profile.folder()}; the fonts stay installed."))
            else:
                items.append(SelectItem("Add a torrent-finder profile", ("profile", "add"), is_action=True,
                                        hint="the painting behind the app", description=PROFILE_HELP))
        items.append(SelectItem("Back", None, is_action=True))
        return items

    def persist(kind: str) -> None:
        try:
            save(chosen["theme"], chosen["focus"], chosen["density"], chosen["painting"], chosen["fonts"],
                 chosen["profile"])
            state["notice"] = ""
        except (OSError, ValueError) as error:
            state["notice"] = f"[error]Applied for this session, but not saved:[/error] {escape(str(error))}"
            return
        if kind not in ("design", "theme", "painting", "font", "size", "look"):
            return
        if not terminal_profile.installed():
            state["notice"] = FONT_SAVED if kind in ("font", "size") else ""
            return
        try:
            installed = terminal_profile.install_fonts() if kind == "font" else []
            current, size = chosen_font(design_of(chosen["theme"]))
            terminal_profile.write(theme.THEMES[chosen["theme"]], chosen["painting"], font=current, size=size,
                                   plain=plain(design_of(chosen["theme"])))
            state["notice"] = FOLLOWS_NOW if terminal_profile.refresh() else FOLLOWS_LATER
            if installed:
                state["notice"] += " " + NEW_FONTS
        except OSError as error:
            state["notice"] = f"[error]The Windows Terminal profile was not updated:[/error] {escape(str(error))}"

    def add_profile() -> None:
        from torrent_finder.ui.prompts import confirm_prompt
        palette = theme.THEMES[chosen["theme"]]
        shown = paintings.catalog().get(chosen["painting"]) if palette.design == "athanor" else None
        parts = [f"the {palette.name} colours"] + ([f"{escape(shown.title)} behind the text"] if shown else [])
        current, size = chosen_font(palette.design)
        parts.append(f"{current.face} at {current.size_label(size)}")
        if plain(palette.design):
            parts = [f"the {palette.name} colours on Windows Terminal's own page and font"]
        if terminal_profile.missing_fonts():
            parts.append("the PxPlus pixel fonts installed for your account")
        listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
        message = ("Add a [bold]torrent-finder[/bold] profile to Windows Terminal?\n\n"
                   f"It opens the app with {listed}, from the ▾ menu next to the tabs.")
        if not confirm_prompt(message, title="Windows Terminal profile"):
            return
        try:
            terminal_profile.write(palette, chosen["painting"], font=current, size=size, add_font=True,
                                   plain=plain(palette.design))
            if terminal_profile.refresh():
                state["notice"] = "[good]Added[/good] the torrent-finder profile: open it from the ▾ menu next to the tabs."
            else:
                state["notice"] = ("[good]Added[/good] the torrent-finder profile: restart Windows Terminal, "
                                   "then open it from the ▾ menu next to the tabs.")
        except OSError as error:
            state["notice"] = f"[error]The profile was not added:[/error] {escape(str(error))}"

    def remove_profile() -> None:
        try:
            terminal_profile.remove()
            state["notice"] = ("Removed the torrent-finder profile." if terminal_profile.refresh() else
                               "Removed the torrent-finder profile; Windows Terminal drops it when it restarts.")
        except OSError as error:
            state["notice"] = f"[error]The profile was not removed:[/error] {escape(str(error))}"

    def target(value) -> str:
        """The palette a design or colourway row stands for."""
        kind, key = value
        if kind == "design":
            # Choosing the design you are in keeps its colourway; another design starts on its default.
            return chosen["theme"] if design_of(chosen["theme"]) == key else theme.DEFAULT_THEMES[key]
        return key

    def choose(index: int, items: list) -> bool:
        value = items[index].value
        if value is None:
            return False  # Back
        kind, key = value
        if kind == "export":
            export_painting()
            return True
        if kind == "profile":
            if key == "add":
                add_profile()
            else:
                remove_profile()
            items[:] = build()
            return True
        if kind in ("design", "theme"):
            chosen["theme"] = state["preview"] = target(value)
        elif kind == "look":
            chosen["profile"]["look"] = key
        elif kind == "open":
            chosen["profile"]["open_from_tabs"] = key
        elif kind in ("font", "size"):
            design = design_of(state["preview"])  # the sections show the design on screen
            current, size = chosen_font(design)
            if kind == "font":
                chosen["fonts"][design] = _font_choice(design, {"font": key, "size": size})
            else:
                chosen["fonts"][design] = {"font": current.key, "size": key}
        else:
            chosen[kind] = key
        theme.apply(chosen["theme"], focus=chosen["focus"], density=chosen["density"])
        persist(kind)
        items[:] = build()  # markers move; a new design brings its own colours
        return True  # stay: the screen redraws in the new appearance

    def export_painting() -> None:
        """Save the chosen painting in the colours on screen."""
        try:
            path = paintings.export(chosen["painting"], theme.THEMES[state["preview"]], paintings.export_folder())
            state["notice"] = f"[good]Saved[/good] {escape(path.name)} in {escape(str(path.parent))}"
        except (OSError, ValueError, KeyError) as error:
            state["notice"] = f"[error]The painting was not saved:[/error] {escape(str(error))}"

    def preview(index: int, items: list) -> bool:
        value = items[index].value
        if not value:
            return True
        if value[0] not in ("design", "theme"):
            return choose(index, items)
        state["preview"] = target(value)
        theme.apply(state["preview"])
        items[:] = build()
        return True

    def status() -> str:
        shown = theme.THEMES[state["preview"]]
        label = f"{theme.DESIGNS[shown.design].name} · {shown.name}"
        return f"previewing {label}" if state["preview"] != chosen["theme"] else f"using {label}"

    def footer() -> str:
        lines = []
        if state["notice"]:
            lines.append(state["notice"])
        source = override_source()
        if source == "env":
            lines.append(f"{ENV} chooses the theme at startup; the saved theme applies when it is unset.")
        elif source == "cli":
            lines.append("This run uses --theme; the saved theme applies to later runs.")
        lines.append(PROFILE_NOTE if terminal_profile.in_profile() else BACKGROUND_NOTE)
        lines.append("↑/↓ navigate  •  Enter apply  •  Space preview  •  Esc back")
        return "\n".join(lines)

    items = build()
    start = next(i for i, item in enumerate(items) if item.value == ("theme", chosen["theme"]))
    try:
        arrow_select(items, title="Settings › Appearance", status=status, footer=footer,
                     start_index=start, on_action=choose, key_actions={" ": preview})
    finally:
        if state["preview"] != chosen["theme"]:
            theme.apply(chosen["theme"])  # leaving during a preview (Esc or Back): the applied theme returns
