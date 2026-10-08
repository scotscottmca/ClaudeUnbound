# Bootstrap report: did full1 gain from gym1's memory? (#22)

Data: `D:\ClaudeUnboundRuns\gym1` (from scratch, 2026-10-07 17:51 to 10-08 00:28) and `full1` (`--bootstrap-from gym1`, started 10-08 08:04; read up to 13:30, while still live). Active time is the sum of gaps between log lines, leaving out any gap over 5 min. Excluded gaps: gym1 18:43–48, 18:50–58, 19:45–20:07 (operator rewind and harness batch #59/#60) and 21:41–47; full1 08:18–23 and 12:16–13:22 (66 min of harness work, after badge 1). "Calls" means every MCP log line; "game" means calls minus get_state, screenshots, verification records, wiki and save/load.

## Milestones (cumulative from the start of the run)

| Milestone (first arrival) | gym1 active / calls / game | full1 active / calls / game | full1 ÷ gym1 (time) |
|---|---|---|---|
| Out of Shadow Base (Frozen Heights) | 27 min / 343 / 215 | 11 min / 246 / 140 | 0.41 |
| Frozen Heights exit (Route 1) | 51 / 640 / 415 | 34 / 406 / 240 | 0.66 |
| Bellin Town | 54 / 667 / 433 | 34 / 408 / 242 | 0.63 |
| Icicle Cave | 126 / 1274 / 871 | 42 / 539 / 336 | 0.34 |
| Route 2 | 144 / 1464 / 982 | 74 / 1008 / 612 | 0.51 |
| Dresco Town | 209 / 2272 / 1473 | 117 / 1582 / 982 | 0.56 |
| Badge 1 | 356 / 3929 / 2467 | 169 / 2289 / 1402 | 0.47 |

Per segment, full1 was faster everywhere except Icicle Cave to Route 2 (gym1 18 min, full1 31 min; full1 whited out to the rival there). Most of the gain is in two segments. Bellin → Icicle Cave took 72 min in gym1 and 8 min in full1, but gym1's figure includes roughly 20–37 min of progress the operator discarded at 20:07. Dresco → badge took 147 min in gym1 and 52 min in full1.

**Stalls and repeats (to badge 1):** WATCHDOG fired 3 times in gym1 and 4 in full1 (one of those was an oscillation note at Frozen Heights, 08:26). "No path" results: gym1 39 of about 294 logged navigation calls (gym1 logged no results before about 19:05), full1 22 of 198. An identical failed walk_to/travel_to repeated straight after itself: gym1 19, full1 31. Of full1's 31, 23 were in Icicle Cave, mostly re-issuing walks that a wild battle had stopped, which follows from the battle-every-wild rule. Whiteouts: gym1 1 (Dresco, against Bram in the battle house), full1 3 (rival at 09:08, Route 2 at 09:37 and 09:55).

**Cost:** I couldn't compare cost. Rotated chunks record `cost_usd` null or 0, so only 5 of 20 gym1 chunks ($7.75) and 5 of 24 full1 chunks ($2.31) have a cost at all. As a proxy, I summed main-loop input tokens (mostly cache reads) from the transcripts; subagents aren't included. Through Dresco: gym1 about 280–300M, full1 about 150–180M. Through badge 1: gym1 about 460M, full1 about 240–250M. Gym1 used a Sonnet main loop until 21:52, while full1 used the Haiku router throughout, so the dollar gap is wider than the token gap.

## Confounders (none caused by bootstrap)

- **Against full1:** the 2x speed cap and one-core pinning (#90/#91; gym1 ran uncapped), the battle-every-wild rule (#93, 322 `fight` calls vs gym1's 100), and crashed chunks (09:10, 09:24, 10:27 exit 1, plus two 25-second chunks at 08:34–35).
- **For full1:** the tools gym1 lacked or got late: `type_name`, `throw_ball`, `use_item`, the `switch_to` fixes, battle `advance_dialog`, `fight`/`run_away` (gym1 got these at 21:47), and the planner's stair and ice fixes. Gym1 also lost a whole chunk to a stalled Sonnet 5 session (423 actions) and had an operator rewind.
- **Exploration was not equal.** Before the badge, gym1 entered 27 maps and full1 15. Full1 never entered 12 interiors that gym1 explored: Bellin Center, Bellin houses (Heal Balls, Food Thief), the rival's house, the Frozen Heights house, Dresco Center 1F/2F and 4 Dresco houses (Zygarde #070, the Ducklett trade). Its own 09:55 plan said "enter all houses" before the gym. Much of the Dresco → badge gain comes from skipping that work, so it isn't efficiency.

## Evidence the memory was used (full1 transcripts)

- 08:04, strategist, Shadow Base exit: "Your previous run did get out: [4,10] (21,23) leads to [4,11]".
- 09:55, the route to Bellin: "Memory says Dresco has no Poké Mart … use `travel_to('Route 1')`, then `walk_to(11,48)` … Don't use `travel_to('Bellin Town')`". This is gym1's x=11 edge note. The shopping detour took about 6 min.
- Gym door: full1 reached Dresco at 10:06:58 and was inside the gym ([7,4]) at 10:07:24, using gym1's "DRESCO GYM = door (16,12)". At 10:50 it wrote "Next target is the Dresco Gym (16,12)". Gym1 took 108 min from reaching Dresco to entering the gym.
- Gym prep (09:55): "per old notes: Flabebe Lv15 Fairy, Gloom Lv16 Grass/Poison, double battle". Full1 won the gym on its first attempt.
- Not memory: the Route 2 healer heals you automatically when you come out of Icicle Cave, so healing there proves nothing.

## Evidence it hurt

- **Rival name.** At 08:04 the agent wrote "I'm naming the rival 'Hugo'". That name came from gym1's notes ("rival hugo"). Policy #88 (name him Copilot) landed at 08:07, after the prompt was built. The name entry went wrong and left the rival permanently named **"Hv"**. A learnings entry notes it cost "~40 calls for a 4-letter name".
- **Stale opponent previews.** At 08:52 the strategist said "Next comes Larvitar Lv13 … going by last run's notes" and planned the switches around that. The rival's second Pokémon depends on your starter, and this time it was Gible. Full1 whited out to it at 09:08, partly because it also walked into the trigger at low HP. At 09:38 the agent noted "Previous-run note listed Roggenrola; wrong for this run" for Hiker Nob, around the time of the 09:37 whiteout.
- **Overhead and confusion.** The first session spent its opening calls rewriting 5 memory files to mark them stale. The objectives line "Old notes … describe a PREVIOUS run" was then carried through every rewrite. At 10:50 the agent called "Hv" on the gym sign "stale from the previous run", although Hv is this run's rival.

## Verdict

**Probably helped a little; low confidence.** By the numbers, the #22 exit test passes: full1 used 0.47x the active time and 0.58x the calls to badge 1, and fewer calls at every shared milestone. I can tie only a few shortcuts directly to bootstrapped notes: the Route 1 → Bellin edge, the Bellin Mart and the no-Mart-in-Dresco fact, the gym door, and Mirskle's team. Together they plausibly saved tens of minutes, not hours. The rest of the gap comes from newer tools, gym1's rewind and Sonnet stall, and full1 skipping exploration. Stale previews cost about 40 calls and contributed to one whiteout.

## Recommendations for #22

1. **Carry over:** `map_notes.md` (layout, doors, warps, routes, tool traps such as "travel_to Bellin lands in a pocket"), generic `learnings.md` rules, service NPCs from `npcs.md` (healers, marts, nurse and clerk tiles), and gym leader teams from `opponents.md`.
2. **Strip at copy time** instead of asking the first session to edit: talked/beaten/visited flags, "WANTS ME BACK", "All doors entered", mission progress (keep each mission's id, giver and location), and names the old run chose (rival, nicknames). Drop rival teams, or tag them "depends on your starter". Keep stripping `objectives`, `team` and `items`, as today.
3. **Add a provenance marker.** Prefix each carried line with `[prev run, unverified]` and switch it to `[verified run N]` once it holds again. Tell the agent that a prev-run fact is a hint to check cheaply and never a reason to skip exploring a building. This applies the "hypothesis until verified" rule from `docs/learnings.md` to memory.
4. **Run a fair A/B before closing #22:** same harness SHA, same model and router, same speed cap, two fresh runs (with and without bootstrap) to Route 2 or badge 1, and log the harness SHA and model per chunk in `usage.jsonl`. Also record cost for rotated chunks; the cost comparison was impossible this time.
