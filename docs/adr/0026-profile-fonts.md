# ADR-0026: Fonts and text sizes in the Windows Terminal profile, per design

Status: accepted (2026-10-05). Extends ADR-0022's Windows Terminal profile.

## Context

The profile drew every design in PxPlus IBM VGA 8x16 at 12 pt: the Simple
design too, and at a size that makes a fullscreen 1080p window 235x60 cells.
The user wanted to change the font while keeping each design's style. An app
cannot set a terminal's font; the profile can.

## Decision

Settings › Appearance gets **Font** and **Text size** sections on Windows,
for the design on screen. Each design keeps its own font and size (the
`fonts` entry of the saved appearance), so switching designs switches to a
font that suits it:

- **Athanor**: pixel fonts from the Ultimate Oldschool PC Font Pack v2.2
  (CC BY-SA 4.0, bundled unmodified): IBM VGA 8x16 (the default), IBM VGA
  9x16, Toshiba TxL1 8x16, AST Premium Exec 8x19 and IBM XGA-AI 12x20. Chosen
  from the pack's 56 PxPlus fonts for distinct looks; every one has the same
  781 glyphs, so none covers less of the app's symbols than the original.
  Rainbow 100 was rejected (it draws the double-line frame as `=`), as were
  the 8-pixel and stretched variants. Sizes are multiples of the cell (×1,
  ×1.5, ×2, ×3; 12 pt is 16 pixels at 100% scaling), drawn aliased with no
  made-up bold; half sizes are marked uneven.
- **Simple**: fonts Windows and Windows Terminal bring: Cascadia Mono (the
  default), Cascadia Code, Consolas and Lucida Console, at 10 to 20 pt, drawn
  as Windows Terminal draws them.

Bundled fonts are installed for the user, all missing ones at once: when the
profile is added (its confirmation says so) or when a font is first chosen.
An open Windows Terminal tab keeps the font collection it first loaded, so a
font installed after it opened shows only in new tabs, and the screen says
so; afterwards every font and size change applies at once through the
settings reload (ADR-0022). A font Windows lacks is left out of the profile
rather than named, so Windows Terminal never warns about it.

## Consequences

- Big screens can use larger text: IBM VGA 8x16 at ×2 makes the 235x60 grid
  117x30, and XGA-AI's larger cell does it at ×1.
- The wheel grows by four fonts (about 310 KB).
- Elsewhere the rows are not shown: other terminals keep their own fonts.
