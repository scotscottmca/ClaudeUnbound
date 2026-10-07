# Building Claude a harness for Unbound

Getting Claude (Fable 5.1 or Opus 5.5) to play Pokemon Unbound on its own is a realistic project for one experienced engineer, taking **roughly 6–10 weeks to a first full attempt**. Most of the work goes into a new Unbound-specific state layer, not the agent. **No existing harness runs Unbound**, and none can be pointed at it unchanged. Clad3815's FireRed harness ties every address, menu detector and name table to vanilla FireRed symbols. Continual Harness ties its "minimal" interface to thousands of lines of per-game Emerald and Red readers. Three facts make the port tractable. First, Unbound is built on Skeli's open-source CFRU engine, which **keeps most vanilla FireRed 1.0 RAM addresses** and publishes them in a linker map. Second, a maintained Unbound save editor (PUSE) has already checked box, party and bag layouts against Unbound 2.1.1.1 running in mGBA. Third, Anthropic reports that **Claude Fable 5 beat FireRed with a minimal, vision-only harness**, so the model needs much less scaffolding than 2025-era agents did. The recommended build is a thin mGBA bridge with a small, verified CFRU RAM reader, a deterministic pathfinder over the live collision map, Claude driving through MCP tools with a self-curated memory folder, and Continual-Harness-style periodic refinement added later. The hard parts are Unbound-specific: no decomp or map data, unknown flag and variable meanings, a heavily modified battle engine, and a story roughly 2–3x FireRed's length that keeps revisiting multi-part dungeons. The main open number is cost. Extrapolating from published runs puts a full playthrough at **thousands of dollars**, and no Claude-on-Unbound baseline exists to narrow it.

## Two reference harnesses, two different lessons

The two open-source harnesses most worth studying solve different problems. Clad3815's `gpt-play-pokemon-firered` is the best example of a FireRed state layer. Continual Harness is the best example of a learning loop. Neither gives you both for Unbound.

**Clad3815/gpt-play-pokemon-firered** has four layers: mGBA running a Lua socket server, a **~20k-line Python FastAPI bridge** that reads RAM, a ~6k-line Node.js OpenAI agent loop, and a web dashboard ([GitHub](https://github.com/Clad3815/gpt-play-pokemon-firered)). The Lua side does more than send keys. Before each step it checks the overworld callback, field-control locks, the in-battle bit and the player-avatar state, and after the step it confirms the player moved. The model sees three raw screenshots plus an SVG tile-grid overlay, an `<extracted_ram_data>` block it is told to treat as authoritative, a fog-of-war minimap that marks unexplored tiles with "❓", and its own memory, objectives, summaries and self-critiques. It has **one tool, `execute_action`**, which takes key presses (including an `a_until_end_of_dialog` macro), map markers, memory writes, objective updates, `path_to_location` and console restart. Pathfinding is the odd part. A separate GPT call runs inside an OpenAI code-interpreter container and maintains its own Python pathfinding script from call to call. A critic pass runs every 55 steps and a summary every 120 steps. The system prompt is 1,300 lines ([GitHub](https://github.com/Clad3815/gpt-play-pokemon-firered)). The design leans heavily on the vanilla game. Every address resolves from the pret `pokefirered.sym` file, and a missing symbol silently returns 0 unless strict mode is on. UI state comes from matching `gMain.callback2` and task function pointers against vanilla symbols. Species, move and item names come from static vanilla-ID JSON. Progress milestones are vanilla event flags. The license is **CC BY-NC 4.0**, so its code cannot be used commercially. Clad3815's earlier GPT streams show the payoff of this kind of scaffolding: GPT-5 finished Red in 6,470 steps against 18,184 for o3, and the gains came from fewer hallucinations and better spatial reasoning ([TechRadar](https://www.techradar.com/ai-platforms-assistants/chatgpt/gpt-5-just-completed-pokemon-red-in-a-new-world-record-time-claude-gemini-and-chatgpt-o3-arent-even-close)). No results for the FireRed run itself have been published.

**sethkarten/continual-harness** (Karten et al., arXiv 2605.09998, May 2026) is the renamed and generalized PokeAgent speedrun framework. It models a harness as four persisted stores: system prompt, sub-agents, executable Python skills, and memory ([arXiv](https://arxiv.org/html/2605.09998)). After a 25-step warmup, a "Refiner" that uses the same model as the agent reads the recent trajectory and makes JSON create/update/retire edits to each store. It does this every 25 steps up to step 200, then every 100 steps ([harness_evolver.py](https://github.com/sethkarten/continual-harness/blob/main/agents/utils/harness_evolver.py)). Learned harnesses carry over between runs through `--bootstrap-from`. On Emerald through the second gym with Gemini 3 Pro, the self-refining harness reached **100% of milestones at a $130 median, against 98% at $215** for the minimal harness. On Red it recovered most of the gap to the hand-engineered expert harness ([arXiv](https://arxiv.org/html/2605.09998)). The gain depends on model strength. It was high-variance on Gemini 3 Flash and worse than baseline on Flash-Lite, and an independent August 2026 paper on evolvable harnesses found that harness evolution did not help on tasks beyond the model's capability ([arXiv 2608.08466](https://arxiv.org/abs/2608.08466)). Two features matter most for this project. Continual Harness already supports an Anthropic backend, and `run_cli.py` exposes the game through an **MCP proxy to external CLI agents, Claude Code included**, each in a firewalled devcontainer ([README](https://github.com/sethkarten/continual-harness)).

What Continual Harness does not provide matters just as much. Its "minimal" interface is not game-agnostic. The ASCII map and `get_game_state` sit on a **5,125-line hard-coded Emerald memory reader** and about 7k lines of decomp-derived map tooling. The Red port took around 4,000 lines: an emulator wrapper, a 790-line memory reader with 23 addresses, a map reader, a map preprocessor that converted the pokered decomp into 224 JSON maps, and 549 lines of manual map fixes ([pokemon_red_integration.md](https://github.com/sethkarten/continual-harness/blob/main/docs/pokemon_red_integration.md)). The Refiner can change prompts, skills and memory. It cannot change the RAM readers or the tool surface, and there is **no raw memory-read tool**, so Continual Harness as shipped cannot discover an unknown game's RAM layout ([PokeAgent.py](https://github.com/sethkarten/continual-harness/blob/main/agents/PokeAgent.py)). Its long-run failure modes are well documented and Unbound will hit them too:

- Skill duplication. The shipped Red bootstrap holds 13 near-identical BFS navigation skills.
- Stale, step-specific objectives baked into the evolved prompt.
- Authored memory that mostly goes unused.
- A Gemini tool-schema loop that lasted 1,003 turns, during which the agent stopped writing new tools after about 500 turns of stalling ([arXiv](https://arxiv.org/html/2605.09998)).

A code-level quirk is also worth noting. The Refiner's skill `add` path never stores the `code` field, so newly created skills hold only a description until a later update adds code ([harness_evolver.py](https://github.com/sethkarten/continual-harness/blob/main/agents/utils/harness_evolver.py)).

The broader lesson from 2025–26 runs is that scaffolding needs shrink as models improve. Anthropic's Claude Plays Pokemon added navigator features (Surf, spin tiles, gate side-entrances) as models changed. By April 2026, Anthropic was reporting that Opus 4.6 kept a tidy 10-file memory folder and had 3 badges at the same step count where Sonnet 3.5 had 31 duplicated files and was stuck in the second town ([Claude blog](https://claude.com/blog/harnessing-claudes-intelligence)). In June 2026, Fable 5 beat FireRed with no maps, navigation aids or extra state ([Shacknews](https://www.shacknews.com/article/149574/claude-ai-pokemon-firered-fable-5)). That result is the strongest argument for starting thin, with one caveat. FireRed is heavily covered in pretraining, and Unbound's Borrius region is not.

## CFRU keeps the RAM map but rewrites the data

Unbound is closed source, ships only as a patch for a clean US FireRed 1.0 ROM, and has had no release since **2.1.1.1 (December 2022)** ([GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA)). It runs on CFRU, an injection framework. CFRU compiles new C and assembly into free ROM space (default 0x08900000) and hooks vanilla routines rather than relocating vanilla globals. Its `BPRE.ld` linker script is a ready-made vanilla FireRed 1.0 symbol map ([CFRU](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/BPRE.ld)). Most of the RAM state a harness needs is at addresses already published there and in CFRU's `ram_locs.h`. The following are **direct reuses**:

- `gMain` 0x030030F0
- the save-block pointers at 0x03005008 and 0x0300500C
- `gMapHeader` 0x02036DFC
- the object events at 0x02036E38
- `gPlayerAvatar` 0x02037078
- `gPlayerParty` 0x02024284
- `gBattleMons` 0x02023BE4
- `gBattleTypeFlags` 0x02022B4C
- `sTextPrinters` 0x02020034
- `gStringVar4` 0x02021D18
- `gDisplayedStringBattle` 0x0202298C

([ram_locs.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/new/ram_locs.h)). Text uses the standard Gen 3 charmap with no custom encoding ([CFRU charmap.tbl](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/charmap.tbl)). Collision and metatile behavior can be read from the live map layout through `gMapHeader`, the same RAM route Clad3815's `world/` module uses. Unbound's new maps are therefore readable without any decomp.

The breaks are specific and fixable:

| Area | Vanilla FireRed assumption | Unbound / CFRU reality | Fix |
|---|---|---|---|
| Party data | XOR-encrypted, substructs shuffled by PID % 24 | **Encryption NOPed out**; fixed order, species at struct offset 0x20 ([CFRU bytereplacement](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/bytereplacement); [atendev reader](https://github.com/atendev/pokemon-memory-reader)) | Delete the decryption; use PUSE's party offsets |
| PC boxes | Vanilla box format in one storage region | 58-byte compressed records across four RAM regions, verified on 2.1.1.1 ([PUSE](https://github.com/Zannael/PUSE/blob/master/romre/CFRU_IMPLEMENTATION_PLAN.md)) | Port PUSE's `pc.py` layout |
| Species/moves/abilities | Fixed vanilla-size tables at vanilla ROM addresses | IDs up to 1293 with gaps, 923 moves, 293 abilities, all repointed ([PUSE DISCOVERIES](https://github.com/Zannael/PUSE/blob/master/romre/DISCOVERIES.md)) | Use PUSE's anchor-scan extractors to build name tables from the ROM |
| Bag | 3 pockets, vanilla save offsets | Main pocket at section 13 + 0xAD8, 450 slots, plain u16 ID + count ([PKHeX.Everywhere PR #520](https://github.com/arleypadua/PKHeX.Everywhere/pull/520)) | Find the RAM address by diffing; Radical Red's 0x0203BB20 is a candidate |
| Battle state | `gBattleMons` only | Extra state behind the `gNewBS` pointer at 0x0203E038 (terrain, Mega, Z, Dynamax) ([CFRU battle.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/include/battle.h)) | Read the `gBattleMons` core first; check the `gNewBS` layout against Unbound later |
| Flags/vars | Vanilla story flags | CFRU adds flags 0x900+ and vars 0x5000+; Unbound's story flags are undocumented ([CFRU config.h](https://github.com/Skeli789/Complete-Fire-Red-Upgrade/blob/master/src/config.h)) | Discover by diffing; track progress by badges and map visits |
| Menus | Detected by vanilla callback pointers | Reworked start menu, bag, Pokedex/DexNav, summary, missions, all in CFRU free space | Coarse mode detection (overworld/battle/dialog/other) plus vision |
| Save | Signature 0x08012025 (CFRU default) | Signature 0x01121999 ([PUSE sections.py](https://github.com/Zannael/PUSE/blob/master/backend/core/sections.py)) | Only matters for offline save parsing |

Treat the ability table with caution. Public CFRU stores abilities as `u8`, yet Unbound has 293 of them, so Unbound's private engine fork has diverged from the public source in at least this one place. **Every address taken from CFRU source must be confirmed on the actual ROM** before the harness relies on it. Turning strict mode on, so a missing symbol fails loudly instead of returning 0, should be the first change made to any borrowed code. The ready-made tools for this verification are PUSE's headless mGBA C probe (frame stepping, key input, `busRead8`, savedata cloning) and its ROM extractors ([PUSE tools](https://github.com/Zannael/PUSE/tree/master/backend/tools)). PUSE is MIT-licensed and still maintained.

## Unbound is a harder game than FireRed for an agent

The engine is not the only difficulty. The game itself makes an agent's job harder. The community walkthrough has **39 main-story parts plus a postgame part**, against roughly 8–10 natural segments in FireRed ([unboundwiki](https://unboundwiki.com/walkthrough/)). The route keeps doubling back: Thundercap Mountain appears three times and Cinder Volcano twice. That rewards persistent map memory and penalizes agents that rely on walkthrough knowledge from pretraining. Unbound also carries more systems an agent has to learn: an 84-entry mission log (only one mission is mandatory), DexNav, raids, day/night tied to the real-time clock, Mega Evolution, Z-Moves, Dynamax, and an options menu that changes how the game behaves ([GameBrew](https://www.gamebrew.org/wiki/Pokemon_Unbound_GBA); [unboundwiki Missions](https://unboundwiki.com/missions/)).

Several settings work in an agent's favor, and the harness should set them before the first step:

- **Vanilla difficulty.** Harder modes must be chosen at the start and add stronger AI and item restrictions. Level caps are also lower on Vanilla: 22 after badge 1 and 66 at the end, against 26 and 75 on harder modes ([unboundwiki Game Settings](https://unboundwiki.com/game-mechanics/game-settings/); [pokemoncoders](https://www.pokemoncoders.com/level-caps-in-pokemon-unbound/)).
- **Normal puzzle difficulty.** Several puzzles get much harder on Challenging ([unboundwiki Challenging Puzzles](https://unboundwiki.com/misc-info/challenging-puzzles/)). These include the Cube Space teleporter maze, the multi-floor switch puzzle in Dehara Gym, the Distortion World boulder pushes and the Hoopa sliding-tile puzzle.
- **Cutscene skip.** Unbound is very dialogue-heavy, so every skipped text box is one less model call.
- **Quick HM.** Unbound's HM rules are already relaxed: a party Pokemon that can learn an HM can use it without knowing it, though HMs such as Rock Climb still gate progress ([unboundwiki Part 29](https://unboundwiki.com/walkthrough/part-29/)).

The level caps cut both ways. They rule out the cheap LLM-agent tactic of out-leveling every boss, so battles need real type and damage reasoning.

Some specific sections are predictable sinks:

- **Ice-sliding caves.** The Icicle Cave north route is a 21-move solution.
- **Boulder-into-hole puzzles.**
- **The Antisis Gym ring challenge.** Flying, Psychic and Fairy moves are banned there, which tests whether the agent reads and follows rules ([unboundwiki Part 29](https://unboundwiki.com/walkthrough/part-29/)).
- **Long dungeons** such as Shadow Base, Antisis Sewers, Crystal Peak and Victory Road.

All four classes of failure seen in earlier agents get worse here: navigation errors, loops, menu misreads and context loss over thousands of steps ([LessWrong](https://www.lesswrong.com/posts/7mqp8uRnnPdbBzJZE/is-gemini-now-better-than-claude-at-pokemon)). Unbound does have one asset FireRed-era harnesses never used. The community wiki is a structured corpus of the walkthrough, trainer teams, puzzle solutions and item locations ([unboundwiki](https://unboundwiki.com/)), and RetroAchievements sets give a ready-made milestone list ([RetroAchievements](https://retroachievements.org/game/17530/comments)). Whether the agent may read the wiki is a design choice to make early. Continual Harness forbids walkthroughs. A practical "beat the game" goal makes the wiki fair game, at least for puzzle solutions.

On the emulator side, use mGBA 0.10+ with the save type forced to Flash 128K and RTC enabled. ROM hacks sometimes miss auto-detection, and Unbound's daily features need the clock ([mGBA forums](https://forums.mgba.io/printthread.php?tid=435)). For reproducible runs, pin the RTC to a fixed or offset time.

## Recommended architecture: thin state, deterministic tools, learned policy

The recommendation follows from the evidence above. A strong model gains more from a **small, correct state layer** than from a large, fragile one, and every line of vanilla-specific bridge code is a liability on a private-engine fork. Build a new Unbound bridge sized like the Red port's reader (hundreds of lines, not twenty thousand). Borrow design patterns from Clad3815, and borrow the agent plumbing and learning loop from Continual Harness.

**Emulator layer.** Use mGBA with a Lua socket script modeled on Clad3815's. Its endpoints should cover reading memory ranges, taking a screenshot, sending verified key sequences, and saving and loading savestates, with automatic savestate backups every few minutes. An alternative is the mGBA Python bindings that Continual Harness already uses for Emerald. Choose whichever stack you prefer. The Lua route gives the in-emulator step verification "for free", and the Python route sits closer to the Continual Harness code. Write the code fresh rather than copying it if commercial use is ever possible, because of the NC license.

**State layer.** This is the Unbound-specific core, an estimated 800–1,500 lines. It returns a compact JSON block covering:

- map bank, map number and name
- player x/y and facing
- a mode flag (overworld, battle, dialog or other menu), derived from `gMain` callbacks, the battle bit and text-printer activity
- the party, read unencrypted: species, level, HP, status, moves, PP, item
- in battle, both active battlers' `gBattleMons` entries
- the current dialog text from `sTextPrinters`/`gStringVar4`
- badge count and money

It also builds a collision grid of the viewport from the live map layout's metatile behaviors, and a warp/NPC list from the object events. The name tables come from PUSE-style ROM extraction. Bag, flags, `gNewBS` and the mission log are left out of the first version. Add each one only when a logged failure shows the model needed it.

**Tool surface,** exposed as MCP tools so Claude Code or the Agent SDK can drive the game directly. The Continual Harness `run_cli.py` path shows the pattern. The tools are:

- `press_buttons` (short sequences, with a per-press before/after trace)
- `advance_dialog` (the `a_until_end_of_dialog` macro)
- `get_state`
- `get_screenshot`
- `navigate_to(x, y)`, a **deterministic A* over the collision grid** plus a fog-of-war explored-tiles store, rather than Clad3815's code-interpreter sub-model
- `save_state` / `load_state` for recovery
- `read_memory(addr, len)` for debugging and discovery, which Continual Harness lacks and which lets the model or a developer find bag, flag and mission RAM by diffing

**Agent layer.** Claude runs one action per turn on a screenshot plus the state JSON. It keeps a self-curated memory directory (objectives, learnings, map notes, boss dossiers), the pattern Anthropic found newer Claude models handle well. Context compaction should be triggered by token count. A critic pass every ~50 steps catches stalls. A watchdog forces a reflection or a reload when position and state stop changing for N steps.

**Learning layer (phase 4, optional).** Port Continual Harness's Refiner, which is game-agnostic, to maintain skills, sub-agents and memory. Add two fixes the Red bootstrap shows are needed:

- a merge/dedupe instruction for skills
- a rule that keeps step-specific objectives out of the system prompt

Fix the skill-`add` code bug when porting.

| Component | Reuse | Adapt | Rebuild |
|---|---|---|---|
| mGBA Lua socket loop, step verification, savestate backups | Clad3815 pattern | Strip FireRed callback checks to CFRU-verified ones | — |
| Charmap and text decoding | Clad3815 `text/`, CFRU charmap | — | — |
| Map/collision from live RAM layout | Clad3815 `world/` approach | Verify metatile behavior IDs on Unbound | — |
| Fog-of-war minimap, markers, anti-loop prompt rules | Clad3815 design | — | — |
| Party decoding | — | — | New: unencrypted CFRU layout (PUSE offsets) |
| Species/move/ability/item names | PUSE extractors | — | Tables generated from the ROM |
| Menu/UI detection | — | — | Coarse mode flag plus vision |
| Battle state | `gBattleMons` addresses | CFRU `BattlePokemon` offsets | `gNewBS` once verified |
| Progress milestones | — | RetroAchievements list, badges | Map-visit and flag milestones via diffing |
| Pathfinding | — | — | Deterministic A* (replaces the code-interpreter sub-model) |
| Agent loop, MCP proxy, metrics, devcontainer | Continual Harness `run_cli.py`, Claude backend | Point at the Unbound game server | — |
| Self-refinement (prompt/skills/sub-agents/memory) | Continual Harness Refiner | Dedupe and objective hygiene; fix the skill-`add` bug | — |

## Phased build plan with rough effort

The phase durations below are estimates for one engineer who knows Python and has some emulator experience. No source in the research gives build-effort figures, so treat them as planning numbers, not measurements.

| Phase | Weeks | Deliverable | Exit test | Issues |
|---|---|---|---|---|
| 0. Ground truth | ~1 | Patched Unbound 2.1.1.1 ROM (checked against PUSE's SHA-256), mGBA with Flash 128K and pinned RTC, a RAM probe script, verification of each `BPRE.ld` address against live values | Party, position, map ID and dialog text read correctly across 10 hand-played scenes | [Milestone](https://github.com/scotscottmca/ClaudeUnbound/milestone/1): [#1](https://github.com/scotscottmca/ClaudeUnbound/issues/1), [#2](https://github.com/scotscottmca/ClaudeUnbound/issues/2), [#3](https://github.com/scotscottmca/ClaudeUnbound/issues/3), [#4](https://github.com/scotscottmca/ClaudeUnbound/issues/4) |
| 1. Thin bridge | 1–2 | Socket bridge, state JSON, verified key presses, savestates, ROM-extracted name tables, collision grid, `read_memory` | Scripted bot walks from Bellin Town to Route 2 using only bridge output | [Milestone](https://github.com/scotscottmca/ClaudeUnbound/milestone/2): [#5](https://github.com/scotscottmca/ClaudeUnbound/issues/5), [#6](https://github.com/scotscottmca/ClaudeUnbound/issues/6), [#7](https://github.com/scotscottmca/ClaudeUnbound/issues/7), [#8](https://github.com/scotscottmca/ClaudeUnbound/issues/8), [#9](https://github.com/scotscottmca/ClaudeUnbound/issues/9) |
| 2. Vision-first agent | 1–2 | MCP tools, Claude agent loop, memory folder, compaction, critic, stall watchdog, cost logging, game options pre-set (Vanilla, normal puzzles, cutscene skip) | Claude reaches the first gym (Dresco Town) without human intervention | [Milestone](https://github.com/scotscottmca/ClaudeUnbound/milestone/3): [#10](https://github.com/scotscottmca/ClaudeUnbound/issues/10), [#11](https://github.com/scotscottmca/ClaudeUnbound/issues/11), [#12](https://github.com/scotscottmca/ClaudeUnbound/issues/12), [#13](https://github.com/scotscottmca/ClaudeUnbound/issues/13), [#14](https://github.com/scotscottmca/ClaudeUnbound/issues/14) |
| 3. Unbound hardening | 2–3 | A* navigator plus fog of war, battle-state block (`gBattleMons` and later `gNewBS`), map-name table, milestone tracker (badges, RetroAchievements, map visits), puzzle-knowledge policy | Badges 1–3 reached; stall rate and per-milestone cost logged | [Milestone](https://github.com/scotscottmca/ClaudeUnbound/milestone/4): [#15](https://github.com/scotscottmca/ClaudeUnbound/issues/15), [#16](https://github.com/scotscottmca/ClaudeUnbound/issues/16), [#17](https://github.com/scotscottmca/ClaudeUnbound/issues/17), [#18](https://github.com/scotscottmca/ClaudeUnbound/issues/18), [#19](https://github.com/scotscottmca/ClaudeUnbound/issues/19), [#20](https://github.com/scotscottmca/ClaudeUnbound/issues/20) |
| 4. Self-refinement | 1–2 | Continual Harness Refiner port with dedupe and objective hygiene, bootstrap save/load across runs | A bootstrapped second run beats the first on steps per milestone | [Milestone](https://github.com/scotscottmca/ClaudeUnbound/milestone/5): [#21](https://github.com/scotscottmca/ClaudeUnbound/issues/21), [#22](https://github.com/scotscottmca/ClaudeUnbound/issues/22) |
| 5. Full run operations | ongoing | Long-run supervision, savestate rollback policy, budget alarms | Champion defeated | [Milestone](https://github.com/scotscottmca/ClaudeUnbound/milestone/6): [#23](https://github.com/scotscottmca/ClaudeUnbound/issues/23) |

The order matters. Phase 0 is cheap and catches the one failure that would poison everything else: a silently wrong address on Unbound's private engine. Phase 2 comes before Phase 3 on purpose. Anthropic's FireRed result suggests Fable-class models may need less help than expected, so measure where the model actually fails before building navigators and battle readers. Adding features only in response to observed failures is also how Claude Plays Pokemon evolved.

**Cost.** No published figure exists for Claude on Unbound. These are the anchors:

- Continual Harness spent $110–$215 per two-gym Emerald segment with Gemini 3 Pro, assuming 25% cached input ([arXiv](https://arxiv.org/html/2605.09998)).
- PokeAgent measured Claude Sonnet 4.5 at 3–4x the cost of other baseline models ([arXiv 2603.15563](https://arxiv.org/html/2603.15563)).
- GPT-5 needed about 6,500 steps for Red.

Unbound is 2–3x FireRed's length, has harder battles and new maps, so assume **15,000–40,000 agent steps** for a first full run (inference). The per-run cost is then approximately steps × (cached-context tokens × cache-read price + fresh tokens × input price + ~1–3k output tokens × output price), plus 5–10% for critic and summary passes. With a 30–60k-token context that is mostly cache hits, that lands in the low-to-mid thousands of dollars at current frontier prices. Repeated runs to tune the harness would multiply that. Keeping the prompt prefix stable for caching, sending one screenshot rather than Clad3815's three, and using deterministic tools instead of model sub-calls for navigation are the three biggest cost levers.

**Risks, in order of severity:**

1. **Private-engine divergence.** Unbound's engine is not public CFRU, and the ability-count mismatch proves they differ. Mitigation: Phase 0 verification, strict symbol mode, and `read_memory` diffing.
2. **Long-horizon drift and loops** across a 39-part story with repeated dungeon revisits. Mitigation: map memory, the stall watchdog, savestate rollback, and the critic.
3. **Battle difficulty.** Level caps block overleveling, and Mega, Z and Dynamax add state the model cannot see on screen. Mitigation: a battle-state block and optional trainer-team knowledge from the wiki.
4. **Cost overrun.** Mitigation: budget alarms and per-milestone cost tracking from day one.
5. **Puzzle sinks.** Mitigation: normal puzzle difficulty plus a policy decision on wiki access.
6. **Licensing.** Mitigation: treat Clad3815 as reference only for anything commercial.

Capability-floor risk is low. Both 2026 self-improvement papers find that refinement amplifies strong models, and Fable 5.1 and Opus 5.5 sit well above the Flash-Lite floor. No Claude numbers on Continual Harness exist yet, though.

## Conclusion

The research changes where the effort goes. In 2025, Pokemon harness work meant giving the model more: denser state, LLM pathfinders, 1,300-line prompts. For a Fable-class model on Unbound, most of the engineering is **making a small amount of state trustworthy** on a closed-source engine, because a wrong address does more damage than a missing one. The agent side is mostly solved and reusable. The CFRU linker map and PUSE's verified layouts turn what looked like a reverse-engineering project into a few weeks of verification.

The most valuable output may not be a finished playthrough. A harness built this way, with a thin verified reader, `read_memory` exposed to the model, and Continual Harness-style refinement on top, would be the first real test of whether a frontier model can finish a game it has effectively never seen. It would also test whether that model can extend its own observation layer by discovering RAM through diffing, which no published Pokemon agent has done. Set up the run with logging from the start: every step's tokens, cost and milestone. The per-milestone cost curve should be treated as a key result alongside the credits roll.
