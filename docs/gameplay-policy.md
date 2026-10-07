# Gameplay policy

How Claude should play Unbound. Unbound is very in-depth, so the goal is a thorough playthrough rather than a speedrun. These rules feed the agent's system prompt and memory design (Phase 2).

## Exploration

- Talk to as many NPCs as possible.
- Enter every building.
- Read every notice board and store it in memory. Notice boards carry important information.

## Conversations

- Evaluate every conversation for usefulness and store the useful parts in memory.

## Battles

- Record every battle opponent, including their Pokémon's types and abilities.
- After a defeat, use that record to build a team suited to the rematch.

## Pokémon

- Rename every Pokémon captured. Names are entirely Claude's choice.

## Quests

- Unbound has a mission (quest) system. Complete every mission as soon as it becomes possible.

## Reference material

- Claude may consult the community wiki ([unboundwiki.com](https://unboundwiki.com/)) for anything: walkthrough, trainer teams, puzzle solutions, missions, item locations. This settles the wiki-access question the research report left open.
- The wiki is indexed into a local searchable corpus that Claude queries on demand. It is not loaded into memory wholesale. Memory holds what Claude learns while playing, and looks things up in the wiki when it needs them.

## Impact on the plan

- These rules put the full mission log (84 missions), notice boards, conversations and opponent records in scope for the memory design and the state layer. The research report treated only one mission as mandatory.
- Full exploration and every mission raise the step count, and so the cost, well above the report's main-story estimate of 15,000–40,000 steps.
