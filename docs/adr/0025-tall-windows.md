# ADR-0025: Tall windows keep the key bar at the bottom and fill rows with details

Status: accepted (2026-10-05). Extends ADR-0020's layout and ADR-0023's
inspector pane.

## Context

Menus were drawn from the top: header, list, the focused row's help, a rule,
the key bar, then nothing. In a maximised window most of the frame stayed
empty below them. Measured on every screen at the user's sizes (137x36 and,
fullscreen with the profile's 12 pt pixel font, 235x60), typical menus used
8 to 15 of 32 rows, and 5 to 27 of 56 in the list column beside 1 to 6 used
in the inspector pane. The key bar also moved from screen to screen with the
length of each list.

Filling the space with new content (the painting in the text grid, more
tips) was ruled out as clutter; ADR-0022 had already rejected art in the
grid.

## Decision

In roomy windows (comfortable density, past the selector's short-window
threshold), every selector screen:

- **keeps its footer on the bottom rows**: the focused row's help, notices,
  the rule and the key bar sit at the bottom of the frame, above the tip;
  the list stays at the top. The key bar is in the same place on every
  screen, whatever the length of the list. With the inspector pane, the
  footer is at the bottom of the list column.
- **shows the focused row's details below the list when there is no room
  beside it**: the `SelectItem.inspect` lines the pane shows in wide windows
  go above the key bar, in rows the list leaves empty (one row stays between
  them), cut with "…" when they do not fit. They never cost list rows.

Settings' rows got such details (the appearance in use, the terminal command,
the network check), split out of the main menu's Settings row.

Compact density and short windows keep the old layout, so they keep every
row for the list.

The text itself can be larger in the Windows Terminal profile (ADR-0026),
which is what shrinks a fullscreen grid; the layout only uses the rows it has.

## Consequences

- Short menus read as one full-screen layout: list on top, help and keys at
  the bottom, instead of a block at the top of an empty frame. The eye
  travels further from a short list to its keys in very tall windows.
- `tests/test_tall_layout.py` pins the footer's place, the tip, compact
  density, short and wide windows, and the details' room.
