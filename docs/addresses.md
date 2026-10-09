# Unbound 2.1.1.1 RAM addresses

Checked against live RAM in mGBA 0.10.5 with `bridge/probe.py`. `bridge/state.py` reads all of the verified ones at once.

Status: **verified** = values match what's on screen; **plausible** = right shape, meaning not proven; **pending** = needs a scene not yet reached.

| Symbol | Address | Status | Evidence |
|---|---|---|---|
| `gMain` | 0x030030F0 | verified | callback1 0x08056535 / callback2 0x080565B5 (vanilla `CB1/CB2_Overworld`) in overworld, 0x080123E5 / 0x08011101 (`BattleMainCB2`) in battle, callback2 0x08137EE9 with the summary screen open (callback1 unchanged); `vblankCounter2` (+0x24) advances ~60 per 60 frames; `vblankCounter1` (+0x20) is a pointer, NULL |
| `gSaveBlock1Ptr` | 0x03005008 | verified | → 0x0202552C. `pos` (+0) changed y 2→4 after walking down 2 tiles; `location` (+4) group/num match the object event; `mapLayoutId` (+0x32) matches `gMapHeader`; `playerPartyCount` (+0x34) is the saved copy, stale until save. `money` (+0x290) is a plain u32: read 3848, matching the trainer card (SaveBlock2's XOR key at +0xF20 is 0). Flags at +0xEE0; badge flags assumed vanilla 0x820–0x827, all 0 before the first gym (**unverified**) |
| `gSaveBlock2Ptr` | 0x0300500C | verified | → 0x02024588. `playerName` (+0) decodes "Claude"; play time at +0xE |
| Play time | SaveBlock2 +0x0E | verified | u16 hours, u8 minutes +0x10, u8 seconds +0x11, u8 frames +0x12 (vanilla). Read live (agent paused, emulator running): 4h 23m, seconds 1 → 4 over 3 s of wall time. Used by `ui/server.py` |
| Pokédex owned flags | SaveBlock1 +0x38D (0x020258B9) | verified | CFRU's expanded dex, not vanilla SaveBlock2 +0x28 (all zero on Unbound). 0x7D bytes, bit n-1 = national dex n. Read live: 12 bits = Caterpie, Zubat, Swinub, Magby, Seedot, Makuhita, Numel, Duskull, Beldum, Metang, Patrat, Pumpkaboo, exactly the run's party + the 8 `throw_ball` "caught" results in log.jsonl (Beldum gift, Metang by evolution); no other species. Seen flags are the 0x7D bytes before it (SaveBlock1 +0x310, 0x0202583C): 58 bits, a superset of owned. Used by `ui/server.py` |
| Growth rate | base stats +0x13 | verified | 0 medium fast, 1 erratic, 2 fluctuating, 3 medium slow, 4 fast, 5 slow (Gen 3 curves). Live party exp (`gPlayerParty` +0x24) fell between the thresholds for each member's level and the next: Metang 25 (3), Makuhita 23 and 22 (2), Zubat 21 (0), Swinub 18 (5), Patrat 17 (0). Used by `ui/server.py` |
| `gSaveBlock3Ptr` | 0x03005010 | plausible | → 0x02029314 (EWRAM). Contents not checked |
| `gMapHeader` | 0x02036DFC | verified | layout/events/scripts are ROM pointers (scripts at 0x09E8FD70, Unbound's expanded space); `mapLayoutId` 0x197 = SaveBlock1's; `mapType` 8 (indoor) in an indoor map. Walking to the next map: group/num 4/10 → 4/11 and `mapLayoutId` 0x197 → 0x198 in both SaveBlock1 and `gMapHeader`, with new layout/event pointers |
| `gObjectEvents` | 0x02036E38 | verified | 0x24 each. Player is `localId` 0xFF; `currentCoords` (+0x10) = SaveBlock1 `pos` + 7; facing (+0x18 low nibble) 1 = down after walking down, 4 = right when talking to an NPC on the right |
| `gPlayerAvatar` | 0x02037078 | verified | `flags` 0x01 (on foot), `objectEventId` (+5) 0 = player's slot |
| `gPlayerPartyCount` | 0x02024029 | verified | u8, 0 → 1 on receiving the starter. Use this, not SaveBlock1 +0x34, which only syncs on save |
| `gPlayerParty` | 0x02024284 | verified | 100 bytes each, **unencrypted**, substructs in fixed order: Growth +0x20 (species 246 Larvitar, exp 560 = level 10 medium-slow), Attacks +0x2C (moves 43/88/201/44, PP 30/15/10/25, matching Leer/Rock Throw/Sandstorm/Bite), EVs +0x38, Misc +0x44 (met location 0x85 = current map's region section). Nickname +8 "Larvitar", OT +0x14 "Claude", OT ID +4 = SaveBlock2's. Level +0x54 = 10, HP +0x56/+0x58 = 30/30, stats follow. Slot 2 (scene 10): Snorunt, level 8, HP 5/27, moves Astonish/Leer with PP 12/29, all matching the party screen; Larvitar at 20/32 HP. Status +0x50 reads 0 for both with no condition; a nonzero status is not yet observed. Held item +0x22 = 44 = Berry Juice (vanilla item ID, confirmed on screen) |
| `gEnemyParty` | 0x0202402C | verified | Same unencrypted layout as `gPlayerParty`. Shadow Grunt's Inkay: species 794, level 7, HP 25/25; slot 2 Skorupi 504, level 7. Wild Snorunt in slot 0: 346, level 8, HP 28 |
| `gBattleMons` | 0x02023BE4 | verified | 0x58 each, 4 battlers (player, enemy, partner, enemy 2 in a multi battle: Larvitar, Inkay, Beldum, Skorupi). Species +0, stats +2..+0xB, moves +0xC, IVs +0x14, stat stages +0x18 (all 6), ability +0x20 (u8: Larvitar 62 = Guts), types +0x21/+0x22 (Larvitar 5/4 Rock/Ground, Inkay 17/14 Dark/Psychic), PP +0x24, HP +0x28, level +0x2A, max HP +0x2C, item +0x2E, nickname +0x30. Larvitar's entry matches its party slot exactly. Wild Snorunt (scene 6): species 346, level 8, types 15/15 (Ice). The ability byte is correct in Unbound's own numbering (see Abilities): Inkay 191 = Contrary, Snorunt 39 = Inner Focus |
| `gBattleTypeFlags` | 0x02022B4C | verified | 0 before the first battle, but **not cleared after a battle** (still 0x40000D back in the overworld), so only read it while callback2 is `BattleMainCB2`. 0x40000D in the multi battle with a partner (DOUBLE, IS_MASTER, TRAINER, CFRU in-game partner 0x400000); 0x4 (IS_MASTER only) in a wild single battle |
| `sTextPrinters` | 0x02020034 | verified | 0x24 each. Printer 0: `active` (+0x1B) 1 both while printing (`state` +0x1C = 0, `currentChar` +0 advancing through `gStringVar4`) and while waiting for A (`state` 2). **Instant text leaves the cursor stale**: the 3/71 mission banner script prints both windows without touching the printers (all 32 inactive, script parked in the sign wait 0x08A0F275), and printer 0's `currentChar` stayed at 0x02021D53, past the new message's 0xFF (+0x2A) and just after the old save prompt's (+0x3A). A finished printer's cursor is just past gStringVar4's first 0xFF, so `current_text` uses that position when no printer is active |
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

### Battle bag (#94)

| Name | Address | Status | Evidence |
|---|---|---|---|
| battle-bag callback2 | 0x08107EE1 | verified | after Cube (action cursor 1) + A in a wild battle; 0x08107F11 for a frame while it opens. Closing on Use: 0x08030AED, 0x080777E9, then `BattleMainCB2` |
| bag state (`gBagMenuState`-like) | 0x0203ACFC | verified | +0 callback 0x08030AED, +4 location 5 (battle) |
| open pocket | 0x0203AD02 | verified | u16: 2 Poké Balls, LEFT → 1 (Key Items screen), LEFT → 0; RIGHT stops at 2, LEFT at 0 (only 3 pockets in battle). Reopens on the last pocket used |
| cursor row per pocket | 0x0203AD04 + 2 × pocket | verified | Key Items: DOWN DOWN read 0 → 2 at 0x0203AD06; Poké Balls: DOWN 0 → 1 (Cancel) at 0x0203AD08 |
| list scroll per pocket | 0x0203AD0A + 2 × pocket | verified (pocket 0, field bag) | see the start menu / field bag table below; `use_item` reads it, `throw_ball` doesn't (it checks the selected name) |
| "<item> is\nselected." | `gStringVar4` | verified | printed when A on a ball opens Use / Cancel (cursor starts on Use) |

- After the throw: "Claude used\nPoké Ball!", then "Gotcha!\nZubat was caught!" (waits for A), exp and level-up messages (the level-up stat box waits for A with no printer active), "…'s data was\nadded to the Pokédex." and its Pokédex page (also A with no printer), then "Give a nickname to the\ncaptured Zubat?" (Yes/No, printer inactive). Yes → naming callback2 0x0809FB71. The party count only rises after the nickname step.

### Start menu, field bag and items (use_item, #101)

| Name | Address | Status | Evidence |
|---|---|---|---|
| start-menu cursor | 0x020370F4 | verified | u8 icon index; RAM diff RIGHT RIGHT LEFT read 0 → 1 → 2 → 1, matching the label (Pokédex, Pokémon List, Cube V3). Vanilla `sStartMenuCursorPos`'s address |
| start-menu task | `gTasks` 0x03005090 (16 × 0x28: func +0, isActive +4), func 0x0806F1F1 | verified | active in the fixture with the menu open and after START, gone after B both times; not present while an NPC dialog runs. callback2 stays `CB2_Overworld` and `sLockFieldControls` is 1 with the menu open, so this task is the only way to tell the start menu from a script |
| field bag | callback2 0x08107EE1 | verified | the same callback as the battle bag (0x08107F11 while opening); `gBagMenuState` +4 location 0 (field) vs 5 (battle). Same pocket (0x0203AD02) and cursor (0x0203AD04 + 2 × pocket) fields; three pockets here too (Items 0, Key Items 1, Poké Balls 2) |
| list scroll per pocket | 0x0203AD0A + 2 × pocket | verified (pocket 0) | with 17 items: DOWN from row 2 read cursor 3 scroll 0, then cursor stays 3 while scroll counts 1..12, then cursor 4, 5 (Cancel = cursor + scroll 17), then wraps to 0/0. Selected row = cursor + scroll: cursor 2 + scroll 9 showed Max Potion, item 11. Items stuffed into the pocket with a test-only `write16` in a scratch copy of probe.lua |
| field party screen | callback2 0x0811EBA1 | verified | the battle party screen's callback (0x0811EBD1 while opening); same `gPartyMenu` cursor (+9) and the same two-column grid (0 1 / 2 3 / 4 5, Cancel 7), shown with six Pokémon in field order |

- Field: START → Cube (icon 2) → A → Items pocket → item → A shows "<item> is\nselected." with Use / Give / Toss / Cancel (cursor on Use) → A → "Use on which Pokémon?" → target → A. The HP bar counts up in `gPlayerParty` HP while it animates, then "<name>'s HP was restored\nby N point(s)." prints in `gStringVar4` (printer state 1 while waiting for A).
- **Unbound keeps the party screen open after a field item**: A on the message returns to "Use on which Pokémon?" for another use (vanilla returns to the bag). B → bag, B → start menu, B → overworld. Between the bag and the start menu, callback2 is 0x08056809, then `CB2_Overworld` with no start-menu task for ~6 frames before the task restarts.
- Battle: action menu Cube → the battle bag → Items pocket → item → A (Use / Cancel) → A → the battle party screen ("Use on which Pokémon?", battle order) → target → A → the same message → A: 0x080777E9 while it closes, then `BattleMainCB2` and the turn runs. Worked in a wild and a trainer battle (gBattleTypeFlags 0xC).

### Battle party screen (switch_to)

| Name | Address | Status | Evidence |
|---|---|---|---|
| battle party-screen callback2 | 0x0811EBA1 | verified | forced and chosen switch screens; 0x0811EBD1 for ~6 frames while it opens, 0x080777E9 for ~8 frames while it closes |
| `gPartyMenu` | 0x0203B0A0 | verified | +9 cursor slot (menu row), (+8 >> 4) & 3 == 1 double layout byte. The battle screen is always the two-column grid regardless (0 1 / 2 3 / 4 5, Cancel 7; walked: RIGHT 0→1, DOWN 1→3, LEFT 3→2, DOWN 2→4, RIGHT 4→7) |
| `gBattlePartyCurrentOrder` | 0x0203B0DC (`gPartyMenu` + 0x3C) | plausible | 3 bytes, one nibble per menu row, high nibble first. `01 23 45` at the start of a wild battle; `10 23 45` after switching Ion (field 0) out for Makuhita (field 1); on a forced-switch screen `15 42 03` with menu Ice, Pearl, Dusl, cob, Owl, Chomp, which read as "row i shows field slot nibble(i)" gives exactly the later overworld order. **But** in a 4-member double battle it read `14 02 35` with field Ion, Makuhita, Makuhita, Batty and menu Ion, Batty, Makuhita, Makuhita, which fits neither direction. Not used by code |
| `gBattlerPartyIndexes` | 0x02023BCE | verified | u16 per battler, a **field** slot: battler 0 read 0 (Ion) → 1 after Makuhita was sent in, while field order stayed Ion, Makuhita. Double: battler 0 = 0 (Ion), battler 2 = 3 (Batty, field slot 3) |
| `gBattleMons` +0x48 | personality | verified | equals the party mon's +0 (Ion 0x2B97B956, Batty 0xC51DAF1D in a double). `switch_to` uses it to tell who is in battle, independent of party order and duplicate names |

- **While the battle party screen is open, `gPlayerParty` itself is in battle (menu) order**, Pokémon in battle first, like vanilla's `UpdatePartyToBattleOrder` / `UpdatePartyToFieldOrder`. Traced frame by frame after a switch to Makuhita: slot 0 read Ion until callback2 became 0x0811EBD1, Makuhita from that same frame, and Ion again on the frame it became 0x080777E9. So `get_state`'s party is field order except while that screen (and anything opened from it, e.g. Summary, untested) is up. The order persists across turns: after one switch, field order and menu order differ for the rest of the battle.
- **Double battle:** menu rows 0 and 1 are the two Pokémon in battle (the double layout's top row, left/right). After Ion fainted on Route 2, the forced screen read Ion 0/43, Batty 37/37, Makuhita 14/45, Makuhita 0/50: Batty was the partner in battle, so "Batty is already in battle!" was the game being right. In a double, a chosen switch is queued and the partner then picks its action; the swap happens when the turn runs.
- Messages on this screen ("Makuhita is already in battle!", "Makuhita can't be switched out!") are not in `gStringVar4` or `gDisplayedStringBattle`; screenshot them. The second came from Zubat's Mean Look: `gBattleMons[0]` status2 (+0x50) read 0x04000000 (vanilla `STATUS2_ESCAPE_PREVENTION`).

## Naming screen

| Name | Address | Status | Evidence |
|---|---|---|---|
| `sNamingScreen` (pointer) | 0x0203998C | verified | points at the struct (0x02002D60 on the rival and Beldum screens); the struct is heap-allocated, so after a capture it moved and fixed addresses read garbage. Fields below are offsets from it |
| naming-screen callback2 | 0x0809FB71 | verified | rival and Beldum nickname screens; changes once OK is confirmed |
| `textBuffer` | +0x1800 (was 0x02004560) | verified | 0xFF → 0xBB ('A') on typing; `naming.py` read back "Copilot" / "Iron Man" |
| `currentPage` (u8) | +0x1E22 (was 0x02004B82) | verified | 2 lower, 0 others, 1 upper; SELECT cycles 2→0→1, ~20 frames per switch |
| cursor x / y | `gSprites[cursorSpriteId (+0x1E23)].data[0..1]` (0x0202063C + 0x44·id + 0x2E/0x30) | verified | sprite 0 on both screens tested; RIGHT RIGHT DOWN LEFT diffed 0→1→2→2→1 / 0→0→0→1→1. x 8 is the button column (page, Back, OK) |

- Lower/upper pages match FireRed's grid (`abcdef .` / `ghijkl ,` / `mnopqrs ` / `tuvwxyz `), mapped by typing each key and reading the buffer. Typing a capital switches to lower case automatically.

## Objects

- Object graphics 92 = item on the ground (Poké Ball sprite): verified on Route 2, objects at (8,28) and (17,27) sit exactly on the two ball sprites in a screenshot. Hidden items are bg events kind 7 (not handled).

`gObjectEvents` entry fields (0x24 bytes), read-only on the Crater Town gym (6/2), 2026-10-08. `world.objects()` reads them and `bot.sneak` uses them (docs/gym-mechanics.md):

| Field | Offset | Status | Evidence |
|---|---|---|---|
| graphicsId | +0x05 | verified | Guard 22, object id 3 91, item ball 92. Matches the template (+1) |
| movementType | +0x06 | verified | Vanilla numbering. Object id 3: 8 (FACE_DOWN), facing down. Guard id 7: 0x1B (WALK_LEFT_AND_RIGHT), seen walking left and right along row 27. Id 11: 0x24 (WALK_SEQUENCE_RIGHT_DOWN_UP_LEFT), range x4 y3 from (24,6): recorded looping right, down, up, left, 14 steps of 16 frames, matching vanilla `MoveNextDirectionInSequence` (`bot.sequence_cycle`). Matches the template (+9) |
| trainerType | +0x07 | verified | 1 on the guard and template trainers, 0 on others. Matches the template (+0xC, u16) |
| initialCoords | +0x0C | verified | (18,27)+7 for the guard = the template position |
| facing / movement direction | +0x18 low / high nibble | verified | 3 while walking left, 4 while walking right |
| movementRange | +0x19 (x low nibble, y high) | plausible | Guard 0x19 (rangeX 9) = template 0x9. The patrol is init − 9 .. init (x 9..18), which is exactly vanilla `MovementType_WalkBackAndForth`: 0x1B (WALK_LEFT_AND_RIGHT) sets off left, reverses when the next step would leave the range box, and reverses again on getting back to its initial coords. So the patrol is start .. start ∓ range in the set-off direction (0x19 up, 0x1A down, 0x1B left, 0x1C right), not start ± range. Status: verified for guard 7 (see the patrol bullet below) |
| movementActionId | +0x1C | plausible | 0x12 while stepping left, 0x13 while stepping right, 0xFF when idle |
| trainerRange (sight) | +0x1D | verified (offset), plausible (meaning) | Guard 1 = template trainerRange (+0xE, u16) 1. Template trainers ids 2/4/5/6 have 4/3/4/3. Behaviour: caught stepping onto the tile right in front of the guard ((19,27), guard at (18,27) facing right: "Gotcha!", warped to (27,24)); not caught standing on (20,27) with the guard 7–8 tiles away facing it. Consistent with vanilla "sees N tiles straight ahead". A range above 1 has not been tested |
| patrol timing | — | verified | 16 frames per tile (`gMain.vblankCounter2` deltas of 16 between moves), turns at an end within the same step (at (9,27) facing left, then 2 frames later at (10,27) facing right); cycle ~288 frames. The player walks a tile in 8 |

- **Patrol model (`bot.Patrol`, #130).** A back-and-forth walker with both turning points known (lo, hi) runs through a cycle of 2·(hi−lo) states, one per 16-frame step: (lo, minus), (lo+1, plus) … (hi, plus), (hi−1, minus) … (lo+1, minus); 288 frames for the guard's x 9..18. Each object read is stamped with `gMain.vblankCounter2` (+0x24, read just before; the objects are read on the next frame). One read gives the cycle index and the frame its step began to within 16 frames; every later read narrows that frame, so after reads on both sides of a step it is exact, and the state at any later frame follows (regress: 0 mispredicted frames over two cycles, simulated). A read that doesn't fit (held up by the player or another object, wrong turning points) drops the model and the learned turning points until the walker is seen turning again. Turning points are learned from the reads around a facing flip: it walked 2T − P − Q steps between them, the frame stamps give that count to within one, and its parity settles it. The template's start ± movement range (and walls) bound where an unmodelled walker is predicted to go. Status: plausible (built on the verified timing above; not yet checked against a live crossing).
- **Turning points are fixed, not random: verified for guard 7.** The agent's notes said that guard 7 "random-walks x=9..20, turning every few tiles". That came from coarse get_state snapshots taken hundreds of frames apart, which show the guard facing right at some x and read as "turned there". Against that note:
  - The full1 transcripts hold 322 get_state readings of id 7. Every one is a state of the fixed 9..18 cycle, and all 18 states occur, at 10–28 readings each: (9, left), (10..18, right), (10..17, left). None is at x 19 or 20, and none is (9, right) or (18, left).
  - #112's 30 s of frame-level read-only samples gave 1,271 predictions with no misses. The raw samples weren't kept.
  - Vanilla's movement code is deterministic for this type (see movementRange above), and the template predicts 9..18.

  So `sneak` seeds a walker's turning points from its template (`bot.SET_OFF`, `_seed`), once per watcher, when the whole stretch is open. A read that contradicts the seed drops it, and the tool learns the turning points by watching. When something stands in its way, vanilla walks in place rather than turning. The model reads that as a contradiction, and the turn isn't learned as a turning point.
- **Only objects near the camera are live.** With the player at (20,26), guard 8 (template (8,27), patrols x 1..15) wasn't in `gObjectEvents`. Watchers off screen are invisible to any tool.
- **Object template** (`events` +4, 24 bytes): + elevation (+8), movementType (+9), movementRange (+0xA), trainerType (+0xC, u16), trainerRange (+0xE, u16), script (+0x10), flag (+0x14). Verified on 6/2 for the two objects that were loaded (ids 3 and 7): graphics, movement type, range, trainer type and sight all match.

## Pokédex

| Name | Address | Status | Evidence |
|---|---|---|---|
| species → national dex | ROM 0x09A41FEA, u16[internal species id] | verified | The only ROM offset where 8 known species line up (Bulbasaur 1, Zubat 41, Swinub 220, Treecko 252, Makuhita 296, Beldum 374, Gible 443, Patrat 504; internal ids 1, 41, 220, 277, 335, 398, 496, 557). Decoding the live owned flags through it gives exactly the run's catches plus party (14 species) |
| owned flags | SaveBlock1 +0x38D, 0x7D bytes, bit n-1 = national n | verified | see the UI notes; `state.caught(p, species)` reads it |

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
| Object event template | events +4 pointer | 24 bytes: localId (+0), graphicsId (+1), x (+4, s16), y (+6, s16), trainerType (+0xC, u16). Verified: Cinder Volcano 45/4 template 11 = (14,15) graphics 161, trainer, same as the live object. Templates hidden by a flag are listed too |
| Dynamic warp | warp mapGroup/mapNum 0x7F/0x7F | "back where you came from" (Hidden Grotto 1/7's exits, Dehara Dept. 0/0). There's no header for it: naming it read garbage and crashed `read_world` in any such map. Verified (ROM) |

- **`world.rom_world(group, num)`** builds the same grid from the ROM alone (header layout → block map, same encoding as the VMap). Verified against `read_world` on Cinder Volcano 45/4: 60×60, every tile identical, same warps, signs and connections. The "layout field differs for Route 1" note above predates the XOR'd group table and is unconfirmed with the de-obfuscated header; map scripts that set metatiles at runtime would also differ (none seen yet).
- **`route()` only counts walkable links** (`map_links`): a connection needs one seam tile pair walkable on both sides, each opening onto at least `bot.POCKET` tiles; a warp buried in solid rock (it and its neighbours all collision) is dropped. ROM evidence: Route 4 3/72's south seam with Route 5 3/73 (x 0–31) is walkable only at (15..19,40), 5 tiles of shore enclosed by lake and wall (waterfall row at y 36, wall above); Route 4's KBT Expressway warps (112,7)/(113,7) are behavior 0x15 with collision in solid rock. Water seams count as closed (the planner doesn't surf). Of 282 connections, 163 fail this test, nearly all wall-to-wall or water.

- **Elevation matters.** Walk-tested on Route 1: from elevation 3 the player can't step onto elevation 5 even with collision 0. The rule (vanilla): blocked unless the player's elevation is 0, or the tile's is 0, 15 or equal. Elevation-0 tiles (stairs, ramps) reset the player's elevation; 15 (bridges) keeps it. The grid shows other-level walkable tiles as `:`.
- **Walk test** (Route 1, savestate restored after): right 3 tiles then blocked, left 7 then blocked, up 1 then elevation-blocked, all exactly as the grid predicted.
- **Behavior IDs** match vanilla FireRed's on Route 1 by appearance: 0x02 tall grass, 0x21 sand (snow), 0x23 ice, 0x3B ledge south, 0x60 cave door (warp to Icicle Cave), 0x84 sign. Walk-tested so far: collision and elevation only. Ledges, ice, water and doors are **not yet walk-tested**.
- **Sideways stairs** (Unbound/CFRU, not vanilla): 0xB4 and 0xB5 move you diagonally. Walk-tested in Frozen Heights: RIGHT on 0xB4 (12,22) lands on (13,21); LEFT on 0xB5 (13,21) returns to (12,22). Pressing RIGHT from (12,21) into the 0xB5 tile does nothing (different elevation). Other orientations: pending. Ice (0x23) slides walk-tested on the same route.
- **Hop gap 0x7F** (Unbound, not vanilla; collision 0, elevation 1, drawn between land strips over water): pressing LEFT or RIGHT toward it jumps over it and lands two tiles on. Walk-tested in Grim Woods (45/1): LEFT from (10,33) lands on (8,33) and RIGHT back on (10,33); LEFT from (8,33) lands on (6,33). Up/down: verified in Fallshore's lily-pad map 14/15 from the full run's own walk tests: DOWN (23,11) -> (23,13), UP (16,18) -> (16,16), (26,16) <-> (26,18), UP (4,26) -> (4,24). Any direction. Verified.
- **Ledge landings ignore elevation**: jumping the 0x3B ledge at Grim Woods (16,24)->(16,26) goes from elevation 3 onto elevation 5, and the player takes the landing tile's elevation (read back 5). Verified.
- **A warp event fires only on a warp behavior** (verified, walk test from gym 1's `badge1.ss1`). Dresco Town 7/4 (outside the gym) lists three warp events at (7..9,18), all to Dresco Town 3/71, but only (8,18) has behavior 0x65 (south arrow); (7,18) and (9,18) are 0x00 plain floor with collision below. On the side tiles DOWN does nothing and LEFT/RIGHT/UP 4-frame taps only turn the player; DOWN on (8,18) warps to 3/71 (16,13). Wide mats can carry an event per tile, so pick the tile whose behavior is in `world.WARP`.
- **Arrow warp timing** (verified, same test): DOWN on 0x65 sets `sLockFieldControls` and the fade runs past `state.press()`'s settle (the trace reads mode `other`, locked, no movement); the map changes on a second look ~40 frames later. Arriving at 3/71 the first time runs a story script ("Mission Objective Updated: A Hero's Journey"); the stale printer text then read "overwrite it?" (the last in-game save prompt), not the banner. Fixed (see `sTextPrinters`): `dialog` now reads the bottom box, "Talk to Prof. Log's friend in Dresco Town!", from gStringVar4. The banner itself ("Mission Objective Updated:" at ROM 0x09FB0055, then "A Hero's Journey") is printed straight from ROM into its own window and is in no RAM buffer, so `dialog` doesn't report it; take a screenshot to read it.

## Abilities (#4)

Unbound numbers abilities differently from public CFRU, so never use CFRU's `ABILITY_*` constants. Use the ROM's own tables:

| Table | ROM address | Layout |
|---|---|---|
| Ability names | 0x08A36398 | 293 entries × 17 bytes, Gen 3 text. 0 = "-------", 77 = "Unused" |
| Species base stats | 0x099E0C9C | 0x1C per species. Base stats +0..+5 (HP Atk Def Spe SpA SpD), types +6/+7, EV yield u16 +0x0A (2 bits per stat, same order; verified against the wiki's EV-yield table: Charizard SpA 3, Blastoise SpD 3, Snorlax HP 2, Caterpie HP 1, Alakazam SpA 3, Metang Def 2, Hariyama HP 2), growth rate +0x13, ability 1 +0x16, ability 2 +0x17 (0 = none), hidden ability +0x1A. Larvitar is species 246, Inkay 794, Snorunt 346 |
| Party Pokemon training data | gPlayerParty + 100*i | verified (#156): EVs u8 x6 +0x38, IVs 5 bits x6 packed in u32 +0x48 (HP Atk Def Spe SpA SpD), nature = personality (+0x00) % 25, stored stats u16 x6 +0x58 (maxHP Atk Def Spe SpA SpD). Evidence: recomputing all six live party members' stats from base stats + IVs + EVs + level + nature matched the stored stats exactly (2026-10-09). Nature mints, if Unbound has them, are unverified |
| PC storage | gPokemonStoragePtr 0x03005010 (-> 0x02029314 in this run) | verified (#157): current box u8 at +0; compressed 58-byte Pokemon from +4 filling vanilla's 0x8340-byte box area (579 slots = boxes 1-19 + box 20 slots 1-9); box names 9 bytes each at +0x8344. Record: +0 personality, +4 OT id, +8 nickname, +0x14 OT name, +0x1C species u16, +0x1E item u16, +0x20 EXP u32, +0x25 friendship, +0x27 4 moves packed 10 bits each, +0x2C EVs x6, +0x33 met level, +0x36 IVs 5 bits x6. Evidence: nicknames scanned in RAM matched the agent's box notes; moves decode to the species' movesets; level from EXP (growth-rate curves, species +0x13) reproduces all six party levels. Boxes 20+: location pending |

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
