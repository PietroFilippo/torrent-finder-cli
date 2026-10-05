# ADR-0027: Athanor's plain look in the profile, and opening it from other tabs

Status: accepted (2026-10-05). Extends ADR-0022 and ADR-0026.

## Context

Two requests about the Windows Terminal profile:

- Start the app with its full look (page, painting, pixel font) from the
  command typed in any tab, instead of opening the profile from the ▾ menu.
- Keep, as a choice, the look Athanor has outside the profile: the app draws
  the same frame and colours everywhere, and outside the profile they sit on
  Windows Terminal's own page and font with no painting.

Windows Terminal keeps background pictures and fonts in profiles. The escape
sequences it understands can recolour a tab (OSC 4, 10, 11, 12) but nothing
sets a picture, a font or the tab's profile: its OSC 1337 handles only
`SetMark` and its own OSC 9001 only `CmdNotFound` (checked in its source). A
running program cannot give its own tab the profile's look.

## Decision

- **Look** (Settings › Appearance › Windows Terminal, Athanor only): *Full*,
  the colourway's page, the painting and the chosen pixel font, or *Plain*,
  which leaves the colour scheme, picture and font out of the profile so
  Windows Terminal draws its own page and font, as in any other tab. Font and
  Text size are hidden in Plain, where they do not apply. Saved in the
  appearance's `profile` entry; Simple has no such choice.
- **Open from other tabs** (off by default, offered once the profile
  exists): when the command starts interactively in a Windows Terminal tab
  of another profile, it runs `wt -w 0 new-tab -p torrent-finder`, passing
  its arguments with the profile's own command (`;` escaped, since it starts
  Windows Terminal's next command), and exits; that tab gets its prompt back.
  It happens before anything is recorded or drawn. Without `wt`, or when it
  fails, the app runs where it was started.

Other terminals are out of scope: some can show pictures (iTerm2's OSC 1337
`SetBackgroundImageFile`, Konsole profiles, Kitty's remote control), none of
them was available to test.

## Consequences

- Typing the command can bring the full look, at the cost of a second tab;
  this is why it is a choice and off until chosen.
- The plain look in the profile is exactly what other tabs show, so the
  profile then only gives the app its own entry in the ▾ menu.
