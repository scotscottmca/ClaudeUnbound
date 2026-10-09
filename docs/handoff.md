# Handoff: state of the project

Read [operator-runbook.md](operator-runbook.md) first. This file is the current state; the operator updates it when
the state changes materially (a run starts or ends, a milestone completes).

_Last updated: 2026-10-09, when the operator role moved from a long Opus session to the Haiku-led operator session._

## Where things stand

**Vanilla full run (`D:\ClaudeUnboundRuns\full1`) is finished for our purposes and parked.**
- **Result:** 4 badges (Dresco, Crater Town, Blizzard City, Fallshore City), 6,477 agent actions over 25 hours
  wall-clock (including pauses and operator interventions), 38 catches (all nicknamed).
- **Cost:** about $50 API-equivalent in total (`run.spent_so_far`; the console's old "spent" figure summed session
  running totals and was wrong, #150).
- **Where it stopped:** the runner was stopped on purpose at step 6477 (Fallshore City 14/3, just after badge 4). The
  game is still running in mGBA; it was the test bed for the menu tools (#161, #109). While testing, the operator
  watched Mel's post-gym scene (received **HM02 Fly**; mission now "Follow Mel to Epidimy Town"), and bought
  3 Potions and 10 Poke Balls in the Fallshore Mart. The party is unchanged; the player stands in the Mart (14/5).
- **Final team:** Ion (Metang 43), Brawn (Hariyama 40), Bulwark (Hariyama 37), Batty (Crobat 39), Pip (Watchog 38),
  Splash (Samurott 37).

**Next goal: an Expert-difficulty run** (milestone "Phase 6: Expert run"). Expert differences (wiki "Difficulty"
and "Level Caps"):
- level caps on by default: 20 / 26 / 32 / 36 / 40 / (45 after Tarmigan Mansion) / 52 / 57 / 61 / 75 by badges;
- trainers scale to your highest level (bosses to it, others 5-7 below);
- Ace Trainers, Experts and trainers after 4 badges have 252 EVs in their two best stats;
- Shift battle style by default;
- the "4 Items Only" restriction (meaning to be confirmed);
- you start with a Macho Brace;
- Véga at Cinder Volcano is fought without a partner.

## Expert work: done
- **#156:** the agent sees natures, EVs (with the 510/252 limits), IVs and real stats (`team_details`), each foe's EV
  yield in battle, and the level cap with who is at it. Party layout verified by recomputing all six stored stats.
- **#157:** the agent sees its PC (`pc_boxes`). CFRU's compressed 58-byte storage was decoded; boxes 1-19 are readable.
- **#158:** battle matchups show damage estimates (% of the foe's max HP, likely-KO flags) and speed order. The foe
  is estimated from base stats and level, using Expert's EV rule; our own stats are exact. Offsets verified in a live
  battle.
- **Runner:** `--difficulty expert` stores the difficulty in the workspace's `run.json`, passes it to the MCP server
  (`UNBOUND_DIFFICULTY`), and seeds the agent's objectives to pick Expert at the new-game prompt.
- **Last-resort walkthrough (#153, #159, #160):** indexed by section, gated, nothing reaches memory.

- **#161 menu tools, verified live:** `give_item` / `take_item` / `reorder_party` (party menu) and `pc_deposit` /
  `pc_withdraw` / `pc_swap` (Center PC; never selects Release).
- **#109 `buy`, verified live:** stock and money checks; the bonus Premier Ball for 10 balls.
- **#164:** 33 garbled item names fixed (Unbound stores a pointer for long names).
- **#165 `fly`, verified live:** flies to visited towns (Dresco and back). The agent knows Unbound's HM rule: any Pokemon
  that could learn an HM can use it from the party menu, without being taught. The full1 save holds HM01 Cut, HM02 Fly
  and HM06 Rock Smash.
- **agent/CLAUDE.md:** the team tools, plus the Expert policy. Read matchups; losing is information, so record the
  opponent and pick a fix (train to the cap, catch a counter, PC swap, EV training, held items); EVs, natures,
  held items, the lead, shopping.

## Expert work: to do
1. **#162:** start the Expert run (the checklist is in the issue):
   ```
   python bridge/launch.py --detach runner --min cmd /c "python -u agent\run.py --workspace D:\ClaudeUnboundRuns\expert1 --fresh --bootstrap-from D:\ClaudeUnboundRuns\full1 --difficulty expert --baseline D:\Repos\ClaudeUnbound\run\baseline_expert.ss1 --goal-badges 8 --budget-usd 150 >> D:\ClaudeUnboundRuns\expert1.console.log 2>&1"
   ```
   `--fresh` stops the current mGBA and loads `run/baseline_expert.ss1`, a **true Expert new game**. The human
   played the intro on 2026-10-09: New Game, difficulty **Expert** (default Expert settings: Shift, 4 Items Only,
   Capped Exp. Share), **puzzle difficulty Easy** (the human's choice: the test is battles and team-building, not
   puzzles). It stops at the first point of control: Shadow Base cell (1,2), no party yet.

   Other start files:
   - `run/baseline.ss1`: the Vanilla start;
   - `run/baseline_difficult.ss1`: a Difficult variant made from it.

   The runner refuses a non-Vanilla `--fresh` without `--baseline`. The Vanilla run's in-game save is kept at
   `D:\ClaudeUnboundRuns\full1\Unbound_full1_final.sav` (and `run/Unbound.sav.*.full1.bak`).

   **Spectator (port 8765):** the one still running watches `full1` and holds the port. After the runner has
   created `expert1` (about a minute), stop it and start a new one:
   ```powershell
   Get-CimInstance Win32_Process -Filter "name='python.exe'" | ? { $_.CommandLine -match 'ui\\server\.py' } | % { Stop-Process -Id $_.ProcessId -Force }
   python bridge/launch.py --detach spectator --min python D:\Repos\ClaudeUnbound\ui\server.py --workspace D:\ClaudeUnboundRuns\expert1 --port 8765
   ```
   Check that http://127.0.0.1:8765/ answers, and tell the human to refresh the page. Then start the
   spectator for `expert1` and arm `ops/watch_run.py D:\ClaudeUnboundRuns\expert1`.

- **#166:**
  - `use_on` (vitamins / stones / Rare Candy). Live: Calcium +10 SpA EVs. The evolution path still needs a live check.
  - `teach_tm` (forget-move flow). Live: TM40 to Batty, TM10 to Pip.
  - `clear_obstacle` (Unbound: facing it and pressing A uses Cut / Rock Smash). Live: three rocks and a tree on
    Route 2.
- **Research before the run** (two web-research agents, 2026-10-09; verify in play):
  - **Item Restrictions "4 Items Only":** items used in **trainer battles**, and in wild battles where the Pokemon
    can't be caught. Expert can't loosen it. Whether it's per battle, and what counts, is not documented.
  - **Shift:** the game asks to switch after you KO a trainer's Pokemon. The wording, and whether it shows in
    doubles, are not documented.
  - **Level caps:** the post-Tarmigan step comes from beating Successor Maxima at Tarmigan Mansion (Tarmigan Town,
    after badge 4, before Dehara). Rare Candy does nothing at the cap (CFRU source).
  - **Boxes:** CFRU has 25. The addresses of boxes 20-25 are in docs/addresses.md (plausible).
  - **No mints.** The Nature Changer NPC is in Tehl Town (1 free after 'Seasonal Research', then $50,000) and at
    the Battle Frontier (50 BP). The nature is probably rewritten into the personality.
  - **Stat Scanner:** on Difficult and up, Log's Assistant in Frozen Heights once 50+ are owned.
  - **Vitamins:** they work up to 252 EVs (CFRU patches the vanilla 100 cap).

## Other open issues
- **#146:** walk_to learns refused moves. No live recurrence yet; follow-up: walk-test sideways-stair behaviours
  0xB0-0xB3 when nothing is playing.
- **#150:** idle breaker and cost tally. The tally is verified; the breaker hasn't fired live yet.
- **#159, #160:** walkthrough excerpt and section index. Verify on the next gated use.
- **#22:** bootstrap across runs. The Expert run's bootstrap from full1 is its test.
- **#23:** full-run umbrella.

## Things to know
- **Detached processes:** mGBA, the runner and the spectator must be started detached (`launch.py`, `--detach`). The
  Claude app auto-updated once and took down everything started from its shells (#151).
- **The playing agent's subagents** (verifier/strategist/expert/refiner in `agent/agents.json`) are separate from
  the operator's ops-* subagents.
- **Operator hints:** go into `<workspace>\operator.md`, in the human's words. They are announced to the agent
  immediately (#154).
- **The human's standing rules** are in the operator memory (loaded automatically) and runbook section 5. The ones
  most often relevant:
  - one mGBA;
  - no savestate rollback;
  - 2x speed;
  - issue per change with full write-ups;
  - verify fixes on the next real occurrence;
  - battle every wild Pokémon (catch it if new, run only if losing);
  - pick up reachable items;
  - rival name Copilot;
  - walkthrough only as gated last resort, and never into memory.
