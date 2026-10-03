"""Listing metadata and explicitly labelled filename hints, without network I/O."""

import re
from torrent_finder.language_tags import has_brazilian_audio, has_brazilian_subtitles


def detail_lines(row):
    name = str(row.get("name", "Unknown"))
    lines = ["Full name: " + name]
    for key, label in (("provider_label", "Provider"), ("source", "Source"),
                       ("uploader", "Uploader (listing)"), ("resolution", "Resolution (listing)"),
                       ("audio_language", "Audio language (listing)"),
                       ("subtitle_language", "Subtitle language (listing)"),
                       ("language", "Language (listing; track unspecified)"),
                       ("knaben_tracker", "Originating tracker"),
                       ("apibay_cached_at", "Cached APIBay metadata (last-known-good)"),
                       ("page_url", "Listing"), ("fetched_at", "Metadata fetched")):
        if row.get(key):
            lines.append(f"{label}: {row[key]}")
    hints = []
    if not row.get("resolution"):
        hints.extend(dict.fromkeys(re.findall(r"\b(?:480p|720p|1080[pi]|2160p|4k)\b", name, re.I)))
    if not row.get("audio_language") and has_brazilian_audio(name):
        hints.append("PT-BR audio tag")
    if not row.get("subtitle_language") and has_brazilian_subtitles(name):
        hints.append("PT-BR subtitle tag")
    if re.search(r"\bpt[ ._-]*pt\b", name, re.I):
        hints.append("PT-PT tag (track unspecified)")
    if re.search(r"\bdual[ ._-]+audio\b", name, re.I):
        hints.append("Dual Audio (languages unspecified)")
    if not any(row.get(key) for key in ("language", "audio_language", "subtitle_language")):
        for pattern, label in ((r"\b(?:eng|english)\b", "English"),
                               (r"\b(?:jpn|japanese)\b", "Japanese"),
                               (r"\b(?:spa|spanish)\b", "Spanish"),
                               (r"\b(?:portuguese|português)\b", "Portuguese (region unspecified)")):
            if re.search(pattern, name, re.I):
                hints.append(label + " tag (track unspecified)")
    if not row.get("uploader"):
        match = re.match(r"\[([^\]]+)\]", name)
        if match:
            hints.append("release group: " + match[1])
    if hints:
        lines.append("Filename hints: " + "; ".join(hints))
    lines.append("Listing labels and filename hints do not verify media tracks or availability.")
    return lines
