# Gameplay policy

How Claude should play Unbound. Unbound is very in-depth, so the goal is a thorough playthrough rather than a speedrun. These rules feed the agent's system prompt and memory design (Phase 2).

## Exploration

- Talk to every NPC **once**, and remember what they said. Talk to them again only if they gave a reason to come back (a trade, a mission to report back on, "show me X Pokémon", a rematch). Decided 2026-10-07.
- Enter every building.
- Read every sign and notice board **once** and store what matters in memory (notice boards always: they carry important information). Don't re-read them.

## Field obstacles

- Ignore cuttable trees, breakable rocks and boulders until the team can use the matching field move (Cut, Rock Smash, Strength); note them and return later. Decided 2026-10-07.

## Conversations

- Evaluate every conversation for usefulness and store the useful parts in memory.

## Battles

- Play the type matchup: compare move types against the foe's types (and the foe's against yours), and switch to a better-matched Pokémon mid-battle when that's the stronger play. Decided 2026-10-07.
- Record every battle opponent, including their Pokémon's types and abilities.
- After a defeat, use that record to build a team suited to the rematch.

## Pokémon

- Battle every wild Pokémon encountered; catch it if possible (Poké Balls in the bag); run only if the fight may be lost. Decided 2026-10-08 (user).
- A species already caught isn't caught again: defeat it or run (user, 2026-10-08). The Pokédex owned flags decide.
- Always catch special (non-random) encounters: Pokémon met as visible objects or events. Decided 2026-10-07.
- Rename every Pokémon captured. Names are entirely Claude's choice.
- Never reload a savestate to get unstuck or retry: that's cheating (user, 2026-10-08). Losses and dead ends are played through. Runner autosaves exist only to recover from an emulator crash.
- Name the rival **Copilot** (user's choice). This overrides any rival name in memory carried over from an earlier run.
- Catch Pokémon actively to build a full, type-diverse team of six, and raise all of them (rotate the lead), up to the level caps. Decided 2026-10-07.

## Quests

- Unbound has a mission (quest) system. Complete every mission as soon as it becomes possible.

## Reference material

- Claude may consult the community wiki ([unboundwiki.com](https://unboundwiki.com/)), **limited to three sections** (decided 2026-10-07):
  - [Pokémon](https://unboundwiki.com/pokemon/): where to get each one, abilities, evolutions and all other Pokémon info;
  - [Items](https://unboundwiki.com/items/): every item;
  - [Locations](https://unboundwiki.com/locations/): towns, cities and other places.
- **No walkthrough or mission pages.** Claude works out the story, routes and missions from the game itself (NPCs, signs, notice boards) and its own memory.
- The three sections are indexed into a local searchable corpus that Claude queries on demand. It is not loaded into memory wholesale.

## Items

- Record every item when it's obtained (where, what it does) and update the record when it's used, given or sold, so Claude always knows what's available, especially during battle.

## Impact on the plan

- These rules put the full mission log (84 missions), notice boards, conversations, items and opponent records in scope for the memory design and the state layer. The research report treated only one mission as mandatory.
- Full exploration and every mission raise the step count, and so the cost, well above the report's main-story estimate of 15,000–40,000 steps.
