# ADR-0021: Themes: fixed colour roles, palettes as data

Status: accepted (2026-10-04). Amends the colour paragraph of ADR-0020; its
layout rules stand.

## Context

ADR-0020 gave the Quiet look one blue scale with one job per shade, as module
constants in `ui/theme.py`. Users asked for other colours, and the accepted
trade-off of that ADR (the fixed shades lose contrast on light terminal
backgrounds) left light-terminal users without a readable option. A review
of every screen also found the shades were not the problem: the screens left
useful lines empty and drew state words (`timed out`, `blocked`, `On`) in
plain text although the palette already had state colours.

## Decision

**Roles are fixed; palettes are data.** `theme.Palette` holds one colour per
role and nothing else:

| Role | Job |
| --- | --- |
| `accent` | the brand, cursor bar, focused row, keys, Prefer |
| `sky` | section and column headings, the subject after a crumb |
| `steel` | labels, hints, separators, Off, disabled rows |
| `deep` | rules and bars |
| `fill` | the focused row's background with the "fill" focus style |
| `good` / `warn` / `bad` | On / Auto / failures; seed health; feedback |

`theme.THEMES` registers six palettes: **Quiet Blue** (the default: the
terminal's own `bright_blue` with the ADR-0020 shades), **Iris** (violet),
**Lagoon** (teal), **Ember** (warm; Auto moves to orange so it never looks
like the accent), **Mono** (no hue; weight carries structure) and **Paper**
(every shade darker than a light page, with darker state colours). Dark
palettes leave good/warn/bad to the terminal's named green, yellow and red.

`theme.apply()` rebinds every role name in the module (`ACCENT`, `KEY`,
`MUTED`, `SECTION`, `SUBJECT`, `RULE_STYLE`, …), refills `STYLES` in place,
rebuilds `constants.custom_theme` and pushes it on the shared console, so the
next frame of every screen follows; screens read `theme.X` at render time and
nothing captures a colour at import. Markup uses role names (`[warn]`,
`[alert]`, `[banner]`), never colour names.

Two switches sit beside the palette:

- **Focus**: "bar" (the cursor bar and bold text, as before) or "fill" (the
  focused row also takes the `fill` background to the right margin; the
  results table fills its focused row too).
- **Density**: "comfortable" or "compact". Every spacing decision asks
  `theme.roomy(height, threshold)`; compact answers no at any size, so lists
  keep the short-window layout and gain the rows rules and spacers took.

**Resolution at startup**: `--theme NAME` (this run only), then
`TORRENT_FINDER_THEME`, then the saved `settings.appearance` (`theme`,
`focus`, `density`), then Quiet Blue. An unknown environment value is named
on the main menu and ignored; unknown saved values fall back silently. The
update viewer, a separate process, applies the saved appearance too.
Appearance is a portable preference in settings backups.

**Settings › Appearance** shows every theme with its four shades as swatches
and sample words in its own colours; Space previews a theme in place, Enter
applies and saves it, Esc puts the saved one back. Focus and density are
chosen on the same screen.

`NO_COLOR` keeps working through Rich: colour is dropped, bold stays, so the
focused row still reads by weight and the cursor bar.

## Related layout additions (same change)

These keep ADR-0020's rules (one physical line per row, one key bar):

- `SelectItem` labels and hints may be `Text`, so a state word, a bar or a
  matched prefix keeps its colour; alignment measures plain text. Hints line
  up across section headings. A number-only hint is a value, not a key.
- `arrow_select(intro=…)` draws a summary under the header (the download
  menu's torrent facts); it keeps one line in compact windows and gives way
  in tiny ones.
- `?` lists every key of a screen (its footer's, then the standard ones; the
  results table adds digits, d, n, r, m and paging). "? keys" joins the key
  bar only when it needs no extra line.
- Header status carries what a screen is about: version, update and network
  verdict on the main menu; counts on Filters, Stats, Bookmarks, Episodes;
  failures on Search diagnostics. A subject follows a crumb (`Filters ›
  Movies & Series`), never a dash, so it takes the subject shade.

## Consequences

- A new screen gets every theme for free by using role names.
- A new role is a design change: add it to `Palette`, every palette and this
  ADR, never as a one-off colour in a screen.
- `scripts/ui_snapshots.py themes` captures every screen in every theme (and
  the filled focus) and fails on any word one shows and another does not, or
  on an overflowing frame; `capture LABEL quiet:compact` checks the compact
  density. `tests/test_themes.py` covers palettes, `apply()` and resolution.
- Rich caches a style's escape codes on first render: tests that drive
  selectors without asserting on output patch `selector._render`, so a
  16-colour write never leaks into a later true-colour assertion.
