# ADR-0031: Paintings without frames, wide works and a lantern icon

Status: accepted (2026-11-04). Amends [ADR-0022](0022-athanor-design.md).

## Context

The Athanor paintings looked pasted on. The engravings are positives, so their
light paper became a solid block of ink on the dark page, and the window cut
each plate off along a hard edge. Several also carried their own frame: a
printed margin and caption (Charon), paper margins (the Raven, *Melencolia I*),
an ornamental border (Flammarion), a plate edge (Maier) or a whole card (the
Hermit). The user wanted the paintings to belong to the page, to have one
that fills the window, and an icon for the profile. Their reference was the
duotone, grainy, full-bleed imagery of the Hermes Agent site: the style, not
its images.

ADR-0022 rejected stretching a plate across the window: covering a 16:9
window cuts more than half of a tall Doré plate. That still holds for plates.

## Decision

**At build time** (`scripts/build_paintings.py`) each painting is cropped to
the picture (its margins, captions and borders removed) and reduced to two
tones with the dot screen that suits it: error diffusion for fine engraving
lines, **grain** (a threshold varied at random by up to 35% of the range,
carrying half the diffusion error: enough grain to read as film, not noise) for
soft tonal plates (Doré, *The Deluge*), or a horizontal **line screen** for a light
subject (*The windmills*). An outline drawing on pale paper (the Hermit) is
**inverted** first, so its lines glow on the page instead of lighting a solid
block. `--out` builds into another folder to compare.

**At run time** (`paintings.render`) the edges toward the text **dissolve**
into the page: the share of dots kept falls to none across 40% of a plate's
width on its inner side (`reach` shortens it for a subject near that side,
such as the Hermit's lantern) and 8% of its height at the top and bottom,
with an 8x8 ordered threshold choosing which dots go. The edge against the
window's own side stays whole. The fade follows the placement (left fades
right, both sides fades the gap away), so each placement has its own picture
name. The engraving's own dots carry the fade, so no blur or alpha is needed,
the PNG stays 1- or 2-bit, and Windows Terminal, which offers no masks, only
has to draw it.

**Ink.** The colourways' `ink` doubles its distance from the page, for a
painting that is present, not barely there. A plate under the text (on the
left, or the faded companion) keeps `FAINT` (55%) of it, a wide work
`ACROSS_INK` (85%). Text keeps its contrast in every case.

**Wide works.** Ten landscape works, CC0 or public domain on Wikimedia
Commons, are marked `wide` in the catalogue: five mezzotints by John Martin
(*Satan presiding at the Infernal Council* and *Pandemonium*, both from
*Paradise Lost* like the Doré plates, *The Deluge*, *The Fall of Nineveh*,
*The Opening of the Seventh Seal*), Rembrandt's etching *The Three Trees*,
Friedrich's *Abbey in the Oakwood* and *Sea of Ice*, Doré's *Over London by
Rail* and Böcklin's *Isle of the Dead*. Mostly dark with light focal points,
they suit a background behind text. Settings › Appearance lists them under
their own heading, oldest first, after none and the plates; saving the
painting as an image has its own heading below the painting side. A wide work always goes
**across** (`uniformToFill`, centred, every edge dissolving), whatever the
saved painting side, which is kept for the next plate; Settings hides the
side for it.

**The icon.** The profile's tab shows a lantern (the Hermit's: the seeker's)
drawn on a 16x16 grid and written 64 pixels square with a transparent ground
(`write_png(..., transparent=True)` adds a `tRNS` chunk). Steel draws the
metal; the brighter of accent and sky draws the flame, the other the glass,
so it follows every palette, Simple included and in the plain look.

**Updating.** `terminal_profile.LOOK_VERSION` ends every picture and icon name,
because Windows Terminal caches pictures by path. At start, an installed
profile whose icon lacks the current version (`stale`) is rewritten once from
the saved appearance (`appearance.refresh_stale_profile`), so an update shows
the new look without a visit to Settings.

**Both sides.** The left plate is the painting's usual companion unless the
user chooses another plate under Left painting (`appearance.companion`, saved,
validated by backups; `paintings.left_plate` falls back to the companion when
the choice is the painting itself, a wide work or unknown). The spread's
picture name names both plates.

*Amended after release, 2026-11-04 (look v3):* the grain was softened (its
random spread from 85% to 35%) because it read as too granular, and the left
plate became a choice. `LOOK_VERSION` went to `v3`, so profiles drawn by
v0.11.0 are redrawn once at start.

## Rejected

- **Inverting every plate**: the paper is dots too, so the box stays, and
  tonal plates become negatives.
- **Lowering Windows Terminal's opacity**: a dimmer box is still a box.
- **Hand-drawn masks per painting**: the best result, but manual work for
  each plate. Possible later for a few favourites.
- **Piranesi's *Carceri***: mostly white paper, which would light the whole
  window.
- **Greyscale assets dithered at run time**: larger, and
  slow in pure Python, for a choice made once per painting.

## Consequences

- The paintings ship 20 PNGs (about 560 KB in all). Rendering a dissolved
  plate in pure Python takes a fraction of a second, once per choice.
- A new painting is a `plate(...)` line in the build script with its crop and
  screen; `wide=True` makes it fill the window.
- Tests that start the app with the profile supported must stub
  `refresh_stale_profile`, or a stale profile on the test machine is rewritten.
