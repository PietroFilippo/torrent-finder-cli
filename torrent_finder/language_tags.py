"""Conservative Portuguese audio/subtitle checks on release names.

Indexers do not expose track languages. These are tag heuristics, not media
inspection: unlabelled releases cannot be classified, and uploader names are
never language evidence. Keep subtitle context separate from audio evidence.
"""

import re

from torrent_finder.filters import strip_accents


_BRAZIL = (
    r"(?:pt\s*br|pob|brazilian\s+(?:portuguese|pt)"
    r"|portugues(?:e)?\s+(?:(?:(?:do|de)\s+)?brasil|brasileiro|br))"
)
_PORTUGUESE = rf"(?:{_BRAZIL}|pt\s*pt|portugues(?:e)?(?:\s+de\s+portugal)?|brasileir[oa]|pt|por|br)"
_SUB_LABEL = r"(?:subs?|subtitles?|legendas?|leg|legendad[oa])"
_JOIN = r"[\s:=\[\]()]*"
_SUB_PREFIX = re.compile(rf"\b{_SUB_LABEL}\b{_JOIN}(?:(?:em|in)\s+)?\b{_PORTUGUESE}\b")
_SUB_SUFFIX = re.compile(rf"\b{_PORTUGUESE}\b{_JOIN}\b{_SUB_LABEL}\b")
_SUBTITLE_CUE = re.compile(rf"\b(?:{_SUB_LABEL}|multisubs?)\b")
_DUB_TAG = re.compile(r"\b(?:dublad[oa]|dublagem|nacional)\b")
_BRAZIL_TAG = re.compile(rf"\b{_BRAZIL}\b")
_BRAZIL_AUDIO_TAG = re.compile(rf"\b(?:{_BRAZIL}|brasileir[oa]|br)\b")
_AUDIO_LABEL = r"(?:audio|dub|dubbed|dubbing|dublad[oa]|dublagem)"
_AUDIO_PREFIX = re.compile(rf"\b{_AUDIO_LABEL}\b{_JOIN}(?:em\s+)?\b{_PORTUGUESE}\b")
_AUDIO_SUFFIX = re.compile(rf"\b{_PORTUGUESE}\b{_JOIN}\b{_AUDIO_LABEL}\b")


def _normalize(name: str) -> str:
    return re.sub(r"[._-]+", " ", strip_accents(name).casefold())


def _without_spans(text: str, spans: list[tuple[int, int]]) -> str:
    for start, end in spans:
        text = text[:start] + " " * (end - start) + text[end:]
    return text


def _track_tags(text: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    # Prefer labels before a language: in "Audio PT-BR Subs English", PT-BR
    # belongs to Audio, not Subs. Only look for reversed tags in unclaimed text.
    audio = [m.span() for m in _AUDIO_PREFIX.finditer(text)]
    subs = [m.span() for m in _SUB_PREFIX.finditer(text)]
    remaining = _without_spans(text, audio + subs)
    audio.extend(m.span() for m in _AUDIO_SUFFIX.finditer(remaining))
    subs.extend(m.span() for m in _SUB_SUFFIX.finditer(remaining))
    return audio, subs


def has_brazilian_audio(name: str) -> bool:
    """Require explicit Brazilian language evidence outside subtitle tags.

    Generic Portuguese, dublado and nacional tags do not establish a region.
    Brazilian tags need an audio/dub context when subtitle cues are present;
    a subtitle's PT-BR tag cannot qualify unlabelled or European audio.
    """
    text = _normalize(name)
    audio, subs = _track_tags(text)
    audio_text = _without_spans(text, subs)
    if any(_BRAZIL_AUDIO_TAG.search(text[start:end]) for start, end in audio):
        return True
    if not _BRAZIL_TAG.search(audio_text):
        return False
    return bool(_DUB_TAG.search(audio_text) or not _SUBTITLE_CUE.search(text))


def has_portuguese_subtitles(name: str) -> bool:
    """Require a subtitle tag, never just an audio-language marker."""
    text = _normalize(name)
    _audio, subs = _track_tags(text)
    return bool(re.search(r"\b(?:legendad[oa]|leg)\b", text) or subs)
