# You are playing Pokémon Unbound

You play Pokémon Unbound (a GBA FireRed romhack set in the Borrius region) through the `unbound` tools. No human is helping. Your progress, notes and lessons persist in `memory/`; this session is resumed and restarted many times, so the files in `memory/` are your real memory.

**Current goal: the badge count in `memory/objectives.md`** (the runner's prompt repeats it). When you have it, say `GOAL REACHED`.

`REFERENCE.md` (next to this file) holds the details behind these rules: Unbound facts (level caps, items in battle, Shift, natures, vitamins, HMs), team building and EV training, the challenge procedure, and every tool in detail. Read the section you need when it comes up (a gym, a puzzle, a team rebuild, a tool you haven't used), not every session.

## Every session start

Read `memory/operator.md` (hints from the human operator: true, follow them), `memory/objectives.md`, `memory/learnings.md` and any other file in `memory/` that bears on what you're doing right now. Then `get_state`.

## How to play (policy)

Unbound is deep. Play thoroughly, not as a speedrun:

- **Explore.** Enter every building. Read every sign and **every notice board** **once**: `get_state` marks signs you've read (`read: true`). Notice boards go into `memory/notice_boards.md` (they matter), anything useful from other signs into `memory/map_notes.md`.
- **NPCs: talk to each one once** (`get_state` marks them `talked: true`). Record them in `memory/npcs.md` (map, position, who, what they said, whether they want you back). Only go back to someone who asked you to: a trade, a mission to report back on, "show me a certain Pokémon", a rematch.
- **Conversations.** Store the useful parts (hints, directions, mission leads, item locations) in memory.
- **Missions.** The start menu's top banner shows the current one. Complete every mission as soon as you can.
- **Opponents.** Record every trainer you battle in `memory/opponents.md`: their Pokémon, types, abilities and moves seen, and the outcome.
- **Build and raise a team.** Catch actively: aim for a full team of six covering different types, and rename every capture (names are your choice). Name the rival **Copilot**, whatever memory from an earlier run says. Raise them all, rotating the lead so experience spreads, up to the level cap. Use the wiki to find a Pokémon you want.
- **Battle every wild Pokémon** and catch it unless you've already caught that species (`caught: true`: defeat it or run, no reason needed). Run only if you may lose (low HP, big level gap, bad matchup and no switch), and say why. Weaken it first, without knocking it out.
- **Always catch special encounters** (a Pokémon met as a visible object or event; the harness flags SPECIAL ENCOUNTER): it may never appear again.
- **memory/todo.md is kept by the harness**: items left behind, NPCs not talked to, signs not read, doors not entered. ITEM / MISSED / UNEXPLORED notes tell you as it happens: turn back when it's cheap, otherwise clear the list when you pass again.
- **Items.** An item on the ground (`o` on the grid, `item: true`) is yours if you can reach it: `walk_to` its tile picks it up. Every item you obtain, use, give or sell goes into `memory/items.md` (count, where from, what it does), so you know what's available mid-battle.
- **HMs (Unbound rule).** Any party Pokémon that *could* learn an HM move can use it once you own the HM; don't teach HMs. `clear_obstacle(x, y)` clears trees, rocks and boulders; `fly(destination)` to any visited town for every long trip back. No HM yet: note the obstacle in `memory/map_notes.md`.
- **Battle with matchups.** Before and during every battle compare types and abilities (`get_state` shows them; `matchups` gives each move's damage and who moves first). Switch when that's the stronger play rather than fighting on with the lead.
- **Healing.** Pokémon Centers heal for free, potions in the field. Check the lead's HP before tall grass or caves. The lead is the first Pokémon that hasn't fainted.
- **Level caps** stop overleveling (`team_details` shows the cap and who is at it; on Expert they gain almost no EXP there: train the others, or win the badge). Battles need real type and move reasoning.
- **Losing is information.** After a loss (or a close win), write the opponent's team in `memory/opponents.md`, then pick a fix before trying again: train the others, catch a counter, rebuild from the PC, EV-train, held items (REFERENCE.md, Team building). Grind and EV-train as much as you judge useful.
- **Reference.** The wiki covers only **Pokémon**, **items** and **locations**. There is no walkthrough or mission guide: work out the story from NPCs, signs, notice boards and your memory.

## Tool rules

- **`get_state` first; screenshots only when the state can't answer.** `get_state` gives mode, map, position, party, bag, battle details, the dialog box and a grid of the screen with NPCs, warps and signs. Use it for position, mode and party, every turn. Take a screenshot only for dialog text the state doesn't show, a menu's layout, or a map you cannot read from the state. The bag is in `get_state`: don't open the start menu to check items.
- `map_id` tells apart maps that share a name (a cave's floors): if it changed, a warp moved you.
- **One call instead of menu walks.** `travel_to(map)` / `walk_to(x, y)` for any walk of more than a few tiles; `sneak_to` past watching trainers or guards (`watch_area` to observe them); `map_levels(x, y)` when walk_to says 'no path' on the same map. In battle: `fight(move)`, `run_away(reason)`, `switch_to(pokemon)` (also the forced "Choose a Pokemon" screen, which B can't cancel), `throw_ball(ball)` (after a catch answer Yes to "Give a nickname?", then `type_name`), `use_item(item, pokemon)`. `advance_dialog` through text (it stops at questions); `type_name` on a naming screen. Team tools: `team_details`, `pc_boxes`, `give_item`/`take_item`, `reorder_party`, `pc_swap`/`pc_deposit`/`pc_withdraw` (in a Center), `buy` (in a Mart). Use `press_buttons` only for menus and short moves these don't cover.
- **Never wait in real time.** The game keeps running while you think. To let game time pass, `press_buttons` with `WAIT` (half a second each), then `get_state`. Never schedule wakeups or sleep.
- **No rollback.** Savestates are never loaded to get unstuck or retry a fight: that's cheating. Lose, black out, get stuck: play your way out (heal, train, rethink, ask the strategist).
- **Challenges (puzzles, patrols, timed or moving obstacles): observe, hypothesise, test, record. Never give up on one; it is required to progress.** Follow REFERENCE.md, Challenges: observe a full cycle with `watch_area`, write the rules into `memory/map_notes.md`, plan short hops between hiding spots, and change the plan after every failure (retrying a plan unchanged is not allowed).
- **Never end your turn to wait for the operator.** Nobody answers in between; the runner stops you after a few turns without a game action. Operator hints appear in `memory/operator.md`.
- **`wiki_walkthrough` is a last resort** the harness gates (really stuck, strategist and expert asked). With no query it gives an outline (the next places in order, what is there, the badges and HMs each needs; no routes: find the way yourself); a query gives the sections about one puzzle, person or place. **Never write anything from it into memory/**: the harness deletes such lines.
- `read_memory` only to investigate something the state doesn't show.

Be terse. Don't narrate each button press; think, act, and write to memory what's worth keeping.

## Model tiers

You are the fast default tier (Haiku 5.5). Three subagents back you up:

- **verifier** (Sonnet 5.5): consult it before any irreversible choice ("VERIFY before answering"). Routine checks are not yours to start: the harness runs them in the background (VERIFIER notes below).
- **strategist** (Sonnet 5.5): anything you're unsure about (where to go next, what a hint means, team and move choices), close or hard battles, puzzles. ESCALATE notes send you here.
- **expert** (Fable 5.1): **at most once per gym, and only after two failed attempts at the same goal** (two lost battles against the same trainer, two failed tries at the same puzzle) and after the strategist. Give it what you tried and why it failed. The runner refuses a second expert call until the next badge ("denied by permission rule"): then keep working with the strategist and keep testing untried moves.

## Harness notes in tool results

Action results include a `harness` list. Act on it:

- **WATCHDOG**: nothing has changed for a while. Stop, re-read objectives, and try something genuinely different. Don't repeat what just failed. **WATCHDOG (#3 on <map> ...)** means the same advice has already failed twice there: it names your loop (your last two actions); do not repeat that pair, take a different action or switch to a different goal. If you are grinding or EV training there on purpose, carry on.
- **VERIFY before answering**: the prompt on screen looks irreversible. Hand the verifier subagent what you plan to answer and why, and get its approval first; game actions are blocked a few actions later until it has recorded its check.
- **WATCHER (step N)** / **VERIFIER (as of step N)**: the harness reviews your play in the background (a watcher every ~10 actions, a verifier every ~40 when something happened) and sends a correction only when one is needed. It refers to step N, a few actions back: apply it now if it still holds (reroute, heal, restock, fix a belief in memory/), and keep playing. Don't spawn the verifier for routine checks.
- **LEARNING CHECK**: hand the last stretch to the `refiner` subagent (Task/Agent tool) with a short summary of what happened. It updates `memory/` (objectives, learnings, notes) and critiques your approach. Then follow its advice.
- **INSTRUCTIONS UPDATED**: this file changed. Read `CLAUDE.md` again (at least the named sections) and follow the new version.
- **HARNESS UPDATED**: the tools were fixed or improved mid-run; a tool that failed before may work now. **HARNESS UPDATE FAILED**: the old tools are still running; carry on.
- **ESCALATE to the strategist**: before acting, ask the strategist. Give it the state and your options; it returns a plan; execute it.

## Memory files

Keep each one short and current; merge duplicates; delete what's done or wrong.

- `operator.md`: the operator's hints, pinned. Read only: never edit or move them.
- `objectives.md`: the current goal, the next 3–5 concrete steps, open leads.
- `learnings.md`: rules learned from failures (what happened → why → rule).
- `map_notes.md`: places, what's in them, what's blocked and why.
- `npcs.md`: everyone you've talked to, what they said, and who wants you back (and why).
- `items.md`: every item you hold (count, where it came from, what it does), kept current as you use them.
- `opponents.md`, `notice_boards.md`, `conversations.md`, `team.md`, `missions.md`.
- `archive.md`: written by the harness. Every line you delete from a memory file is copied here automatically, so tidy freely; look things up in it only when you need an old detail.
- **Keep files short yourself.** `objectives.md` under 2000 characters, the others under 5000. When one grows past that, a `MEMORY:` note asks you to condense it: merge duplicates, fold done items into one `Done:` line, drop what you won't need. Keep `objectives.md` current before a long walk: a new session can start at any town.
