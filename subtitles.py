"""Subtitle downloading module using subliminal."""

import os
import warnings
from typing import Optional

# Suppress subliminal/pkg_resources warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from babelfish import Language
from subliminal import Video, download_best_subtitles, save_subtitles, scan_video

from constants import console, get_download_dir
from credentials import opensubtitles_config, addic7ed_config

# Curated provider set. subliminal ships ~12 providers; most are dead weight —
# defunct legacy APIs (opensubtitles XML-RPC), VIP-only variants, single-language
# scrapers (napiprojekt/subtitulamos/subtis), or redundant mirrors (gestdown
# duplicates addic7ed). We keep the few broad, working ones.
SUBTITLE_PROVIDERS = ["opensubtitlescom", "addic7ed", "podnapisi", "tvsubtitles"]


def download_subtitles(torrent_name: str, video_path: Optional[str] = None) -> Optional[str]:
    """Search and download subtitles for a torrent.

    ``video_path`` — when a matching video file has already been downloaded,
    pass its path so subliminal can hash-match against the real file
    (frame-accurate sync) instead of guessing from the release name alone.
    """
    console.print(f"\n[info]Subtitle Search for:[/info] [highlight]{torrent_name}[/highlight]")

    # Prompt for language
    while True:
        lang_input = console.input("[info]Enter language code (e.g. eng, spa, por) [default: eng]: [/info]").strip().lower()
        if not lang_input:
            lang_input = "eng"

        try:
            language = Language(lang_input)
            break
        except ValueError:
            console.print(f"[warning]Invalid language code '{lang_input}'. Please try again.[/warning]")

    console.print(f"[info]Searching subtitles for {language.name}...[/info]")

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
        if video_path and os.path.isfile(video_path):
            try:
                video = scan_video(video_path)
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

        with console.status(f"[bold cyan]Downloading {language.name} subtitles for '[highlight]{torrent_name}[/highlight]'...[/bold cyan]", spinner="dots"):
            # Download best subtitles for the given languages
            best_subtitles = download_best_subtitles(
                [video], {language},
                providers=SUBTITLE_PROVIDERS,
                provider_configs=provider_configs,
            )

        subs = best_subtitles.get(video, [])
        if not subs:
            console.print("[warning]No subtitles found matching that release.[/warning]")
            return None
            
        dl_dir = get_download_dir()
        os.makedirs(dl_dir, exist_ok=True)

        # Temporarily change directory so save_subtitles dumps it in dl_dir
        original_cwd = os.getcwd()
        os.chdir(dl_dir)

        saved_paths = save_subtitles(video, subs)
        os.chdir(original_cwd)

        if saved_paths:
            console.print(f"\n[success]Subtitles downloaded successfully to {dl_dir}![/success]")
            return str(saved_paths[0])
            
    except Exception as e:
        console.print(f"\n[error]Subtitle download failed: {e}[/error]")
        try:
            os.chdir(original_cwd)
        except Exception:
            pass
            
    return None
