"""Shared keyboard mechanics for multi-select menus."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from torrent_finder.ui import theme
from torrent_finder.ui.selector import SelectItem


@dataclass(frozen=True)
class SelectionPolicy:
    """Caller-owned state rules; clear also visits disabled rows."""

    is_active: Callable[[int, SelectItem], bool]
    set_active: Callable[[int, SelectItem, bool], None]
    invert: Callable[[int, SelectItem], None]
    toggle: Callable[[int, SelectItem], None]
    clear: Callable[[int, SelectItem], None]


class MultiSelection:
    """Selector callbacks over original row indexes, independent of the viewport.

    Navigation belongs to the selector. An anchor stays on its original row
    while the cursor moves, and a range may end on an action or section header.
    Only all, invert, range and the current-row toggle skip disabled rows.
    """

    def __init__(self, indexes: Sequence[int], confirm_index: int,
                 policy: SelectionPolicy) -> None:
        self.indexes = indexes
        self.confirm_index = confirm_index
        self.policy = policy
        self.anchor: int | None = None

    def select_all(self, cursor: int, items: list[SelectItem]) -> bool:
        for i in self.indexes:
            if items[i].enabled:
                self.policy.set_active(i, items[i], True)
        return True

    def invert(self, cursor: int, items: list[SelectItem]) -> bool:
        for i in self.indexes:
            if items[i].enabled:
                self.policy.invert(i, items[i])
        return True

    def clear(self, cursor: int, items: list[SelectItem]) -> bool:
        for i in self.indexes:
            self.policy.clear(i, items[i])
        return True

    def confirm(self, cursor: int, items: list[SelectItem]) -> int:
        return self.confirm_index

    def set_anchor(self, cursor: int, items: list[SelectItem]) -> bool:
        if cursor not in self.indexes:
            return True
        if self.anchor is not None and 0 <= self.anchor < len(items):
            items[self.anchor].marker = ""
        self.anchor = cursor
        items[cursor].marker = theme.MARKER
        return True

    def range_toggle(self, cursor: int, items: list[SelectItem]) -> bool:
        if self.anchor is None:
            return self.set_anchor(cursor, items)
        lo, hi = sorted([self.anchor, cursor])
        target = not self.policy.is_active(self.anchor, items[self.anchor])
        indexes = set(self.indexes)
        for i in range(lo, hi + 1):
            if i in indexes and items[i].enabled:
                self.policy.set_active(i, items[i], target)
        items[self.anchor].marker = ""
        self.anchor = None
        return True

    def toggle_current(self, cursor: int, items: list[SelectItem]) -> bool:
        if cursor in self.indexes and items[cursor].enabled:
            self.policy.toggle(cursor, items[cursor])
        return True

    @property
    def key_actions(self) -> dict[str, Callable[[int, list[SelectItem]], object]]:
        actions = {"v": self.set_anchor, "V": self.range_toggle, " ": self.toggle_current}
        for key, callback in (("a", self.select_all), ("i", self.invert),
                              ("c", self.clear), ("w", self.confirm)):
            actions[key] = actions[key.upper()] = callback
        return actions
