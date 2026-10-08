# Unbound 2.1.1.1 RAM addresses

Checked against live RAM in mGBA 0.10.5 with `bridge/probe.py`. `bridge/state.py` reads all of the verified ones at once.

Status: **verified** = values match what's on screen; **plausible** = right shape, meaning not proven; **pending** = needs a scene not yet reached.

| Symbol | Address | Status | Evidence |
|---|---|---|---|
| `gMain` | 0x030030F0 | verified | callback1 0x08056535 / callback2 0x080565B5 (vanilla `CB1/CB2_Overworld`) in overworld, 0x080123E5 / 0x08011101 (`BattleMainCB2`) in battle, callback2 0x08137EE9 with the summary screen open (callback1 unchanged); `vblankCounter2` (+0x24) advances ~60 per 60 frames; `vblankCounter1` (+0x20) is a pointer, NULL |
| `gSaveBlock1Ptr` | 0x03005008 | verified | → 0x0202552C. `pos` (+0) changed y 2→4 after walking down 2 tiles; `location` (+4) group/num match the object event; `mapLayoutId` (+0x32) matches `gMapHeader`; `playerPartyCount` (+0x34) is the saved copy, stale until save. `money` (+0x290) is a plain u32: read 3848, matching the trainer card (SaveBlock2's XOR key at +0xF20 is 0). Flags at +0xEE0; badge flags assumed vanilla 0x820–0x827, all 0 before the first gym (**unverified**) |
| `gSaveBlock2Ptr` | 0x0300500C | verified | → 0x02024588. `playerName` (+0) decodes "Claude"; play time at +0xE |
| `gSaveBlock3Ptr` | 0x03005010 | plausible | → 0x02029314 (EWRAM). Contents not checked |
| `gMapHeader` | 0x02036DFC | verified | layout/events/scripts are ROM pointers (scripts at 0x09E8FD70, Unbound's expanded space); `mapLayoutId` 0x197 = SaveBlock1's; `mapType` 8 (indoor) in an indoor map. Walking to the next map: group/num 4/10 → 4/11 and `mapLayoutId` 0x197 → 0x198 in both SaveBlock1 and `gMapHeader`, with new layout/event pointers |
| `gObjectEvents` | 0x02036E38 | verified | 0x24 each. Player is `localId` 0xFF; `currentCoords` (+0x10) = SaveBlock1 `pos` + 7; facing (+0x18 low nibble) 1 = down after walking down, 4 = right when talking to an NPC on the right |
| `gPlayerAvatar` | 0x02037078 | verified | `flags` 0x01 (on foot), `objectEventId` (+5) 0 = player's slot |
| `gPlayerPartyCount` | 0x02024029 | verified | u8, 0 → 1 on receiving the starter. Use this, not SaveBlock1 +0x34, which only syncs on save |
| `gPlayerParty` | 0x02024284 | verified | 100 bytes each, **unencrypted**, substructs in fixed order: Growth +0x20 (species 246 Larvitar, exp 560 = level 10 medium-slow), Attacks +0x2C (moves 43/88/201/44, PP 30/15/10/25, matching Leer/Rock Throw/Sandstorm/Bite), EVs +0x38, Misc +0x44 (met location 0x85 = current map's region section). Nickname +8 "Larvitar", OT +0x14 "Claude", OT ID +4 = SaveBlock2's. Level +0x54 = 10, HP +0x56/+0x58 = 30/30, stats follow. Slot 2 (scene 10): Snorunt, level 8, HP 5/27, moves Astonish/Leer with PP 12/29, all matching the party screen; Larvitar at 20/32 HP. Status +0x50 reads 0 for both with no condition; a nonzero status is not yet observed. Held item +0x22 = 44 = Berry Juice (vanilla item ID, confirmed on screen) |
| `gEnemyParty` | 0x0202402C | verified | Same unencrypted layout as `gPlayerParty`. Shadow Grunt's Inkay: species 794, level 7, HP 25/25; slot 2 Skorupi 504, level 7. Wild Snorunt in slot 0: 346, level 8, HP 28 |
| `gBattleMons` | 0x02023BE4 | verified | 0x58 each, 4 battlers (player, enemy, partner, enemy 2 in a multi battle: Larvitar, Inkay, Beldum, Skorupi). Species +0, stats +2..+0xB, moves +0xC, IVs +0x14, stat stages +0x18 (all 6), ability +0x20 (u8: Larvitar 62 = Guts), types +0x21/+0x22 (Larvitar 5/4 Rock/Ground, Inkay 17/14 Dark/Psychic), PP +0x24, HP +0x28, level +0x2A, max HP +0x2C, item +0x2E, nickname +0x30. Larvitar's entry matches its party slot exactly. Wild Snorunt (scene 6): species 346, level 8, types 15/15 (Ice). The ability byte is correct in Unbound's own numbering (see Abilities): Inkay 191 = Contrary, Snorunt 39 = Inner Focus |
| `gBattleTypeFlags` | 0x02022B4C | verified | 0 before the first battle, but **not cleared after a battle** (still 0x40000D back in the overworld), so only read it while callback2 is `BattleMainCB2`. 0x40000D in the multi battle with a partner (DOUBLE, IS_MASTER, TRAINER, CFRU in-game partner 0x400000); 0x4 (IS_MASTER only) in a wild single battle |
| `sTextPrinters` | 0x02020034 | verified | 0x24 each. Printer 0: `active` (+0x1B) 1 both while printing (`state` +0x1C = 0, `currentChar` +0 advancing through `gStringVar4`) and while waiting for A (`state` 2) |
| `gStringVar4` | 0x02021D18 | verified | holds the full expanded NPC message; standard Gen 3 charmap |
| `gDisplayedStringBattle` | 0x0202298C | verified | "You are challenged by Shadow Grunt!" while that message was on screen |
| `sLockFieldControls` (ScriptContext2) | 0x03000F9C | verified | u8: 0 walking freely, 1 with the start menu open (callback2 stays `CB2_Overworld`, so this is the only menu signal), back to 0 on close. Found by RAM diff |
| `Var8000` | 0x020370B8 | plausible | u16 script vars; values change between overworld and NPC dialog |
| `gNewBS` ptr | 0x0203E038 | plausible | 0x02002D60 in overworld (stale, not NULL), 0x020179B4 in both battles so far (EWRAM heap). Struct layout not checked |

## Bag (#17)

Pockets are arrays of u16 item ID + u16 count, no XOR, in EWRAM:

| Pocket | Address | Slots | Status |
|---|---|---|---|
| Items (main) | 0x0203BB20 | 450 | verified: Potion ×1 and Repel ×1 matched the Cube's Items pocket; using the Potion zeroed its slot immediately |
| Key Items | 0x0203C228 | 75 | verified: Costume Box ×1 (0x708 = 450 × 4 after the main pocket) |
| Poké Balls | 0x0203C354 | ? (reading 50) | verified contents (Poké Ball ×4); size unknown |
| TMs, Berries | | | pending: no items yet |

- Found by searching EWRAM for (item, count) pairs seen on the bag screen. Radical Red's 0x0203BB20 was right.
- Slots aren't compacted until the bag closes: a used-up item leaves a zero slot first.
- The bag is "Cube V3", the third icon in Unbound's start-menu bar (Pokédex?, Pokémon List, Cube V3, …, trainer card).

## Naming screen

| Name | Address | Status | Evidence |
|---|---|---|---|
| `sNamingScreen` (pointer) | 0x0203998C | verified | points at the struct (0x02002D60 on the rival and Beldum screens); the struct is heap-allocated, so after a capture it moved and fixed addresses read garbage. Fields below are offsets from it |
| naming-screen callback2 | 0x0809FB71 | verified | rival and Beldum nickname screens; changes once OK is confirmed |
| `textBuffer` | +0x1800 (was 0x02004560) | verified | 0xFF → 0xBB ('A') on typing; `naming.py` read back "Copilot" / "Iron Man" |
| `currentPage` (u8) | +0x1E22 (was 0x02004B82) | verified | 2 lower, 0 others, 1 upper; SELECT cycles 2→0→1, ~20 frames per switch |
| cursor x / y | `gSprites[cursorSpriteId (+0x1E23)].data[0..1]` (0x0202063C + 0x44·id + 0x2E/0x30) | verified | sprite 0 on both screens tested; RIGHT RIGHT DOWN LEFT diffed 0→1→2→2→1 / 0→0→0→1→1. x 8 is the button column (page, Back, OK) |

- Lower/upper pages match FireRed's grid (`abcdef .` / `ghijkl ,` / `mnopqrs ` / `tuvwxyz `), mapped by typing each key and reading the buffer. Typing a capital switches to lower case automatically.

## ROM name tables (#6)

`bridge/tables.py` builds `bridge/names.json` from these, checking each against known names:

| Table | ROM address | Layout | Count |
|---|---|---|---|
| Species names | 0x0966A98C | 11 bytes each | 1,294 (0–1293, last is Urshifu) |
| Move names | 0x08A40A10 | 13 bytes each | 923 |
| Ability names | 0x08A36398 | 17 bytes each | 293 |
| Items | 0x08876200 | 44-byte item structs, name in the first 14 bytes, item ID at +14 | 729 |
| Type names | 0x08A4EAD4 | 7 bytes each, abbreviated ("Electr"); vanilla order, 18–22 unused, Fairy = 23. `state.py` spells them out | 24 |
| Map section names | 0x083F1CAC | u32 pointers, index = mapsec − 0x58 | 109 (0x58–0xC4) |

- A map's name is its map section's name: `gMapHeader` +0x14, e.g. 0x85 Shadow Base, 0x65 Route 1. Indoor maps share their town's section.
- The vanilla item table at 0x083DB028 is unused (no references); the live one is the repointed copy.
- A few late item names use custom font glyphs to fit 14 bytes (e.g. item 724, Galarica Wreath) and decode with `?`.
- Ability display aliases (IDs 256–292) aren't applied: names show the shared effect's name (Rayquaza → Cloud Nine, displayed in game as Air Lock).

## Map, collision and events (#8)

`bridge/world.py` builds a viewport (15×10) and a whole-map grid plus NPC, warp, sign and connection lists.

| What | Address | Notes |
|---|---|---|
| `gBackupMapLayout` (VMap) | 0x03005040 | verified. s32 width, s32 height, u16* map. Width/height = layout + 15/14 (7-tile border, filled from connected maps). Found in `MapGridGetMetatileIdAt`'s literal pool |
| Map block (u16) | | metatile ID bits 0–9, collision 10–11, elevation 12–15 |
| Map layout | `gMapHeader` +0 | s32 width/height, then border, map, primary tileset (+0x10), secondary tileset (+0x14). Use the live pointer: the ROM header's layout field differs for Route 1 |
| Tileset | | metatile attributes pointer at +0x14, u32 each; behavior = attr & 0x1FF. Primary tileset holds metatiles 0–639 |
| Map events | `gMapHeader` +4 | counts (objects, warps, coord events, bg events) then 4 pointers. Warp 8 bytes: x, y, elevation, warpId, mapNum, mapGroup. Bg event 12 bytes: x, y, elevation, kind (7 = hidden item) |
| Connections | `gMapHeader` +0xC | s32 count, pointer to 12-byte entries: direction (1 S, 2 N, 3 W, 4 E), s32 offset, group, num |
| Map groups | 0x08B70498 | **obfuscated**: each group pointer is XOR'd with 0x00B749DE (Unbound's hook at 0x09ED15D4 replaces `Overworld_GetMapHeaderByGroupAndId`); entries are map header pointers, header +0x14 = map section |
| Player elevation | object event +0x0B low nibble | |

- **Elevation matters.** Walk-tested on Route 1: from elevation 3 the player can't step onto elevation 5 even with collision 0. The rule (vanilla): blocked unless the player's elevation is 0, or the tile's is 0, 15 or equal. Elevation-0 tiles (stairs, ramps) reset the player's elevation; 15 (bridges) keeps it. The grid shows other-level walkable tiles as `:`.
- **Walk test** (Route 1, savestate restored after): right 3 tiles then blocked, left 7 then blocked, up 1 then elevation-blocked, all exactly as the grid predicted.
- **Behavior IDs** match vanilla FireRed's on Route 1 by appearance: 0x02 tall grass, 0x21 sand (snow), 0x23 ice, 0x3B ledge south, 0x60 cave door (warp to Icicle Cave), 0x84 sign. Walk-tested so far: collision and elevation only. Ledges, ice, water and doors are **not yet walk-tested**.
- **Sideways stairs** (Unbound/CFRU, not vanilla): 0xB4 and 0xB5 move you diagonally. Walk-tested in Frozen Heights: RIGHT on 0xB4 (12,22) lands on (13,21); LEFT on 0xB5 (13,21) returns to (12,22). Pressing RIGHT from (12,21) into the 0xB5 tile does nothing (different elevation). Other orientations: pending. Ice (0x23) slides walk-tested on the same route.

## Abilities (#4)

Unbound numbers abilities differently from public CFRU, so never use CFRU's `ABILITY_*` constants. Use the ROM's own tables:

| Table | ROM address | Layout |
|---|---|---|
| Ability names | 0x08A36398 | 293 entries × 17 bytes, Gen 3 text. 0 = "-------", 77 = "Unused" |
| Species base stats | 0x099E0C9C | 0x1C per species. Types +6/+7, ability 1 +0x16, ability 2 +0x17 (0 = none), hidden ability +0x1A. Larvitar is species 246, Inkay 794, Snorunt 346 |

- **Storage is u8 everywhere.** Species base stats and `gBattleMons` +0x20 hold a single byte. No species uses an ID above 255.
- **IDs 256–292 are display-name aliases**, not separate abilities: Air Lock, Vital Spirit, White Smoke, Pure Power, Iron Barbs, Solid Rock, Turboblaze, Teravolt, the Neighs, Libero and so on. The species table stores the effect's ID (Rayquaza 13 Cloud Nine, Ferrothorn 24 Rough Skin, Reshiram 152 Mold Breaker) and the game shows the alias name for specific species. The alias lookup isn't a plain (species, id) table; it's probably in code. Left for #6, since only the display name depends on it.
- **Party struct has no ability field.** The ability comes from the species table:
  - IV word +0x48 bit 31 = `hiddenAbility` (CFRU), meaning use +0x1A. Bit 30 = egg. Not yet seen set.
  - Otherwise personality (+0) bit 0 picks ability 1 (even) or ability 2 (odd), falling back to ability 1 when ability 2 is 0. Even → ability 1 is confirmed: the caught Snorunt (PID 0x59EEE024) shows Inner Focus on its summary screen and reads 39 in battle; a wild Snorunt (even PID) and Inkay (even) also read ability 1. **Odd → ability 2 is not yet observed.**
  - Gigantamax: CFRU puts it in bit 15 of the origin word (+0x46). Not yet seen set.
- **`gBattleMons` +0x20** is the battler's current ability (u8, same numbering), and matched the party-derived ability in every check.
- The scene 6 reading of 105 (Ice Body) for a wild Snorunt couldn't be re-checked. It fits a different Snorunt with an odd PID.

## Phase 0 exit test

Party, position, map ID and dialog text read correctly across 10 hand-played scenes, each checked against a screenshot or the player's report:

| # | Scene | Result |
|---|---|---|
| 1 | Overworld, standing | pass |
| 2 | Dialog mid-print | pass |
| 3 | Dialog waiting for A | pass |
| 4 | Starter received | pass |
| 5 | Map change | pass (found `gBattleTypeFlags` stays set after battle) |
| 6 | Wild battle, move menu | pass |
| 7 | Battle message on screen | pass |
| 8 | Trainer battle, move menu | pass |
| 9 | Summary screen open | pass |
| 10 | Two party members, both damaged | pass (status condition not observed) |

## Notes

- Mode detection: battle if callback2 is `BattleMainCB2` (0x08011101), dialog if printer 0 is active, overworld if callback2 is `CB2_Overworld` and field controls aren't locked, else other (menus, cutscenes).
- `gStringVar4` keeps the last message after the box closes, so only trust it when printer 0 is active.
