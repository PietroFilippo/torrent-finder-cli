"""Portable, literal release-name rules; never native indexer operators."""

from dataclasses import asdict, dataclass
from torrent_finder.result_view import words


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
            raise ValueError("Invalid release-name rules")
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
        labels = {"all_words": "All", "any_words": "Any", "phrase": "Phrase", "exclude_words": "Exclude"}
        return "; ".join(f"{labels[k]}: {v}" for k, v in self.snapshot().items() if v.strip())
