# Learnings

Failures, their root causes, and the rule each one taught. Read this before building or playing. Add an entry whenever something goes wrong or an assumption turns out false; merge entries that say the same thing. This is the seed of the agent's self-curated memory (Phase 2) and of the Refiner's input (Phase 4).

## Rules

1. **Vanilla knowledge is a hypothesis, not a fact.** About half the FireRed/CFRU assumptions made so far were wrong on Unbound. Before building on one, test it with a cheap experiment (a RAM diff, a walk test, a screenshot).
2. **Never act blind in an unrecognised state.** If the mode is `other` or the screen isn't one the code knows, look (screenshot plus RAM) and identify it before pressing anything. A "press B to close it" fallback can't handle forced prompts.
3. **Every autonomous loop logs each action and detects both stalls and oscillation.** Stop on no change for N steps *and* on the same tile being re-entered repeatedly (count arrivals, not presses). Watch the log live; never pipe a run through `tail` or otherwise hide it until it ends. The user must never be the first to notice a loop.
4. **An interrupted command may still be running.** After any interruption, check for and kill leftover processes before starting new ones. One client drives the emulator at a time.
5. **Check the party before walking into grass.** The lead (first Pokémon still standing) should be healthy, and fleeing isn't guaranteed. Heal with items or at a Pokémon Center.
6. **Commit to a plan; re-plan only on a real change.** Re-planning every step lets moving NPCs or a changed cost flip the route back and forth. Keep one consistent cost model instead of switching policies mid-trip.
7. **Identify places by ID, not name.** Several maps share a name (Bellin Town is at least six). Route across the ROM map graph, and treat hops that turn out blocked as closed: the ROM can't see story gates.
8. **Unknown screen: wait and look again before giving up.** Transitions (e.g. the encounter wipe) are brief states with their own callbacks; waiting presses nothing.

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

| 2026-10-07 | Bot bounced between two tiles again; the user spotted it again | A wandering NPC in a one-tile corridor flipped the per-step plan; the stall detector ignored moving-in-place; the run's output was hidden behind `tail` | 3, 6 |
| 2026-10-07 | Bot walked back toward its start after a battle | Plan discarded after battle and re-made with post-battle HP, which flipped the grass cost; a fainted first slot counted as the lead | 5, 6 |
| 2026-10-07 | "No connection to Route 2" from Bellin Town | Targeted maps by name; Bellin is several maps | 7 |
| 2026-10-07 | Route search took a shortcut through map 4/9 | 4/9 is a hub linking every town; not walkable | 7 |
| 2026-10-07 | Bot couldn't enter Icicle Cave | Invisible story-gate object on the cave mouth; the ROM graph says open | 7 |
| 2026-10-07 | Bot stopped on an "unknown screen" | It was the wild-encounter wipe (callback2 0x080565A9) | 8 |

| 2026-10-07 | My run monitor never fired during the first 200 agent actions | `grep --line-buffered` piped into `cut`, which buffers; events sat in the pipe | 3: every pipe stage in a watch must flush per line (`awk ... fflush()`); verify a watch fires once before trusting its silence |
| 2026-10-07 | The agent asked `walk_to` for a shelf tile and fell back to one press per turn | Tools assumed the target is walkable; agents aim at what they see (NPCs, signs, objects) | Design tools for the target the model will naturally give (walk next to it and face it) |

| 2026-10-07 | Told the user "there is no Sonnet 5.5"; it exists (it's the current `sonnet` alias) | Trusted a cached model table from June instead of checking live | 1: check the live source (a one-line `claude -p --model X` call) before stating a fact about models |

| 2026-10-07 | Killing the runner by command-line match also killed my own shell | The match text (`agent/run.py`) appeared in the killing command's own command line | Match processes by PID or by an exact executable plus argument, never by a substring the killer itself contains |
| 2026-10-07 | Changing the runner's model needed a restart that orphaned the running chunk | The model was a constant loaded at start | Settings that may change mid-run are re-read each cycle (`model.txt`) |

## Signals found along the way

- Battle: player controller `gBattlerControllerFuncs[0]` (0x03004FE0) = 0x0802E439 at the action menu, 0x0802EA11 at the move menu. Cursors: action 0x02023FF8 (0 Fight, 1 Cube, 2 Pokémon, 3 Run), move 0x02023FFC.
- In-battle party screen ("Choose a Pokémon"): callback2 0x0811EBA1.
- Unbound's battle menu is Fight / Cube / Pokémon / Run.
- Wild-encounter screen wipe: callback2 0x080565A9.
- Story gates are often invisible objects: active object events with no visible sprite (e.g. graphics 33 on Icicle Cave's mouth). The grid shows them as `N`.
