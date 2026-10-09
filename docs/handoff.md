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
  game is still running in mGBA at that point; it is the **test bed for the menu tools (#161)**: nothing is playing,
  so a tool may drive the emulator.
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

## Expert work: to do (in order)
1. **#161 menu tools:** PC deposit/withdraw/swap, give/take held item, reorder party. Build and verify on the parked
   full1 game (no runner playing). Each tool re-reads party/storage to verify its result.
2. **#109 buy tool:** purchase from a Poké Mart in one call (vitamins, held items).
3. **agent/CLAUDE.md, Expert policy:** losing is information. Record the opponent's team, then train to the cap,
   catch a counter, rebuild from the PC, EV-train the stats that matter, and hand out held items. Use
   team_details/pc_boxes and the damage estimates.
4. **#162:** start the Expert run (the checklist is in the issue):
   ```
   python bridge/launch.py --detach runner --min cmd /c "python -u agent\run.py --workspace D:\ClaudeUnboundRuns\expert1 --fresh --bootstrap-from D:\ClaudeUnboundRuns\full1 --difficulty expert --goal-badges 8 >> D:\ClaudeUnboundRuns\expert1.console.log 2>&1"
   ```
   `--fresh` stops the current mGBA and starts a new game; full1's save and workspace are kept. Then start the
   spectator for `expert1` and arm `ops/watch_run.py D:\ClaudeUnboundRuns\expert1`.

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
