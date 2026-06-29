"""Subtitle downloading module using subliminal."""

import os
import re
import warnings
from typing import Optional

# Suppress subliminal/pkg_resources warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from babelfish import Language
from subliminal import Video, download_best_subtitles, save_subtitles, scan_video
from subliminal.cache import region as _subliminal_region

from torrent_finder.constants import console, get_download_dir

# subliminal caches provider auth tokens (e.g. the OpenSubtitles.com session) in
# a dogpile cache region that must be configured before use. As a library (not
# the subliminal CLI) we configure it ourselves; otherwise downloads fail with
# RegionNotConfigured. A per-process memory backend is enough for a CLI run.
try:
    _subliminal_region.configure("dogpile.cache.memory")
except Exception:
    pass  # already configured
from torrent_finder.credentials import opensubtitles_config, addic7ed_config

# Curated provider set. subliminal ships ~12 providers; most are dead weight —
# defunct legacy APIs (opensubtitles XML-RPC), VIP-only variants, single-language
# scrapers (napiprojekt/subtitulamos/subtis), or redundant mirrors (gestdown
# duplicates addic7ed). We keep the few broad, working ones.
SUBTITLE_PROVIDERS = ["opensubtitlescom", "addic7ed", "podnapisi", "tvsubtitles"]


def _lang_label(language) -> str:
    """Human-friendly language label, e.g. 'Portuguese (BR)' or 'English'."""
    name = getattr(language, "name", str(language))
    country = getattr(language, "country", None)
    if country is not None:
        return f"{name} ({country.alpha2})"
    return name


def _parse_one_language(token: str):
    """Parse a single language token into a babelfish Language, or None.

    Accepts alpha-3 (``eng``), alpha-2 (``en``), IETF region variants
    (``pt-BR``), and OpenSubtitles codes (``pob`` = Brazilian Portuguese).
    """
    t = token.strip()
    if not t:
        return None
    # IETF / region variant first (pt-BR, pt_BR) so the country is preserved.
    if "-" in t or "_" in t:
        try:
            return Language.fromietf(t.replace("_", "-"))
        except Exception:
            pass
    low = t.lower()
    for parse in (
        lambda: Language(low),                    # alpha-3: eng, por
        lambda: Language.fromalpha2(low),         # alpha-2: en, pt
        lambda: Language.fromopensubtitles(low),  # pob -> pt-BR
        lambda: Language.fromname(t.title()),     # "portuguese"
    ):
        try:
            return parse()
        except Exception:
            continue
    return None


def _parse_languages(raw: str):
    """Parse a comma/space separated string into ordered, de-duped Languages.

    Returns ``(languages, unknown_tokens)``, preserving the user's order since
    the first language becomes the primary subtitle track.
    """
    tokens = [t for t in re.split(r"[,\s]+", raw.strip()) if t]
    languages, unknown, seen = [], [], set()
    for tok in tokens:
        lang = _parse_one_language(tok)
        if lang is None:
            unknown.append(tok)
            continue
        key = (lang.alpha3, getattr(lang, "country", None))
        if key not in seen:
            seen.add(key)
            languages.append(lang)
    return languages, unknown


def _saved_path_for(subtitle, video, dl_dir: str):
    """Reconstruct the on-disk path that ``save_subtitles`` wrote, mirroring
    its naming (``<video>.<lang>.<ext>``) so we can return real file paths."""
    try:
        rel = subtitle.get_path(video, language_format="alpha2")
        return os.path.join(dl_dir, os.path.basename(rel))
    except Exception:
        return None


def download_subtitles(torrent_name: str, video_path: Optional[str] = None) -> list[str]:
    """Search and download subtitles, optionally in several languages.

    The user may enter multiple language codes separated by commas; every
    available one is downloaded and the saved paths are returned in the user's
    priority order (first = primary track). ``video_path`` — when the matching
    video has already been downloaded, hash-match the real file for accurate
    sync instead of guessing from the release name.
    """
    console.print(f"\n[info]Subtitle Search for:[/info] [highlight]{torrent_name}[/highlight]")
    console.print(
        "[dim]Tip: enter one or more languages separated by commas (e.g. eng, por "
        "or pt-BR). The first found becomes the primary track.[/dim]"
    )

    # Prompt for one or more languages.
    while True:
        raw = console.input("[info]Language code(s) [default: eng]: [/info]").strip()
        if not raw:
            languages, unknown = [Language("eng")], []
            break
        languages, unknown = _parse_languages(raw)
        if languages:
            break
        console.print("[warning]No valid language codes recognised. Try e.g. eng, por, pt-BR.[/warning]")

    if unknown:
        console.print(f"[warning]Ignored unrecognised code(s): {', '.join(unknown)}[/warning]")

    label_list = ", ".join(_lang_label(l) for l in languages)
    console.print(f"[info]Searching subtitles for:[/info] [highlight]{label_list}[/highlight]")

    # Per-provider credentials (if configured) unlock the best sources; without
    # them those providers still run anonymously with tighter limits.
    provider_configs = {}
    os_cfg = opensubtitles_config()
    if os_cfg:
        provider_configs["opensubtitlescom"] = os_cfg
    add_cfg = addic7ed_config()
    if add_cfg:
        provider_configs["addic7ed"] = add_cfg
    if not os_cfg:
        console.print(
            "[dim]Tip: set OpenSubtitles.com credentials for far better matches "
            "(see README).[/dim]"
        )

    try:
        # Prefer hashing the real downloaded file — this lets OpenSubtitles match
        # the exact release for accurate timing. Fall back to parsing the name.
        video = None
        hash_matched = False
        if video_path and os.path.isfile(video_path):
            try:
                video = scan_video(video_path)
                hash_matched = True
                console.print(
                    f"[dim]Matching against downloaded file "
                    f"[/dim][highlight]{os.path.basename(video_path)}[/highlight] "
                    f"[dim]for accurate sync.[/dim]"
                )
            except Exception:
                video = None
        if video is None:
            # Virtual video from the release name; the .mkv suffix makes
            # subliminal treat the string as a standard video filename.
            video = Video.fromname(f"{torrent_name}.mkv")

        with console.status(f"[bold cyan]Downloading subtitles for '[highlight]{torrent_name}[/highlight]'...[/bold cyan]", spinner="dots"):
            # subliminal downloads the best subtitle per requested language.
            best_subtitles = download_best_subtitles(
                [video], set(languages),
                providers=SUBTITLE_PROVIDERS,
                provider_configs=provider_configs,
            )

        found = best_subtitles.get(video, [])

        dl_dir = get_download_dir()
        os.makedirs(dl_dir, exist_ok=True)
        # Normalise to UTF-8 so accented characters (e.g. Portuguese ç/ã/é)
        # render correctly in players instead of as mojibake from the
        # subtitle's original latin-1/cp1252 encoding.
        saved = save_subtitles(video, found, directory=dl_dir, encoding="utf-8")

        # Map each saved subtitle's language -> path.
        saved_by_key = {}
        for sub in saved:
            p = _saved_path_for(sub, video, dl_dir)
            if p:
                saved_by_key[(sub.language.alpha3, getattr(sub.language, "country", None))] = p

        # Report per requested language (in priority order) and collect the
        # primary-first list of paths. A generic request (e.g. ``por``) matches
        # any country of that language.
        ordered_paths: list[str] = []
        for lang in languages:
            match = None
            want_country = getattr(lang, "country", None)
            for (a3, country), p in saved_by_key.items():
                if a3 == lang.alpha3 and (want_country is None or country == want_country):
                    match = p
                    break
            if match:
                if match not in ordered_paths:
                    ordered_paths.append(match)
                console.print(f"[success]✓ {_lang_label(lang)} — {os.path.basename(match)}[/success]")
            else:
                console.print(f"[warning]✗ {_lang_label(lang)} — no subtitle found.[/warning]")

        if not ordered_paths:
            console.print("[warning]No subtitles found matching that release.[/warning]")
            # Only meaningful when we matched by name — with a hashed file there's
            # nothing better to fall back to.
            if not hash_matched:
                console.print(
                    "[dim]Tip: searched by release name. If you've downloaded the "
                    "video, search again to match by file hash — more reliable, "
                    "especially for non-English titles.[/dim]"
                )
            return []

        console.print(f"\n[success]Saved to {dl_dir}.[/success]")
        return ordered_paths

    except Exception as e:
        console.print(f"\n[error]Subtitle download failed: {e}[/error]")
        return []


def test_opensubtitles(username: str, password: str, apikey: str | None = None):
    """Verify OpenSubtitles.com credentials by logging in.

    Returns ``(ok, message)`` where ``ok`` is True (verified), False (rejected),
    or None (couldn't verify — rate limit / network). Calls ``login()``
    explicitly; ``initialize()`` only sets up the session and would reuse a
    cached token, so it can't detect a wrong password on its own.
    """
    from subliminal.providers.opensubtitlescom import OpenSubtitlesComProvider
    kwargs = {"username": username, "password": password}
    if apikey:
        kwargs["apikey"] = apikey
    provider = OpenSubtitlesComProvider(**kwargs)
    try:
        provider.initialize()
        provider.login()  # actually authenticate; raises on bad credentials
        return True, "Login successful"
    except Exception as e:
        msg = str(e) or type(e).__name__
        low = msg.lower()
        if any(t in low for t in ("401", "unauthor", "invalid", "403", "forbidden")):
            return False, "Invalid username or password"
        if any(t in low for t in ("429", "too many", "rate")):
            return None, "Rate limited by OpenSubtitles — try again shortly"
        return None, f"Couldn't verify ({msg[:120]})"
    finally:
        try:
            provider.terminate()
        except Exception:
            pass


def test_addic7ed(username: str, password: str):
    """Addic7ed can't be verified cheaply.

    Its subliminal provider just stores the username/password as cookies and
    flips ``logged_in`` without any login round-trip, so a wrong password would
    look identical to a right one. Return None ("couldn't verify") rather than a
    misleading success.
    """
    return None, "Addic7ed can't be verified automatically; it'll be used on the next search."
