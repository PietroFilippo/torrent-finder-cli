# ADR-0020: Quiet terminal design

Status: accepted (2026-10-04). Amends the presentation details of ADR-0008;
its responsive rules (one-line selectable rows, progressive table columns,
live resize) stand. The colour paragraph below is amended by
[ADR-0021](0021-themes.md): the roles stay, the shades come from a palette.

## Context

Every screen stacked a bordered banner holding only the app name, a bordered
menu panel and, on the results screen, a fully ruled table. Five rows of a
24-row terminal went to chrome before the first choice, so the provider list was
windowed to four of seven providers. Emoji icons rendered at different widths
across terminals and misaligned rows. Shortcut letters trailed labels
(`Confirm  [w]`), footers mixed keys and prose in five colours, the download
menu did not say which torrent was picked, and search progress ran on the main
screen between two alternate-screen views. A few screens (credential form,
security warning, confirmation dialog, acquisition results, update display)
drew their own panels and did not follow the menus' conventions.

## Decision

`torrent_finder/ui/theme.py` owns one look, "Quiet", for every screen.

- **Frames** (anything drawn on the alternate screen) start with one header
  line: `torrent-finder › <screen>` with an optional right-aligned status, such
  as a list position, result counts or a version change. A long screen name
  continues on a second, indented line instead of being cut. Content sits under
  a two-cell margin on both sides. No boxes or panels: in windows with room, a
  thin muted rule replaces the spacer line under the header and the one above
  the key bar, so frames gain structure without growing.
- **Rows** keep one physical line. A cursor bar `▍` in a gutter marks focus;
  multi-select states (`On`/`Auto`/`Off`, `Off`/`Require`/`Prefer`, `✓`/`•`)
  share one fixed-width column; inline hints line up within each run of
  consecutive hinted rows. Shortcut letters live in the hint column, not in
  labels, and are drawn like keys. Section headers are bold uppercase labels.
- **Footers stay strings.** `parse_footer` splits each line on `•`/`|`; a
  segment that starts with a key name (`Enter`, `Ctrl+F`, `↑/↓`, a single
  letter…) followed by its action becomes a key-bar segment, anything else is
  prose shown above the key bar with its own markup. A screen without key
  segments gets the default keys. Key segments never split across lines.
- **Logs** (download, stream and acquisition output on the main screen) start at
  column 0, aligned with the tools' own output, with a column-0 app header,
  titled report blocks and one pause-line style.
- **Colours** form one blue scale, each shade with one job. The accent is the
  terminal's own `bright_blue`, so it matches the user's palette: the app name,
  the focused row, the cursor bar and keys. Three fixed shades sit around it,
  tuned to Windows Terminal's Campbell blue: a light sky blue for section and
  column headings and for the subject of a screen (the query, torrent, provider
  or folder after the screen name, `Screen › subject`), a steel blue-grey for
  labels, hints, separators, `Off` and disabled rows (`theme.labelled` tints
  the `Label:` part of `Label: value` lines), and a deep blue for rules. Green
  / yellow / red stay the terminal's named colours for good / warn / bad.
  Content, descriptions and key actions keep the terminal's normal text colour;
  the screen name is bold. Terminals without true colour get the nearest named
  colour. The shades are chosen for dark backgrounds; on a light theme the sky
  headings lose contrast (the accent, keys and content still follow the
  terminal), which is the accepted trade-off for a palette that looks the
  same everywhere. Theme names (`accent`, `muted`, `sky`, `key`, `success`, `warning`,
  `error`, …) are registered in `constants.custom_theme`, including Rich's
  spinner and progress-bar styles; consoles that render app markup must use
  that theme, and frames the app writes to the terminal itself (selector,
  text fields, search progress) render through `constants.buffer_console`,
  which keeps the colour depth of the real console so the fixed shades
  survive.
- **No emoji in menus.** Provider, engine and credential icons remain data.
- Random tips sit on the bottom rows (`arrow_select(tip=…)`), below a gap,
  only when the screen leaves those rows empty, so they never cost list
  rows. Search progress is a frame on the alternate screen, redrawn in
  place line by line. Text fields share `prompts.input_screen`.

## Consequences

- Behaviour, keys and return values are unchanged; only drawing moved. Frames
  measure their own chrome (header lines, context, wrapped key bar), so lists
  get more rows in the same window: the provider list fits at 80×24.
- New screens describe keys in their footer string and get the key bar for
  free; prose belongs on its own footer line or segment.
- `scripts/ui_snapshots.py` captures every screen at three sizes and reports
  words that disappear and frames that overflow; run it before and after
  presentation changes. `tests/test_quiet_layout.py` covers the shared pieces.
- Titles and footers are Rich markup; literal brackets in footers that are not
  markup (`[/]`) must be passed as `Text`.
