"""Shared transactional editor for literal name rules."""

from torrent_finder.i18n import t
from torrent_finder.name_rules import NameRules
from torrent_finder.ui.selector import SelectItem, arrow_select

# i18n: converted


def edit_name_rules(rules):
    from torrent_finder.ui.prompts import PROMPT, get_query_with_shortcut, input_screen
    draft = NameRules.restore(rules.snapshot())
    while True:
        labels = {"all_words": t("All words"), "any_words": t("Any word"), "phrase": t("Exact phrase"),
                  "exclude_words": t("Exclude words")}
        explanation = t("Release names only. Case, accents and punctuation are normalized. "
                        "Whole words; exact phrase means consecutive words. All populated rules apply together. "
                        "Source/uploader names and genres are not searched.")
        items = [SelectItem(label, key, hint=getattr(draft, key) or t("off", ctx="name rule"), description=explanation)
                 for key, label in labels.items()]
        items += [SelectItem(t("Apply rules"), "apply"), SelectItem(t("Cancel"), "cancel")]
        pick = arrow_select(items, title=t("Literal release-name rules"), footer=t("Enter edit • Esc discard"))
        if pick is None or items[pick].value == "cancel":
            return rules
        key = items[pick].value
        if key == "apply":
            return draft
        render = input_screen(t("Release-name rules › {rule}", rule=labels[key]), explanation,
                              t("Empty clears this rule."), keys=t("Enter apply  •  Esc cancel"))
        value = get_query_with_shortcut(PROMPT, initial=getattr(draft, key), screen_renderer=render)
        if isinstance(value, str) and value != "GO_BACK":
            setattr(draft, key, value.strip())
