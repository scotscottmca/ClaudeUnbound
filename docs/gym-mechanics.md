# Gym mechanics catalog

A harness-facing catalog of the **kinds** of movement and battle mechanics Unbound's gyms use, so tools can handle each kind in general. It was compiled from unboundwiki.com's gym pages (the `gyms/` index, the eight gym pages, walkthrough parts 6–7 and `misc-info/challenging-puzzles/`), read once on 2026-10-08 with the user's one-time approval.

**Scope.** This file lists mechanic types and the gyms that use them, by name only. It contains no routes, switch orders, quiz answers or per-gym solutions. Those stay out of this file, out of `agent/CLAUDE.md`, out of the agent's memory and out of the wiki index (`bridge/wiki.py`): the agent solves each gym itself.

Treat the wiki's descriptions as hypotheses (learnings rule 1). The Crater Town rows were checked in RAM; the rest have not been checked yet.

## Movement mechanics

| Mechanic | How it works | Gyms | Harness capability |
|---|---|---|---|
| **Patrol guards and safe zones** | Trainer objects walk back and forth along corridors. If one sees you, "Gotcha!" plays and you are warped back to the entrance, or to a checkpoint once you have reached it. There is no battle. Side alcoves are hiding spots. Verified in RAM, see below. | Crater Town | **`sneak_to(x, y)`** (`bot.sneak`). It learns where each patroller turns and syncs its step timing to the frame (`bot.Patrol`, docs/addresses.md), finds safe zones (tiles no patrol can ever see), and crosses from one safe zone to the next only in a window where the whole crossing stays unseen, waiting the exact frames for it; it never stops on a watched tile and steps off one at once. Following a guard as it walks away (shadowing) falls out of the same timing. Watchers off screen count as watching their whole template patrol. It stops with the text if a script starts. |
| **Timing and rotating sight lines** | Trainers face a fixed direction, turn on a timer, or walk a fixed loop. You pass while one looks away; being seen starts a battle. | Blizzard City, Fallshore City, Dehara City, Polder Town (avoidable trainers) | `sneak_to`: a fixed-facing watcher's sight line is planned around. A rotating or wandering watcher (any movement type that isn't fixed or back-and-forth) is predicted to face any way, which is conservative: the tool may wait until it runs out of wait time, then says so. |
| **Darkness and limited vision** | The screen is dark apart from a circle around the player, and the circle widens as you beat trainers. Sprites are invisible in the dark (the agent confirmed this by screenshot). | Crater Town | Already covered: `get_state`'s grid and NPC list come from RAM, so darkness doesn't hide them. Trust the state, not screenshots. |
| **Steam or visibility meter** | Surfing raises a meter step by step. Once it is full you are blinded and swept back to the entrance. Standing on land resets it. | Polder Town | Not built. It needs a RAM read of the meter (a var or a counter) and a "rest on land when it is near full" rule. The planner also doesn't surf yet. |
| **Teleport tiles across floors** | Fans lift you up a floor; holes and trap doors drop you down. | Blizzard City, Dehara City | Partly covered: tiles with warp behavior show as `D`, and travel_to and walk_to follow warps. A hole you fall into changes the map, which walk_to reports. The agent records in memory which tile goes where. |
| **Switches and barriers** | Turning a bulb or switch on opens a barrier. On harder settings some switches must be turned back off, which means backtracking. | Dehara City | Partly covered: barriers are collision, so the grid updates after a switch (`setmetatile` changes the live map), and walk_to re-reads the grid every call. Not built: a list of switch states (they are flags or vars). |
| **Ordered buttons or a hidden room** | Pressing buttons in the right order, deduced from story clues, opens a hidden room. | Redwood Village | Model reasoning only. The agent reads its clues and keeps them in memory. |
| **Water hopping** | You cross between islands by stepping on rocks and lily pads, and ride a placed Lapras through waterfalls. | Fallshore City | Partly covered: the hop gap 0x7F (`=`) is modelled. Lily pads and Lapras are unverified. |
| **Ice and sliding** | You keep sliding until you hit something. No gym page mentions it, but routes have it. | (routes: Frozen Heights) | Already in the planner (`SLIDE_ICE` 0x23). |

## Battle mechanics

These affect battles, not movement, so `fight` and the matchup notes are where they matter.

| Mechanic | Gyms |
|---|---|
| A field effect that lowers every Pokémon's accuracy (fog; Defog or weather removes it) | Dresco Town |
| Per-turn damage to anything that isn't Dark or Ghost type (or has Magic Guard, Unaware or Oblivious) | Crater Town |
| Inverse type chart | Fallshore City |
| Electric and Steel types float, so they are immune to Ground moves | Dehara City |
| Banned move types (Flying, Psychic and Fairy against trainers; the leader bans your most common of the three) | Antisis City |
| A gauntlet of consecutive battles with one Pokémon, healed between fights, no switching | Antisis City |

`moves.matchups` doesn't model these field effects yet. When one applies, the agent has to reason about it itself.

## Verified in RAM: Crater Town gym (map 6/2)

Read-only reads of the live game on 2026-10-08, plus the run's log. See `docs/addresses.md` (Objects) for the fields.

- **Watchers are ordinary trainer objects.** The guard is object id 7: trainer type 1, movement type 0x1B (walk left and right), sight range 1 (object event +0x1D, the same as the template's trainerRange). It patrols row 27 between x 9 and 18 and turns at each end within the same step. It walks one tile every 16 frames, so a full cycle takes about 288 frames; the player walks a tile in 8. The map lists four patrollers like it (ids 7, 8, 12 with movement type 0x1B, ids 9 and 10 with 0x1C), all with sight 1, plus id 11 on a walk sequence (type 36). The fixed-facing trainers (ids 2 and 4–6) have sight 3–4.
- **What "caught" means.** In the run's log (step 1797), the player stepped onto (19,27) while the guard stood at (18,27) facing right. "Gotcha!" played and the player was warped to (27,24) with no battle. When the player stood on (20,27) with the guard 7–8 tiles away facing it (steps 1826–1834), nothing happened. So sight is short, and the check runs while the player is standing still.
- **Objects outside the camera aren't live.** Only objects near the screen are in `gObjectEvents`. Guard 8 (x 1..15 on row 27) wasn't loaded while the player stood at (20,26). Any tool sees only the watchers on screen.
- **Predictions were checked against live samples.** 30 s of read-only samples of the guard gave 1,271 (prediction, later observation) pairs, each within the 32-frame horizon, with no misses, both before and after the turning points were learned. The learned turning points were (9,27) and (18,27). With them known, the only tiles the guard can ever see are row 27, x 8..19. The player's waiting tile (20,26) and the alcove tiles below the row (for example (16,28)) are safe zones.

## Open questions (check in play)

- Whether the checkpoint is a flag or a var, and how it is set.
- Whether a defeated trainer's sight still counts. `sneak_to` counts every trainer object as a watcher, which is conservative.
- Answered: the patrollers' turning points follow vanilla `WalkBackAndForth`. A walker goes from its start out to start ∓ range in the direction it sets off and back (guard 7: 18 → 9), with fixed turns. See docs/addresses.md, Objects. `sneak_to` seeds them from the template and falls back to watching if a read contradicts the seed.
