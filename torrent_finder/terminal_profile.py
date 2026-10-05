"""A Windows Terminal profile that shows the app in its own colours, painting and font.

Terminals draw background pictures; an app cannot. On Windows the app can add
a "torrent-finder" profile to Windows Terminal with a JSON fragment: a folder
Windows Terminal reads when it starts, %LOCALAPPDATA%\\Microsoft\\Windows
Terminal\\Fragments\\torrent-finder. The profile starts the app with the
theme's page and text as its colour scheme, the Athanor painting (recoloured
in the colourway's ink) as its background picture, and the PxPlus IBM VGA
8x16 font, installed for the current user. Nothing is written until the user
asks; afterwards the profile follows their appearance choices, and removing
it deletes the folder. Windows Terminal 1.24 and later load a fragment's
pictures from its own folder; earlier versions show the colours and font
without the picture. See docs/adr/0022-athanor-design.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from torrent_finder import paintings

APP = NAME = "torrent-finder"
FONT_FACE = "PxPlus IBM VGA 8x16"
FONT_FILE = "PxPlus_IBM_VGA_8x16.ttf"
FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
_FONTS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"

# Windows Terminal names fragment profiles by two UUIDv5 steps from its own
# namespace: the app's folder name, then the profile name, both as UTF-16LE.
_TERMINAL_NAMESPACE = uuid.UUID("f65ddb7e-706b-4499-8a50-40313caf510a")


def profile_guid(app: str, name: str) -> str:
    def utf16(text: str) -> str:
        return text.encode("utf-16-le").decode("ascii")
    return "{%s}" % uuid.uuid5(uuid.uuid5(_TERMINAL_NAMESPACE, utf16(app)), utf16(name))


PROFILE_GUID = profile_guid(APP, NAME)

# Windows Terminal's default scheme, for the Simple palettes' named colours.
CAMPBELL = {
    "black": "#0C0C0C", "red": "#C50F1F", "green": "#13A10E", "yellow": "#C19C00",
    "blue": "#0037DA", "magenta": "#881798", "cyan": "#3A96DD", "white": "#CCCCCC",
    "bright_black": "#767676", "bright_red": "#E74856", "bright_green": "#16C60C", "bright_yellow": "#F9F1A5",
    "bright_blue": "#3B78FF", "bright_magenta": "#B4009E", "bright_cyan": "#61D6D6", "bright_white": "#F2F2F2",
}


def supported(environ=None) -> bool:
    """Windows, where Windows Terminal reads fragments from the local app data folder."""
    environ = os.environ if environ is None else environ
    return sys.platform == "win32" and bool(environ.get("LOCALAPPDATA"))


def folder(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    return Path(environ["LOCALAPPDATA"]) / "Microsoft" / "Windows Terminal" / "Fragments" / APP


def fragment_path(environ=None) -> Path:
    return folder(environ) / f"{APP}.json"


def installed(environ=None) -> bool:
    """Whether the user added the profile (its fragment exists)."""
    return supported(environ) and fragment_path(environ).is_file()


def in_profile(environ=None) -> bool:
    """Whether this run is inside the profile's own tab."""
    environ = os.environ if environ is None else environ
    return environ.get("WT_PROFILE_ID", "").casefold() == PROFILE_GUID.casefold()


def command() -> list[str]:
    """How the profile starts the app: this binary, the installed command, or this Python."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    launcher = shutil.which(APP)
    return [launcher] if launcher else [sys.executable, "-m", "torrent_finder"]


def _hex(colour: str, fallback: str) -> str:
    if colour.startswith("#"):
        return colour
    return CAMPBELL.get(colour, fallback)


def scheme(palette) -> dict:
    """A colour scheme with the palette's page and text, and its states where the ANSI colours go."""
    dark = not palette.light
    text = palette.text or ("#CCCCCC" if dark else "#24292F")
    good = _hex(palette.good, CAMPBELL["green"])
    warn = _hex(palette.warn, CAMPBELL["yellow"])
    bad = _hex(palette.bad, CAMPBELL["red"])
    accent = _hex(palette.accent, CAMPBELL["bright_blue"])
    sky = _hex(palette.sky, CAMPBELL["bright_cyan"])
    steel = _hex(palette.steel, CAMPBELL["bright_black"])
    return {
        "name": f"{NAME} {palette.name}",
        "background": palette.page, "foreground": text,
        "cursorColor": accent, "selectionBackground": _hex(palette.deep, CAMPBELL["blue"]),
        "black": _hex(palette.fill, CAMPBELL["black"]), "red": bad, "green": good, "yellow": warn,
        "blue": steel, "purple": CAMPBELL["magenta"], "cyan": sky, "white": text,
        "brightBlack": steel, "brightRed": bad, "brightGreen": good, "brightYellow": accent,
        "brightBlue": sky, "brightPurple": CAMPBELL["bright_magenta"], "brightCyan": sky,
        "brightWhite": sky if dark else "#000000",
    }


def fragment(palette, image: "Path | None", font: bool, launch: list[str], starting: str) -> dict:
    """The fragment: one profile and its colour scheme."""
    colours = scheme(palette)
    profile = {
        "guid": PROFILE_GUID,
        "name": NAME,
        "commandline": subprocess.list2cmdline(launch),
        "startingDirectory": starting,
        "colorScheme": colours["name"],
        "tabTitle": NAME,
    }
    if image:
        # A bare file name: Windows Terminal looks for it beside the fragment.
        profile.update(backgroundImage=image.name, backgroundImageStretchMode="uniform",
                       backgroundImageAlignment="right", backgroundImageOpacity=1.0)
    if font:
        profile.update(font={"face": FONT_FACE, "size": 12}, antialiasingMode="aliased")
    return {"profiles": [profile], "schemes": [colours]}


def font_installed() -> bool:
    """Whether Windows lists the VGA font, for this user or for everyone."""
    try:
        import winreg
    except ImportError:
        return False
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, _FONTS_KEY) as key:
                index = 0
                while True:
                    if winreg.EnumValue(key, index)[0].startswith(FONT_FACE):
                        return True
                    index += 1
        except OSError:
            continue
    return False


def install_font(environ=None) -> Path:
    """Install the bundled font for the current user, as Windows' own Install does."""
    import ctypes
    import winreg
    environ = os.environ if environ is None else environ
    target = Path(environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts" / FONT_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FONTS / FONT_FILE, target)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _FONTS_KEY) as key:
        winreg.SetValueEx(key, f"{FONT_FACE} (TrueType)", 0, winreg.REG_SZ, str(target))
    try:
        ctypes.windll.gdi32.AddFontResourceW(str(target))  # usable now, without signing out
    except (AttributeError, OSError):
        pass
    return target


def write(palette, painting: str, environ=None, *, add_font: bool = False) -> Path:
    """Write (or rewrite) the profile for *palette* and *painting*; returns the fragment's path.

    The painting shows only with an Athanor colourway. With *add_font* the
    font is installed first when Windows does not have it.
    """
    target = folder(environ)
    target.mkdir(parents=True, exist_ok=True)
    if add_font and not font_installed():
        install_font(environ)
    image = None
    if palette.design == "athanor" and painting in paintings.catalog():
        image = paintings.export(painting, palette, target)
    for old in target.glob(f"{APP}-*.png"):
        if old != image:
            old.unlink()  # Windows Terminal caches pictures by path, so each look gets its own file
    launch = command()
    starting = str(Path(__file__).resolve().parent.parent) if launch[1:2] == ["-m"] else "%USERPROFILE%"
    data = fragment(palette, image, font_installed(), launch, starting)
    path = fragment_path(environ)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def remove(environ=None) -> None:
    """Delete the profile's folder; Windows Terminal drops the profile when it next starts."""
    target = folder(environ)
    if target.exists():
        shutil.rmtree(target)
