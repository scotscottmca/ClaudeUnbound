# Pokemon Unbound internals: reading game state from emulator memory

Method: I shallow-cloned and grepped the CFRU, DPE, PUSE (Unbound save editor) and atendev/pokemon-memory-reader repos, and ran web searches and fetches. Where I cite repo files, I read the line in question myself. The CFRU links point to master as of 2026-10-07.

## 1. What CFRU and DPE change compared with vanilla FireRed (BPRE)

### Takeaway
CFRU is an injection framework. It inserts C/ASM into free ROM space (default 0x08900000) and hooks or rewrites vanilla routines. It does not relocate vanilla engine globals, so most pret/pokefirered (FR 1.0) RAM addresses still hold. The big differences for a RAM reader are listed below.
- **Party Pokémon data is unencrypted and unshuffled.** Species sits at struct offset 0x20.
- **PC boxes use a 58-byte packed format** and are spread across four RAM regions.
- **The save block is extended** with "parasite" space and flash sectors 30/31.
- **New battle state lives in `gNewBS`**, a pointer at 0x0203E038.
- **Species, move and ability tables are expanded and repointed** into ROM free space.

### Cited Findings
- **How CFRU builds and inserts code.** CFRU features include "Save-block expansion", "Expanded PC Boxes (up to 25!)" and Gen 8 battle mechanics. The build inserts at `OFFSET_TO_PUT` set in make.py and produces `test.gba` plus an **`offsets.ini`** that lists where each inserted symbol landed. That file is a per-build artifact and is not published for Unbound. — [CFRU README](https://github.com/Skeli789/Complete-Fire-Red-Upgrade)
- **Default ROM origin.** `linker.ld` sets the ROM origin to `0x08000000 + 0x900000` (code at 0x08900000+) and EWRAM at 0x02000000. — [CFRU linker.ld](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/linker.ld)
- **`BPRE.ld` is a vanilla-symbol map.** It is a roughly 2,069-line linker script of vanilla FR 1.0 symbol addresses that CFRU code links against. Selected entries:

  | Symbol | Address |
  |---|---|
  | `gMain` | 0x030030F0 |
  | `gSaveBlock1` (pointer) | 0x03005008 |
  | `gSaveBlock2` (pointer) | 0x0300500C |
  | `gSaveBlock3` (pointer) | 0x03005010 |
  | `gTasks` | 0x03005090 |
  | `gPlayerPartyCount` | 0x02024029 |
  | `gPlayerParty` | 0x02024284 |
  | `gEnemyParty` | 0x0202402C |
  | `gBattleMons` | 0x02023BE4 |
  | `gBattleStruct` | 0x02023FE8 |
  | `gBattleTypeFlags` | 0x02022B4C |
  | `gActiveBattler` | 0x02023BC4 |
  | `gBattlersCount` | 0x02023BCC |
  | `gBattlerPartyIndexes` | 0x02023BCE |
  | `gDisplayedStringBattle` | 0x0202298C |
  | `gStringVar1` / `gStringVar2` / `gStringVar3` / `gStringVar4` | 0x02021CD0 / 0x02021CF0 / 0x02021D04 / 0x02021D18 |
  | `gMapHeader` | 0x02036DFC |
  | `gEventObjects` (pret `gObjectEvents`) | 0x02036E38 |
  | `Var8000` | 0x020370B8 |
  | `gWindows` | 0x020204B4 |
  | `sTextPrinters` | 0x02020034 |
  | `gPaletteFade` | 0x02037AB8 |
  | `gNewBS` | 0x0203E038 |

  — [CFRU BPRE.ld](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/BPRE.ld)
- **More RAM addresses** from `include/new/ram_locs.h`:

  | Symbol | Address |
  |---|---|
  | `gWarp1` | 0x02031DBC |
  | `gPlayerAvatar` | 0x02037078 |
  | `gSpecialVar_LastResult` | 0x020370D0 |
  | `gSpecialVar_LastTalked` | 0x020370D2 |
  | `gWeatherPtr` | 0x02037F34 |
  | `gSafariSteps` | 0x02039996 |
  | `gQuestLogMode` | 0x0203ADFA |
  | `gSelectedEventObject` | 0x03005074 |
  | `gScriptEnv1` | 0x03000EB0 |
  | `gTrainerId` | 0x02020000 |

  CFRU-new RAM listed elsewhere in its headers:

  | Symbol | Address | Source file |
  |---|---|---|
  | `gFollowerState` | 0x0203B818 | `include/new/follow_me.h` |
  | `gPedometers` | 0x0203B7BC | `include/new/overworld.h` |
  | `gKeypadSetter` | 0x0203B7B0 | `include/new/read_keys.h` |

  — [CFRU include/new/ram_locs.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/new/ram_locs.h)
- **Battle globals stay at vanilla addresses.** `include/new/ram_locs_battle.h` lists them, including:

  | Symbol | Address |
  |---|---|
  | `gSideTimers` | 0x02023DE4 |
  | `gDisableStructs` | 0x02023E0C |
  | `gProtectStructs` | 0x02023E8C |
  | `gCurrentMove` | 0x02023D4A |
  | `gBattleMoveDamage` | 0x02023D50 |
  | `gBattlerAttacker` | 0x02023D6B |
  | `gBattlerTarget` | 0x02023D6C |
  | `gBattleTextBuff1` | 0x02022AB8 |
  | `gBattleBufferA` | 0x02022BC4 |

  — [CFRU ram_locs_battle.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/new/ram_locs_battle.h)
- **New battle struct.** `extern struct NewBattleStruct* gNewBS; //0x203E038`. This is a *pointer* to a heap-allocated struct holding CFRU's new battle state (terrain, Mega, Z-move, Dynamax and similar). — [CFRU include/battle.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/battle.h)
- **`BattlePokemon` changes.** CFRU's `struct BattlePokemon` keeps the vanilla 0x58-byte layout with these changes:
  - `altAbility:1` bit at 0x17
  - new `type3` at 0x18
  - `statStages` at 0x19
  - `u8 ability` at 0x20, `type1` at 0x21, `type2` at 0x22
  - `hp` at 0x28, `level` at 0x2A, `maxHP` at 0x2C, `item` at 0x2E
  - `status1` at 0x4C, `status2` at 0x50

  The species base-stats struct keeps `ability1` and `ability2` as u8 at +0x16 and +0x17. — [CFRU include/pokemon.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/pokemon.h)
- **Party Pokémon substructs.**
  - Substructure 0 gains a `pokeball` byte.
  - Substructure 3 gains `gigantamax:1` and `hiddenAbility:1`.
  - The CFRU `struct Pokemon` typedef lays substructs out in a fixed order:
    - Growth at 0x20: species, item, exp, ppBonuses, friendship, pokeball
    - Attacks at 0x2C: moves[4], pp[4]

  — [CFRU include/pokemon.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/pokemon.h)
- **Pokémon encryption is removed.** `bytereplacement` has a `##Decryption##` block that NOPs the XOR and substruct-shuffle code at 0x0803F906–0x0803FD94 and 0x0804051E. A separate `##Remove Save Encryption##` block is commented out (`#`). — [CFRU bytereplacement](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/bytereplacement)
- **An independent reader confirms the unencrypted layout.** atendev's BizHawk reader notes that for Radical Red (another CFRU hack) species "Stores directly at offset 32, unencrypted 16 bit little endian". Its Radical Red address profile:

  | Field | Address |
  |---|---|
  | `partyAddr` | 0x02024284 |
  | `enemyPartyAddr` | 0x0202402C |
  | `gBattleMons` | 0x02023BE4 |
  | `itemsPocket` | 0x0203BB20 (in RAM) |

  It also notes CFRU items are "4 bytes each, 2 for ID and 2 for quantity". — [atendev/pokemon-memory-reader gamesdb.lua / gen3partyreader.lua](https://github.com/atendev/pokemon-memory-reader)
- **PC box storage format.** CFRU compresses box Pokémon to `struct CompressedPokemon`, 58 bytes (0x3A).
  - Moves are packed as 10-bit fields.
  - Contest stats, ribbons and fateful encounter are dropped.
  - IVs are a packed u32.

  Box RAM, as hard-coded in CFRU:

  | Boxes | Address |
  |---|---|
  | 1–19 | `0x2029314 + 4` (vanilla `gPokemonStorage` region) |
  | 20–22 | `0x0203CB44` |
  | 23–24 | `0x02027434` |
  | 25 | `0x02024638` |

  — [CFRU src/pokemon_storage_system.c](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/pokemon_storage_system.c); [include/new/pokemon_storage_system.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/new/pokemon_storage_system.h)
- **Save block expansion.**
  - Flash sectors are 0xFF0 data bytes plus a footer, 14 sectors per slot. The CFRU file signature is `0x08012025`.
  - A "parasite" block of 0xEC4 bytes lives at RAM `0x0203B174`. It fills unused tails of section 0 (0xCC bytes), section 4 (0x258) and section 13 (0xBA0).
  - Flash sectors 30 and 31 are loaded into RAM right after the parasite, at `0x0203B174 + 0xEC4`.
  - Checksummed sizes: section 0 = 0xF24, section 4 = 0xD98, section 13 = 0x450.
  - The source credits the idea to JPAN.

  — [CFRU src/save.c](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/save.c)
- **New flags and vars.** CFRU adds flags 0x900–0x92A and 0xE00+ (daily) and vars 0x5000+. Examples:
  - `FLAG_INVERSE` 0x900
  - `FLAG_DOUBLE_BATTLE` 0x907
  - `FLAG_AUTO_RUN` 0x914
  - `FLAG_FAST_BATTLE_MESSAGES` 0x925
  - `VAR_DEXNAV` 0x500C

  `SAVE_BLOCK_EXPANSION` ("DO NOT COMMENT OUT!"), `TIME_ENABLED` (day/night) and `EXPANDED_TEXT_BUFFERS` are enabled. Unbound may use different values; see Gaps. — [CFRU src/config.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/config.h)
- **DPE (Dynamic Pokémon Expansion).**
  - Expands Pokémon data with no fixed repoint addresses ("Dynamic insertion, meaning no worrying about repointing ever!").
  - Supports up to 999 dex entries plus forms and 128 TMs/tutors.
  - Moves the seen/caught flag RAM into expanded save space.
  - Built from `BPRE0.gba` (FR 1.0).

  — [DPE README](https://github.com/Skeli789/Dynamic-Pokemon-Expansion)
- **Unbound table sizes, extracted from the ROM by the PUSE project:**
  - Species name table runs to ID 1293 (Urshifu), with a placeholder gap after ID 252 (Egg) and 253 (MISSINGNO?), resuming at 277 Treecko.
  - 923 move names.
  - 293 abilities (17-byte entries).
  - Species names are 11-byte entries.

  — [PUSE romre/DISCOVERIES.md](https://github.com/Zannael/PUSE/blob/master/romre/DISCOVERIES.md)

### Inferences
- An ability count of 293 is above u8 range, yet public CFRU stores abilities as `u8`. Unbound's private engine has probably widened ability storage, or uses extra bits; the unpublished 2.x engine may also differ elsewhere. Treat ability IDs in `gBattleMons` and base stats as needing verification against Unbound.
- Species IDs are not dense (there are gaps of `?` rows). Map IDs to names with a table extracted from the ROM, not by assuming National Dex order.
- **Save-block pointer shuffle.** Vanilla FR randomizes save-block pointers via `SetSaveBlocksPointers` (`offset = Random() & ...`; [pret load_save.c](https://github.com/pret/pokefirered/blob/master/src/load_save.c)). CFRU hard-codes the box RAM addresses, and the PUSE runtime probe found the boxes at those fixed addresses in Unbound. So the shuffle is likely neutralized; CFRU's byte patches at 0x0804C062/0x0804C064/0x0804C13C sit in that code region. Still, always dereference `gSaveBlock1Ptr` (0x03005008) rather than assuming a fixed address.

### Gaps
- I did not find the layout of CFRU's `struct NewBattleStruct` for the Unbound build. It is defined in CFRU `include/battle.h` but would need checking against Unbound, because Unbound's engine is a private fork.
- I could not confirm whether Unbound keeps CFRU's flag and var numbering. Unbound's script flags are undocumented publicly.

## 2. Is Unbound source public? Community tools for Unbound saves and RAM

### Takeaway
Unbound itself is closed source: there is no public repo or symbol file, and Skeli releases only patches. CFRU and DPE are open and are the closest public reference. Usable Unbound-specific tooling is concentrated in save editors:
- **PUSE** is MIT-licensed, actively maintained (last commit 2026-10-07), and includes ROM table extractors plus an mGBA headless RAM probe.
- **PKHeX.Everywhere** has had an Unbound bag-editing PR merged (2026-10-02).
- **OpenHome** fixed CFRU box handling for Unbound and Radical Red (merged 2026-09-26).

I found no Ironmon-style Lua tracker or Archipelago world for Unbound.

### Cited Findings
- **PUSE overview.** PUSE is a "Pokémon Unbound (online) Save Editor" targeting **Unbound v2.1.1.1**. It edits party, PC (boxes 1–24 plus a "Preset" box 26) and bag. Its data tables are `items.txt`, `pokemon.txt`, `moves.txt` and `tms.txt`, described as "ROM-truth". It is MIT-licensed. — [PUSE GitHub](https://github.com/Zannael/PUSE)
- **Unbound save signatures.** Unbound's save sector signature is `0x01121999` (or `0x01121998`), not CFRU's default `0x08012025`. That confirms Unbound sets `CUSTOM_FILE_SIGNATURE`. — [PUSE backend/core/sections.py](https://github.com/Zannael/PUSE/blob/master/backend/core/sections.py); compare [CFRU save.c](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/save.c)
- **Unbound 2.1.1.1 RAM box layout, verified by PUSE.** PUSE disassembled the ROM (box-pointer table at ROM 0x0A6CB2C) and checked it with an mGBA 0.10.5 headless probe. The layout matches CFRU's defaults:

  | Boxes | RAM address |
  |---|---|
  | 1–19 | 0x02029318 |
  | 20–22 | 0x0203CB44 |
  | 23–24 | 0x02027434 |
  | Final "Preset" box | 0x02024638 |

  The preset box name pointer is at RAM 0x020315F5. The save-size table is at ROM 0xA6CD88, referenced from 0xDA23C. The verified ROM SHA-256 is `7aa25bbf…739f7`. Save regions:

  | Storage | Save region |
  |---|---|
  | Boxes 1–19 | sections 5–13 |
  | Boxes 20–22 | physical sectors 30/31 (no footer/checksum) |
  | Boxes 23–24 | sections 2–3 |
  | Preset | section 0 + 0xB0 |

  — [PUSE romre/CFRU_IMPLEMENTATION_PLAN.md](https://github.com/Zannael/PUSE/blob/master/romre/CFRU_IMPLEMENTATION_PLAN.md)
- **Party record offsets** (100-byte unencrypted party mon):

  | Field | Offset |
  |---|---|
  | PID | 0x00 |
  | OTID | 0x04 |
  | nickname | 0x08 |
  | checksum | 0x1C |
  | data | 0x20 |
  | level | 0x54 |
  | current HP | 0x56 |
  | max HP | 0x58 |
  | Atk / Def / Spe / SpA / SpD | 0x5A / 0x5C / 0x5E / 0x60 / 0x62 |

  **PC record offsets** (58-byte compact record):

  | Field | Offset |
  |---|---|
  | species | 0x1C |
  | item | 0x1E |
  | exp | 0x20 |
  | moves | 0x24 |
  | EVs | 0x2C |
  | IVs | 0x36 (bit 30 = egg, bit 31 = hidden ability) |

  — [PUSE backend/modules/party.py, pc.py](https://github.com/Zannael/PUSE/tree/master/backend/modules)
- **Bag data.**
  - Main pocket: section 13 + 0xAD8, 450 slots, overflowing into sector 30.
  - Items are u16 ID + u16 count with no XOR.
  - TMs are reusable.

  — [PKHeX.Everywhere PR #520](https://github.com/arleypadua/PKHeX.Everywhere/pull/520); [PUSE bag.py](https://github.com/Zannael/PUSE/blob/master/backend/modules/bag.py)
- **PUSE extraction and probe tooling.**
  - The ROM extraction tools (`extract_unbound_species_table.py`, moves, abilities, base stats, items) locate tables by anchor-string and structural scanning, not by fixed offsets.
  - `unbound_emulator_probe.c` drives mGBA's C core API (`mCoreFind`, `runFrame`, `busRead8`, `savedataClone`) through a stdin protocol: `frames N keys`, `read addr len path`.

  — [PUSE backend/tools](https://github.com/Zannael/PUSE/tree/master/backend/tools)
- **OpenHome.** PR #1005 "Fixes bug preventing boxes 15-18 from being saved correctly in Unbound and Radical Red" (merged 2026-09-26), so OpenHome has CFRU save support. — [OpenHome PR #1005](https://github.com/andrewbenington/OpenHome/pull/1005)
- **Ironmon-Tracker** supports FR/LG/R/S/E only. It is a Lua tool for BizHawk 2.8+ and mGBA 0.10+, and mGBA mode is text-only. There is no Unbound support; an Emerald Archipelago extension exists. — [Ironmon-Tracker](https://github.com/besteon/Ironmon-Tracker); [Tracker Add-ons wiki](https://github.com/besteon/Ironmon-Tracker/wiki/Tracker-Add-ons)
- **atendev/pokemon-memory-reader** is a BizHawk Lua script with a REST API. It supports Emerald, FireRed and Radical Red (generation "CFRU"), keyed by ROM SHA-1. It does not support Unbound. — [atendev/pokemon-memory-reader](https://github.com/atendev/pokemon-memory-reader)
- **Unbound features in decomp.** A decomp recreation of Unbound's Quest Menu exists, with Skeli contributing. That suggests some Unbound features reached decomp projects, not that Unbound's source is published. — [PokeCommunity Unbound quest menu](https://pokecommunity.com/threads/unbound-quest-menu.477500/)

### Inferences
- The fastest Unbound RAM profile is CFRU `BPRE.ld` plus the PUSE-verified box addresses. Add Radical Red's CFRU profile as a sanity reference for party and battle addresses; they share the CFRU engine.
- PUSE's mGBA probe is a ready-made template for a headless harness, in C. The same `busRead8` approach works from mGBA Python bindings.

### Gaps
- I found no PKHeX core (kwsch) support for Unbound and no official PKHeX plugin. Searches returned only generic PKHeX pages.
- I found no Unbound Archipelago apworld and no Unbound Lua tracker in searches.
- I did not find "Unbound Cloud" or Discord-hosted RAM maps (Discord is not indexable).
- I did not verify whether the Unbound bag in *RAM* lives at the Radical Red address 0x0203BB20.

## 3. Does pret/pokefirered symbol knowledge apply?

### Takeaway
Yes, for core overworld and engine globals. CFRU's `BPRE.ld` lists the vanilla FR 1.0 addresses for `gMain`, `gSaveBlock1/2/3` pointers, `gMapHeader`, `gEventObjects`, `gTasks`, `gStringVar*`, `sTextPrinters` and the battle globals, and CFRU links against them. pret names differ in places (`gEventObjects` = `gObjectEvents`; `gSaveBlock1` = `gSaveBlock1Ptr`). The base ROM is FR **1.0**, so use pokefirered `firered` (rev 0) symbols, not rev 1.

### Cited Findings
- CFRU symbol addresses from `BPRE.ld` (`gMain` 0x030030F0, `gSaveBlock1` 0x03005008, `gMapHeader` 0x02036DFC, `gEventObjects` 0x02036E38, `gTasks` 0x03005090). — [CFRU BPRE.ld](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/BPRE.ld)
- DPE and CFRU are built from `BPRE0.gba`, which is FR 1.0. — [DPE README](https://github.com/Skeli789/Dynamic-Pokemon-Expansion)
- pret `load_save.c`: `gSaveBlock1Ptr = &gSaveBlock1 + offset`, with `offset = Random() & (SAVEBLOCK_MOVE_RANGE-1 & ~3)`. Pointers must be dereferenced. — [pret pokefirered load_save.c](https://github.com/pret/pokefirered/blob/master/src/load_save.c)
- Ironmon-Tracker distinguishes FR v1.0 (softwareVersion 0x00680000) and v1.1 (0x01670000) and stores per-version symbol JSON (for example `"gBattleMons":"02024a80"`). That shows addresses differ between revisions. — [Ironmon-Tracker GameSettings.lua](https://github.com/besteon/Ironmon-Tracker/blob/main/ironmon_tracker/GameSettings.lua)

### Inferences
- SaveBlock1 field offsets probably match vanilla: location and warp data, flags, vars, and the map object templates CFRU references (`gSaveBlock1->location.mapGroup`, `registeredItems`). Items and expanded flags/vars move into parasite or extra space.
- Metatile and collision data come from `gMapHeader->mapLayout` and `gBackupMapLayout`. Vanilla code handles these and should still work, but Unbound's maps are new data in ROM. Read them via pointers, never via hard-coded ROM addresses.
- Map bank and number IDs are Unbound-specific, so a map-name table must be extracted from the ROM or built by hand.

### Gaps
- I did not find a published `.sym` file for Unbound. Unbound-specific new RAM (quest/mission log, DexNav state, day/night) must be found by memory diffing.

## 4. Practical approaches for a harness

### Takeaway
Use mGBA, through its Python bindings, Lua scripting (0.10+), or the C core API as PUSE does, or BizHawk with Lua over a socket. Read:
- party at 0x02024284 (unencrypted CFRU layout)
- battle state at `gBattleMons` 0x02023BE4 and `gBattleTypeFlags`
- position via `gSaveBlock1Ptr`

Then derive everything Unbound-specific by RAM diffing, using CFRU source as the structural guide.

### Cited Findings
- mGBA scripting is available in 0.10+. Ironmon-Tracker runs on mGBA 0.10.0+ (text-only output) and on BizHawk 2.8+. — [Ironmon-Tracker](https://github.com/besteon/Ironmon-Tracker)
- PUSE's headless mGBA C probe uses frame stepping, key input, `busRead8` memory reads and savedata cloning, built against mGBA 0.10.5. — [PUSE unbound_emulator_probe.c](https://github.com/Zannael/PUSE/blob/master/backend/tools/unbound_emulator_probe.c)
- A BizHawkClient-to-mGBA bridge script exists, the Archipelago-style connector. — [Zunawe gist](https://gist.github.com/Zunawe/d41677500b08694c9985f67f41896cc5)
- atendev's reader exposes BizHawk Lua RAM reads as a REST API, with per-ROM address profiles that include CFRU. — [atendev/pokemon-memory-reader](https://github.com/atendev/pokemon-memory-reader)
- The TASVideos Gen 3 resource page documents vanilla RAM. — [TASVideos Pokemon Gen3](https://tasvideos.org/GameResources/GBA/PokemonGen3)

### Inferences
What to re-derive for Unbound:
- ROM addresses of the species, move, ability and item name tables. Use PUSE's extractors, or a pointer scan from the vanilla table references.
- Bag RAM location.
- `gNewBS` struct layout.
- Flag and var meanings.
- Map ID names.
- Quest-log RAM.

Vanilla FR harness code that decrypts party data (the XOR plus `personality % 24` order) must be **disabled** for Unbound.

### Gaps
- I found no public AI-agent harness for Unbound specifically.

## 5. Text extraction

### Takeaway
Dialogue can be read from RAM through the vanilla text system:
- `sTextPrinters` at 0x02020034, whose `currentChar` pointer points into the ROM/RAM string
- `gStringVar4` at 0x02021D18, the expanded message buffer for msgbox
- `gDisplayedStringBattle` at 0x0202298C in battle

Unbound uses the standard Gen 3 English charset: CFRU `charmap.tbl` is the vanilla table (A=0xBB, a=0xD5, 0=0xA1, 0xFF terminator). No custom font encoding was found.

### Cited Findings
- `sTextPrinters` 0x02020034 and `gStringVar1–4` 0x02021CD0–0x02021D18. — [CFRU BPRE.ld](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/BPRE.ld)
- `gDisplayedStringBattle` 0x0202298C and `gBattleTextBuff1/2/3` 0x02022AB8/0x02022AC8/0x02022AD8. — [CFRU ram_locs_battle.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/new/ram_locs_battle.h)
- CFRU `charmap.tbl` (150 lines) uses the standard Gen 3 mappings (0xBB=A, 0xF0=:, 0xB5=♂, 0xB6=♀). — [CFRU charmap.tbl](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/charmap.tbl)
- PUSE decodes Unbound ROM names with the same map: 0xA1 digits, 0xBB uppercase, 0xD5 lowercase, 0xFF end. — [PUSE extract_unbound_species_table.py](https://github.com/Zannael/PUSE/blob/master/backend/tools/extract_unbound_species_table.py)
- CFRU text changes:
  - `EXPANDED_TEXT_BUFFERS` adds extra scripting string buffers at locations not in `BPRE.ld`.
  - `AUTOSCROLL_TEXT_BY_HOLDING_R` is enabled.
  - `FLAG_FAST_BATTLE_MESSAGES` 0x925 makes battle text print with no wait.

  — [CFRU config.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/config.h); [CFRU src/text_printer.c](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/text_printer.c)

### Inferences
- The robust approach is to read the `TextPrinter` struct for window 0 or the message window (pret layout: `printerTemplate.currentChar` pointer) and decode from that pointer up to 0xFF. Control codes 0xFC/0xFD (placeholders) are expanded beforehand into `gStringVar4` for msgbox text.
- Unbound's custom menus (missions, Quest log, DexNav) print via the same window and text system but may use their own buffers. Screen OCR or a screenshot is the fallback.

### Gaps
- I could not confirm Unbound's address for the expanded text buffers. Search RAM for known on-screen strings encoded with the Gen 3 charmap.
