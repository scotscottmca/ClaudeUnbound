# Unbound 2.1.1.1 RAM addresses

Checked against live RAM in mGBA 0.10.5 with `probe/probe.py`. `probe/state.py` reads all of the verified ones at once.

Status: **verified** = values match what's on screen; **plausible** = right shape, meaning not proven; **pending** = needs a scene not yet reached.

| Symbol | Address | Status | Evidence |
|---|---|---|---|
| `gMain` | 0x030030F0 | verified | callback1 0x08056535 / callback2 0x080565B5 (vanilla `CB1/CB2_Overworld`) in overworld, 0x080123E5 / 0x08011101 (`BattleMainCB2`) in battle, callback2 0x08137EE9 with the summary screen open (callback1 unchanged); `vblankCounter2` (+0x24) advances ~60 per 60 frames; `vblankCounter1` (+0x20) is a pointer, NULL |
| `gSaveBlock1Ptr` | 0x03005008 | verified | → 0x0202552C. `pos` (+0) changed y 2→4 after walking down 2 tiles; `location` (+4) group/num match the object event; `mapLayoutId` (+0x32) matches `gMapHeader`; `playerPartyCount` (+0x34) is the saved copy, stale until save |
| `gSaveBlock2Ptr` | 0x0300500C | verified | → 0x02024588. `playerName` (+0) decodes "Claude"; play time at +0xE |
| `gSaveBlock3Ptr` | 0x03005010 | plausible | → 0x02029314 (EWRAM). Contents not checked |
| `gMapHeader` | 0x02036DFC | verified | layout/events/scripts are ROM pointers (scripts at 0x09E8FD70, Unbound's expanded space); `mapLayoutId` 0x197 = SaveBlock1's; `mapType` 8 (indoor) in an indoor map. Walking to the next map: group/num 4/10 → 4/11 and `mapLayoutId` 0x197 → 0x198 in both SaveBlock1 and `gMapHeader`, with new layout/event pointers |
| `gObjectEvents` | 0x02036E38 | verified | 0x24 each. Player is `localId` 0xFF; `currentCoords` (+0x10) = SaveBlock1 `pos` + 7; facing (+0x18 low nibble) 1 = down after walking down, 4 = right when talking to an NPC on the right |
| `gPlayerAvatar` | 0x02037078 | verified | `flags` 0x01 (on foot), `objectEventId` (+5) 0 = player's slot |
| `gPlayerPartyCount` | 0x02024029 | verified | u8, 0 → 1 on receiving the starter. Use this, not SaveBlock1 +0x34, which only syncs on save |
| `gPlayerParty` | 0x02024284 | verified | 100 bytes each, **unencrypted**, substructs in fixed order: Growth +0x20 (species 246 Larvitar, exp 560 = level 10 medium-slow), Attacks +0x2C (moves 43/88/201/44, PP 30/15/10/25, matching Leer/Rock Throw/Sandstorm/Bite), EVs +0x38, Misc +0x44 (met location 0x85 = current map's region section). Nickname +8 "Larvitar", OT +0x14 "Claude", OT ID +4 = SaveBlock2's. Level +0x54 = 10, HP +0x56/+0x58 = 30/30, stats follow. Slot 2 (scene 10): Snorunt, level 8, HP 5/27, moves Astonish/Leer with PP 12/29, all matching the party screen; Larvitar at 20/32 HP. Status +0x50 reads 0 for both with no condition; a nonzero status is not yet observed. Held item +0x22 = 44 = Berry Juice (vanilla item ID, confirmed on screen) |
| `gEnemyParty` | 0x0202402C | verified | Same unencrypted layout as `gPlayerParty`. Shadow Grunt's Inkay: species 794, level 7, HP 25/25; slot 2 Skorupi 504, level 7. Wild Snorunt in slot 0: 346, level 8, HP 28 |
| `gBattleMons` | 0x02023BE4 | verified | 0x58 each, 4 battlers (player, enemy, partner, enemy 2 in a multi battle: Larvitar, Inkay, Beldum, Skorupi). Species +0, stats +2..+0xB, moves +0xC, IVs +0x14, stat stages +0x18 (all 6), ability +0x20 (u8: Larvitar 62 = Guts), types +0x21/+0x22 (Larvitar 5/4 Rock/Ground, Inkay 17/14 Dark/Psychic), PP +0x24, HP +0x28, level +0x2A, max HP +0x2C, item +0x2E, nickname +0x30. Larvitar's entry matches its party slot exactly. Wild Snorunt (scene 6): species 346, level 8, types 15/15 (Ice). Ability byte is wrong for some species: Inkay reads 191, Snorunt 105, neither a real ability of theirs under CFRU numbering: see #4 |
| `gBattleTypeFlags` | 0x02022B4C | verified | 0 before the first battle, but **not cleared after a battle** (still 0x40000D back in the overworld), so only read it while callback2 is `BattleMainCB2`. 0x40000D in the multi battle with a partner (DOUBLE, IS_MASTER, TRAINER, CFRU in-game partner 0x400000); 0x4 (IS_MASTER only) in a wild single battle |
| `sTextPrinters` | 0x02020034 | verified | 0x24 each. Printer 0: `active` (+0x1B) 1 both while printing (`state` +0x1C = 0, `currentChar` +0 advancing through `gStringVar4`) and while waiting for A (`state` 2) |
| `gStringVar4` | 0x02021D18 | verified | holds the full expanded NPC message; standard Gen 3 charmap |
| `gDisplayedStringBattle` | 0x0202298C | verified | "You are challenged by Shadow Grunt!" while that message was on screen |
| `Var8000` | 0x020370B8 | plausible | u16 script vars; values change between overworld and NPC dialog |
| `gNewBS` ptr | 0x0203E038 | plausible | 0x02002D60 in overworld (stale, not NULL), 0x020179B4 in both battles so far (EWRAM heap). Struct layout not checked |

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

- Mode detection: battle if callback2 is `BattleMainCB2` (0x08011101), dialog if printer 0 is active, overworld if callback2 is `CB2_Overworld`, else other.
- `gStringVar4` keeps the last message after the box closes, so only trust it when printer 0 is active.
