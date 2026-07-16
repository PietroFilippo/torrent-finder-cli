# ADR-0008: Responsive terminal layout

Status: accepted (2026-07-15)

## Context

The interactive UI originally treated terminal width as fixed. Selector rows,
hints, descriptions, result columns, and streaming headers were sized by
Python string length or desktop-oriented minimums. In a narrow window this
cropped explanatory text, compressed every result column at once, and could
place streaming subprocess output inside a wrapped header.

Wrapping every selectable row is not viable: row height would vary with the
cursor and invalidate viewport windowing. The UI needs separate rules for
navigable rows and contextual prose.

## Decision

`torrent_finder.ui.layout` owns terminal-cell-aware ellipsis and marquee
helpers. Wide characters are measured by rendered cells, not code points.

Selectors keep each navigable row to one line. At narrow widths, inline hints
move into the selected item's context area; hints, descriptions, and footers
wrap. Their rendered line counts reduce the number of list rows shown, while
action rows stay accessible.

Result tables use four progressive layouts:

- full: all applicable columns;
- medium: source, name, size, and seeds;
- compact: selection, index, name, and seeds;
- minimal: one combined result column.

Metadata hidden by a layout is shown in the selected-row caption. The live
result screen watches terminal size changes and recalculates its layout,
visible row count, and scroll offset without reopening the screen.

Torrent information uses the available width instead of a 40-column floor.
Streaming headers measure their actual rendered height and start any child
output scroll region below it.

## Consequences

- Narrow windows preserve commands and selected-result context instead of
  squeezing every field into unreadable columns.
- List navigation remains stable because selectable rows do not change height.
- Width thresholds and reserved-height estimates are presentation policy and
  should be covered by characterization tests when changed.
- Extremely small terminals may show only one selectable row, but navigation
  still exposes the full list.