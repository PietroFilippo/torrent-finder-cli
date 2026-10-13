# Torrent Finder user guide

How each part of Torrent Finder works, organised by task. To install it, see
the [README](../README.md#install). For each source's measured coverage and
known gaps, see the [provider reference](PROVIDER_REFERENCE.md).

## Contents

1. [Getting around](#getting-around)
2. [Providers and sources](#providers-and-sources)
3. [Searching](#searching)
4. [Filters, presets and engines](#filters-presets-and-engines)
5. [Searching across providers](#searching-across-providers)
6. [Working with results](#working-with-results)
7. [Downloading](#downloading)
8. [Streaming and subtitles](#streaming-and-subtitles)
9. [History, stats, bookmarks and backups](#history-stats-bookmarks-and-backups)
10. [Appearance](#appearance)
11. [Settings and startup checks](#settings-and-startup-checks)
12. [Credentials](#credentials)
13. [Your data](#your-data)
14. [Updating](#updating)

## Getting around

The app draws on the terminal's alternate screen, so your scrollback is left
as it was when you quit.

### The main menu

- **CONTINUE** reopens your newest search. A plain keyword search reopens the
  search field with its query.
- **SEARCH** lists the providers. **Games**, **Software** and **Manga** open a
  submenu of their sources. Each row shows the engines it will search and its
  preferred or required presets.
- **TOOLS**: **Install update** (only when one is available), **Quick
  actions**, **Credentials** (with how many are set), **Download folder** (with
  its path) and **Settings** (appearance, terminal command, network check).
- The header shows the version, a pending update and, once the network check
  has run, **VPN** or **IP visible**.

Keys: **F** opens the highlighted provider's filters and engines and comes
back, **H** search history, **S** usage stats, **T** tips, **Tab** quick
actions, **U** install update.

Anime, Movies & Series, General Games, General Manga and Books open **Search
options** first: keyword search, [alternate-title search](#alternate-titles),
[topic discovery](#topic-discovery) and [search by creator](#search-by-creator).

### Keys on every screen

| Key | Action |
|---|---|
| ↑/↓ | Move |
| PgUp/PgDn, Home/End | Move a page; jump to the first or last choice |
| Enter | Choose |
| Space | Tick a checkbox, or cycle a mode in Filters & engines |
| Esc | Back or cancel |
| ? | List every key of this screen, including those a narrow key bar leaves out |
| Ctrl+C | Cancel the running operation |

Long lists show your position at the right of the header line.

### The search prompt

- Type a title and press **Enter**.
- **Ctrl+N** adds another title ([several titles at once](#several-titles-at-once)).
- **Ctrl+F** opens filters and engines; **Tab** opens quick actions, keeping
  what you typed.
- **RECENT**, under the field, lists this provider's past searches that contain
  what you have typed; **↑/↓** walk it.
- The prompt has no single-letter shortcuts, so a query can start with any letter.
- **Esc** backs out one step at a time: it clears the line, then brings back the
  last added title for editing, and leaves only when everything is empty.

### Quick actions

**Tab** on the main menu, on What's Next or at a search prompt:

| Key | Action |
|---|---|
| F | Filters & engines |
| A | [Alternate-title search](#alternate-titles) |
| D | [Discover by topic / genre](#topic-discovery) |
| H | [Search history](#search-history) |
| B | [Bookmarks / download later](#bookmarks) |
| L | Bookmark current search |
| E | [Settings backup / import](#settings-backup-and-import) |
| Q | [qBittorrent connection / progress](#qbittorrent-webui) |
| S | [Usage stats](#usage-stats) |
| T | Tips & shortcuts |
| U | Install update (when one is available) |

From a provider's search prompt the actions keep that provider. From a general
menu, the search-specific ones (filters, alternate titles, topic discovery,
bookmarking a search) first ask which provider.

### After a download: What's Next

When a download or handoff finishes, choose **Continue to What's Next** or
**Back to download options** (Esc does the same). Back keeps the same torrent,
file and subtitle choices, or batch selection, and never repeats the download
or handoff.

What's Next has a key for every row: **R** search again, **P** change provider,
**M** main menu, **Tab** quick actions, **H** history, **S** stats, **T** tips,
**C** credentials, **Q** exit. Lowercase letters work too. Exit, **Q**, **Esc**
or **Ctrl+C** ask for confirmation; declining returns to the menu.

### Quitting

On the main menu, quitting takes two presses of **Esc** or **Ctrl+C**, in any
mix. After the first, "Press Esc or Ctrl+C again to quit" appears under the key
bar; any other choice, a submenu included, cancels it.

### Tips

A random tip sits at the bottom of the main menu and What's Next when the screen
has empty rows there, so it never pushes choices off screen. The tips browser
(**T** on the main menu or What's Next, **Tab → T** at a search prompt) has
**/** to search categories, text and tags, **C** to cycle categories, **X** to
clear the search and **Esc** to go back.

## Providers and sources

A **provider** is what you are looking for; its **engines** are the sources it
searches. Several providers share engines (APIBay, Knaben, Nyaa), so they are
not independent catalogs.

| Provider | `-t` | Engines: On / Auto / Off by default | Account |
|---|---|---|---|
| Movies & Series | `movie` | APIBay, Nyaa live-action / Knaben / YTS, SolidTorrents | none |
| Games › General | `game` | APIBay, Online-Fix, FitGirl / Knaben / SolidTorrents | none |
| Games › Online-Fix | `online-fix` | Online-Fix | none |
| Games › FitGirl | `fitgirl` | FitGirl | none |
| Software › Desktop | `software` | APIBay, Knaben / – / SolidTorrents | none |
| Software › Mobile | `mobile` | Knaben / APIBay / SolidTorrents, F-Droid | none |
| Software › RuTracker | `rutracker` | RuTracker | required |
| Anime | `anime` | Nyaa / Knaben / APIBay, SolidTorrents | none |
| Manga › General | `manga` | Nyaa (EN), APIBay Comics / Knaben / Nyaa (Raw), Nyaa (Non-English) | none |
| Manga › Madokami | `madokami` | Madokami | required |
| Books | `books` | Libgen, APIBay E-books and Audio books / Knaben / SolidTorrents | none |

`movies`, `games` and `book` work for `-t` too, and `-t all` is
[search across providers](#searching-across-providers).

- **Movies & Series** covers films and TV. When a torrent holds several video
  files, the [episode flow](#episodes) starts by itself.
- **General Games** covers PC, consoles, ROMs and repacks: The Pirate Bay's game
  categories plus the FitGirl and Online-Fix sites.
- **Online-Fix** searches [online-fix.me](https://online-fix.me) for co-op and
  online game cracks. Search and download need no account (the file host checks
  the referring page, not a login). A pick saves the `.torrent` into your
  download folder, opens it in your torrent client and shows the archive
  password (`online-fix.me`). Online-Fix matches title text literally: when a
  title with several words finds nothing, the app suggests one distinctive word
  to try (`Starve` for Don't Starve Together).
- **FitGirl** searches the official [fitgirl-repacks.site](https://fitgirl-repacks.site),
  the one trustworthy source for FitGirl repacks: fake "FitGirl" uploads on
  public trackers are a known malware vector. The magnet comes from the post
  when you pick a result.
- **Desktop** searches The Pirate Bay's Applications categories and Knaben
  together.
- **Mobile** is Android only (APK, MOD, OBB) and says so when you search. The
  optional **F-Droid** engine adds free and open-source apps from the official
  repository; rows show the exact package (`VLC [org.videolan.vlc]`). A pick
  downloads F-Droid's suggested APK from f-droid.org, and only from there. Apps
  published per CPU type get the suggested build, the done panel says so and
  links the package page. Android checks the APK's signature on install;
  F-Droid's PGP signature is linked, not checked. F-Droid has no commercial apps.
- **RuTracker** logs into [rutracker.org](https://rutracker.org) and searches it
  directly: software, audio and rare content. It warns when no login is set.
  RuTracker currently blocks scripted logins with Cloudflare's browser check;
  the search then reports **blocked** (an access problem, not a wrong password)
  and waits five minutes before trying again. The app does not get around the check.
- **Anime** searches Nyaa's English-translated category by default
  ([other categories](#anime-and-manga-sources)).
- **General Manga** searches Nyaa Literature and The Pirate Bay's Comics.
- **Madokami** searches the private [manga.madokami.al](https://manga.madokami.al)
  library ([direct downloads](#direct-downloads), no torrent client).
- **Books** searches Libgen (anonymous [direct downloads](#direct-downloads))
  and The Pirate Bay's E-books and Audio books; SolidTorrents' eBook category is
  opt-in. Libgen rows show format and language (`[epub, English]`), and presets
  cover EPUB, PDF, Kindle (MOBI/AZW3), Audiobook and English.

### Engine modes

Each engine is **On**, **Auto** or **Off**, saved per provider:

- **On** engines are searched every time, in parallel; results are merged and
  duplicates (the same info hash) removed.
- **Auto** engines run only when the On engines return no rows at all. Books
  and Mobile also run them when no row is the requested book or app. Rows
  your own filters remove later never trigger Auto.
- **Off** engines are skipped, unless an active preset, or a preset word typed
  after the title, needs them for that search.

Engines without a safe fallback role offer On and Off only. More sources
improve availability, but no setting can guarantee results: every source can
be down.

**Knaben** is a meta-index with a [documented API](https://knaben.org/api/v2/),
used through its cacheable v2 searches as Knaben asks. One request per search
asks for the provider's categories, at most 50 rows. Unsafe and adult rows stay
hidden, zero-seed rows stay listed, rows need a valid info hash, and the
focused row shows the tracker Knaben found it on. Desktop searches it On beside
APIBay because, in the October 2026 audit, APIBay took 5.4 s on average and
found 8 of 32 programs where Knaben took 0.8 s and found 26.

**APIBay** sometimes answers with a false "no results". Every APIBay search
runs live first; a successful result is saved, and a later empty or failed
attempt can show it again, marked `Apibay*` (a legend under the table explains
it). The cache keeps 128 searches.

**SolidTorrents**, when it asks the app to slow down, is paused for every
provider for the time it gives (a minute when it gives none, at most 15
minutes), and the search says when it will be asked again.

## Searching

### Several titles at once

At the search prompt, **Ctrl+N** adds another title; **Enter** searches them
all together, and the results merge into one list. A **From** column shows which
title each result came from.

### While a search runs

Each provider gets a line with its engines' states (searching, a row count,
timed out, blocked…), plus providers finished, results ready, elapsed time and
what is still pending. **Enter** shows the results received so far; **Esc**
cancels back to the prompt.

Keyword, combined, alternate-title and creator searches stop waiting after
**30 seconds** and run at most six engine requests at once. They keep every
result already received; notices name the providers that did not finish. A
time-limited search can miss slow sources: search that provider on its own, or
press **r** in the results to [retry](#diagnostics-and-retry).

### How results are ordered

Movies & Series, Anime, Books, Desktop, Mobile and Madokami put the searched
title first; the other providers sort by seeders. Then
[preferred presets](#require-or-prefer) break ties.

- **Movies** rank the film above sequels and remakes (`Blade Runner` before
  `Blade Runner 2049`), read translated `Матрица / The Matrix` listings, and
  treat `Part 2` and `Part Two` alike. A year in the query must match. A query
  with release tags (`Finding Nemo 1080p`, `… pt-br`) also searches the bare
  title and lists tagged releases first.
- **Books** rank the exact title, with or without its author, above titles that
  merely contain it; Libgen's direct downloads lead among equally good matches.
  When the author is known (from search by creator, alternate titles, words in
  the query, or a quick Open Library lookup that counts only a clearly dominant
  work), that author's listings come first and Libgen entries by a clearly
  different author drop below.
- **Desktop** ranks the program above longer products containing its name
  (Photoshop before Photoshop Lightroom or Elements). A platform typed after the
  name (`Photoshop mac`, `… windows`, `… linux`, `… portable`) also searches the
  name alone and lists that platform first.
- **Mobile** ranks the app itself above look-alikes and add-ons (`Minecraft`
  before `… for Minecraft`). Typed tags (`Minecraft obb`, `… apk`, `… mod`) work
  like Desktop's platforms; the APK preset is usually better as Prefer than
  Require.
- **Madokami** lists the series named as searched, and everything in it, first;
  then spin-offs and other areas, then titles that merely contain the words.
  Rows say what a pick opens: `[series folder]`, `[folder]` or `[file]`.
- **Anime** ranks matching titles ahead of incidental word matches. When a short
  title such as `Saki` is crowded out of Nyaa's recent feed, one catalog lookup
  recovers older releases.

### Other spellings and names

When the sources answer but nothing matches the title, the app searches once
more under other spellings, in every provider, and a notice names what it
searched:

- **Digits** for spelled-out numbers: `Twenty First Century Boys` →
  `21st Century Boys`, `Mob Psycho Hundred` → `Mob Psycho 100`.
- **Short vowels** for romanized long ones: `Shingeki no Kyoujin` →
  `Shingeki no Kyojin`, `Mahjong Hishouden` → `Mahjong Hishoden`. A source finds
  only the spelling it lists.
- **AniList names** (Anime, General Manga, Madokami): only when AniList lists
  what you typed as one of its names (long vowels and hyphens aside) or its top
  match's title begins with it. The names searched are the romaji title as
  releases write it, the English title, and short names the romaji contains.
  `Yokohama Shopping Log` finds `Yokohama Kaidashi Kikou`; `Mahjong Hishoden:
  Naki no Ryuu` (or just `Mahjong Hishoden`) finds `Mahjong Hishouden Naki no
  Ryuu` and `Naki no Ryuu`. In a search across providers, every selected
  provider searches these names.
- **Madokami** retries without punctuation such as `:`, which its site search
  cannot handle.
- **FitGirl and Online-Fix** search the title alone, without words such as
  `fitgirl`, `repack` or `linux`, and ignore apostrophes (`Baldurs Gate 3` finds
  `Baldur’s Gate 3`). Their results must match the words of the game title, not
  post bodies or neighbouring links. When FitGirl finds nothing it tries the
  final number written the other way (`Civilization VI` → `Civilization 6`,
  `Grand Theft Auto 5` → `Grand Theft Auto V`). Both game providers share one
  FitGirl search when they run the same query.

Titles are never translated: if the English title finds nothing, try the
release title in the language you want (`Procurando Nemo`).

**Language words after a title.** Typing a language after the title
(`Berserk português`) applies that language preset to the search, also searches
the title alone, and says how many results carry the language. Anime and Manga
have Portuguese, Spanish, French, Italian and Raw presets, which rank or require
tagged releases and search the matching Nyaa category even when it is Off.

### Search by creator

Search by the people and companies behind the work instead of a title:

| Provider | Roles | Sources (keyless) | Optional upgrade |
|---|---|---|---|
| Anime | director, studio | AniList | |
| Movies & Series | director, studio | Wikidata | TMDB key |
| General Manga | writer, magazine | AniList, Jikan | |
| General Games | developer, publisher (kept apart: a company can be both) | Wikidata | Twitch/IGDB credentials |
| Books | author | Open Library, best-known books first | |

Type a name, choose the right match, then tick which of the creator's works to
include (a paged checklist, 100 per page, **n**/**p** to page). The app runs a
normal search for each title and merges the results, so every download, stream
and episode option still applies. Games results include Online-Fix. From the
command line: `torrent -t anime --by director --name "Hayao Miyazaki"`.

### Alternate titles

**Tab → A** at the search prompt, or **Search options**. Identify a work by
title, year or type and catalog ID, tick up to six of its English, native,
romanized or other names with **Space**, and press **w** to search them all.

Catalogs: [AniList](https://anilist.gitbook.io/anilist-apiv2-docs/docs/reference/object/media)
for Anime and Manga, [TMDB](https://developer.themoviedb.org/reference/search-multi)
for Movies and Series (TMDB key needed), [IGDB](https://api-docs.igdb.com/) for
Games (Twitch/IGDB credentials needed) and
[Open Library](https://openlibrary.org/dev/docs/api/search) for Books. Any
provider accepts names typed by hand. Catalog browsing stops after three
pages; only the chosen work's extra names are fetched. **n → Names searched**
in the results lists the queries used (the source attempts also show preset
additions), and history replays exactly those names.
Identifying a work does not mean releases exist, nor does it exclude
similarly named ones.

### Topic discovery

**Tab → D**, or **Search options**. Look up one topic phrase at a time, pick
explicit catalog terms, and browse works that match **all** of them:

- [AniList](https://docs.anilist.co/reference/query): anime and manga genres and
  tags; tags need at least 60% relevance. `time travel` finds the term **Time
  Manipulation**, which you review before using; `mahjong` finds **Mahjong**.
- [TMDB](https://developer.themoviedb.org/reference/discover-movie): movie and
  TV genres and keywords (TMDB key needed).
- [IGDB](https://api-docs.igdb.com/): game genres, themes, modes and keywords
  (Twitch credentials needed). Add `co-op` and `survival` separately.
- [Open Library](https://openlibrary.org/dev/docs/api/subjects): one book
  subject per search. Other catalogs allow up to three terms.

Choose at most three works across three catalog pages, then review up to two
names per work before the release search. A search across providers uses only
the selected providers that suit the catalog, shown before searching. History
keeps the exact names chosen. English catalog vocabulary works best; whole
sentences are not understood. Desktop and Mobile have no discovery and use
ordinary keyword search. A topic says nothing about release availability or
working multiplayer.

## Filters, presets and engines

Open them with **Ctrl+F** at the search prompt, **F** on a highlighted provider,
or **Tab → F**. Changes apply after **w** (save); a provider's settings are kept
across runs.

### Require or prefer

Presets (resolutions, known uploaders and repackers, trusted release groups,
languages, formats) cycle **Off → Require → Prefer** with **Space** or
**Enter**:

- **Require 1080p** hides every other resolution.
- **Prefer 1080p** lists 1080p releases higher and keeps 720p and 480p.

Recommended order keeps title relevance first where the provider has it, then
preferences. Sorting by seeders, date, name or size overrides preferences;
required presets always apply. Presets enabled in older versions stay
**Require**.

**Anime has no default resolution filter**, so older 480p and 720p releases
show. If 1080p is set to Require, that is your saved choice: cycle it to Prefer
or Off and save with **w**.

Keys in the menu: **Space** cycles a preset or engine mode; **a** sets engines
On and presets Require; **i** toggles engines On/Off and presets Require/Off
(Prefer becomes Off); **c** clears presets; **v** drops an anchor and
**Shift+V** toggles everything between it and the cursor; **w** saves. **Clear
filters** clears required and preferred presets and keeps engine modes.

### Name rules

**Ctrl+F → Literal release-name rules** has four fields: **All words**, **Any
word**, **Exact phrase** and **Exclude words**. They match release names only,
ignoring case, accents and punctuation. Words match whole words; a phrase needs
the words in a row. All filled-in rules apply together and exclusions win. For
example, All `Saki`, Any `720p 1080p`, Exclude `sample` keeps either resolution
without `sample` releases. Clear a field to turn its rule off; apply the editor,
then save the settings menu. These rules filter what comes back: they are not
sent to the search engines and do not find topics. A search across providers
has its own shared rules too, beside each provider's.

From the command line, `-f WORD` keeps results containing a keyword and
`-x WORD` drops them; both can be repeated.

### Anime and manga sources

Anime's **Nyaa category** is English-translated (the default),
Non-English-translated, Raw, or all Anime. It applies to Nyaa only; other
engines cannot enforce a language scope. Manga has separate **Nyaa (EN)**,
**Nyaa (Raw)** and **Nyaa (Non-English)** engines. These choices are saved per
provider and per profile.

### Brazilian Portuguese

**Movies & Series:** press **Ctrl+F**, cycle **Dublado (PT-BR)** to Require
with **Space** and save with **w**.

- It needs an explicit Brazilian audio tag: `PT-BR`, `PTBR`, `Português
  Brasileiro`, `Brazilian Portuguese`. Generic `dublado`, `nacional` or
  `Português`, uploader names, PT-PT audio, "Dual Audio" and a PT-BR subtitle
  tag alone do not count.
- **Legendado (PT subs)** is a separate preset for Portuguese subtitles;
  requiring both needs both kinds of tag.
- Set to Require or Prefer, the presets also search with release words appended (`Toy
  Story` → `Toy Story pt-br`, `Toy Story dublado`; subtitles add `legendado`)
  and include Knaben and SolidTorrents even when they are saved Off. The search
  screen shows the engines in effect; clearing the preset restores your
  selection.

**Anime** has separate **PT-BR audio tags** and **PT-BR subtitle tags** presets.
Pick the Nyaa category separately: a non-English category holds many languages.

Limits: language checks read release names, not the tracks. A genuinely
Brazilian release without a regional tag stays hidden, and a mistagged one
cannot be caught. Preferences rank by what the name says; they don't verify
the tracks either. SolidTorrents may report zero seeders, which puts its rows
last among equally good matches.

## Searching across providers

**Search across providers** searches every provider, or a saved selection such
as Anime + Manga, and merges the results.

1. Choose **Search across providers** on the main menu.
2. At the search prompt press **Ctrl+F** and open **Providers**: **c** clears the
   selection, **Space** toggles providers (say **Anime** and **Manga · General**),
   **w** confirms. Add **Manga · Madokami** if you have its login.
3. Optionally set **All providers: include/exclude name phrases**, or open
   **Provider engines and presets** to configure each source. Every provider
   keeps its own engines, presets and categories: Anime's resolution presets
   apply only to Anime.
4. **Save and return** (**w**), then search. **Esc** in this menu discards every
   unsaved edit, nested provider settings included.

The first profile starts with all providers selected and copies your
individual settings, except that Anime starts without a resolution
requirement. After that it is independent: changing it does not change solo
searches, and the reverse.

**Shared phrases.** Includes keep a result matching at least one
comma-separated phrase (`batch, volume`); excludes remove a result matching any
(`sample, trailer`), even if an include also matches. They check the result
name, ignore case, and do not add words to your query. For a resolution limit
on Anime alone, use its presets: `1080p` as a shared include also hides manga
and books without it.

**The merged list** puts title relevance first, then preferred presets, then
each provider's own order. A torrent found by several providers appears once,
under the most specific one (a release Movies & Series finds through Knaben's TV
category, which includes anime, is listed under Anime; FitGirl over General
Games), with every matching provider and title kept. Direct downloads and site
entries stay separate unless they share the same source identity. The provider
shows in a column on wide windows and beside the title on narrow ones.

**Problems** such as a missing or rejected login appear as notices while the
other providers' results stay usable. Short windows show a notice count: **n**
opens the notices and returns to the same result. Requests still running when
you cancel finish in the background, but no new retries start. Search by
creator works only through the individual providers.

### Profiles

In **Search across providers → Ctrl+F**, the **Profile** row saves a copy as a
new profile, switches, renames or deletes. Each profile keeps its providers,
engine modes, required and preferred presets, shared name rules and **Result
order**. A profile can select a single provider (say, PT-BR movies).

- **Save and return** commits every change, including edits made before
  switching profile; **Esc** cancels the whole draft.
- Deleting asks first and always keeps at least one profile. Your earlier
  combined settings become **Default**.
- Profiles are separate from individual provider settings.
- Replaying a history entry restores its setup for that search only; saving it
  creates a **History search** profile you can rename.
- `--profile NAME` and `--providers` change only that session. Profile names
  are not case-sensitive.

**Result order** saves a sort with the profile; it applies to the merged list
and overrides the providers' own sorts. **f** in the results changes only that
view.

## Working with results

| Key | Action |
|---|---|
| Enter | Open the download menu, or the batch menu when results are ticked |
| Space, a, c | Tick a result; tick all in the current view; clear |
| 0-9 | Jump to a result number |
| ←/→ | Previous or next page |
| i, then [ and ] | Expand the release's full name and details; scroll them |
| f | Refine and sort |
| b | Bookmark the ticked results, or the focused one |
| n | Notices and search diagnostics |
| r | Retry failed sources |
| m | Load more |
| d | Download the ticked results |
| Esc | Back |

Under the focused result, a **Tags** line lists what its name carries
(resolution, source, codec, audio, HDR, PT-BR or dual audio, release group),
with the tags a preferred preset asks for ticked, and **Ranked:** says why it
sits there (exact title, starts with the search, prefers 1080p…). The view line
counts results per source. The expanded view (**i**) separates listing metadata
from hints read off the file name, which do not verify audio or subtitle tracks.

The table drops columns as the window narrows; hidden fields show under the
focused row, and long names scroll when focused. Resizing redraws the open
screen.

### Refine and sort

**f** filters by words, by exact media title (ignoring common release tags) or
by exact file name, and sorts by Recommended order, newest upload, most
seeders, name or size. Unknown upload dates sort last. Filtering clears ticks
on rows it hides; sorting keeps them.

### Diagnostics and retry

**n**, even after an empty search, shows each provider, engine and query:
rows returned and kept, which filter removed rows, time taken, cached rows,
login failures, request errors and timeouts. Counts are before duplicates are
merged. A saved login is configuration, not proof that it works; the menu
offers to verify it.

**r** retries only failed or unfinished requests, keeping received results and
required filters. Stopping a retry or a page request keeps earlier results.

### Load more

**m** asks Nyaa and Knaben for another page (Nyaa continues after its first
feed page; Knaben advances 50 rows). New rows are merged without duplicates,
and the focused row, ticks, refinement and sort are kept. Each press fetches at
most 24 pages within the same 30-second limit, up to ten pages per source and
query; Off engines and unused Auto engines are not asked. **n** shows used-up
queries, engines without paging and failed pages, which **r** retries without
skipping. Other engines return what their first request gives.

## Downloading

Picking a result opens the download menu. **Back to results** returns to the
same list; **Cancel** goes to What's Next.

| Section | Rows |
|---|---|
| Torrent & files | Browse torrent files (episode selection); Torrent info |
| Subtitles | Subtitle source for streams; Search & download subtitles |
| Stream to VLC | webtorrent, then peerflix |
| Download | Open in your torrent client (recommended, and the only one that seeds); Send to qBittorrent WebUI; aria2c; webtorrent; peerflix |
| Other | Copy magnet link; Open torrent page in the browser |
| Settings | Save to (download folder); Quiet mode; Unpack page archives |

The focused row's help explains each option's trade-offs (speed, seeding, file
selection).

- **Open in client** hands the magnet to your system's default torrent client
  (qBittorrent, Transmission…). With files picked, untick the rest in its dialog.
- **aria2c** is the fastest terminal download: it resumes and downloads only
  the files you picked. **webtorrent** and **peerflix** are slower; they ignore
  file picks and download the whole torrent, and the menu warns you.
- **Quiet mode** replaces the full-screen progress of aria2c, webtorrent and
  peerflix with a single spinner, and is saved. Episode info, VLC key hints and
  Ctrl+C still work.
- A failed or missing tool, or **Ctrl+C**, brings you back to this menu with
  your search kept. Failed downloads keep their error output until you
  acknowledge it.

### Batch downloads

Tick several results with **Space** (also across titles of a multi-title or
creator search) and press **Enter**:

- **Open all in your client**: **Esc** stops partway.
- **Send selection to qBittorrent WebUI**: magnets and Online-Fix torrent files.
- **Download all with aria2c**: one parallel process, no client needed.
- **Copy all magnet links**: RuTracker and FitGirl links are resolved on demand.

Online-Fix, Madokami, Libgen and F-Droid entries have no magnet and are skipped
by aria2c and copying.

### Choosing files

**Browse torrent files** (Anime, Movies & Series, Manga, Books) lists every file:
videos, subtitles, artwork, `.nfo`, samples, or a manga's volumes and chapters.
It needs aria2c to fetch the file list from other peers, which can take a
minute or time out when none are reachable (listed seed counts can be stale).
**Esc** cancels the wait. If no list is found, choose it again to retry; a list
once found is kept for that torrent.

Keys: **Space** ticks, **a** all, **i** invert, **c** clear, **v** drops an
anchor and **Shift+V** toggles the range to the cursor, **w** saves. Reopening
shows your ticks; saving with nothing ticked clears the selection; **Esc**
keeps the previous one. Checklists of 500+ files scroll with the action rows
kept in view.

### Torrent info

**Torrent info**, for results from Nyaa, The Pirate Bay and YTS, fetches details
from the source page: category, uploader, date, description, comments and the
full file list.
It also guesses **whether subtitles are embedded** from names and metadata (an
anime "English-translated" category, a `[Subbed]` tag) and confirms it with
`ffprobe` when ffmpeg is installed and the video is already downloaded, which
tells a soft-subbed MKV from a raw release.

### Direct downloads

Libgen, Madokami, F-Droid and Online-Fix `.torrent` files download straight to
your download folder with a progress bar; **Esc** leaves the wait before one
starts. A file arrives under its final name only when complete, never
replaces an existing file (a taken name becomes `Name (1).ext`), and
server-provided names are made safe.

- **Libgen** searches its live mirrors, moving to the next when one fails or
  answers empty, and resolves the download link when you pick a result.
- **Madokami**: picking a folder opens it; step into release folders, see file
  sizes and tick the volumes you want; **Esc** goes up a level. Two or more
  files from one series are saved together in a folder named after it
  (`Naki no Ryuu/`, `One Piece/One Piece [Viz]/`), and a later single file joins
  it when it exists.

### Download folder

**Download folder** on the main menu, or **Save to** in the download menu,
sets where aria2c, webtorrent and peerflix downloads, subtitles and direct
downloads go: the default (`downloads` in the app's [data folder](#your-data)),
`~/Downloads`, or a path you type (created if missing). If the folder can't be used when a download starts (a disconnected
drive, say), the app says why and lets you choose another, keeping your torrent
and files. Streams and client handoffs use their own paths.

### Unpack page archives

Off by default; turn it on under **Download folder** or in the download menu.
Manga and comic archives (`.zip`, `.cbz`, `.rar`, `.cbr`, `.7z`, `.cb7`) that
hold only images become a folder of pages beside them, and the archive is
deleted once the pages are in place. It covers Madokami files and torrents
downloaded in the app, not a client you hand a magnet to, nor files already in
the folder. Other archives (games, software, documents) are left alone. ZIP and
CBZ always work; RAR and 7z need the `tar` built into Windows 10/11 and macOS,
7-Zip or UnRAR, otherwise they stay packed with a note saying why.

### qBittorrent WebUI

Set the WebUI address and login under **Quick actions → Q → Configure /
verify** or **Credentials → qBittorrent WebUI** (the username is optional for
trusted access; for a remote client, use its HTTPS address). The download and
batch menus then offer **Send to qBittorrent WebUI**:

- Choose a folder on the client's computer and an existing category, then
  send. Torrents already in the client are detected and left where they are.
- Magnets, resolved site magnets and Online-Fix torrent files work; direct
  downloads don't. The whole torrent is added: pick files in qBittorrent.
- The app shows the client's real state, progress, speed, ETA and destination;
  **R** refreshes. A sent request or 100% progress is not reported as a
  verified finished download.
- The app never enables the WebUI or changes its network exposure or
  authentication. It uses the
  [WebUI API v2](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29).

## Streaming and subtitles

### Stream to VLC

**Stream with webtorrent** (the default) or **peerflix** (try it when
webtorrent stalls). Both need VLC.

- Each stream opens its own VLC window, on Windows even when VLC allows only
  one instance. Close it and press **v** to reopen it without losing progress.
- Next or previous episode, or **Ctrl+C**, closes only that window; other VLC
  playback is never touched.
- A stream that ends with an error says so and shows the last lines of a small
  log in your temp folder.
- With files picked, the stream plays those in order and skips non-video picks
  (with a warning), so you can download the `.srt` and `.nfo` too. A selection
  without any video stops with an error rather than playing another file.

### Episodes

Streaming a torrent with two or more videos without picking files first
fetches the file list (aria2c; **Esc** or **Ctrl+C** returns to the menu
without streaming), queues every video in episode order (`S01E01`, ` - 01`,
`[01]`, `Episode 01`, ` E01`; alphabetical otherwise), and lets **n** and **b**
jump to the next and previous episode. Single-file movies just play.

### Subtitles for streams

The **Subtitles** row chooses how VLC gets them:

- **auto-detect from torrent** (default): finds `.srt`, `.ass`, `.ssa`, `.vtt`
  and `.sub` files for each video (same name, a language tag like `.en.srt`, or
  a `Subs/` folder with episode-numbered files like `01.ass`). Those for the
  episodes you stream download with aria2c in one batch before playback, so
  changing episode never waits; later streams fetch only missing ones. English
  is the main track when available.
- **external file**: a recent `.srt` or `.ass` from your download folder, or a
  path you type, attached to every episode in the session.
- **off**.

### Subtitle download

**Search & download subtitles** uses [subliminal](https://github.com/Diaoul/subliminal)
with OpenSubtitles.com, Addic7ed, Podnapisi and TVsubtitles (subliminal's other
providers are defunct, VIP-only or single-language, and are skipped). Enter one or more
languages separated by commas (`eng, por`, `pt-BR`; ISO codes and regional
variants work). Every language found is downloaded; the first in your order
becomes VLC's main track and the rest switchable tracks, and missing languages
are reported. A downloaded video is matched by hash for exact sync; otherwise by
release name. The saved file becomes the external subtitle for your next
stream.

OpenSubtitles.com credentials greatly improve results. For Anime, a
[Jimaku](https://jimaku.cc) lookup runs first when its API key is set, because
the other providers index few anime fansubs.

## History, stats, bookmarks and backups

### Search history

**H** on the main menu (or **Tab → H**). Each entry shows the provider, when, and
the presets active then; filter by provider (**P**), date (**D**: today, week,
month) or kind (**T**: keyword or by-creator) and change the sort (**S**).
Picking one runs it again; a search across providers brings back its profile's
settings. The last 2,000 distinct searches are kept, and repeating a search
moves it to the top. Clearing history asks first.

### Usage stats

**S** on the main menu (or **Tab → S**): sessions, total time, searches, top
queries, torrents picked, download methods picked and completed (with success
rate), average seeders of picks and preset use. Resetting asks first.

### Bookmarks

**b** in the results bookmarks the ticked results, or the focused one.
**Tab → Bookmark current search** saves the typed query with its provider or
profile settings. **Tab → Bookmarks / download later** (**B**) reopens a saved
result's normal download flow, compares saved results in one table, refreshes
a listing with its original search settings, or removes entries.

Bookmarks survive restarts and show when their details were fetched. They keep
direct downloads and site entries whose magnet isn't resolved yet; saving one
downloads or resolves nothing. A refresh that doesn't find the same listing
keeps the old entry; saved details don't prove the torrent is still available.

### Settings backup and import

**Tab → Settings backup / import** moves settings between computers as a JSON
file. A normal export holds provider choices, profiles, the download folder and
stream preferences; history is optional. Credentials, bookmarks, stats and
machine-specific launcher and update state are left out. Exports always use a
new file name, never overwriting one.

Import checks the file and previews it before **Apply import**:

- **Merge** keeps your other entries; incoming provider preferences win, profiles
  match by name, and your active profile stays selected.
- **Replace** replaces portable preferences and provider choices.

Both keep bookmarks, stats and machine settings; history changes only if the
backup has it. Check that an imported download folder exists. A malformed file
or failed write leaves your settings as they were.

Credentials have their own, clearly labelled export and import. That file is
plain text and holds credential-file values only, never environment variables,
which still take precedence after import.

## Appearance

**Settings › Appearance** chooses the design and its colours. Each row previews
its own colours; **Space** previews on the whole screen and **Enter** saves.

- **Athanor** (the default) frames each screen like a roguelike scriptorium: a
  double-line frame whose top edge names the screen (`torrent-finder » Movies &
  Series › dune`), a message line above saying what just happened, and a status
  line below (searches, picks, bookmarks, keys pressed, the date, the VPN check
  and the version). Colourways: **Citrinitas** (default, lamplight amber),
  **Rubedo**, **Albedo**, **Viriditas**, **Nigredo**.
- **Simple** is the quiet look: one header line naming the screen with what it
  is about on the right, thin rules, no boxes or emoji. Themes: **Quiet Blue**
  (your terminal's bright blue), **Iris**, **Lagoon**, **Ember**, **Mono**,
  **Paper** (for light terminals).
- **Focus** is a cursor bar or a tinted row; **Density** **Compact** drops rules
  and spacer lines at every size, so lists show more rows.
- `--theme NAME` or `TORRENT_FINDER_THEME=NAME` use a theme for one run or shell
  without saving it. `NO_COLOR` is honoured.

Themes colour the text; the background is your terminal's. Set your terminal
to a light colour scheme before choosing Paper (Windows Terminal: `Ctrl+,` ›
your profile › Appearance › Color scheme), unless you use the profile below.

### Paintings

Athanor has a **painting**, chosen apart from the colours, which recolour it:
ten public-domain engravings, six by Gustave Doré, plus Dürer's *Melencolia I*,
the Flammarion engraving, Pamela Colman Smith's *Hermit* and an emblem from
Maier's *Atalanta Fugiens*, or none. Terminals draw background pictures, not
apps, so:

- **On Windows**, **Add a torrent-finder profile** gives Windows Terminal a
  profile that opens the app on the theme's own page, with the painting behind
  the text (Windows Terminal 1.24 or later; older ones get colours and font
  only) and the design's **font** and **text size**: five bundled pixel fonts
  for Athanor, such as IBM VGA 8x16 and XGA 12x20 (whole-number sizes keep them
  sharp), or Cascadia, Consolas or Lucida Console for Simple. The profile
  appears at once and follows later choices, open tabs included, without a
  restart. Athanor's profile has a **full look** (page, painting, pixel font) or
  a **plain look** (Windows Terminal's own page and font). Removing the profile
  deletes its folder; the fonts stay installed.
- **Open from other tabs** (off by default) makes the command, typed in another
  Windows Terminal tab, open the app in a torrent-finder tab of the same window,
  because a program cannot change the picture or font of the tab it runs in.
- **Elsewhere**, **Save the painting as an image** writes a PNG in your colours
  to `Pictures/torrent-finder`; set it as your terminal's background picture.

### Window sizes

- **Wide windows** (150 columns, such as a maximised window) show an inspector
  beside menus: on the main menu, a provider's engines and modes, its presets,
  your recent searches there and how often you searched and picked from it;
  Continue's earlier searches; which logins are set; the download folder's free
  space; the appearance in use. Other menus show the row's help there.
- **Tall windows** put those details under the list, and the help and key bar
  on the bottom rows, in the same place on every screen.
- **Narrow or short windows** wrap hints without changing row height, drop
  spacer lines, continue long screen names on a second header line, and scroll
  long names when focused. Very small windows (about 20×8) crop the results
  table's last keys.

## Settings and startup checks

### Terminal command

`torrent-finder` is the command, and pip and pipx installs add `torrent`.
**Settings › Terminal command** can add `tf`, `find-torrent` or `tfind`
instead: one app-owned launcher that passes every argument through, refuses to
replace an unrelated command of the same name, and can be removed from the same
screen. If its folder is not on your PATH, Windows offers to add it to your user
PATH; elsewhere the app tells you which folder to add.

### Network exposure warning

At startup the app asks `ip-api.com` about your public address and shows your IP
and location (masked as `•••.•.•••.•` until you press **R**, so the screen is
safe to share), ISP, ASN and a verdict:

- ✓ **Proxy/VPN flagged** by the IP database.
- ✓ **Hosting/datacenter IP**: likely a VPN exit, not a home connection.
- ✓ **VPN provider name detected** (Mullvad, Proton, Nord…).
- ! **Mobile carrier IP**: your carrier and peers see this IP.
- ! **Residential ISP IP**: every peer and tracker sees your real IP.

**Enter** continues, **R** shows or hides the IP and location, **D** stops
showing the warning, **Esc** quits. `-y` or `TORRENT_SKIP_WARNING=1` skip it for
a run. **Settings › Network exposure info** shows it again; once it has run, the
main menu's header says **VPN** or **IP visible**.

### Terminals that can't draw the interface

On Windows 10's legacy console (or with `TERM=dumb`) the interface would come out
garbled. The app detects this and prints fixes to copy: best, install
[Windows Terminal](https://aka.ms/terminal) (`winget install -e --id
Microsoft.WindowsTerminal`); otherwise, a `reg add` command that turns on ANSI
colours in the console.

## Credentials

Choose **Credentials** on the main menu. For each integration you can view,
enter or update, and clear its login. Entering opens one form: **↑/↓** or
**Tab** move, **Enter** advances, **Esc** cancels, then Save. Saved values are
checked against the service where possible and written to
`subtitle_credentials.json`; the view masks passwords and keys, with a toggle
to show them.

Environment variables take precedence over the file, and the menu says when
one is set. **Clear** only empties the file: unset the variable to remove a
credential set there. File keys are the variable names in lowercase:

```json
{
  "opensubtitles_username": "your_user",
  "opensubtitles_password": "your_pass",
  "tmdb_api_key": "your_key"
}
```

Setting a variable for new terminals:

```powershell
# Windows (PowerShell)
[Environment]::SetEnvironmentVariable("TMDB_API_KEY", "your_key", "User")
```

```bash
# macOS / Linux: add to your shell profile
export TMDB_API_KEY="your_key"
```

What each one does (the variables are listed in the
[README](../README.md#credentials)):

- **OpenSubtitles.com**: a free account greatly improves subtitle results and
  allows hash matching against a downloaded file. The API key is optional.
  Free accounts have a small daily download limit.
- **Addic7ed** (TV series): a free account raises rate limits; it runs
  anonymously, with lower limits, without one.
- **Jimaku** (anime): a free API key (jimaku.cc → account settings) adds an anime
  subtitle lookup before subliminal; without it Anime uses subliminal alone.
- **RuTracker**: a free account is required; the provider returns nothing
  without one.
- **Madokami**: an account is required; the whole site is behind a login.
- **Online-Fix**: optional; search and download work without it.
- **TMDB**: a free v3 API key (themoviedb.org → Settings → API) makes Movies &
  Series by director or studio richer and enables its alternate titles and
  topic discovery. Without it, creator search uses Wikidata.
- **IGDB**: free Twitch credentials (dev.twitch.tv → register an application →
  Client ID and a new Client Secret, shown only once) do the same for Games.
- **qBittorrent WebUI**: see [qBittorrent WebUI](#qbittorrent-webui).

The credentials form shows these steps too. Madokami and RuTracker show a clear
message when a login is missing or rejected.

## Your data

Settings, history, stats, bookmarks and provider choices live in
`filter_state.json`, with credentials beside it in `subtitle_credentials.json`:

| System | Folder |
|---|---|
| Windows | `%USERPROFILE%\.torrent-finder-cli\` |
| macOS | `~/Library/Application Support/torrent-finder-cli/` |
| Linux | `$XDG_DATA_HOME/torrent-finder-cli/` (or `~/.local/share/torrent-finder-cli/`) |

On Windows this folder doesn't depend on which Python runs the app, so a new
Python install can't make your credentials seem to vanish. The default
download folder is `downloads` in `%LOCALAPPDATA%\torrent-finder-cli\` on Windows, or
in the folder above on macOS and Linux.

- **Saving.** Searches and counters are saved in the background about a second
  after they happen, so closing the window loses nothing. Explicit actions
  (saving a profile, confirming filters, clearing history, resetting stats,
  bookmarks, imports) save at once, and a failure is reported.
- **Several windows** can be open at once. Each saves only its own changes onto
  the current file, under a short lock (`filter_state.json.lock`), so no window
  undoes another's bookmarks or settings.
- **A damaged file** is never overwritten. At startup the app offers to try
  again or continue without saving, and for damaged content, to keep a renamed
  copy and start fresh.
- **Upgrading from older versions:** on first run, settings from earlier
  locations (the platform data folder, the repository, the package and Store
  Python's private folders) are merged into this file; the originals are left
  alone. Credentials are recovered from them only when the credential file
  doesn't exist: each integration takes the newest copy with its fields, and a
  username stays with its password. An existing credential file, even one
  emptied by clearing, wins. An unreadable credential file produces a warning
  and blocks saving rather than overwriting it. Credentials in environment
  variables must be set on each machine.
- **`apibay_cache.json`**, in the same folder, holds up to 128 recent APIBay
  results (public listing data). Deleting it only forgets those; settings and
  history are untouched.
- **`update.log`** holds the output of the last in-app update.

## Updating

The app checks for a new version at startup (at most once a day, silently on
failure): against PyPI for pip and pipx installs, `origin` for a git clone and
the latest Release for a standalone binary. When there is one, it shows a
yellow notice. Press **U** on the main menu, choose
**Install update** there, or **Tab → Install update** at a search prompt:

- **pip or pipx**: runs `pip install -U torrent-finder-cli` for the app's own
  Python, then `pipx upgrade torrent-finder-cli` so pipx's records stay right
  (pipx does it all when it installed the app from a file, URL or git). A failed
  install is reported as a failure.
- **Standalone binary**: opens the Releases page so you can download the new file.
- **Source clone**: runs `git pull`.

The update runs in the same window. Its screen shows each step (preparing,
downloading, installing, finishing), a bar with the download percentage and
size while pip downloads, the elapsed time, and the result. After a successful
update, press any key and the app restarts with the new version; if it fails,
the version you had keeps running. Full installer output goes to `update.log`
beside your settings.

On Windows a running program's file can't be replaced, so the app renames its
own launcher (`torrent-finder.exe`) out of the way and deletes the old copy on a
later start. If another Torrent Finder window is open, the update stops before
changing anything and asks you to close it. **Ctrl+C** can't stop an update
halfway; the screen says so and the update finishes.

Updating **from v0.9.0 or earlier** uses the installed version's method once:
it closes the app and installs in the background (on Windows with a separate
progress window). Later updates run in the same window.

To preview the update screen without installing or changing anything:
`torrent-finder --preview-update` (success, about seven seconds) or
`torrent-finder --preview-update failure` (about six). Both wait for a key and
don't restart the app.

To update by hand, close every Torrent Finder window and run
`pipx upgrade torrent-finder-cli` (or `python -m pip install --upgrade
torrent-finder-cli`) in a separate terminal. If an older version reported
Windows `WinError 32` while replacing `torrent-finder.exe`, do exactly that: its
earlier "harmless" message did not mean the update had finished.
