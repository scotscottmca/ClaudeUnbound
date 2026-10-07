# Pokemon Unbound as an LLM-Agent Target: Gameplay, Structure, Mechanics, Tooling

Research note (2026-10-07). Source access caveat: the PokeCommunity thread (403), TV Tropes (403), pokemoncoders level-cap page (403), Fandom wiki (402) and a Reddit mirror (502) could not be fetched; facts below come mainly from unboundwiki.com (community wiki), gamebrew.org, and search-result snippets. Search snippets are flagged as such. No ROM links included.

## 1. What Unbound is: version, region, length, structure, postgame

### Takeaway
Unbound is Skeli's FireRed-based hack set in the original Borrius region. The latest stable release is 2.1.1.1, last updated Dec 2022, and I found no newer release. It has 8 gyms, Elite Four and a Champion, and a 39-part main walkthrough plus postgame. That makes it markedly longer than FireRed and much more cutscene- and story-heavy.

### Cited Findings
- Latest version listed as "Unbound 2.1.1.1 + UBF 2.0.1" (UBF = Unbound Battle Frontier demo, a separate build), author Skeli, last updated December 20, 2022. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- Search snippet: "Version 2.1.1+ is the latest release with all bug fixes and the complete story including post-game"; v2.0 released Dec 19, 2021, which refined the story, redesigned characters, added a new organization (the Science Society), added more anti-frustration features and more postgame missions. — [unboundwiki Unbound Cloud page / search snippet](https://unboundwiki.com/game-mechanics/unbound-cloud/); [Miketendo64 patch notes article](https://miketendo64.com/2021/09/22/feature-patch-notes-screenshots/)
- Base: Pokemon FireRed (US). Region: Borrius (fan-made). Pokemon from Gen I–VII with Gen VIII mechanics. Mascot: Hoopa Unbound. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- Story: an ancient dark force sealed centuries ago; the villain organization "Shadows" wants to release it. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- The wiki walkthrough has 39 main-story parts plus Part 40 (postgame: "Ruins of Void & Saving Mom"). Order: Frozen Heights/Bellin Town → Icicle Cave/Rt 2 → Dresco Town (Gym 1) → Grim Woods → Cinder Volcano → Crater Town/KBT Expressway (Gym 2) → Valley Cave → Frost Mountain/Blizzard City (Gym 3) → Fallshore City, Epidimy, Tehl Town → Fallshore Gym (4) → Thundercap Mountain → Tarmigan Mansion → Dehara City → Ruins of Void → Cinder Volcano Depths & Shadow Base → Dehara Gym (5) → Auburn Waterway/Lost Tunnel → Thundercap Mountain again → Great Desert/Gurun Town → Vivill Woods & Distortion World → Vivill Town → Antisis City/Port/Sewers → Antisis Gym (6) & Icy Hole → Antisis side of Thundercap → Seaport City warehouses → boat to East Borrius → Polder Gym (7) & Safari Zone → Cootes Bog/Magnolia Town → Crystal Peak → Redwood Gym (8) → Route 18 "Pre-E4 grind" → Victory Road → Pokemon League. — [unboundwiki walkthrough index](https://unboundwiki.com/walkthrough/)
- Postgame includes battle facilities, missions, legendary encounters and KBT Expressway mining. Mewtwo, Genesect, Marshadow, Meltan/Melmetal, Poipole/Naganadel are missing from normal play and are distributed via Mystery Gift codes postgame. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- The postgame story continues: you defeat "Aklove" in the Depths of the Ruins of Void, which triggers a second credits sequence. — [unboundwiki Missions](https://unboundwiki.com/missions/)
- Over 180 original music tracks. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)

### Inferences
- With 39 walkthrough parts against roughly 8–10 natural segments in FireRed, the main story is probably 2–3x FireRed's length. Community playtimes are commonly quoted at 40–60+ hours, but I did not find a source for that, so treat it as unverified.
- The route is not linear in the Kanto sense. Thundercap Mountain is visited three times (Parts 15, 23, 30) and Cinder Volcano twice (5, 19). An agent needs a persistent map memory and "where do I go next" knowledge.

### Gaps
- I could not confirm from the PokeCommunity OP whether any release after 2.1.1.1 exists as of Oct 2026. The thread was blocked. I found no evidence of one.
- I found no sourced hours-to-beat figure, and no HowLongToBeat data was fetched.

## 2. Mechanics and QoL systems that differ from FireRed

### Takeaway
Unbound replaces much of FireRed's friction. It has no HM slaves, unlimited bag space, auto-run, DexNav, raids, missions, day/night and modern battle mechanics. It also adds more systems an agent has to learn: the mission log, raid dens, DexNav, the Unbound Cloud and an extended options menu.

### Cited Findings
- QoL features: unlimited bag space, auto-run, DexNav, daily raids, and a revised HM system. Battle features: physical/special split, Fairy type and modern type chart, Mega Evolution, Z-Moves, Dynamax (raids). — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA); [search snippet, unboundwiki/pokemoncoders](https://www.pokemoncoders.com/pokemon-unbound/)
- Also: a mission system with 80+ objectives, character customization, and a dynamic day/night cycle. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- HM system: if a party Pokemon can *learn* an HM, it can use that field move in the overworld without knowing it. In the postgame you can buy an "ADM" key item that lets any party member use all HMs. A free Move Deleter can remove HM moves. — [search snippet citing unboundwiki move-deleter / fandomspot](https://unboundwiki.com/misc-info/useful-npcs/move-deleter/); [FandomSpot no-HM hacks list](https://www.fandomspot.com/pokemon-hacks-with-no-hms/)
- HMs still gate progress. For example, Rock Climb is obtained after beating Antisis Gym leader Big Mo and is required for Icy Hole. — [unboundwiki Part 29](https://unboundwiki.com/walkthrough/part-29/)
- Missions: 84 total, 27 only available postgame. Only Mission #001 ("A Hero's Journey" = finish the main story) is mandatory. Mission HQ is in Fallshore City, with rewards at 20 missions (Type: Null), 45 (Latios) and 65 (Shiny Charm). After the postgame Aklove fight, the Missions screen shows locations of incomplete missions. — [unboundwiki Missions](https://unboundwiki.com/missions/)
- Options menu: Battle options (Battle Effects, Battle Style, Item Restrictions, EXP distribution, Team Preview, Type Icons, Nickname prompts); General options (**Puzzle Difficulty**, **Quick HM**, **Cutscene skipping**); Audio options. — [unboundwiki Game Settings](https://unboundwiki.com/game-mechanics/game-settings/)
- Other mechanics pages: DexNav, Gen 8 encounter activation, Swarms, Unbound Cloud. — [unboundwiki Game Mechanics](https://unboundwiki.com/game-mechanics/)
- Unbound Cloud is a website that stores Pokemon from your save file in cloud storage and helps move, transfer and trade Pokemon between boxes. — [unboundwiki Unbound Cloud (search snippet)](https://unboundwiki.com/game-mechanics/unbound-cloud/)
- Raid dens have their own wiki page with drop tables, and there is a mining item list (KBT Expressway mining). — [unboundwiki home](https://unboundwiki.com/)
- RTC must be enabled for daily events (raids and other daily activities). — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)

### Inferences
- For an agent, the **Cutscene skipping** and **Quick HM** options are high-value settings to turn on at game start. Unbound is very dialogue-heavy, and every skipped text box saves inference calls. Exactly what "Quick HM" does was not documented in what I could fetch.
- Set **Puzzle Difficulty** to normal/easy. On challenging, several puzzles become much harder (see section 3).
- Unlimited bag space plus pockets means the bag UI differs from FireRed's. A FireRed-trained memory-reading harness probably cannot reuse vanilla RAM offsets for the bag, party or options, because Unbound uses the CFRU engine (inference: Skeli authored CFRU, a large FireRed engine upgrade) and relocates many structures. Verify against the Unbound/CFRU source or by RAM inspection.

### Gaps
- I could not verify a crafting system. No source mentioned crafting.
- I found no sourced specifics on the Unbound start menu or PC redesign, follow-me Pokemon, a ride system, or a randomizer in the main game. The Ydarissep Pokédex mentions "Randomizers and Rebalanced Stats (Scalemons)" options (search snippet), but I could not confirm whether these are in-game new-game options.
- Mega/Z/Dynamax availability timing (e.g. when the Key Stone and Z-Ring are obtained) is not confirmed.

## 3. Difficulty modes, level caps, and hard sections for an AI

### Takeaway
There are four modes. Vanilla (sometimes called Easy or Casual) is the agent-friendly choice. Harder modes must be picked at the start, you can drop down but never go back up, and they add stronger AI, bigger teams and in-battle item restrictions. Level caps and trainer scaling exist. The known AI pain points are optional "challenging" puzzles (Cube Space, Dehara Gym, Distortion World boulders, Hoopa tile puzzle), ice-sliding caves, the Antisis Gym restricted-move ring challenge, and repeated revisits to multi-part dungeons.

### Cited Findings
- Four modes, listed as "ranging from Easy to Insane": Easy/Vanilla, Difficult, Expert, Insane. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA). The naming conflicts: a search snippet calls the lowest mode "Casual" ([search snippet](https://www.pokemoncoders.com/level-caps-in-pokemon-unbound/)), and the wiki options page calls it "Vanilla" ([unboundwiki](https://unboundwiki.com/game-mechanics/game-settings/)).
- "Harder modes are only available at the start of the game … no flip-flopping between Vanilla and harder modes to gain more Exp … Difficult mode may still be accessed from Vanilla mode." — [unboundwiki Game Settings](https://unboundwiki.com/game-mechanics/game-settings/). (The wording is ambiguous. My reading is that you can always lower the difficulty, but going from Vanilla back up is limited to Difficult.)
- Insane mode: advanced AI, restricted healing in battle, tougher teams. — [search snippet](https://www.pokemoncoders.com/level-caps-in-pokemon-unbound/) (secondary source)
- Level caps: cap after badge 1 is 22 in Vanilla vs 26 in Difficult+. Final cap is 66 Vanilla vs 75 Difficult+. Trainer levels scale with your party if you are ahead of the base curve. — [pokemoncoders search snippet](https://www.pokemoncoders.com/level-caps-in-pokemon-unbound/) (page itself returned 403)
- An "Item Restrictions" battle option exists. — [unboundwiki Game Settings](https://unboundwiki.com/game-mechanics/game-settings/)
- Puzzles affected by the Puzzle Difficulty setting: (1) Cube Space in the Ruins of Void (teleporter maze); (2) Dehara City Gym (switches across floors, "more backtracking"); (3) Distortion World (multiple boulder-push sequences, "especially hard" on Challenging); (4) Hoopa tile puzzle (sliding-tile image, "significantly easier in normal difficulty since the individual tiles can be picked and dropped at will"). — [unboundwiki Challenging Puzzles](https://unboundwiki.com/misc-info/challenging-puzzles/)
- The Distortion World is entered after raiding the Vivill Warehouse, alongside the character Jax (story-mandatory, Part 25). — [search snippet re unboundwiki](https://unboundwiki.com/misc-info/challenging-puzzles/); [walkthrough index](https://unboundwiki.com/walkthrough/)
- Icicle Cave / Icy Hole have ice-sliding puzzles. The north puzzle on Icicle Cave 1F takes 21 moves to reach the Skiers Club. The south puzzle requires pushing a Strength boulder into a hole to reach B1F. Some NPCs must be talked to from a specific side. — [unboundwiki Part 29](https://unboundwiki.com/walkthrough/part-29/)
- Antisis Gym ring challenge: three trainers with one Pokemon each, and Flying-, Psychic- or Fairy-type moves are forbidden. Then you fight leader Big Mo with your full team. — [unboundwiki Part 29](https://unboundwiki.com/walkthrough/part-29/)
- Other walkthrough sections that are likely hard for an agent, by name: Grim Woods, Valley Cave, Frozen Forest, Thundercap Mountain (3 visits), Tarmigan Mansion, Ruins of Void, Shadow Base, Lost Tunnel, Great Desert, Antisis Sewers, Cootes Bog, Crystal Peak, Victory Road. The walkthrough labels Part 37 as "Pre-E4 Grind". — [unboundwiki walkthrough index](https://unboundwiki.com/walkthrough/)

### Inferences
- Recommended agent configuration: Vanilla difficulty, normal puzzle difficulty, cutscene skip on. Even Vanilla is widely regarded as harder than FireRed (not sourced). Expect boss trainers with competitive-style sets that need real type and damage reasoning.
- Level caps help an agent because grinding past the cap is impossible. They also hurt, because a weak agent cannot simply overlevel past a hard boss (a known cheap LLM-agent strategy).
- Ice-sliding and boulder puzzles are classic failure modes for vision-only agents. Pre-computed solutions from the wiki (such as the 21-step Icicle Cave route) could be fed in as knowledge.
- The ring challenge's move-type restriction is a rules-reading test. An agent that ignores it may be disqualified or forced to restart.

### Gaps
- No exact per-mode rules were found for Difficult, Expert and Insane (e.g. whether Expert/Insane ban bag items in battle, force Set mode, or give opponents EVs). The primary docs (OP, Discord) were inaccessible.
- No source covers dark caves/Flash usage, a full level-cap table, or which gym leaders the community considers the hardest bosses.
- "Shadow Warriors" was not confirmed as a term. Sources call the villains "Shadows" (GameBrew), and the Science Society is a second organization added in 2.0.

## 4. Patching, base ROM, and emulator compatibility

### Takeaway
Unbound is distributed as a patch for a clean US FireRed ROM, not as a standalone ROM. It needs RTC emulation for daily features. Expect FireRed's Flash 128K save type. Under mGBA, RTC data is appended to the .sav, and hacks sometimes need a manual save-type override.

### Cited Findings
- Requires Pokemon FireRed (US) and lists the file as "Pokemon Fire Red (U) (Squirrels)". Patching tools are included in the download. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- RTC must be enabled for daily events. — [GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)
- A user reported Unbound showing an "enable RTC" message on every start on a platform without an RTC toggle (mGBA forum thread context, PS Vita port). mGBA appends 16 bytes of RTC state to the save file. ROM hacks may not be auto-detected as Flash 128K and may need a manual override. — [mGBA forums (search synthesis)](https://forums.mgba.io/printthread.php?tid=5737); [mGBA forums](https://forums.mgba.io/printthread.php?tid=435)
- RetroAchievements has Unbound game entries (IDs 17530 and 24224), which suggests it runs under RetroArch/RAIntegration-supported emulators. — [RetroAchievements 17530 comments](https://retroachievements.org/game/17530/comments); [RetroAchievements 24224](https://retroachievements.org/game/24224)

### Inferences
- For an agent harness: run mGBA (or BizHawk with the mGBA core) with save type forced to Flash 128K and RTC enabled. The FireRed game code (BPRE) is preserved by patching, so auto-detection usually works, but verify.
- The RTC requirement makes runs non-deterministic across wall-clock time (day/night, daily raids). For reproducible agent runs, pin or fake the RTC time (mGBA supports a fixed or offset RTC).

### Gaps
- Patch format (UPS vs BPS) and the required FireRed revision (1.0 vs 1.1) were not confirmed from a primary source. GameBrew only says "patching tools included". My recollection that it requires FireRed v1.0 (squirrels dump) and a .bps patch is unverified.
- No primary-source emulator recommendation or known-incompatible list was found (OP blocked).

## 5. Knowledge resources usable by an agent; speedrun/nuzlocke community

### Takeaway
There is a rich, structured community knowledge base: unboundwiki.com (walkthrough, locations, trainers, raids, missions, items), trainer docs, a boss Showdown-calc fork, and the Ydarissep Pokédex. Together they could serve as a retrieval corpus for an agent. I found no sourced speedrun data.

### Cited Findings
- unboundwiki.com sections: Walkthrough (40 parts), All Pokemon, Items (evolution items, Mega Stones, Z-Crystals, TMs/HMs, Zygarde Cells, held/key items, berries, balls, hidden items, mining items), Locations, Missions (individual pages such as /missions/mission-004/), Gyms, Raid Dens, Move Tutors, Elite Four, Legendary Pokemon, Extras/Side-quests (Magnolia Café), Useful NPCs. — [unboundwiki home](https://unboundwiki.com/)
- Community resource list (from search snippet of a nuzlocke resource page): the Unbound Wiki "collates information from most of the documents, including trainer spreads, Pokémon locations, item locations, and Raid Drops"; "Trainer Docs" directory linking an "Unbound Calculator"; a Pokemon Showdown damage calculator for Unbound bosses; and the "Ydarissep Pokédex" with "practically all information regarding every Pokémon", including Randomizer and Scalemons options. — [Nuzlocke University resources (search snippet)](https://nuzlockeuniversity.ca/resources/)
- Subreddit r/PokemonUnbound is active (mirror shows a Dec 2024 snapshot). — [mirror listing](https://red.applefritter.com/r/PokemonUnbound)
- RetroAchievements sets exist (see above), which is a structured milestone list useful for progress tracking. — [RetroAchievements 17530](https://retroachievements.org/game/17530/comments)

### Inferences
- An agent could pre-load the wiki walkthrough (Parts 1–40), the gym and E4 rosters, and the puzzle solutions page as RAG context. The calc fork with boss sets enables pre-battle planning.
- RetroAchievements achievement definitions give a ready-made progress or reward signal for benchmarking an agent.

### Gaps
- Exact URLs for the Trainer Docs, the Unbound calc and the Ydarissep Pokédex were not retrieved (the source page wasn't fetched directly). The Ydarissep dex is believed to be hosted on GitHub Pages, unverified.
- I found no speedrun.com leaderboard data, nuzlocke rule-set specifics, or YouTube walkthrough index.
- Discord documentation mirrors were not accessible.
