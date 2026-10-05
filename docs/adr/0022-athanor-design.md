# ADR-0022: The Athanor design: a framed scriptorium, paintings and a terminal profile

Status: accepted (2026-10-04). Amends ADR-0021: every palette now belongs to a
design, the default is Athanor's Citrinitas, and a terminal profile may give
the page the theme's colour and a painting.

## Context

ADR-0021 gave the Quiet look six palettes. Users liked a roguelike desktop
style (a NetHack-like status line, the IBM VGA font, warm "srcery" colours and
Gustave Doré engravings behind the terminal) and asked for it as the default,
with the earlier themes kept as a "Simple" category, and with the painting
chosen apart from the colours.

An app cannot draw behind its own text: the page is the terminal's. Drawing
an engraving in the text grid (braille or half-block characters) turns a Doré
plate into noise at 80x24 and takes the rows the content needs.

## Decision

**Designs.** `theme.Design` holds a name, a note, a glyph set and whether it
is framed. **Athanor** (the default) draws `@` for the cursor, `»` between
the parts of a screen name, `√`/`∙` for checkboxes and `▓` bars. **Simple** is
the ADR-0021 look, unchanged. Every `Palette` names its design;
`theme.palettes(design)` lists them and `DEFAULT_THEMES` says which one a
design starts on. Athanor has five colourways named for the stages of the
alchemical work: **Citrinitas** (the default: lamplight amber on parchment),
**Rubedo**, **Albedo**, **Viriditas** and **Nigredo**. A colourway adds roles
the frame needs: `page` (its background), `text`, `ink` (the painting),
`frame` and `bar_bg` (the message and status lines). The resolution order of
ADR-0021 stands; its last step is now Citrinitas.

**The chrome** (`ui/chrome.py`). Screens build their content as before and
pass it to `chrome.compose()` (or wrap a Rich renderable in `chrome.Framed`),
which returns exactly the window's height:

- a **message line**: the newest `chrome.announce()` message, `--More--` when
  others wait (the quit guard stays under the key bar, as in Simple);
- the **frame's top edge** carrying the header, `torrent-finder » Screen ›
  subject`, and the screen's status;
- the content between `║` sides that take the two margin cells, so content
  keeps its columns and ADR-0020's one-line-per-row rules hold;
- the bottom edge and a **status line**: Searches, Picked, Bookmarks and T
  (keys read this session), then the date, the network verdict and the
  version.

`theme.view_height()` is what a screen may use. Windows under 40x12 get no
frame; the two lines need 24 rows and the comfortable density. When framed,
`theme.frame_header()` returns nothing because the frame carries the name.
The main menu shows a MUD-style room in tall windows (`~ The Index ~`, a
description, the obvious exits).

**Paintings** (`paintings.py`, `assets/paintings`). Ten public-domain works,
six of them Doré's, plus Dürer's *Melencolia I*, the Flammarion engraving,
Pamela Colman Smith's *Hermit* and Merian's emblem for Maier's *Atalanta
Fugiens*, ship as two-tone dithers 560 dots high (about 25 KB each) with
`catalog.json` and `CREDITS.md`. `scripts/build_paintings.py` rebuilds them
from Wikimedia Commons and refuses any scan not marked public domain. At run
time a painting is recoloured into the colourway's `ink` on its `page` and
scaled by whole pixels with `zlib` and `struct` only. The painting is its own
saved choice (`settings.appearance.painting`: a key or `none`), so any
painting goes with any colourway. Settings › Appearance lists them under
Painting for the Athanor design.

**Where a painting shows.** The terminal draws it:

- On Windows, Settings › Appearance › Windows Terminal adds a
  `torrent-finder` profile (`terminal_profile.py`) through a JSON fragment
  in `%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\torrent-finder`.
  Its colour scheme puts the theme's page and text in the background and
  foreground, with the states on the ANSI colours. Its background picture is
  the painting in that colourway, uniform and right-aligned. The picture is a
  bare file name beside the fragment, which Windows Terminal 1.24 and later
  resolve; earlier versions show the profile without it. Its font is PxPlus
  IBM VGA 8x16 (bundled with its CC BY-SA 4.0 licence; installed for the
  current user, after a confirmation that says so), drawn aliased. The GUID
  follows Windows Terminal's rule for fragment profiles. The profile runs the
  frozen binary, the installed `torrent-finder` command, or this Python with
  `-m torrent_finder` from the source checkout.
- Nothing is written until the user asks. Afterwards, colour and painting
  choices rewrite the profile, each look under its own picture name because
  Windows Terminal caches pictures by path. Remove deletes the folder (the
  font stays). Windows Terminal reads fragments when it starts, and the
  screen says so.
- Elsewhere, "Save the painting as an image" writes the PNG in the colours on
  screen to `~/Pictures/torrent-finder`, for the terminal's own background
  setting.

ADR-0021 rejected painting the page from the app. That still holds: the
profile asks the terminal to do it, so the padding, subprocess output and
resizes all show the theme's page. In the profile, Paper finally gets its
light page.

## Rejected

- **Art in the text grid** (braille, half blocks, sixel): illegible at
  terminal sizes, covered by every redraw, and it costs content rows.
- **Shipping the scans**: the dithers are a twentieth of the size, and
  recolouring needs only one bit per dot.
- **Editing Windows Terminal's settings.json**: fragments are the documented
  extension point, and deleting one folder undoes them.

## Consequences

- The package ships `torrent_finder/assets/**` (`[tool.setuptools.package-data]`);
  release binaries add `--collect-data torrent_finder`.
- A new screen composes through `chrome.compose`/`chrome.Framed` and asks
  `theme.view_height()` for its rows. A new painting is a line in
  `build_paintings.PAINTINGS`; the catalogue order is the menu order.
- Most layout tests describe the Simple design, so `tests/conftest.py` applies
  it around every test, and Athanor tests apply Citrinitas themselves.
  `tests/test_athanor_chrome.py`, `test_paintings.py` and
  `test_terminal_profile.py` cover the frame, the codec and catalogue, and
  the fragment. A conftest fixture keeps every test away from the real
  Windows Terminal folder.
