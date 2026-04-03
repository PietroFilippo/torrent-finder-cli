"""Subtitle downloading module using subliminal."""

import os
import warnings
from typing import Optional

# Suppress subliminal/pkg_resources warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from babelfish import Language
from subliminal import Video, download_best_subtitles, save_subtitles

from constants import DOWNLOADS_DIR, console


def download_subtitles(torrent_name: str) -> Optional[str]:
    """Search and download subtitles for the given torrent name."""
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
    
    try:
        # Create a virtual video based entirely on the torrent name formatting
        # Subliminal will extract title, year, group, resolution, etc from it
        # Append .mkv to trick subliminal into treating it as a standard video file
        video = Video.fromname(f"{torrent_name}.mkv")
        
        # Download best subtitles for the given languages
        best_subtitles = download_best_subtitles([video], {language})
        
        subs = best_subtitles.get(video, [])
        if not subs:
            console.print("[warning]No subtitles found matching that release.[/warning]")
            return None
            
        if not os.path.exists(DOWNLOADS_DIR):
            os.makedirs(DOWNLOADS_DIR)
            
        # Temporarily change directory so save_subtitles dumps it in DOWNLOADS_DIR
        original_cwd = os.getcwd()
        os.chdir(DOWNLOADS_DIR)
        
        saved_paths = save_subtitles(video, subs)
        os.chdir(original_cwd)
        
        if saved_paths:
            console.print(f"\n[success]Subtitles downloaded successfully to {DOWNLOADS_DIR}![/success]")
            return str(saved_paths[0])
            
    except Exception as e:
        console.print(f"\n[error]Subtitle download failed: {e}[/error]")
        try:
            os.chdir(original_cwd)
        except Exception:
            pass
            
    return None
