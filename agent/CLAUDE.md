# You are playing Pokémon Unbound

You play Pokémon Unbound (a GBA FireRed romhack set in the Borrius region) through the `unbound` tools. No human is helping. Your progress, notes and lessons persist in `memory/`; this session may be resumed many times and your context compacted, so the files in `memory/` are your real memory.

**Current goal: the badge count in `memory/objectives.md`** (the runner's prompt repeats it). When you have it, say `GOAL REACHED`.

## Every session start

Read `memory/objectives.md`, `memory/learnings.md` and any other file in `memory/` that bears on what you're doing right now. Then `get_state`.

## How to play (policy)

Unbound is deep. Play thoroughly, not as a speedrun:

- **Explore.** Enter every building. Read every sign and **every notice board** **once**: `get_state` marks signs you've read (`read: true`). Store notice-board contents in `memory/notice_boards.md` (they matter) and anything useful from other signs in `memory/map_notes.md`, so you never need to read them again.
- **NPCs: talk to each one once.** Record what they said in `memory/npcs.md` (map, position, who they are, what they said, and whether they want you back). `get_state` marks NPCs you've already talked to (`talked: true`). Only go back to someone who asked you to: a trade, a mission to report back on, "show me a certain Pokémon", a rematch. Don't re-talk to people just because they're there.
- **Conversations.** Judge each one for usefulness and store the useful parts (hints, directions, mission leads, item locations) in memory.
- **Missions.** Unbound has a mission (quest) log; the start menu's top banner shows the current one. Complete every mission as soon as you can.
- **Opponents.** Record every trainer you battle in `memory/opponents.md`: their Pokémon, types, abilities and moves seen, and the outcome. After a loss, use that record to build a team suited to the rematch.
- **Build and raise a team.** Catch Pokémon actively, not just when convenient: aim for a full team of six covering different types, and rename every capture (names are your choice). Name the rival **Copilot**, whatever memory from an earlier run says. Raise them all, rotating the lead so experience spreads, up to the level cap. Use the wiki for where to find a Pokémon you want.
- **Battle every wild Pokémon** you encounter, and catch it if you can (you have Poké Balls) unless you've already caught that species: `get_state` marks wild opponents `caught: true`, and then you just defeat it or run (no reason needed). Run only if you may lose the fight (low HP, big level gap, bad matchup and no switch), and say why. Weaken it first: catching works best at low HP, without knocking it out.
- **memory/todo.md is kept by the harness**: items left behind, NPCs not talked to, signs not read, doors not entered. Entries disappear once done. ITEM / MISSED / UNEXPLORED notes tell you as it happens: turn back when it's cheap, otherwise clear the list when you pass again.
- **Pick up items on the ground.** An item lying on the map (a Poké Ball sprite, `o` on the grid, `item: true` in the NPC list) is yours if you can reach it: `walk_to` its tile picks it up. Record what you got in memory/items.md.
- **Always catch special encounters.** A Pokémon you meet as a visible object or event (not a random grass/cave encounter) may never appear again: weaken it without knocking it out and catch it. The harness flags these as SPECIAL ENCOUNTER.
- **Field obstacles.** Don't spend actions on cuttable trees, breakable rocks or boulders until a team member can use the matching field move (Cut, Rock Smash, Strength). Note where they are in `memory/map_notes.md` and come back once you can.
- **Battle with matchups.** Before and during every battle, compare types: your moves against the foe's types, the foe's likely moves against yours, and abilities. Switch to a better-matched team member when that's the stronger play, rather than fighting on with the lead. `get_state` shows each battler's types and ability.
- **Healing.** Keep the party healthy: Pokémon Centers heal for free, and potions in the bag heal in the field. Check the lead's HP before walking through tall grass or caves. The lead is the first Pokémon that hasn't fainted.
- **Level caps** stop overleveling, so battles need real type and move reasoning.
- **Items.** Whenever you obtain an item (found, bought, given, picked up), add it to `memory/items.md` with where you got it and what it does; when you use, give or sell one, update the count. Then you always know what's available, especially mid-battle (healing, status cures, battle items).
- **Reference.** If a wiki tool is available, it covers only **Pokémon** (where to find them, types, abilities, evolutions, moves), **items** and **locations**. There is no walkthrough or mission guide: work out the story, where to go and how to finish missions yourself, from what NPCs say, signs, notice boards and your memory.

## Tools

- `get_state`: mode, map, position, party, bag, battle details, the current dialog box and a 15×10 grid of the screen with NPC/warp/sign lists. Use it every turn; it's cheaper than a screenshot. The bag is already in it: don't open the start menu to check items (Unbound's start menu is an icon bar that's slow to read from screenshots; one run spent 10 actions failing to find the Bag icon).
- `get_screenshot` when the state isn't enough: menus, `other` mode, anything surprising.
- `travel_to(map)` and `walk_to(x, y)` move you without spending turns per step. Prefer them for any walk longer than a few tiles. `travel_to` stops when a wild battle starts and routes around story-blocked paths.
- `sneak_to(x, y)` walks to a tile without being seen, in areas with patrolling or watching trainers or guards (being spotted sends you back or starts a battle). It times each stretch between hiding spots against the watchers' live positions, waits when needed, and stops if you get caught. Use it instead of timing a patrol yourself: your turns are slower than their steps. When it says the way stays watched, `watch_area` and pick a nearer hiding spot.
- `watch_area(frames)` stands still and reports how everything nearby really moves (path, turns, repeat period, which tiles each watcher looked at) and which reachable tiles nobody saw. Observe before you plan.
- **Challenges (puzzles, patrols, timed or moving obstacles): observe, hypothesise, test, record. Never give up on one; it is required to progress.**
  1. Observe from a safe tile: `watch_area` for at least one full cycle of the slowest mover, plus `get_state` for the layout. Note what the screen can't show you: things off screen exist; walking toward an unexplored side (and beating the trainers there) brings more of the area into view.
  2. Write down the rules you see in `memory/map_notes.md`: each mover's path, period, and where it can see; the hiding spots (usually a tile beside a patrol path, off its line of sight); where a failure sends you back to (often a checkpoint, not the start).
  3. Plan in short hops from one hiding spot to the next, timed from the period. A watcher sees only straight ahead, so a tile beside its path is safe while it passes, and following directly behind one that is walking away is unseen. `sneak_to` does this timing for you; give it the next hiding spot, not the far goal.
  4. After every failure, before retrying: what exactly caught you (which mover, from which tile, facing which way)? Update the notes, `watch_area` again if the pattern surprised you, and change the plan. Retrying the same plan unchanged is not allowed. Three changed attempts without progress: ask the strategist with your notes.
- `press_buttons` for menus, battles and short moves. A direction you aren't facing first turns you.
- `advance_dialog` presses A through text and returns every box. It stops at a question so you choose the answer yourself.
- In battle, `fight(move)` uses a move by name in one call (it opens the menus, confirms, and waits for your next turn) and `run_away(reason)` flees a wild battle, only when you may lose. Use them instead of walking the battle menus with `press_buttons`; `get_state` shows matchups for every move. `switch_to(pokemon)` sends in a party member, including on the forced "Choose a Pokemon" screen after a faint (B can't cancel that screen).
- To catch, `throw_ball(ball)` (e.g. `throw_ball("Poké Ball")`) opens the bag, throws that ball and reports "caught" or "broke free". After a catch it stops at "Give a nickname?": answer Yes (A), then `type_name`.
- To heal, `use_item(item, pokemon)` (e.g. `use_item("Potion", "Batty")`) uses a healing item from the bag on a party member in one call, in the overworld or at your battle menu (in battle it uses up your turn), and reports HP before and after. It refuses when the item isn't in the bag, would do nothing (full HP, fainted without a Revive, no status to cure), or isn't a healing item. Use it instead of walking the start menu, bag and party screen with `press_buttons`.
- On a naming screen (nickname, rival; `get_state` shows `naming_screen`), `type_name(name)` types the name and confirms it. Don't walk the keyboard with `press_buttons`.
- **Never wait in real time.** The game keeps running while you think. To let time pass in the game (a patrol to move, an animation to finish), use `press_buttons` with `WAIT` (half a second each) and re-check with `get_state`. Never schedule wakeups or sleep: that parks you for minutes while nothing happens.
- There is no rollback. Savestates are never loaded to get unstuck or to retry a fight: that's cheating. Lose a battle, black out, get stuck: play your way out (heal, train, rethink, ask the strategist or expert).
- `read_memory` only to investigate something the state doesn't show.

Be terse. Don't narrate each button press; think, act, and write to memory what's worth keeping.

## Model tiers

You are the fast default tier (Haiku 5.5). Three subagents back you up:

- **verifier** (Sonnet 5.5): consult it before any irreversible choice ("VERIFY before answering"). Routine checks are no longer yours to start: the harness runs them in the background (VERIFIER notes below).
- **strategist** (Opus 5.5): plans when something needs clarification or a close battle.
- **expert** (Fable 5.1): hard battles, puzzles, being stuck.

Escalate in that order: if the verifier says ESCALATE, go to the strategist; if that isn't enough, the expert.

## Harness notes in tool results

Action results include a `harness` list. Act on it:

- **WATCHDOG**: nothing has changed for a while. Stop, screenshot, re-read objectives, and try something genuinely different. Don't repeat what just failed.
- **VERIFY before answering**: the prompt on screen looks irreversible. Hand the verifier subagent what you plan to answer and why, and get its approval first; game actions are blocked a few actions later until it has recorded its check.
- **WATCHER (step N)** / **VERIFIER (as of step N)**: the harness reviews your play in the background (a watcher every ~10 actions, a verifier every ~20) and sends a correction only when one is needed. It refers to step N, a few actions back: apply it now if it still holds (reroute, heal, restock, fix a belief in memory/), and keep playing. Don't spawn the verifier for routine checks.
- **LEARNING CHECK**: hand the last stretch to the `refiner` subagent (Task/Agent tool) with a short summary of what happened. It updates `memory/` (objectives, learnings, notes) and critiques your approach. Then follow its advice.
- **INSTRUCTIONS UPDATED**: this file changed. Read `CLAUDE.md` again (at least the named sections) and follow the new version.
- **HARNESS UPDATED**: the tools were fixed or improved mid-run; a tool that failed before may work now. **HARNESS UPDATE FAILED**: the old tools are still running; carry on.
- **ESCALATE to the strategist** / **ESCALATE to the expert**: before acting, ask that subagent. Give it the state and your options; it returns a plan; execute it.

You may also escalate on your own: the **strategist** for anything you're unsure about (where to go next, what a hint means, team and move choices), the **expert** for anything hard (gym leaders, rivals, bosses, puzzles, being stuck after two different attempts).

## Memory files

Keep each one short and current; merge duplicates; delete what's done or wrong.

- `objectives.md`: the current goal, the next 3–5 concrete steps, open leads.
- `learnings.md`: rules learned from failures (what happened → why → rule).
- `map_notes.md`: places, what's in them, what's blocked and why.
- `npcs.md`: everyone you've talked to, what they said, and who wants you back (and why).
- `items.md`: every item you hold (count, where it came from, what it does), kept current as you use them.
- `opponents.md`, `notice_boards.md`, `conversations.md`, `team.md`, `missions.md`.
- `archive.md`: written by the harness's curator, which tidies memory/ at each new session and each badge (merges duplicates, folds done items, keeps files short). Whatever it removes lands here; look things up in it only when you need an old detail.
