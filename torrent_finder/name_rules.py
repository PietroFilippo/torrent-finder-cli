"""Portable, literal release-name rules; never native indexer operators."""

from dataclasses import asdict, dataclass
from torrent_finder.i18n import N_, t
from torrent_finder.result_view import words

# i18n: converted

# How summary() shows each populated rule.
_SUMMARY = {
    "all_words": N_("All: {words}"), "any_words": N_("Any: {words}"),
    "phrase": N_("Phrase: {words}"), "exclude_words": N_("Exclude: {words}"),
}


@dataclass
class NameRules:
    all_words: str = ""
    any_words: str = ""
    phrase: str = ""
    exclude_words: str = ""

    @classmethod
    def restore(cls, data):
        if not isinstance(data, dict) or any(
            key not in cls.__dataclass_fields__ or not isinstance(value, str)
            for key, value in data.items()
        ):
            raise ValueError(t("Invalid release-name rules"))
        return cls(**data)

    def snapshot(self):
        return asdict(self)

    def matches(self, name):
        tokens = words(name)
        present = set(tokens)
        required, optional = words(self.all_words), words(self.any_words)
        phrase = words(self.phrase)
        return (all(w in present for w in required)
                and (not optional or any(w in present for w in optional))
                and not any(w in present for w in words(self.exclude_words))
                and (not phrase or any(tokens[i:i + len(phrase)] == phrase
                                       for i in range(len(tokens) - len(phrase) + 1))))

    def summary(self):
        """Stable English summary for diagnostics and existing callers."""
        return "; ".join(_SUMMARY[k].format(words=v) for k, v in self.snapshot().items() if v.strip())

    def summary_label(self):
        """The populated rules in the current interface language; empty when none."""
        return "; ".join(t(_SUMMARY[k], words=v) for k, v in self.snapshot().items() if v.strip())
