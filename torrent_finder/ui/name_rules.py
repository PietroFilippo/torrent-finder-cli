"""Shared transactional editor for literal name rules."""

from torrent_finder.name_rules import NameRules
from torrent_finder.ui.selector import SelectItem, arrow_select


def edit_name_rules(rules):
    from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut, input_screen
    draft = NameRules.restore(rules.snapshot())
    labels = {"all_words": "All words", "any_words": "Any word", "phrase": "Exact phrase", "exclude_words": "Exclude words"}
    explanation = ("Release names only. Case, accents and punctuation are normalized. "
                   "Whole words; exact phrase means consecutive words. All populated rules apply together. "
                   "Source/uploader names and genres are not searched.")
    while True:
        items = [SelectItem(label, key, hint=getattr(draft, key) or "off", description=explanation)
                 for key, label in labels.items()]
        items += [SelectItem("Apply rules", "apply"), SelectItem("Cancel", "cancel")]
        pick = arrow_select(items, title="Literal release-name rules", footer="Enter edit • Esc discard")
        if pick is None or items[pick].value == "cancel":
            return rules
        key = items[pick].value
        if key == "apply":
            return draft
        render = input_screen(f"Release-name rules › {labels[key]}", explanation, "Empty clears this rule.",
                              keys="Enter apply  •  Esc cancel")
        value = get_query_with_shortcut(PROMPT, initial=getattr(draft, key), screen_renderer=render)
        if isinstance(value, str) and value != "GO_BACK":
            setattr(draft, key, value.strip())
