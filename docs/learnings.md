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
| 2026-10-07 | Wiki search for "Potion" / "Berry Juice" found no item page | Assumed unboundwiki has a page per item; `items/` only covers evolution items, key items and category lists. Medicine and most held items appear only in location item tables and Pokémon held-item rows | 1 (check what the corpus contains before writing a query against it) |

| 2026-10-07 | My run monitor never fired during the first 200 agent actions | `grep --line-buffered` piped into `cut`, which buffers; events sat in the pipe | 3: every pipe stage in a watch must flush per line (`awk ... fflush()`); verify a watch fires once before trusting its silence |
| 2026-10-07 | The agent asked `walk_to` for a shelf tile and fell back to one press per turn | Tools assumed the target is walkable; agents aim at what they see (NPCs, signs, objects) | Design tools for the target the model will naturally give (walk next to it and face it) |

| 2026-10-07 | Told the user "there is no Sonnet 5.5"; it exists (it's the current `sonnet` alias) | Trusted a cached model table from June instead of checking live | 1: check the live source (a one-line `claude -p --model X` call) before stating a fact about models |

| 2026-10-07 | Killing the runner by command-line match also killed my own shell | The match text (`agent/run.py`) appeared in the killing command's own command line | Match processes by PID or by an exact executable plus argument, never by a substring the killer itself contains |
| 2026-10-07 | Changing the runner's model needed a restart that orphaned the running chunk | The model was a constant loaded at start | Settings that may change mid-run are re-read each cycle (`model.txt`) |

| 2026-10-07 | Two Python edits shipped real line breaks where `\n` escapes were meant (syntax errors) | Code containing backslash escapes was written through a shell heredoc that mangled them | Write code with escapes using the editor tool, not heredocs; run a syntax check after every scripted edit |

| 2026-10-07 | The agent concluded "travel_to keeps looping" and left Bellin Town, its mission's destination | travel_to silently re-routed around a story-blocked cave across half the region (300 steps), and my Phase 1 bot had "reached" Bellin by crossing a map edge that is a dead end (avalanche snow) | Deterministic tools hand surprises back to the model with an explanation; an exit test must reach a place you can actually use, not just a map ID |

| 2026-10-07 | The emulator closed and about 40 minutes of play were lost (back to the last in-game save) | The bridge's autosave existed since #5 but the runner never switched it on | Recovery paths are part of the feature: the runner enables autosave on every start and resumes from the newest one |
| 2026-10-07 | Smooth-walk strides overshot (6 tiles asked, 8 walked) | Assumed vanilla's 16 frames a tile; Unbound walks 8 (and a turn costs 8) | 1: measure timings on Unbound before using them |
| 2026-10-07 | Sign reads came back empty even though A was pressed | In FireRed walking into a sign reads it: the turn toward it opened the sign and the following A closed it | After any input that might start text, look before pressing again |
| 2026-10-07 | A message waiting for A read as `other`, so advance_dialog skipped it | A finished message has no active text printer; the script is parked in a wait-for-button native (sScriptContext1 0x03000EB0, pointers 0x0806951D / 0x08A0F275) | 1 |
| 2026-10-07 | travel_to kept walking into a story gate ("Claude! What are you doing?"), and the user spotted the loop before I did, a third time | The bot path pressed B through the gate's script and retried; my test ran unguarded with a 500 s timeout | Tools stop when a script takes over; my own test scripts are autonomous loops too: cap steps and time, and watch them |
| 2026-10-07 | Committed code whose test hadn't run (twice), and an edit I thought applied had been refused | Chained commit after a test that failed; the editor refuses unread files | Commit only behind a passing test (`test && commit`); confirm every edit result |

| 2026-10-07 | Haiku 5.5 (default tier) ignored every VERIFY note: 61 actions, no verifier calls | Harness notes are suggestions; a cheaper model drops them | Anything that must happen is enforced in code (the verification gate blocks game actions until a verifier records a check) |
| 2026-10-07 | The irreversible-prompt check would never see "Delete a move?" | It only read overworld dialog; move learning happens in battle | Check a trigger against every context its event occurs in |
| 2026-10-07 | Watchdog fired while battle text advanced box by box | Its fingerprint ignored battle text | Progress signals must include every visible state that can change |
| 2026-10-07 | wiki_read, save_state called with missing/renamed arguments (KeyError) | Tools required exact argument names; models reach for natural ones (url) or omit optional-looking ones (name) | Accept the natural aliases, default what can be defaulted, and return a usable error for the rest |
| 2026-10-07 | A second emulator on another port never served | Couldn't see its scripting console; os.getenv / load-reset unconfirmed | Don't sink time into an unobservable side path: test on the main instance at a paused moment instead |

## Signals found along the way

- Battle: player controller `gBattlerControllerFuncs[0]` (0x03004FE0) = 0x0802E439 at the action menu, 0x0802EA11 at the move menu. Cursors: action 0x02023FF8 (0 Fight, 1 Cube, 2 Pokémon, 3 Run), move 0x02023FFC.
- In-battle party screen ("Choose a Pokémon"): callback2 0x0811EBA1.
- Unbound's battle menu is Fight / Cube / Pokémon / Run.
- Wild-encounter screen wipe: callback2 0x080565A9.
- Messages: printers are per window (shops use their own); a finished message waiting for A shows as script mode 2 parked in a wait-for-button native.
- Movement: 8 frames a tile while the key is held, plus 8 to turn first. Walking into a sign reads it.
- Story gates are often invisible objects: active object events with no visible sprite (e.g. graphics 33 on Icicle Cave's mouth). The grid shows them as `N`.
