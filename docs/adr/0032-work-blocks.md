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
  is at least 64 cells, so its key bar fits on one line; under 120 columns,
  where little painting shows, it takes the window's width so its help wraps
  less.
- **The inspector sits right beside the list**, 40 to 56 cells (30% of the
  window), from 120 columns, so a 144-column window has one. Its divider ends
  with its lines; the key bar runs under the list and the pane. A row whose
  hint shows in full is not repeated in the pane, and a pane that would show
  only the row's name is not drawn.
- **The keys do not move with the focus.** When the whole list fits, the
  block keeps rows for the longest help a row has (up to four); a list that
  scrolls keeps its rows instead. On a list of up to 40 rows the pane and
  detail lines are measured for every row before the first frame.
- **The tip is short and sits under the keys**, a row apart: only tips of up to
  180 characters rotate, and a tip that would take more than two lines is not
  shown. The intro and the tip may run 100 cells wide, past a narrow block.
- **`?` always has a place in the key bar**: when it does not fit, the last
  secondary keys give it theirs (`?` lists them).
- **Small windows** (under 60 columns or 18 rows) show two rows of keys:
  moving, Enter, Esc and `?` first, then the others while they fit, and only
  the first word of each when even those need more; `?` lists the rest. The
  focused row's help, the notices and the intro give way until three choices
  show (headings between them do not count). The frame's top edge drops the
  app name before it cuts the screen's name. The results table follows the
  same key budget.
- Confirmations follow the same rule: a 76-cell block of question, rule and
  keys, with Y named for what it does (`Y quit`, `Y delete`).

Text over the painting is measured, not assumed: in a 144x36 window every
Athanor text role (body, muted, accent, sky, good, warn, bad) reaches 4.5:1
against the brightest tenth of the text-cell-sized patches of the painting
behind the pane, over the three densest plates (`tests/test_painted_contrast.py`).
Muted text stays under 70% of body text's contrast, so it still reads as
secondary.

## Consequences

- The space a short screen leaves is in one piece, beside and below the work,
  instead of a band between a list and its keys.
- The key bar's row differs between screens, as the lists do. On one screen
  it stays put while the focus moves.
- `tests/test_tall_layout.py`, `tests/test_inspector.py` and
  `scripts/ui_snapshots.py` (now also at 144x36 and 236x58) pin the block, the
  pane's place and the steady keys.
