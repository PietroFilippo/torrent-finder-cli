# ADR-0032: Screens are work blocks; the rest of the window is the painting's

Status: accepted (2026-11-07). Supersedes ADR-0025's bottom key bar and
ADR-0023's 150-column threshold and window-wide pane.

## Context

ADR-0025 put every selector's key bar on the bottom rows, so the bar stayed
in one place on every screen. In practice a nine-row menu such as What's Next
sat at the top of a 144x36 window with eighteen blank rows (forty at 236x58)
between its last row and its keys. Confirmations put one question in the
top-left corner of an empty frame. Measured on every screen, most menus left
15 to 28 rows empty at 144x36 and 40 to 50 at 236x58, and the empty rows always
cut a list off from its own keys. The inspector pane took 40% of a 150-column
window, even when the focused row had one line to say, while a 144-column
laptop window never got one.

A design review (two outside reviewers and this one, scoring nine aspects)
agreed the problem was where the space went, not how much there was. Filling
every cell is not the answer either: the painting needs room (ADR-0031).

## Decision

A screen is one **work block**: its intro, its list (and the inspector beside
it), the focused row's help, its notices, the rule and the keys, kept
together. The rest of the window is left open, where the painting shows.

- **Every screen starts on the first row**, like the search field and the
  results, so moving between screens never shifts the eye. A long list still
  fills the window, and its keys end up on the last rows.
- **The list column is as wide as its rows** (48 to 108 cells, margins
  included), wide enough to line hints up in one column. A list without a pane
  is at least 64 cells, so its key bar fits on one line.
- **The inspector sits right beside the list**, 40 to 56 cells (30% of the
  window), from 120 columns, so a 144-column window has one. Its divider ends
  with its lines; the key bar runs under the list and the pane. A row whose
  hint shows in full is not repeated in the pane.
- **The keys do not move with the focus.** The block keeps rows for the
  longest help a row has (up to four), and the pane and detail lines keep the
  rows they needed for another row on the same screen.
- **The tip is short and sits under the keys**, a row apart: only tips of up to
  180 characters rotate, and a tip that would take more than two lines is not
  shown. The intro and the tip may run 100 cells wide, past a narrow block.
- **Small windows** (under 60 columns or 18 rows) show two rows of keys:
  moving, Enter, Esc and `?` first, then the others while they fit; `?` lists
  the rest. The focused row's help gives way until three rows of the list show.
  The frame's top edge drops the app name before it cuts the screen's name.
- Confirmations follow the same rule: a 76-cell block of question, rule and
  keys, with Y named for what it does (`Y quit`, `Y delete`).

## Consequences

- The space a short screen leaves is in one piece, beside and below the work,
  instead of a band between a list and its keys.
- The key bar's row differs between screens, as the lists do. On one screen
  it stays put while the focus moves.
- `tests/test_tall_layout.py`, `tests/test_inspector.py` and
  `scripts/ui_snapshots.py` (now also at 144x36 and 236x58) pin the block, the
  pane's place and the steady keys.
