"""Build the fixed, reviewable corpus for the opt-in provider audit."""
import json
from pathlib import Path


# title | year | stratum; availability is deliberately NOT an expectation.
CORPORA = {
    "movies": """
The Matrix|1999|popular
Finding Nemo|2003|popular
Inception|2010|popular
Dune|2021|ambiguous
Dune Part Two|2024|sequel
Parasite|2019|non_english
Seven Samurai|1954|old
Metropolis|1927|old
Stalker|1979|non_english
Coherence|2013|niche
Primer|2004|niche
The Fall|2006|ambiguous
Tokyo Story|1953|old
City of God|2002|pt_br
Central Station|1998|pt_br
Tropa de Elite|2007|pt_br
O Auto da Compadecida|2000|pt_br
Spirited Away|2001|cross_category
Godzilla Minus One|2023|recent
Poor Things|2023|recent
Shogun|2024|series
Dark|2017|series
Severance|2022|series
The Last of Us|2023|series
""",
    "games": """
Cyberpunk 2077|2020|popular
Elden Ring|2022|popular
Baldur's Gate 3|2023|punctuation
Hogwarts Legacy|2023|recent
Starfield|2023|recent
Hades|2020|short
Hollow Knight|2017|indie
Stardew Valley|2016|indie
Terraria|2011|coop
Valheim|2021|coop
Palworld|2024|recent
Lethal Company|2023|coop
It Takes Two|2021|coop
Portal 2|2011|sequel
Half-Life|1998|old
Deus Ex|2000|old
System Shock 2|1999|old
Planescape Torment|1999|niche
Disco Elysium|2019|niche
Outer Wilds|2019|near_match
The Outer Worlds|2019|near_match
Sea of Stars|2023|indie
Prince of Persia The Lost Crown|2024|recent
Dragon's Dogma 2|2024|sequel
""",
    "online-fix": """
Lethal Company|2023|popular
Palworld|2024|popular
Valheim|2021|coop
Phasmophobia|2020|coop
Stardew Valley|2016|coop
Terraria|2011|coop
It Takes Two|2021|coop
Portal 2|2011|old
Left 4 Dead 2|2009|old
Don't Starve Together|2016|punctuation
Deep Rock Galactic|2020|coop
Risk of Rain 2|2020|sequel
Raft|2022|survival
Grounded|2022|survival
Sons of the Forest|2023|survival
The Forest|2018|near_match
Escape the Backrooms|2022|niche
Content Warning|2024|recent
Enshrouded|2024|recent
Abiotic Factor|2024|recent
Pico Park|2021|short
Overcooked 2|2018|coop
Human Fall Flat|2016|coop
Unrailed|2019|niche
""",
    "software": """
Adobe Photoshop|2024|popular
Adobe Premiere Pro|2024|popular
Microsoft Office|2021|popular
Autodesk AutoCAD|2024|popular
Blender|2024|open_source
GIMP|2024|open_source
LibreOffice|2024|open_source
VLC|2024|short
7-Zip|2024|punctuation
WinRAR|2024|popular
DaVinci Resolve|2024|video
Affinity Photo|2022|macos
Final Cut Pro|2024|macos
Logic Pro|2024|macos
Ableton Live|2024|audio
FL Studio|2024|audio
REAPER|2024|audio
MATLAB|2024|technical
Wolfram Mathematica|2024|technical
SolidWorks|2024|technical
SketchUp|2024|technical
Adobe Photoshop CS6|2012|old
Microsoft Office 2007|2007|old
Ubuntu 24.04|2024|linux
""",
    "mobile": """
Minecraft|2024|popular
Stardew Valley|2019|game
Terraria|2013|game
Dead Cells|2020|game
Slay the Spire|2021|game
Monument Valley|2014|game
Monument Valley 2|2017|sequel
Geometry Dash|2013|game
Plants vs Zombies|2011|game
Mini Metro|2016|niche
Bloons TD 6|2018|game
Vampire Survivors|2022|recent
Poweramp|2024|audio
Tasker|2024|utility
Nova Launcher|2024|utility
Moon Reader|2024|reader
Solid Explorer|2024|utility
MX Player|2024|video
VLC|2024|open_source
OsmAnd|2024|open_source
Organic Maps|2024|open_source
K-9 Mail|2024|open_source
Signal|2024|open_source
AnkiDroid|2024|open_source
""",
    "rutracker": """
Adobe Photoshop|2024|software
Microsoft Office|2021|software
AutoCAD|2024|software
Ableton Live|2024|software
FL Studio|2024|software
MATLAB|2024|software
Ubuntu|2024|linux
Blender|2024|open_source
Pink Floyd|1973|audio
Kind of Blue|1959|audio
The Dark Side of the Moon|1973|audio
Beethoven|1808|audio
The Matrix|1999|movies
Stalker|1979|movies
Solaris|1972|movies
Seven Samurai|1954|movies
Saki|2009|anime
Monster|2004|anime
Berserk|1989|manga
Dune|1965|books
The Hobbit|1937|books
Metamorphosis|1915|books
Planescape Torment|1999|games
Disco Elysium|2019|games
""",
    "anime": """
Saki|2009|short
Naruto|2002|popular
One Piece|1999|popular
Attack on Titan|2013|popular
Death Note|2006|popular
Frieren Beyond Journey's End|2023|recent
Dungeon Meshi|2024|recent
Oshi no Ko|2023|recent
Pluto|2023|short
Monster|2004|ambiguous
Mushishi|2005|niche
Haibane Renmei|2002|niche
Texhnolyze|2003|niche
Kaiba|2008|short
Dennou Coil|2007|niche
Serial Experiments Lain|1998|old
Revolutionary Girl Utena|1997|old
Neon Genesis Evangelion|1995|old
Cowboy Bebop|1998|old
Legend of the Galactic Heroes|1988|old
Saki Achiga-hen|2012|sequel
Saki Zenkoku-hen|2014|sequel
Akagi|2005|topic_mahjong
Steins Gate|2011|punctuation
""",
    "manga": """
One Piece|1997|popular
Berserk|1989|popular
Naruto|1999|popular
Death Note|2003|popular
Monster|1994|ambiguous
20th Century Boys|1999|numeric
Vagabond|1998|popular
Yotsuba|2003|short
Yokohama Kaidashi Kikou|1994|niche
Yokohama Shopping Log|1994|alternate_title
Witch Hat Atelier|2016|recent
Dungeon Meshi|2014|recent
Frieren|2020|recent
Chainsaw Man|2018|recent
Dandadan|2021|recent
Sakamoto Days|2020|recent
Akane-banashi|2022|recent
Saki|2006|short
Akagi|1991|topic_mahjong
Hikaru no Go|1998|old
Rose of Versailles|1972|old
Phoenix|1967|old
Nausicaa of the Valley of the Wind|1982|old
Otoyomegatari|2008|niche
""",
    "books": """
Pride and Prejudice|1813|old
Frankenstein|1818|old
Alice in Wonderland|1865|old
Dracula|1897|old
Metamorphosis|1915|short
The Hobbit|1937|popular
Nineteen Eighty-Four|1949|numeric
Dune|1965|short
The Left Hand of Darkness|1969|niche
The Dispossessed|1974|niche
Neuromancer|1984|popular
The Name of the Rose|1980|non_english
Dom Casmurro|1899|pt_br
Memorias Postumas de Bras Cubas|1881|pt_br
The Three-Body Problem|2008|non_english
The Fifth Season|2015|niche
Piranesi|2020|recent
Project Hail Mary|2021|recent
Tomorrow and Tomorrow and Tomorrow|2022|recent
Yellowface|2023|recent
The Rust Programming Language|2023|technical
Designing Data-Intensive Applications|2017|technical
Introduction to Algorithms|2022|edition
Structure and Interpretation of Computer Programs|1996|technical
""",
}
CORPORA["fitgirl"] = CORPORA["games"]
CORPORA["madokami"] = CORPORA["manga"]

# query | aliases (semicolon separated) | scenario | required variant tokens
VARIANTS = {
    "movies": [
        ("FINDING NEMO", "Finding Nemo;Procurando Nemo", "capitalization", ""),
        ("Procurando Nemo", "Finding Nemo;Procurando Nemo", "pt_br_alias", ""),
        ("Cidade de Deus", "City of God;Cidade de Deus", "native_alias", ""),
        ("千と千尋の神隠し", "Spirited Away;千と千尋の神隠し;Sen to Chihiro", "unicode", ""),
        ("Dune Part 2", "Dune Part Two;Dune Part 2", "numeric_variant", ""),
        ("Finding Nemo 1080p", "Finding Nemo;Procurando Nemo", "resolution", "1080p"),
        ("Finding Nemo pt-br", "Finding Nemo;Procurando Nemo", "language_tags", "pt br"),
    ],
    "games": [
        ("CYBERPUNK 2077", "Cyberpunk 2077", "capitalization", ""),
        ("Baldurs Gate 3", "Baldur's Gate 3;Baldurs Gate 3", "punctuation_variant", ""),
        ("バルダーズ・ゲート3", "Baldur's Gate 3;バルダーズ・ゲート3", "unicode", ""),
        ("The Witcher 3 Wild Hunt", "The Witcher 3", "subtitle", ""),
        ("Cyberpunk 2077 fitgirl", "Cyberpunk 2077", "repack", "fitgirl"),
        ("Stardew Valley linux", "Stardew Valley", "platform", "linux"),
        ("Portal Two", "Portal 2;Portal Two", "numeric_variant", ""),
    ],
    "online-fix": [
        ("LETHAL COMPANY", "Lethal Company", "capitalization", ""),
        ("Dont Starve Together", "Don't Starve Together;Dont Starve Together", "punctuation_variant", ""),
        ("Overcooked! 2", "Overcooked 2;Overcooked! 2", "punctuation", ""),
        ("Portal Two", "Portal 2;Portal Two", "numeric_variant", ""),
        ("Lethal Company pt-br", "Lethal Company", "language_tags", "pt br"),
        ("Valheim dedicated server", "Valheim", "edition", "dedicated server"),
        ("人类一败涂地", "Human Fall Flat;人类一败涂地", "unicode", ""),
    ],
    "software": [
        ("ADOBE PHOTOSHOP", "Adobe Photoshop;Photoshop", "capitalization", ""),
        ("Photoshop 2024", "Adobe Photoshop;Photoshop", "edition", "2024"),
        ("Photoshop portable", "Adobe Photoshop;Photoshop", "portable", "portable"),
        ("Photoshop macOS", "Adobe Photoshop;Photoshop", "platform", "macos"),
        ("Office português", "Microsoft Office;Office", "pt_br", "portugues"),
        ("Фотошоп", "Photoshop;Фотошоп", "unicode", ""),
        ("7 zip", "7 Zip;7-Zip", "punctuation_variant", ""),
    ],
    "mobile": [
        ("MINECRAFT", "Minecraft", "capitalization", ""),
        ("Minecraft apk", "Minecraft", "format", "apk"),
        ("Minecraft obb", "Minecraft", "format", "obb"),
        ("Poweramp mod", "Poweramp", "edition", "mod"),
        ("Moon+ Reader", "Moon Reader;Moon+ Reader", "punctuation_variant", ""),
        ("Minecraft português", "Minecraft", "pt_br", "portugues"),
        ("我的世界", "Minecraft;我的世界", "unicode", ""),
    ],
    "rutracker": [
        ("ADOBE PHOTOSHOP", "Adobe Photoshop;Photoshop", "capitalization", ""),
        ("Фотошоп", "Photoshop;Фотошоп", "unicode", ""),
        ("Матрица", "The Matrix;Матрица", "native_alias", ""),
        ("Сталкер", "Stalker;Сталкер", "native_alias", ""),
        ("Pink Floyd FLAC", "Pink Floyd", "format", "flac"),
        ("Office 2007", "Office", "old_edition", "2007"),
        ("Метаморфоза", "Metamorphosis;Метаморфоза;Превращение", "native_alias", ""),
    ],
    "anime": [
        ("SAKI", "Saki;咲", "capitalization", ""),
        ("咲-Saki-", "Saki;咲", "unicode", ""),
        ("Saki 720p", "Saki;咲", "resolution", "720p"),
        ("Saki batch", "Saki;咲", "batch", "batch"),
        ("Saki 01", "Saki;咲", "episode", "01"),
        ("Sousou no Frieren", "Frieren;Sousou no Frieren;葬送のフリーレン", "alternate_title", ""),
        ("Naruto pt-br", "Naruto;ナルト", "language_tags", "pt br"),
    ],
    "manga": [
        ("BERSERK", "Berserk;ベルセルク", "capitalization", ""),
        ("咲-Saki-", "Saki;咲", "unicode", ""),
        ("One Piece v01", "One Piece;ワンピース", "volume", "v01"),
        ("Berserk complete", "Berserk;ベルセルク", "batch", "complete"),
        ("Twenty First Century Boys", "21st Century Boys;Twenty First Century Boys", "numeric_variant", ""),
        ("Berserk português", "Berserk;ベルセルク", "pt_br", "portugues"),
        ("ダンジョン飯", "Dungeon Meshi;Delicious in Dungeon;ダンジョン飯", "native_alias", ""),
    ],
    "books": [
        ("PRIDE AND PREJUDICE", "Pride and Prejudice", "capitalization", ""),
        ("1984", "1984;Nineteen Eighty Four", "numeric_variant", ""),
        ("Memórias Póstumas de Brás Cubas", "Memorias Postumas de Bras Cubas", "accents", ""),
        ("Die Verwandlung", "Metamorphosis;Die Verwandlung", "native_alias", ""),
        ("Pride and Prejudice epub", "Pride and Prejudice", "format", "epub"),
        ("Dune audiobook", "Dune", "format", "audiobook"),
        ("三体", "The Three Body Problem;三体", "unicode", ""),
    ],
}
VARIANTS["fitgirl"] = VARIANTS["games"]
VARIANTS["madokami"] = VARIANTS["manga"]


def build():
    title_aliases = {
        "Finding Nemo": ["Procurando Nemo"], "City of God": ["Cidade de Deus"],
        "Central Station": ["Central do Brasil"], "Spirited Away": ["Sen to Chihiro", "千と千尋の神隠し"],
        "Attack on Titan": ["Shingeki no Kyojin", "進撃の巨人"],
        "Frieren Beyond Journey's End": ["Frieren", "Sousou no Frieren", "葬送のフリーレン"],
        "Dungeon Meshi": ["Delicious in Dungeon", "ダンジョン飯"],
        "Death Note": ["デスノート"], "One Piece": ["ワンピース"], "Saki": ["咲"],
        "Berserk": ["ベルセルク"], "Steins Gate": ["Steins;Gate"],
        "Nineteen Eighty-Four": ["1984"], "Metamorphosis": ["Die Verwandlung"],
        "The Three-Body Problem": ["Three Body Problem", "三体"],
        "Witch Hat Atelier": ["Tongari Boushi no Atelier"],
        "Rose of Versailles": ["Versailles no Bara"], "Otoyomegatari": ["A Bride's Story"],
    }
    exclusions = {
        "The Matrix": ["Reloaded", "Revolutions", "Resurrections"],
        "Dune": ["Part Two", "Part 2", "Messiah", "Children of Dune", "Heretics", "Chapterhouse"],
        "Saki": ["Achiga", "Zenkoku", "全国", "阿知賀", "Koko wa Ore", "Tenkou saki"],
        "Naruto": ["Shippuden", "Boruto"], "Monument Valley": ["Monument Valley 2"],
        "The Forest": ["Sons of the Forest"], "Portal Two": [],
    }
    cases = []
    for slug, text in CORPORA.items():
        entries = []
        for line in text.strip().splitlines():
            title, year, stratum = line.split("|")
            entries.append(dict(query=title, intended=title, aliases=[title], year=int(year),
                                scenario=stratum, variant_tokens="", expectation="availability_unknown"))
        for query, aliases, scenario, tokens in VARIANTS[slug]:
            entries.append(dict(query=query, intended=aliases.split(";")[0], aliases=aliases.split(";"),
                                year=None, scenario=scenario, variant_tokens=tokens, expectation="availability_unknown"))
        entries.append(dict(query="zzqvaudit7f29nonexistent", intended="Synthetic absent title", aliases=[],
                            year=None, scenario="negative_control", variant_tokens="", expectation="no_title_match"))
        assert len(entries) == 32, slug
        for index, case in enumerate(entries, 1):
            case["aliases"] = list(dict.fromkeys(case["aliases"] + title_aliases.get(case["intended"], [])))
            case["exclude_phrases"] = exclusions.get(case["intended"], [])
            case.update(id=f"{slug}-{index:02}", provider=slug)
            cases.append(case)
    return dict(schema=1, created="2026-10-03", baseline="v0.7.0",
                rationale="32 queries per provider: 24 stratified titles/products/artists, 7 variants, 1 synthetic negative. Fixed purposive sample, not a random catalog sample. Years on software/mobile rows identify the audit's intended era, not a claimed first-release date. Title matching is a candidate proxy, not ground truth or recall.",
                cases=cases)


if __name__ == "__main__":
    target = Path("docs/audits/2026-10-03/cases.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(build()['cases'])} cases to {target}")
