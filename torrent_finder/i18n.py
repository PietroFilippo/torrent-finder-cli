"""Interface languages: the English text is the key, looked up when a screen draws.

Code keeps writing English and asks for it in the interface language:
``t("Back")``, ``t("Saved {name}", name=path.name)``, ``tn("{n} result", "{n} results", count)``.
A message has no ID besides its text, plus a context (``ctx``) for the rare
English words two screens translate differently; a missing translation shows
the English. Catalogues are JSON files in ``assets/locales/<code>/``, and every
file in a language's folder is merged, so translators can each own a file.

Nothing is translated at import time. Text defined in a module or class body
is marked with ``N_()`` (so ``scripts/i18n.py`` finds it) and passed to ``t()``
when drawn, so switching language at run time works: the rule the theme
follows ("read theme.X at render time").

The language comes from ``--lang``, then ``TORRENT_FINDER_LANG``, then the
saved ``settings.language``, then the system's display language (not its
regional format), then English. ``qps`` is a pseudo-locale for development:
every message bracketed, accented and padded, so a capture shows unconverted
text and overflow. Standard library only, and nothing from the app, so any
module may import it. See docs/adr/0028-interface-languages.md.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

LOCALES = Path(__file__).resolve().parent / "assets" / "locales"
ENV = "TORRENT_FINDER_LANG"
SETTING = "language"  # settings.language: "auto", or a code from LANGUAGES; missing means auto
AUTO = "auto"
DEFAULT = "en"
PSEUDO = "qps"
# Shipped languages, each named in itself; endonyms are never translated.
LANGUAGES = {"en": "English", "pt-BR": "Português (Brasil)"}
PLURAL_FORMS = ("zero", "one", "other")

_session = {"code": DEFAULT, "source": "system"}
_catalogues: dict[str, dict] = {}


# --- lookup ----------------------------------------------------------------------------

class _Marked(str):
    """A string ``N_`` marked with a context; equal to the plain string everywhere."""

    ctx = ""


def N_(msg: str, /, *, ctx: str = "") -> str:
    """Mark *msg* for the catalogue without translating it: for text defined at import time.

    Pass the result to ``t()`` when drawing. With *ctx*, the string carries it,
    so ``t(MARKED)`` looks up the same entry the catalogue has.
    """
    if not ctx:
        return msg
    marked = _Marked(msg)
    marked.ctx = ctx
    return marked


def _key(msg: str, ctx: str) -> str:
    return f"{ctx}::{msg}" if ctx else msg


def _entry(msg: str, ctx: str):
    """The active catalogue's entry for *msg*: a string, a dict of plural forms, or None."""
    code = _session["code"]
    if code in (DEFAULT, PSEUDO):
        return None
    return catalogue(code).get(_key(msg, ctx or getattr(msg, "ctx", "")))


def _format(text: str, english: str, values: dict) -> str:
    """*text* formatted with *values*; the English when a translation's placeholders break. Never raises."""
    if not values:
        return str(text)
    for template in (text, english):
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            continue
    return str(english)


def t(msg: str, /, *, ctx: str = "", **values) -> str:
    """*msg* (English) in the interface language, formatted with *values* when any are given.

    Without values the text is returned as written, so literal braces need no
    escaping; with values it goes through ``str.format``, named fields only.
    """
    if _session["code"] == PSEUDO:
        return _format(pseudo(msg), msg, values)
    entry = _entry(msg, ctx)
    if isinstance(entry, dict):  # a plural entry asked for as one message
        entry = entry.get("other")
    return _format(entry or msg, msg, values)


def _plural(code: str, n) -> str:
    """The plural category of *n* in *code*.

    English and Brazilian Portuguese alike: "one" for 1, "other" for the rest.
    CLDR and gettext put 0 with 1 in Portuguese; the app deliberately says
    "0 resultados", which reads better for counts. A catalogue entry may give
    a "zero" form, used for 0 in any language.
    """
    return "one" if n == 1 else "other"


def tn(singular: str, plural: str, n, /, *, ctx: str = "", **values) -> str:
    """The form of a counted message for *n*, formatted with *values* and ``{n}``.

    The catalogue entry is keyed by *singular* and holds ``{"one", "other"}``
    and optionally ``"zero"``. Always formatted, so literal braces are doubled.
    """
    values.setdefault("n", n)
    english = singular if n == 1 else plural
    if _session["code"] == PSEUDO:
        return _format(pseudo(english), english, values)
    entry = _entry(singular, ctx)
    if isinstance(entry, dict):
        form = "zero" if n == 0 and entry.get("zero") else _plural(_session["code"], n)
        entry = entry.get(form) or entry.get("other")
    return _format(entry or english, english, values)


def _usable(value) -> bool:
    if isinstance(value, str):
        return bool(value)
    return (isinstance(value, dict) and isinstance(value.get("other"), str) and bool(value["other"])
            and all(form in PLURAL_FORMS and isinstance(text, str) for form, text in value.items()))


def catalogue(code: str) -> dict:
    """Every message of *code*: the ``*.json`` files in its folder, merged in name order.

    Loaded on first use and kept; unreadable files and malformed entries are
    skipped (``scripts/i18n.py check`` reports them).
    """
    if code not in _catalogues:
        merged = {}
        try:
            paths = sorted((LOCALES / code).glob("*.json"))
        except OSError:
            paths = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                merged.update((key, value) for key, value in data.items() if _usable(value))
        _catalogues[code] = merged
    return _catalogues[code]


def reload() -> None:
    """Forget loaded catalogues; the next lookup reads the files again."""
    _catalogues.clear()


# --- languages -------------------------------------------------------------------------

def languages() -> dict[str, str]:
    """Shipped languages: code → the language's own name."""
    return dict(LANGUAGES)


_ALIASES = {"english": "en", "portuguese": "pt-BR", "português": "pt-BR", "portugues": "pt-BR"}
_BY_LANGUAGE = {code.split("-")[0].casefold(): code for code in LANGUAGES}
_TAG = re.compile(r"([a-z]{2,3}?)(?:-?(?:[a-z]{2}|[0-9]{3}))?(?:-.*)?")


def normalise(code: object) -> str | None:
    """The shipped language *code* means, ``qps``, or None.

    Any case, ``-`` or ``_``, an encoding or modifier: ``pt``, ``pt_BR``,
    ``ptbr`` and ``pt-PT.UTF-8`` give ``pt-BR``; ``en_US`` gives ``en``.
    ``C``, ``POSIX``, ``auto`` and unknown languages give None.
    """
    if not isinstance(code, str):
        return None
    folded = code.strip().split(".")[0].split("@")[0].casefold().replace("_", "-")
    if folded == PSEUDO:
        return PSEUDO
    if folded in _ALIASES:
        return _ALIASES[folded]
    exact = next((known for known in LANGUAGES if known.casefold() == folded), None)
    if exact:
        return exact
    match = _TAG.fullmatch(folded)
    return _BY_LANGUAGE.get(match.group(1)) if match else None


def current() -> str:
    """The interface language in use: a code from ``languages()`` or ``qps``."""
    return _session["code"]


def use(code: str | None) -> str:
    """Speak *code* from the next lookup on; returns the code in use.

    Any spelling ``normalise`` accepts; ``auto`` asks the system; anything
    else is English.
    """
    if isinstance(code, str) and code.strip().casefold() == AUTO:
        resolved = detect()
    else:
        resolved = normalise(code) or DEFAULT
    _session["code"] = resolved
    return resolved


# --- what the system speaks ------------------------------------------------------------

_MUI_LANGUAGE_NAME = 0x8
_LOCALE_NAME_MAX_LENGTH = 85


def _windows_ui_language(kernel32=None) -> str | None:
    """The first of the user's preferred display languages, else the default one (``en-US``)."""
    import ctypes

    kernel32 = kernel32 or ctypes.WinDLL("kernel32")
    count, size = ctypes.c_ulong(0), ctypes.c_ulong(0)  # ULONG
    if kernel32.GetUserPreferredUILanguages(_MUI_LANGUAGE_NAME, ctypes.byref(count), None, ctypes.byref(size)) \
            and size.value:
        names = ctypes.create_unicode_buffer(size.value)
        if kernel32.GetUserPreferredUILanguages(_MUI_LANGUAGE_NAME, ctypes.byref(count), names, ctypes.byref(size)) \
                and names.value:
            return names.value  # NUL-separated names; .value stops at the first
    name = ctypes.create_unicode_buffer(_LOCALE_NAME_MAX_LENGTH)
    if kernel32.LCIDToLocaleName(kernel32.GetUserDefaultUILanguage(), name, _LOCALE_NAME_MAX_LENGTH, 0):
        return name.value
    return None


def _windows_region(kernel32=None) -> str | None:
    """The regional format (dates, numbers) Windows uses, as a name (``pt-BR``)."""
    import ctypes

    kernel32 = kernel32 or ctypes.WinDLL("kernel32")
    name = ctypes.create_unicode_buffer(_LOCALE_NAME_MAX_LENGTH)
    return name.value if kernel32.GetUserDefaultLocaleName(name, _LOCALE_NAME_MAX_LENGTH) else None


def _is_c_locale(value: str) -> bool:
    return value.split(".")[0] in ("C", "POSIX")


def _posix_language(environ) -> str | None:
    """gettext's order: ``LANGUAGE`` (a list; its first shipped language) unless the locale
    is C, then ``LC_ALL``, ``LC_MESSAGES``, ``LANG``. ``C`` and ``POSIX`` are English."""
    locale = next((environ.get(name) for name in ("LC_ALL", "LC_MESSAGES", "LANG") if environ.get(name)), None)
    if locale and _is_c_locale(locale):
        return DEFAULT
    wanted = [entry for entry in environ.get("LANGUAGE", "").split(":") if entry]
    return next((entry for entry in wanted if normalise(entry)), wanted[0] if wanted else locale)


def _posix_region(environ) -> str | None:
    """The locale for dates and numbers: ``LC_ALL``, ``LC_TIME`` or ``LC_NUMERIC``, else Python's locale."""
    import locale

    named = next((environ.get(name) for name in ("LC_ALL", "LC_TIME", "LC_NUMERIC") if environ.get(name)), None)
    return named or locale.getlocale()[0]


def system_language(environ=None, platform: str | None = None) -> str | None:
    """The system's display language as it spells it (``en-US``, ``pt_BR.UTF-8``, ``C``), or None."""
    try:
        if (platform or sys.platform) == "win32":
            return _windows_ui_language()
        return _posix_language(os.environ if environ is None else environ)
    except Exception:  # (OSError, AttributeError, ctypes errors): detection never stops the app
        return None


def system_region(environ=None, platform: str | None = None) -> str | None:
    """The system's regional format (dates and numbers) as it spells it, or None."""
    try:
        if (platform or sys.platform) == "win32":
            return _windows_region()
        return _posix_region(os.environ if environ is None else environ)
    except Exception:
        return None


def detect(environ=None, platform: str | None = None) -> str:
    """The shipped language of the system's display language; English when it is none of them."""
    code = normalise(system_language(environ, platform))
    return code if code in LANGUAGES else DEFAULT


def region_suggests(code: str, region: str | None = None) -> str | None:
    """The language the regional format suggests while *code* is English, or None.

    Windows in English with Brazilian dates and numbers gives ``pt-BR``: the
    display language decides, so the app stays English, and may offer
    Portuguese once. *region* replaces the system's regional format.
    """
    if normalise(code) != DEFAULT:
        return None
    suggested = normalise(system_region() if region is None else region)
    return suggested if suggested in LANGUAGES and suggested != DEFAULT else None


# --- startup ---------------------------------------------------------------------------

def _choice(value: object, shipped_only: bool = False) -> str | None:
    """``auto``, a language code, or None for an empty or unknown *value*."""
    if isinstance(value, str) and value.strip().casefold() == AUTO:
        return AUTO
    code = normalise(value)
    return None if shipped_only and code not in LANGUAGES else code


def env_language(environ=None) -> tuple[str | None, str]:
    """The language the environment asks for (a code or ``auto``), and a notice when its value names none."""
    raw = (os.environ if environ is None else environ).get(ENV, "").strip()
    if not raw:
        return None, ""
    code = _choice(raw)
    if code is None:
        return None, t("Ignoring {variable}={value}: not a language ({choices}).",
                       variable=ENV, value=raw, choices=", ".join((AUTO, *LANGUAGES)))
    return code, ""


def resolve(cli: str | None = None, environ=None, saved: object = None) -> tuple[str, str, str]:
    """The language to start with, where the choice came from, and any notice.

    The order is *cli* (``--lang``), ``TORRENT_FINDER_LANG``, *saved* (the
    ``settings.language`` value, None when never chosen), then the system.
    ``auto`` at any step asks the system. The source is ``"cli"``, ``"env"``,
    ``"saved"`` or ``"system"`` (nothing chose). An unknown saved value is
    ignored silently; an unknown environment value gets a notice.
    """
    env_code, notice = env_language(environ)
    for source, value in (("cli", _choice(cli)), ("env", env_code), ("saved", _choice(saved, shipped_only=True))):
        if value:
            return (detect(environ) if value == AUTO else value), source, notice
    return detect(environ), "system", notice


def apply_startup(cli: str | None = None, environ=None, saved: object = None) -> str:
    """Use the startup language; returns a notice for the first screen ("" when none), in that language."""
    code, source, _notice = resolve(cli, environ, saved)
    use(code)
    _session["source"] = source
    return env_language(environ)[1]


def source() -> str:
    """Where this run's language came from: ``"cli"``, ``"env"``, ``"saved"`` or ``"system"``."""
    return _session["source"]


def choose(value: str) -> str:
    """Speak *value* (``auto`` or a code) from now on as the user's saved choice; returns the code in use."""
    code = use(value)
    _session["source"] = "saved"
    return code


# Offered once at startup, in the language it offers (the user may not read the current one's
# word for "Language"), when Windows speaks English but the regional format is one the app has.
SUGGESTION_HINTS = {"pt-BR": "Prefere português? Configurações › Idioma"}
HINT_SETTING = "language_hint_shown"
# Each language described in its own words, for the Language menu.
OWN_WORDS = {"en": "menus and messages in English", "pt-BR": "menus e mensagens em português"}


def suggestion(region: str | None = None) -> str | None:
    """The language a one-time hint may offer at startup, or None.

    Only when nothing chose this run's language (no ``--lang``, no
    environment variable, nothing saved), the system's display language gave
    English, and the regional format is another language the app speaks.
    """
    return region_suggests(_session["code"], region) if _session["source"] == "system" else None


# --- the qps pseudo-locale -------------------------------------------------------------

# What the pseudo-locale leaves alone, and what a translation must keep
# (scripts/i18n.py checks these): placeholders, Rich markup tags, addresses,
# file names, command-line flags, environment variables and key names.
PROTECTED = {
    "placeholder": re.compile(r"\{\{|\}\}|\{[^{}]*\}"),
    "tag": re.compile(r"\\*\[[a-z#/@][^\[\]]*\]"),
    "url": re.compile(r"https?://[^\s\])]+|\b[\w-]+(?:\.[\w-]+)*\.(?:com|org|net|io|to|si|se|ws|cc|me|ru|tv)\b(?:/\S*)?"),
    "file": re.compile(r"(?<![\w.])[\w*-]*\.(?:json|log|txt|py|exe|bat|cmd|toml|md|png|ttf|torrent|srt|ass|zip|rar|7z"
                       r"|part|old|bak)\b"),
    "flag": re.compile(r"(?<![\w-])--?[A-Za-z][\w-]*(?<!-)(?![\w-])"),
    "env": re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"),
    "combo": re.compile(r"\b(?:Ctrl|Shift|Alt)\+(?:[A-Za-z0-9]+\b|[↑↓←→,.])"),
    "key": re.compile(r"(?<![A-Za-z])(?:Enter|Esc|Tab|Space|Backspace|Delete|Del|PgUp|PgDn|Home|End|Ctrl|Shift|Alt"
                      r"|F\d{1,2})(?![A-Za-z0-9])"),
}
_PROTECTED = re.compile("|".join(f"(?:{pattern.pattern})" for pattern in PROTECTED.values()))
_SEGMENTS = re.compile(r"(\s*•\s*|\n)")  # key-bar separators and line breaks: each part is padded alone
_ACCENTS = str.maketrans("aeiouy", "áéíóúý")
_WORD = re.compile(r"[A-Za-z]+")
# A key-bar segment ("Enter select", "↑/↓ navigate"), as ui/theme.py reads them: a message
# that starts with one gets no brackets, which would hide its key from the key bar.
_KEY_ATOM = (r"(?:(?:Ctrl|Shift|Alt)\s?\+\s?(?:[A-Za-z0-9]+|[↑↓←→])|PgUp|PgDn|Home|End|Enter|Esc|Space|Tab"
             r"|Backspace|Delete|Del|F\d{1,2}(?![A-Za-z0-9])|↑↓|←→|[↑↓←→]|[A-Za-z0-9](?![A-Za-z0-9])"
             r"|[\[\]/?,.;:<>+*-](?![A-Za-z0-9]))")
_KEY_LED = re.compile(rf"{_KEY_ATOM}(?:\s?/\s?{_KEY_ATOM})*\s+[A-Za-z0-9(]")


def _accent(word: re.Match) -> str:
    """Accent a word's vowels but its first letter, so a key bar's action still starts with a plain letter."""
    text = word.group()
    return text[0] + text[1:].translate(_ACCENTS)


def _pseudo_part(part: str) -> str:
    pieces, position, letters = [], 0, 0
    for token in _PROTECTED.finditer(part):
        plain = part[position:token.start()]
        letters += len(plain.strip())
        pieces += [_WORD.sub(_accent, plain), token.group()]
        position = token.end()
    plain = part[position:]
    letters += len(plain.strip())
    pieces.append(_WORD.sub(_accent, plain))
    text = "".join(pieces)
    body = text.rstrip()
    return body + "~" * math.ceil(letters * 0.35) + text[len(body):]


@lru_cache(maxsize=4096)
def pseudo(text: str) -> str:
    """*text* in the ``qps`` pseudo-locale: ``⟦Séttíngs › Appéáráncé~~~~⟧``.

    Vowels are accented and each line or key-bar segment is padded by about a
    third with ``~``; protected tokens and separators (`` › ``, `` • ``) stay.
    Brackets mark where a message starts and ends, except one that starts with
    a key (a key bar), which must keep reading as keys.
    """
    if not text.strip():
        return text
    parts = _SEGMENTS.split(text)
    body = "".join(part if index % 2 else _pseudo_part(part) for index, part in enumerate(parts))
    core = body.strip()
    if _KEY_LED.match(PROTECTED["tag"].sub("", core)):
        return body
    start = body.index(core)
    return f"{body[:start]}⟦{core}⟧{body[start + len(core):]}"
