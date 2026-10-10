# Reference (read the section you need, when you need it)

The rules are in `CLAUDE.md`. This file holds the detail behind them. The runner copies it into your workspace at
every chunk start.

## Unbound facts

- **Level caps.** Rare Candy does nothing at the cap. Besides gyms, beating Successor Maxima at Tarmigan Mansion
  (Tarmigan Town, on the way to Dehara City, after badge 4) raises the cap.
- **Items in battle.** At most 4 item uses per trainer battle, and in wild battles where the Pokemon can't be
  caught. Plan heals before the fight.
- **Shift.** After you knock out a trainer's Pokemon the game asks whether you want to switch: a free switch, if
  the next foe's matchup favours another member.
- **Stat Scanner.** Log's Assistant in Frozen Heights gives it once 50+ species are registered as owned.
  (`team_details` already shows EVs and IVs.)
- **Natures.** The Nature Changer in Tehl Town (the house south-west of the Center, after the side mission
  'Seasonal Research') changes a nature: 1 free, then $50,000 each.
- **Vitamins.** They work up to 252 EVs in a stat.
- **HMs and field moves.** A Pokemon doesn't have to be taught an HM to use it: any party Pokemon that *could* learn
  the move can use it once you own the HM (HMs are in the TM Case, Key Items). Open the party menu and pick that
  Pokemon: the move (Cut, Fly, Rock Smash, Strength, Surf...) is listed, but only where it can be used (Fly outdoors;
  Cut facing a tree; Rock Smash facing a rock). Don't teach HMs: that costs a move slot.
- **Field obstacles.** Cut trees, breakable rocks and boulders: once you hold the HM (check the TM Case) and a party
  Pokemon could learn the move, `clear_obstacle(x, y)` clears it. (In Unbound, facing it and pressing A uses the move;
  no menu.) A wild Pokemon may jump out of a rock. Without the HM yet, note it in `memory/map_notes.md`.
- **Fly** with `fly(destination)` to any town or city you have visited (from outdoors).

## Team building (essential on Expert)

- **Read before you fight:** in battle, `matchups` shows each of your moves' damage (% of the foe's HP, likely-KO)
  and who moves first. Use it to pick the move, or the switch-in that takes the hit.
- **After a loss** (or a close win), write the opponent's team in `memory/opponents.md` (species, levels, moves seen),
  then pick a fix before trying again:
  - train the others up to the cap;
  - catch a counter;
  - rebuild from the PC (`pc_boxes` lists what you have; `pc_swap` at a Center);
  - EV-train the stats that matter;
  - hand out held items.
- **EVs:** every Pokemon you defeat gives your whole party EVs in its `ev_yield` stats (the foe line in a battle;
  the Macho Brace doubles them). 4 EVs = +1 stat point at level 100, max 510 in total and 252 in one stat.
  `team_details` shows each member's EVs and how many are left. Train deliberately: e.g. Speed on a fast
  attacker by beating Speed-yield wild Pokemon, rather than whatever battle comes.
- **Natures** raise one stat 10% and lower another (`team_details`). Prefer leads whose nature suits their role.
- **Held items** matter: type boosters (Mystic Water, Charcoal...), Eviolite on a not-fully-evolved Pokemon,
  Leftovers, Choice items, the Macho Brace while EV training. Use `give_item` / `take_item`.
- **The lead** starts every battle: set it with `reorder_party` for the next fight.
- **Shopping:** `buy(item, quantity)` at a Mart (Poke Balls, Potions, status cures; vitamins raise EVs).

## Challenges (puzzles, patrols, timed or moving obstacles)

Observe, hypothesise, test, record. Never give up on one; it is required to progress.

1. Observe from a safe tile: `watch_area` for at least one full cycle of the slowest mover, plus `get_state` for the
   layout. Note what the screen can't show you: things off screen exist; walking toward an unexplored side (and
   beating the trainers there) brings more of the area into view.
2. Write down the rules you see in `memory/map_notes.md`: each mover's path, period, and where it can see; the hiding
   spots (usually a tile beside a patrol path, off its line of sight); where a failure sends you back to (often a
   checkpoint, not the start).
3. Plan in short hops from one hiding spot to the next, timed from the period. A watcher sees only straight ahead, so
   a tile beside its path is safe while it passes, and following directly behind one that is walking away is unseen.
   `sneak_to` does this timing for you; give it the next hiding spot, not the far goal.
4. After every failure, before retrying: what exactly caught you (which mover, from which tile, facing which way)?
   Update the notes, `watch_area` again if the pattern surprised you, and change the plan. Retrying the same plan
   unchanged is not allowed. Three changed attempts without progress: ask the strategist with your notes.
5. **Never end your turn to wait for the operator.** Nobody answers in between: the runner stops you after a few
   turns without a game action. Hints from the operator appear in `memory/operator.md` (re-read it when stuck). Still
   stuck after the strategist and two failed attempts: the expert (once per gym), then keep testing untried moves and
   record each result.
6. **Last resort: `wiki_walkthrough(query, reason)`.** Only when really, really stuck: no progress for a long time,
   the watchdog keeps firing, and the strategist and the expert couldn't fix it (the harness checks this and refuses
   until it's true). Use what it says to get unstuck, but **never write anything from the walkthrough into memory/**:
   the harness deletes such lines. Record only what you then verify yourself in play, in your own words.

## Tools in detail

- `get_state`: mode, map, position, party, bag, battle details, the current dialog box and a 15x10 grid of the screen
  with NPC/warp/sign lists. The bag is already in it: don't open the start menu to check items (Unbound's start menu
  is an icon bar that's slow to read from screenshots; one run spent 10 actions failing to find the Bag icon).
- Several maps can share a name (a cave's floors, a building's rooms). `map_id` in every result tells them apart: if
  it changed, a warp moved you to another floor even though the name didn't change.
- `travel_to(map)` and `walk_to(x, y)` move you without spending turns per step. Prefer them for any walk longer than
  a few tiles. `travel_to` stops when a wild battle starts and routes around story-blocked paths.
- `sneak_to(x, y)` walks to a tile without being seen, in areas with patrolling or watching trainers or guards (being
  spotted sends you back or starts a battle). It times each stretch between hiding spots against the watchers' live
  positions, waits when needed, and stops if you get caught. Use it instead of timing a patrol yourself: your turns
  are slower than their steps. When it says the way stays watched, `watch_area` and pick a nearer hiding spot.
- `watch_area(frames)` stands still and reports how everything nearby really moves (path, turns, repeat period, which
  tiles each watcher looked at) and which reachable tiles nobody saw. Observe before you plan.
- **Levels.** Maps can stack paths: a bridge or walkway over a lower path (lily pads, a road under a bridge). You
  can't step between levels except where the game connects them (stairs, ramps, ledges, a ride). When walk_to says
  'no path' on the same map, or you can't see how to get somewhere, call `map_levels(x, y)`: it lists the map's
  regions, their level, and how each is entered (on foot from which region, or only by a ride/warp/person at its
  edge). Go to where the target's region is entered; don't keep pressing at the place where the levels overlap.
- `press_buttons` for menus, battles and short moves. A direction you aren't facing first turns you.
- `advance_dialog` presses A through text and returns every box. It stops at a question so you choose the answer
  yourself.
- In battle, `fight(move)` uses a move by name in one call (it opens the menus, confirms, and waits for your next
  turn) and `run_away(reason)` flees a wild battle, only when you may lose. `switch_to(pokemon)` sends in a party
  member, including on the forced "Choose a Pokemon" screen after a faint (B can't cancel that screen).
- To catch, `throw_ball(ball)` (e.g. `throw_ball("Poké Ball")`) opens the bag, throws that ball and reports "caught"
  or "broke free". After a catch it stops at "Give a nickname?": answer Yes (A), then `type_name`.
- To heal, `use_item(item, pokemon)` (e.g. `use_item("Potion", "Batty")`) uses a healing item from the bag on a party
  member in one call, in the overworld or at your battle menu (in battle it uses up your turn), and reports HP before
  and after. It refuses when the item isn't in the bag, would do nothing (full HP, fainted without a Revive, no status
  to cure), or isn't a healing item.
- On a naming screen (nickname, rival; `get_state` shows `naming_screen`), `type_name(name)` types the name and
  confirms it. Don't walk the keyboard with `press_buttons`.
- **Team tools (overworld)**. Each one does the whole menu walk in one call and verifies the result:
  - `team_details`: natures, real stats, base stats, EVs, IVs, the level cap.
  - `pc_boxes`: everything in your PC boxes. Works anywhere.
  - `give_item(item, pokemon, replace)`, `take_item(pokemon)`: held items.
  - `reorder_party(pokemon, position)`: e.g. position 1 makes it the lead.
  - In a Pokemon Center: `pc_swap(pokemon, box, slot)`, `pc_deposit(pokemon)`, `pc_withdraw(box, slot)`. They walk
    to the PC themselves and never release a Pokemon.
  - In a Mart: `buy(item, quantity)`. It refuses an item the Mart doesn't sell, or one you can't afford.
- `read_memory` only to investigate something the state doesn't show.
