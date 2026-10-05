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


# --- release tags ------------------------------------------------------------
# Read from the part of a name after its title, so a title word ("Charlotte's
# Web", "Cam") is never taken for a tag. Like the hints above, tags describe
# the name, not verified tracks.

def _token(pattern: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", re.I)


_RESOLUTION = _token(r"2160p|4k|uhd|1080[pi]|720p|576p|480p")
_SOURCE = _token(r"web[-. ]?dl|web[-. ]?rip|blu[-. ]?ray|bdrip|brrip|remux|hdtv|dvdrip|hdcam|hdts|telesync|cam|web")
_EDITION = _token(r"repack|proper|extended|imax|remastered|uncut|director'?s[ .]cut")
_HDR = _token(r"hdr10\+|hdr10|hdr|dolby[ .]?vision|dovi|dv")
_CODEC = _token(r"x26[45]|h[ .]?26[45]|hevc|avc|av1|xvid")
_AUDIO = re.compile(r"(?<![a-z0-9])(ddp|dd\+|e-?ac-?3|ac-?3|aac|dts-hd(?:[ .]ma)?|dts|truehd|atmos|flac|opus|lpcm)"
                    r"(?:[ .]?([257][.][01]))?(?![a-z0-9])", re.I)
_CHANNELS = _token(r"[257][.][01]")
_DUAL = _token(r"dual[ ._-]?audio|dual")
_MULTI = _token(r"multi")
_DUBBED = _token(r"dublado|dub")
_TRAILING_GROUP = re.compile(r"-([A-Za-z0-9]{2,})(?:\.(?:mkv|mp4|avi|torrent))?\s*$")
_LEADING_GROUP = re.compile(r"^\s*\[([^\]]+)\]")

_SOURCE_NAMES = {"webdl": "WEB-DL", "webrip": "WEBRip", "bluray": "BluRay", "bdrip": "BDRip", "brrip": "BRRip",
                 "remux": "Remux", "hdtv": "HDTV", "dvdrip": "DVDRip", "hdcam": "HDCAM", "hdts": "HDTS",
                 "telesync": "TS", "cam": "CAM", "web": "WEB"}
_HDR_NAMES = {"hdr10+": "HDR10+", "hdr10": "HDR10", "hdr": "HDR", "dolbyvision": "Dolby Vision",
              "dovi": "Dolby Vision", "dv": "DV"}
_CODEC_NAMES = {"x264": "x264", "x265": "x265", "h264": "H.264", "h265": "H.265", "hevc": "HEVC", "avc": "AVC",
                "av1": "AV1", "xvid": "XviD"}
_AUDIO_NAMES = {"ddp": "DDP", "dd+": "DDP", "eac3": "EAC3", "ac3": "AC3", "aac": "AAC", "dtshd": "DTS-HD",
                "dtshdma": "DTS-HD MA", "dts": "DTS", "truehd": "TrueHD", "atmos": "Atmos", "flac": "FLAC",
                "opus": "Opus", "lpcm": "LPCM"}


_JOINED_CHANNELS = {"DDP", "AAC", "AC3", "EAC3", "DTS", "FLAC", "LPCM", "Opus"}
_NOT_GROUPS = {"br", "dl", "rip", "hd", "sd", "pt"}


def _compact(value: str) -> str:
    return re.sub(r"[-. ]", "", value.casefold())


def _tag_area(name: str) -> str:
    """The part of *name* after its media title (all of it when no title is found)."""
    from torrent_finder.result_view import media_title
    title = media_title(name)
    if not title:
        return name
    position = name.find(title)
    return name[position + len(title):] if position >= 0 else name


def release_tags(name: str) -> list[str]:
    """Tags a release name carries: resolution, source, edition, HDR, codec, audio, language, group.

    ``Dune Part Two 2024 1080p WEB-DL DDP5.1 Atmos H.264-FLUX`` gives
    ``["1080p", "WEB-DL", "H.264", "DDP5.1", "Atmos", "group FLUX"]``.
    """
    name = str(name or "")
    area = _tag_area(name)
    tags: list[str] = []
    resolutions = [match.group(0).casefold() for match in _RESOLUTION.finditer(area)]
    for value in resolutions:
        if value in ("4k", "uhd"):
            if "2160p" not in resolutions:
                tags.append("4K")
        else:
            tags.append(value)
    tags += [_SOURCE_NAMES.get(_compact(m.group(0)), m.group(0)) for m in _SOURCE.finditer(area)]
    tags += [m.group(0).replace(".", " ").title().replace("'S", "'s") for m in _EDITION.finditer(area)]
    tags += [_HDR_NAMES.get(_compact(m.group(0)), m.group(0).upper()) for m in _HDR.finditer(area)]
    tags += [_CODEC_NAMES.get(_compact(m.group(0)), m.group(0)) for m in _CODEC.finditer(area)]
    with_channels = False
    for match in _AUDIO.finditer(area):
        codec = _AUDIO_NAMES.get(_compact(match.group(1)), match.group(1).upper())
        channels = match.group(2) or ""
        if channels:
            with_channels = True
            # "DDP5.1", "AAC2.0" as releases write them; "TrueHD 7.1", "DTS-HD MA 7.1" with a space.
            channels = channels if codec in _JOINED_CHANNELS else " " + channels
        tags.append(codec + channels)
    if not with_channels:
        tags += [m.group(0) for m in _CHANNELS.finditer(area)]
    if has_brazilian_audio(name):
        tags.append("PT-BR audio")
    elif _DUBBED.search(area):
        tags.append("Dubbed")
    if has_brazilian_subtitles(name):
        tags.append("PT-BR subs")
    if _DUAL.search(area):
        tags.append("Dual audio")
    if _MULTI.search(area):
        tags.append("Multi")
    group = _LEADING_GROUP.match(name) or _TRAILING_GROUP.search(name)
    if group and not (_compact(group.group(1)) in _NOT_GROUPS
                      or re.search(r"(?i)(?<![a-z])pt$", name[:group.start()])):  # PT-BR is not a group
        tags.append("group " + group.group(1))
    return list(dict.fromkeys(tags))


def tag_matches(tag: str, preset_names) -> bool:
    """True when *tag* is what one of *preset_names* asks for (``1080p`` for "1080p", ``x265`` for "x265 / HEVC")."""
    words = set(re.findall(r"[a-z0-9+]+", tag.casefold())) - {"audio", "subs", "group"}
    return bool(words) and any(words <= set(re.findall(r"[a-z0-9+]+", str(name).casefold()))
                               for name in preset_names)
