"""Appearance: the theme, focus style, density and painting, saved per machine.

At startup the theme comes from ``--theme`` (this run only), then the
``TORRENT_FINDER_THEME`` environment variable, then the saved setting, then
Citrinitas (the Athanor design). A theme's design (Athanor or Simple) comes
with it. Focus style, density and the Athanor painting come from the saved
setting; the painting is chosen apart from the colours, which recolour it.
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
DEFAULTS = {"theme": theme.DEFAULT_THEME, "focus": "fill", "density": "comfortable", "painting": paintings.DEFAULT}


def theme_key(name: object) -> str | None:
    """The registered theme a user-typed *name* means: a key or a display name, any case or spacing."""
    if not isinstance(name, str):
        return None
    folded = "".join(name.split()).casefold().replace("-", "").replace("_", "")
    for key, palette in theme.THEMES.items():
        if folded in (key, "".join(palette.name.split()).casefold()):
            return key
    return None


def normalize(value: object) -> dict:
    """A complete, valid appearance dict; anything unknown falls back to its default."""
    value = value if isinstance(value, dict) else {}
    return {
        "theme": theme_key(value.get("theme")) or DEFAULTS["theme"],
        "focus": value.get("focus") if value.get("focus") in theme.FOCUS_STYLES else DEFAULTS["focus"],
        "density": value.get("density") if value.get("density") in theme.DENSITIES else DEFAULTS["density"],
        "painting": paintings.painting_key(value.get("painting")) or DEFAULTS["painting"],
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


_session = {"source": "saved", "painting": DEFAULTS["painting"]}


def apply_startup(cli_theme: str | None = None, environ=None, saved_settings: bool = True) -> str:
    """Apply the startup appearance; returns a notice for the first screen ("" when none).

    Without *saved_settings* the saved appearance is not read (the update
    preview must not load, and so migrate, the settings file).
    """
    appearance, source, notice = resolve(cli_theme, environ, None if saved_settings else DEFAULTS)
    _session["source"] = source
    _session["painting"] = appearance["painting"]
    theme.apply(appearance["theme"], focus=appearance["focus"], density=appearance["density"])
    return notice


def override_source() -> str:
    """``"cli"`` or ``"env"`` when this run's theme overrides the saved one, else ``"saved"``."""
    return _session["source"]


def painting() -> str:
    """The painting this run uses: a catalogue key or ``none``."""
    return _session["painting"]


def save(theme_name: str, focus: str, density: str, painting_name: str | None = None) -> None:
    """Save an explicit appearance choice now; raises ``ValueError``/``OSError`` when that fails.

    Without *painting_name* the current painting is kept.
    """
    from torrent_finder.state import commit_setting
    value = normalize({"theme": theme_name, "focus": focus, "density": density,
                       "painting": painting_name or _session["painting"]})
    commit_setting(SETTING, value)
    _session["source"], _session["painting"] = "saved", value["painting"]


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
                "the painting behind the text (Windows Terminal 1.24 or later) and the PxPlus IBM VGA font, "
                "installed for your account. It follows what you choose here.")
PROFILE_NOTE = "This tab is the torrent-finder profile: its background follows the theme after a restart."


def _painting_help() -> str:
    return PROFILE_PAINTING_HELP if terminal_profile.supported() else PAINTING_HELP


def _painting_rows(chosen: str) -> list:
    """The Painting section's rows: every engraving, then none."""
    rows = []
    for key, entry in paintings.catalog().items():
        rows.append(_choice(entry.title, ("painting", key), key == chosen, f"{entry.artist}, {entry.year}",
                            f"{entry.credit}; public domain. Recoloured in the colourway's ink. {_painting_help()}"))
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
    chosen = {"theme": palette.key, "focus": focus, "density": density, "painting": painting()}
    state = {"preview": palette.key, "notice": ""}

    def design_of(key: str) -> str:
        return theme.THEMES[key].design

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
            items += _painting_rows(chosen["painting"])
            if chosen["painting"] != paintings.NONE:
                items.append(SelectItem("Save the painting as an image", ("export", None), is_action=True,
                                        hint=f"a PNG in the {theme.THEMES[state['preview']].name} colours",
                                        description=f"Into {paintings.export_folder()}. {PAINTING_HELP}"))
        items.append(_section("Focus"))
        for key, label in theme.FOCUS_STYLES.items():
            items.append(_choice(label, ("focus", key), key == chosen["focus"], _focus_hint(key), _FOCUS_HELP[key]))
        items.append(_section("Density"))
        for key, label in theme.DENSITIES.items():
            items.append(_choice(label, ("density", key), key == chosen["density"], _DENSITY_HINTS[key],
                                 _DENSITY_HELP[key]))
        if terminal_profile.supported():
            items.append(_section("Windows Terminal"))
            if terminal_profile.installed():
                items.append(SelectItem("Remove the torrent-finder profile", ("profile", "remove"), is_action=True,
                                        hint="it follows the choices above",
                                        description=f"{PROFILE_HELP} Removing it deletes "
                                                    f"{terminal_profile.folder()}; the font stays installed."))
            else:
                items.append(SelectItem("Add a torrent-finder profile", ("profile", "add"), is_action=True,
                                        hint="the painting behind the app", description=PROFILE_HELP))
        items.append(SelectItem("Back", None, is_action=True))
        return items

    def persist(kind: str) -> None:
        try:
            save(chosen["theme"], chosen["focus"], chosen["density"], chosen["painting"])
            state["notice"] = ""
        except (OSError, ValueError) as error:
            state["notice"] = f"[error]Applied for this session, but not saved:[/error] {escape(str(error))}"
            return
        if kind in ("design", "theme", "painting") and terminal_profile.installed():
            try:
                terminal_profile.write(theme.THEMES[chosen["theme"]], chosen["painting"])
                state["notice"] = "The Windows Terminal profile follows; it changes when Windows Terminal restarts."
            except OSError as error:
                state["notice"] = f"[error]The Windows Terminal profile was not updated:[/error] {escape(str(error))}"

    def add_profile() -> None:
        from torrent_finder.ui.prompts import confirm_prompt
        palette = theme.THEMES[chosen["theme"]]
        shown = paintings.catalog().get(chosen["painting"]) if palette.design == "athanor" else None
        parts = [f"the {palette.name} colours"] + ([f"{escape(shown.title)} behind the text"] if shown else [])
        if not terminal_profile.font_installed():
            parts.append("the PxPlus IBM VGA 8x16 font, installed for your account")
        listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
        message = ("Add a [bold]torrent-finder[/bold] profile to Windows Terminal?\n\n"
                   f"It opens the app with {listed}. It appears when Windows Terminal restarts.")
        if not confirm_prompt(message, title="Windows Terminal profile"):
            return
        try:
            terminal_profile.write(palette, chosen["painting"], add_font=True)
            state["notice"] = ("[good]Added[/good] the torrent-finder profile: restart Windows Terminal, "
                               "then open it from the ▾ menu next to the tabs.")
        except OSError as error:
            state["notice"] = f"[error]The profile was not added:[/error] {escape(str(error))}"

    def remove_profile() -> None:
        try:
            terminal_profile.remove()
            state["notice"] = "Removed the torrent-finder profile; Windows Terminal drops it when it restarts."
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
