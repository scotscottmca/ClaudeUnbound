# Learnings

Failures, their root causes, and the rule each one taught. Read this before building or playing. Add an entry whenever something goes wrong or an assumption turns out false; merge entries that say the same thing. This is the seed of the agent's self-curated memory (Phase 2) and of the Refiner's input (Phase 4).

## Rules

1. **Vanilla knowledge is a hypothesis, not a fact.** About half the FireRed/CFRU assumptions made so far were wrong on Unbound. Before building on one, test it with a cheap experiment (a RAM diff, a walk test, a screenshot).
2. **Never act blind in an unrecognised state.** If the mode is `other` or the screen isn't one the code knows, look (screenshot plus RAM) and identify it before pressing anything. A "press B to close it" fallback can't handle forced prompts.
3. **Every autonomous loop logs each action and has a stall detector.** If position and state haven't changed for N steps, stop and diagnose. Never rely on someone watching the screen.
4. **An interrupted command may still be running.** After any interruption, check for and kill leftover processes before starting new ones. One client drives the emulator at a time.
5. **Check the party before walking into grass.** The lead Pokémon should be healthy, and fleeing isn't guaranteed.

## Log

| Date | What went wrong | Root cause | Rule |
|---|---|---|---|
| 2026-10-07 | Ability bytes looked "wrong" for Inkay and Snorunt | Assumed public CFRU ability numbering; Unbound has its own table | 1 |
| 2026-10-07 | Party read as empty after getting the starter | Read the save block's party count, which only updates on save | 1 |
| 2026-10-07 | Mode stuck on `battle` after a battle | Assumed `gBattleTypeFlags` is cleared after battle; it isn't | 1 |
| 2026-10-07 | Every key press reported "screen changed" | Whole-screen diff; falling snow changes the screen each frame | 1 |
| 2026-10-07 | Start menu read as `overworld` | Assumed menus change callback2; Unbound's start menu doesn't (field-control lock does) | 1 |
| 2026-10-07 | Grid said walkable, player couldn't step | Ignored elevation; Gen 3 blocks steps between levels | 1 |
| 2026-10-07 | Bot walked up and down two tiles; the user spotted it before I did | No per-step log or stall detection; the run was outside my view | 3 |
| 2026-10-07 | A rejected tool call left the bot running and fighting a second client | Rejection doesn't kill the process; the server silently overwrote one client's pending command | 4 (server now replies `err busy`) |
| 2026-10-07 | Bot stuck on "Choose a Pokémon" after Snorunt fainted | Led with a Pokémon on 5 HP; on the forced switch screen the bot pressed B, which does nothing | 2, 5 |
| 2026-10-07 | Fleeing failed ("Can't escape!") | Gen 3 escape odds depend on speed; the bot assumed Run always works | 5 |

## Signals found along the way

- Battle: player controller `gBattlerControllerFuncs[0]` (0x03004FE0) = 0x0802E439 at the action menu, 0x0802EA11 at the move menu. Cursors: action 0x02023FF8 (0 Fight, 1 Cube, 2 Pokémon, 3 Run), move 0x02023FFC.
- In-battle party screen ("Choose a Pokémon"): callback2 0x0811EBA1.
- Unbound's battle menu is Fight / Cube / Pokémon / Run.
