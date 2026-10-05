# ADR-0023: An inspector pane beside lists in wide windows

Status: accepted (2026-10-05). Extends ADR-0020's layout rules; applies to both
designs of ADR-0022.

## Context

A maximised terminal (about 210x52 on a 1080p screen) left most of every menu
empty: the main menu used a third of the rows and under half the width. Taller
lists or more sections would fill some height, but leave the right half empty
and make the menus busier.

## Decision

From 150 columns, a selector whose rows carry help (a description or
`SelectItem.inspect`) shows an **inspector pane** on the right
(`theme.inspector_width`: 40% of the window, 56 to 90 cells):

- It is read-only and follows the focused row: the row's name, its hint, its
  description (moved there from under the list, not repeated), then the lines
  `SelectItem.inspect` returns. Those are computed the first time the row is
  focused and kept (`SelectItem.details()`); a failing source shows nothing.
- The list column is laid out as if the window were that narrow (a per-thread
  layout width read by the row helpers), so rows, hints, marquees and the key
  bar keep their ADR-0020 rules. The header and the tip span the window; a
  `│` in the rule colour divides the two.
- The layout stays put while the cursor moves: the pane shows for the whole
  screen when any row has help, even on rows without any.
- Narrower windows, and screens whose rows have no help (What's Next), keep
  one column, exactly as before.

The main menu fills the pane (`ui/inspector.py`): a provider's engines with
On/Auto/Off, its Require/Prefer presets, recent searches there and its search
and pick counts; a group's sources; the selected providers of Search across
providers; Continue's names, presets and the searches before it; which logins
are set; the download folder's free space and unpack setting; the appearance,
terminal command and network verdict in use. Every other selector with row
help gets the pane with that help.

## Consequences

- A screen gains a richer pane by passing `inspect=` on its rows; the lines are
  plain `Text` in role styles (`inspector.heading`, `inspector.pair`), and user
  text is appended as text, never parsed as markup.
- `scripts/ui_snapshots.py` also captures 200x50, so every screen is checked
  for overflow with the pane.
- `tests/test_inspector.py` covers the layout (threshold, style isolation,
  clipping, the tip, the Athanor frame) and the main menu's details.
