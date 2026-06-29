"""Categorized help and tip catalog for the interactive UI.

The random footer tip and the upcoming all-tips browser read from the same
catalog so shortcut hints, menu guidance, and safety notes stay in one place.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from rich.markup import escape


@dataclass(frozen=True)
class Tip:
    """A single user-facing hint.

    ``tags`` are intentionally plain text so the tips browser can later filter
    by query without knowing about UI labels or categories.
    """

    text: str
    tags: tuple[str, ...] = ()
    rotating: bool = True


@dataclass(frozen=True)
class TipCategory:
    """A named group of related tips."""

    name: str
    tips: tuple[Tip, ...]


TIP_CATEGORIES: tuple[TipCategory, ...] = (
    TipCategory(
        "Search & Navigation",
        (
            Tip("For best results, search using the complete release name.", ("search", "query")),
            Tip("The search prompt has no single-letter shortcuts, so a query can start with any letter (even F, H, S, or T).", ("search", "navigation", "query")),
            Tip("Press Tab at the search prompt for quick actions — filters, history, stats, tips — then F/H/S/T or arrows; your typed query is kept.", ("search", "actions", "hotkey")),
            Tip("Press Esc at the search prompt to go back to provider selection.", ("search", "navigation", "hotkey")),
            Tip("Is a search slow? Press Esc to cancel it instead of waiting out the engine timeouts.", ("search", "cancel", "hotkey")),
            Tip("While typing a query, Left/Right move the cursor and Home/End jump to the ends, so you can fix a typo mid-word.", ("search", "editing", "cursor")),
            Tip("PirateBay (Apibay) answers slowly (~20s) and paces Movies and Games searches; toggle it off via F on the provider screen for instant results.", ("search", "apibay", "speed")),
            Tip("Press F on a highlighted provider to configure its engines and filters without leaving the provider menu.", ("provider", "filters", "hotkey")),
            Tip("Press H on the provider screen to browse search history.", ("provider", "history", "hotkey")),
            Tip("Press S on the provider screen to open usage stats.", ("provider", "stats", "hotkey")),
            Tip("Press T on the provider screen to open this searchable tips browser.", ("provider", "tips", "hotkey")),
            Tip("History entries remember the filter presets you had active at search time.", ("history", "filters", "presets")),
            Tip("History can be filtered by provider, date range, and sort order with P, D, and S.", ("history", "filters", "hotkey")),
            Tip("Use -f and -x on the CLI to add ad-hoc include or exclude keywords.", ("cli", "filters")),
            Tip("Use -t movie, game, software, mobile, rutracker, anime, or manga to choose a provider for direct CLI searches.", ("cli", "provider")),
            Tip("Software is a group: pick it to choose Desktop, Mobile, or RuTracker as the source.", ("software", "apps", "provider")),
            Tip("Need a desktop program? Software → Desktop searches The Pirate Bay Applications plus SolidTorrents; or -t software on the CLI.", ("software", "apps", "cli")),
            Tip("Looking for an Android app? Software → Mobile searches The Pirate Bay's Android category (APK/MOD/OBB); it's Android-only. Try -t mobile.", ("mobile", "android", "cli")),
            Tip("RuTracker (Software → RuTracker) is great for software, audio, and rare content — add your rutracker.org login under Credentials first.", ("rutracker", "credentials", "cli")),
            Tip("Looking for J-dramas or Asian live-action? Movies & Series searches Nyaa too.", ("movies", "nyaa")),
            Tip("Reading manga? The Manga provider scans Nyaa Literature plus Apibay Comics; try -t manga.", ("manga", "nyaa", "cli")),
        ),
    ),
    TipCategory(
        "Filters & Selection",
        (
            Tip("Filter menu keybinds: a select all, i invert, c clear presets, w save.", ("filters", "keybinds")),
            Tip("Episode and filter pickers share keybinds: v drops an anchor, Shift+V toggles the range.", ("selection", "keybinds", "range")),
            Tip("Press Space or Enter on toggleable rows to change their checkbox state.", ("selection", "keybinds")),
            Tip("The Clear filters action clears preset toggles only; engine selections are preserved.", ("filters", "presets", "engines")),
            Tip("Your engine and preset toggles persist across runs in filter_state.json.", ("filters", "state", "persistence")),
            Tip("Results are deduped by info hash across engines, then sorted by seeders.", ("results", "dedupe", "sorting")),
            Tip("Want untranslated manga? Turn on the Nyaa (Raw) engine from the filter menu (press F on the provider screen); it is off by default.", ("manga", "nyaa", "filters")),
            Tip("The result table stays on screen after selection so you can see what you picked.", ("results", "ui")),
        ),
    ),
    TipCategory(
        "Downloads",
        (
            Tip("aria2c is the only downloader that strictly honors your file selection.", ("downloads", "aria2c", "selection")),
            Tip("webtorrent and peerflix may pull the whole torrent even when a file selection is active.", ("downloads", "webtorrent", "peerflix", "selection")),
            Tip("aria2c handles multi-file selection in a single process, which is fastest for batches.", ("downloads", "aria2c", "selection")),
            Tip("Browse torrent files before downloading to pick just the episodes or extras you want.", ("downloads", "episode picker", "selection")),
            Tip("The episode picker remembers your previous selection; re-open it to refine, not rebuild.", ("episode picker", "selection", "state")),
            Tip("Confirming the picker with nothing checked clears the selection; Esc keeps your prior picks.", ("episode picker", "selection", "hotkey")),
            Tip("File-list fetch stalling on a low-seed torrent? Press Esc to cancel and go back.", ("episode picker", "metadata", "hotkey")),
            Tip("The desktop-client magnet option cannot pre-filter files; uncheck unwanted files in the client dialog.", ("downloads", "magnet", "selection")),
            Tip("Copy magnet link puts the selected torrent's magnet URI on your clipboard.", ("downloads", "magnet", "clipboard")),
            Tip("Set a default save folder with Save to; it applies to aria2c, webtorrent, peerflix, and subtitles.", ("downloads", "settings", "folder")),
            Tip("Quiet mode replaces aria2c, webtorrent, and peerflix native progress UIs with a minimal spinner.", ("downloads", "quiet mode", "settings")),
            Tip("Direct download methods print a Ctrl+C reminder because the child process owns the active transfer.", ("downloads", "cancel", "keybinds")),
            Tip("Single-file torrents can be browsed too — open Browse torrent files to inspect or pick the one file.", ("downloads", "episode picker", "single-file")),
            Tip("Open torrent page launches the source page (Nyaa, PirateBay, YTS) in your browser.", ("downloads", "torrent info", "browser")),
            Tip("Torrent info pulls the source page's category, description, and full file list straight into the app.", ("downloads", "torrent info", "origin")),
            Tip("Torrent info flags whether subtitles are embedded in the video: definitively via ffprobe once the file is downloaded, otherwise a release-name heuristic.", ("downloads", "torrent info", "subtitles")),
        ),
    ),
    TipCategory(
        "Streaming",
        (
            Tip("webtorrent is the default streaming backend; peerflix is the fallback if it stalls.", ("streaming", "webtorrent", "peerflix")),
            Tip("VLC is required for Stream to VLC actions.", ("streaming", "vlc")),
            Tip("Press v while streaming to reopen VLC without losing torrent progress.", ("streaming", "vlc", "hotkey")),
            Tip("The v hotkey is a no-op while VLC is already running, which prevents duplicate VLC windows.", ("streaming", "vlc", "hotkey")),
            Tip("Multi-episode streams show n for next and b for previous episode.", ("streaming", "episodes", "hotkey")),
            Tip("Even without a picker selection, multi-episode torrents auto-enable n and b navigation.", ("streaming", "episodes", "metadata")),
            Tip("Pick non-video files such as .srt, .nfo, or .jpg in the browser; downloads grab them, streams skip them.", ("streaming", "downloads", "selection")),
            Tip("If a stream selection contains only non-video files, the stream errors instead of silently choosing another file.", ("streaming", "selection", "video")),
            Tip('If VLC errors with "cannot open MRL", press v after a moment to retry the same stream.', ("streaming", "vlc", "retry")),
            Tip("Quiet mode keeps stream headers and hotkeys visible while hiding backend progress noise.", ("streaming", "quiet mode")),
        ),
    ),
    TipCategory(
        "Subtitles",
        (
            Tip("Subtitle Source auto-detect pulls .srt and .ass files out of the torrent and attaches them to VLC.", ("subtitles", "auto-detect", "streaming")),
            Tip("Auto-detected subtitle matches are downloaded before VLC launches so the first stream can attach them.", ("subtitles", "auto-detect", "vlc")),
            Tip("English-tagged subtitles are prioritized as the primary VLC subtitle track when present.", ("subtitles", "language", "vlc")),
            Tip("Need subs the torrent does not ship? Search & download subtitles auto-pins the result to the next stream.", ("subtitles", "download", "streaming")),
            Tip("Switch Subtitle Source to external to pick any .srt or .ass file from your downloads folder.", ("subtitles", "external", "folder")),
            Tip("Switch Subtitle Source to off when you want VLC to launch without attached subtitles.", ("subtitles", "off", "streaming")),
            Tip("Search several subtitle languages at once: type e.g. eng, por or pt-BR; the first one found becomes the primary track.", ("subtitles", "language", "multi")),
            Tip("Want Brazilian Portuguese specifically? Enter pt-BR; OpenSubtitles treats it separately from European Portuguese.", ("subtitles", "language", "portuguese")),
            Tip("Manage OpenSubtitles, Addic7ed, Jimaku, and RuTracker logins in-app: Credentials on the Select Provider screen.", ("subtitles", "credentials", "provider")),
            Tip("OpenSubtitles.com credentials greatly improve subtitle matches; add them under Credentials.", ("subtitles", "credentials", "opensubtitles")),
            Tip("The RuTracker provider needs a rutracker.org account — set it under Credentials on the Select Provider screen.", ("rutracker", "credentials", "provider")),
            Tip("For anime, a Jimaku API key enables a dedicated fansub lookup that runs before the general subtitle providers.", ("subtitles", "anime", "jimaku")),
            Tip("Already downloaded the video? Subtitle search hash-matches the real file for frame-accurate sync.", ("subtitles", "hash", "sync")),
            Tip("No subtitles found by name? Download the video first, then search again; hash matching is more reliable, especially for non-English titles.", ("subtitles", "hash", "name")),
            Tip("Downloaded subtitles are saved as UTF-8, so accented characters render correctly instead of as mojibake.", ("subtitles", "encoding", "utf-8")),
        ),
    ),
    TipCategory(
        "Safety & Privacy",
        (
            Tip("Your public IP is visible to every peer; a VPN is the only real mitigation.", ("safety", "privacy", "vpn")),
            Tip("The network exposure warning shows public IP, ISP, ASN, location, and proxy or hosting flags.", ("safety", "network exposure")),
            Tip("Press Enter on the network exposure warning to acknowledge and continue.", ("safety", "network exposure", "hotkey")),
            Tip("Press D on the startup warning to permanently dismiss it in filter_state.json.", ("safety", "network exposure", "settings")),
            Tip("Press Esc on the network exposure warning to abort before joining any swarm.", ("safety", "network exposure", "hotkey")),
            Tip("Re-open the network exposure panel anytime from the Network exposure info row on the Select Provider screen.", ("safety", "network exposure", "provider")),
            Tip("The Trusted Uploaders preset is a community reputation heuristic, not a safety guarantee.", ("safety", "filters", "presets")),
            Tip("Seed counts, file names, and uploader tags are not proof that content is safe.", ("safety", "results", "risk")),
        ),
    ),
    TipCategory(
        "State & Stats",
        (
            Tip("Search history, usage stats, quiet mode, download folder, filters, and warning dismissal live in filter_state.json.", ("state", "persistence")),
            Tip("Most state writes are cached in memory and flushed on exit for faster interactions.", ("state", "performance")),
            Tip("Destructive actions such as clear history and reset stats ask for confirmation first.", ("state", "confirmation", "safety")),
            Tip("Reset stats deletes only usage counters; filters, settings, and history are preserved.", ("stats", "reset", "state")),
            Tip("Usage stats track searches, picked torrents, method picks, completions, runtime, and preset usage.", ("stats", "metrics")),
            Tip("Method completion rates count only paths that can report a successful finish.", ("stats", "methods", "completion")),
        ),
    ),
)


def iter_tip_categories() -> tuple[TipCategory, ...]:
    """Return the full categorized tip catalog."""
    return TIP_CATEGORIES


def iter_tips(*, rotating_only: bool = False) -> tuple[Tip, ...]:
    """Return all tips in display order."""
    return tuple(
        tip
        for category in TIP_CATEGORIES
        for tip in category.tips
        if not rotating_only or tip.rotating
    )


def find_tips(query: str = "", category: str | None = None) -> list[tuple[TipCategory, Tip]]:
    """Return catalog tips matching a text query and optional category name.

    Matching is case-insensitive across category name, tip text, and tags. The
    viewer will use this in a later commit for in-page search and filtering.
    """
    needle = query.strip().lower()
    category_key = category.strip().lower() if category else ""
    matches: list[tuple[TipCategory, Tip]] = []

    for tip_category in TIP_CATEGORIES:
        if category_key and tip_category.name.lower() != category_key:
            continue
        for tip in tip_category.tips:
            haystack = " ".join((tip_category.name, tip.text, *tip.tags)).lower()
            if not needle or needle in haystack:
                matches.append((tip_category, tip))

    return matches


# Backwards-compatible flat pool for existing callers.
TIPS: list[str] = [tip.text for tip in iter_tips(rotating_only=True)]


def random_tip() -> str:
    """Return a randomly-picked tip rendered as Rich markup."""
    text = random.choice(TIPS)
    return f"[bold cyan]💡 Tip:[/bold cyan] [italic]{escape(text)}[/italic]"
