# Continual / Self-Improving Game-Playing Harnesses (deep dive: sethkarten/continual-harness)

Notes compiled 2026-10-07. Repo cloned at HEAD commit dated 2026-05-12 ("Add deprecation note for old repo name and PokeAgent Challenge citation"). Source-code claims below come from reading the cloned files directly; links point to the GitHub paths.

## 1. What is sethkarten/continual-harness (paper, architecture, what persists, games, onboarding, results, models, cost)?

### Takeaway
Continual Harness (Karten et al., arXiv 2605.09998, May 2026, Princeton, with Chi Jin and Kiran Vodrahalli among the authors) is a reset-free harness. Every N steps, a same-model "Refiner" reads the recent trajectory and makes JSON CRUD edits to four persisted stores: system prompt, sub-agents, skills (executable Python) and memory. It runs on Pokemon Red (PyBoy) and Emerald (mGBA) only. On Emerald with Gemini 3 Pro it reaches 100% of milestones (through the 2nd gym) at a $130 median, against $215 for the minimal harness. The gain depends heavily on model capability: it is high-variance on Flash and worse than baseline on Flash-Lite.

### Cited Findings
**Paper and lineage**
- The paper is "Continual Harness: Online Adaptation for Self-Improving Foundation Agents" by Seth Karten, Joel Zhang, Tersoo Upaa, Ruirong Feng, Wenzhe Li, Chengshuai Shi, Chi Jin and Kiran Vodrahalli, arXiv 2605.09998, May 2026. Joel Zhang is the creator of Gemini Plays Pokemon (GPP). — [OpenTrain summary](https://www.opentrain.ai/papers/continual-harness-online-adaptation-for-self-improving-foundation-agents--arxiv-2605.09998/); [arXiv](https://arxiv.org/abs/2605.09998)
- The repo was previously `sethkarten/pokeagent-speedrun`, the reference framework for the PokeAgent Challenge (arXiv 2603.15563). It was renamed and generalized. The hand-engineered PokeAgent harness is kept as the `pokeagent` scaffold (H_expert). — [README](https://github.com/sethkarten/continual-harness)
- The repo also contains the GPP benchmark harness that completed Pokemon Blue, Yellow Legacy (hard mode) and Crystal. — [README](https://github.com/sethkarten/continual-harness)

**Formalism**
- The harness H = (system prompt p, sub-agents G, skills K, memory M).
- H_min is the environment interface plus a generic prompt (frames, ASCII text map, button inputs).
- H_expert adds hand-authored pathfinding, battle strategists and domain tools.
- H_CH starts from H_min. After a W-step warmup, every F steps the Refiner "reads the recent trajectory window for failure signatures and emits per-component edits Δ=(Δp, ΔG, ΔK, ΔM)". — [arXiv HTML](https://arxiv.org/html/2605.09998)

**Scaffolds and entry points (from code)**
- Scaffolds: `continualharness`, `pokeagent` (H_expert), `simple` (H_min) and `simplest`.
- `run.py` runs the in-repo Python agent against a FastAPI game server.
- `run_cli.py` exposes the same game through an MCP proxy to external CLI harnesses: Claude Code, Gemini CLI, Codex and Hermes. Each runs in its own devcontainer with a firewall init script (`.devcontainer/claude-agent/` etc.). — [README](https://github.com/sethkarten/continual-harness); repo tree
- Supported VLM backends: OpenAI, OpenRouter, Gemini, Anthropic and Vertex. The README example uses `--backend anthropic --model-name claude-sonnet-4.5`. — [README](https://github.com/sethkarten/continual-harness)

**Refiner mechanics (from `agents/utils/harness_evolver.py` and `System-Design/architecture/harness_evolver.md`)** — [harness_evolver.py](https://github.com/sethkarten/continual-harness/blob/main/agents/utils/harness_evolver.py); [harness_evolver.md](https://github.com/sethkarten/continual-harness/blob/main/System-Design/architecture/harness_evolver.md)
- Activation: requires `--scaffold continualharness --enable-prompt-optimization`.
- Schedule:
  - `MIN_WARMUP_STEPS=25`.
  - Every 25 steps up to step 200, then every 100 steps.
  - The CLI `--optimization-window-length` (e.g. 50) sets the trajectory window size, not the cadence.
- The Refiner uses the same model as the agent, through a text-only VLM call. It is also exposed to the agent as an `evolve_harness` tool.
- Four passes run in order, each wrapped in try/except:
  1. Prompt rewrite (`PromptOptimizer.optimize_prompt`).
  2. Sub-agents: JSON `create`/`update`/`retire`.
  3. Skills: JSON `add`/`update` with code.
  4. Memory: JSON `add`/`update`, using roughly the last 20 steps.
- Each generation is appended to `evolution_log.jsonl`.
- Persisted stores are `subagents.json`, `skills.json` and `memory.json` under the run cache (a `BaseStore` with `mutation_history`).
- Evolved sub-agents:
  - `max_turns` is capped at 50.
  - Instructions are truncated to 12,000 chars.
  - Tools are filtered to an allowlist: `press_buttons, complete_direct_objective, get_game_state, get_map_data, process_memory, process_skill, run_skill, run_code, process_subagent, execute_custom_subagent, process_trajectory_history, replan_objectives`.
  - No `navigate_to`, walkthrough or wiki ("The agent has NO walkthrough or wiki access — it learns entirely through gameplay").
- The skills pass includes a hard-coded "CRITICAL ANTIPATTERN" warning when `run_code` is called 3 or more times with 0 `run_skill` calls. The warning pushes the model to save disposable scripts as reusable skills.

**Skill execution (from `agents/PokeAgent.py`)** — [PokeAgent.py](https://github.com/sethkarten/continual-harness/blob/main/agents/PokeAgent.py)
- Skills are inline Python run with `exec()`. The code reads `args` and sets `result`.
- The globals dict exposes `tools['press_buttons'|'get_game_state'|'get_map_data']` plus collections, heapq, numpy, json, re, math and random.
- `run_code` is restricted to read-only `get_game_state`/`get_map_data`, with this comment: "run_code is for debugging/prototyping ONLY - no game actions allowed".
- The restricted `__builtins__` still includes `__import__`, so the sandbox is not a security boundary.

**Code-level quirk (my observation)**
- In `_evolve_skills`, the `add` branch calls `store.add(path, name, description, effectiveness, importance, source)` and never passes the `code` field the prompt asks for.
- Code only reaches the store through `update` entries, or through the agent's own `process_skill` tool.
- So Refiner-created skills may be description-only until they are updated. — [harness_evolver.py L329-460](https://github.com/sethkarten/continual-harness/blob/main/agents/utils/harness_evolver.py)

**What a learned harness looks like (shipped Red bootstrap, `PokemonRed-GBC/bootstrap_source/`)** — [bootstrap_source](https://github.com/sethkarten/continual-harness/tree/main/PokemonRed-GBC/bootstrap_source)
- Snapshot taken mid-run, at the Lt. Surge battle:
  - `EVOLVED_ORCHESTRATOR_POLICY.md` (5.5 KB).
  - `skills.json` (85 KB): 13 skills, all coordinate-navigation BFS variants (`navigate_to`, `move_to_coords`, `walk_to`, `bfs_move`, `safe_navigate`, `travel_to`, `cave_bfs`, `smart_cave_bfs`, `cave_router`, `smart_navigate`, `city_nav`, `go_to_coords`, and a hardcoded `diglett_nav`).
  - `subagents.json` (42 KB): 7 entries, namely dialogue, pokecenter, map_navigator, battle, shopping, wild-grinder and menu handlers.
  - `memory.json`: 18 entries covering items, badges and topology notes such as "Mt Moon DEFINITIVE Topology".
- The evolved prompt contains:
  - Self-discovered rules, e.g. "NO LONG MANUAL PATHS... Maximum allowed manual directions per turn is 4", "IGNORE THIS WARNING" for false blocked-movement alerts, and not over-spamming A.
  - Step-specific objectives.
  - Praise ("Outstanding Work!").

**Bootstrapping across runs**
- `--bootstrap-from run_data/<id>/end_state/game_state/bootstrap` loads memory, skills, sub-agents and the evolved prompt.
- The paper's variants map to: from-scratch, bootstrap-frozen (no refinement flag), and bootstrap-updating. — [README](https://github.com/sethkarten/continual-harness)

**Results**
- Red is tracked over 18 milestones through the Thunder Badge. Emerald is tracked over 31 milestones through the Knuckle Badge (2nd gym). — [arXiv HTML](https://arxiv.org/html/2605.09998)
- Emerald, Gemini 3 Pro — [arXiv HTML](https://arxiv.org/html/2605.09998):
  - H_CH from scratch reaches "100% of milestones at a $130 median" versus H_min "at 98% for $215, a ~40% cost reduction".
  - The bootstrap variants reach 96–100% at $110–$140.
  - H_CH is "strictly Pareto-dominant over H_min".
- Gemini 3 Flash: bootstrap-updating reaches 80% at $42 versus H_min at 77% for $30. The other variants are high-variance. — [arXiv HTML](https://arxiv.org/html/2605.09998)
- Gemini 3 Flash-Lite falls to "33–13% at comparable or higher cost". The README caveat says: "Don't expect refinement to bootstrap below that capability floor." — [arXiv HTML](https://arxiv.org/html/2605.09998); [README](https://github.com/sethkarten/continual-harness)
- On Red, H_CH "substantially reduces the button-press cost of every monitored milestone relative to H_min". Bootstrap-updating is more efficient than from-scratch at every milestone. It "recovers a majority of the gap" to H_expert. — [arXiv HTML](https://arxiv.org/html/2605.09998); [OpenTrain](https://www.opentrain.ai/papers/continual-harness-online-adaptation-for-self-improving-foundation-agents--arxiv-2605.09998/)
- Navigation skills against an oracle path:
  - The path-cost deficit falls "from a near-half-cost penalty at the start to single digits early on and stays there".
  - CH runs accumulate hundreds of skill invocations per 24-hour run.
  - H_min "never invokes a navigation skill". — [arXiv HTML](https://arxiv.org/html/2605.09998)
- Cost accounting assumes 25% cached input. Sub-agent cost sits about an order of magnitude below the orchestrator's. — [arXiv HTML](https://arxiv.org/html/2605.09998)

**Open-weights extension**
- Gemma-4 models (E2B, E4B, 26B MoE, 31B) were trained on Red. The training sequence was:
  1. SFT on teacher trajectories.
  2. Offline GRPO (G=4, with a Gemini-3-flash per-step oracle as scorer, 590 steps).
  3. Online co-learning: 256-step DAgger rollouts through CH, then PRM scoring, then Gemini-3.1-pro relabeling of low-reward windows, then a soft SFT update.
- Training setup: LoRA r=256, 8K context, H200s.
- The warm-up stages alone gave no milestone gains; gains appeared only in co-learning.
- A Qwen baseline "cannot leave the starting area in a live rollout". — [arXiv HTML](https://arxiv.org/html/2605.09998)

### Inferences
- The "self-improving" part is in-context and harness-level: prompt, JSON stores and Python skills. It never edits the harness's own Python source, the RAM readers or the tool surface. The tool allowlist is fixed.
- Evolved skills mostly reinvent the A* pathfinding that H_expert already ships. The 13 near-duplicate BFS skills suggest library bloat and duplication rather than clean abstraction.
- The ~$130 per 2-gym Emerald run with Gemini 3 Pro implies full-game costs in the low thousands of dollars. This is extrapolation, not reported.

### Gaps
- Exact F/W values used in the paper are not stated in the main text, per the fetched HTML. The code defaults are 25/25→100.
- No Claude results for the CH scaffold appear in the fetched paper text. Claude Sonnet 4.5 appears only as a supported backend and in PokeAgent baselines.
- Per-run token counts and wall-clock time for H_CH were not extracted.
- The cross-game transfer table (Red→Emerald) is only partially captured: skill and sub-agent inheritance of 99.6% and 100% on Emerald, and Red sub-agent inheritance collapsing to 6.4% ± 5.7 in bootstrap-updating.

## 2. Related work: PokeAgent Challenge, Gemini Plays Pokemon, Claude Plays Pokemon, other evolvable-harness work

### Takeaway
The field moved from human-tuned harnesses (GPP and Claude Plays Pokemon (CPP) in 2025) to harnesses where the model writes its own tools and sub-agents (GPP's `define_tool` and `define_agent` in the Crystal and Yellow Legacy runs). Fully automated refinement followed in Continual Harness (May 2026) and generic "evolvable harness" frameworks such as Hierarchical Self-Improvement (Aug 2026). The PokeAgent Challenge showed that a harness is essential: raw VLMs score about 0%, and the speedrun was won by scripted policy distillation plus RL, not a pure LLM.

### Cited Findings
**PokeAgent Challenge, NeurIPS 2025 (arXiv 2603.15563)**
- Format: two tracks, Battling and Speedrunning, with more than 100 teams. — [arXiv abs](https://arxiv.org/abs/2603.15563)
- Speedrun scope: Emerald up to defeating Roxanne. Ranked by completion % and time, with ties broken by action count. — [arXiv HTML](https://arxiv.org/html/2603.15563)
- Baseline: a multi-agent orchestrator with MCP tools (A*, buttons, knowledge retrieval), sub-agents (battle, reflection, gym puzzles, verification) and context compaction. — [arXiv HTML](https://arxiv.org/html/2603.15563)
- Baseline results — [arXiv HTML](https://arxiv.org/html/2603.15563):
  - Gemini 3 Flash was fastest, at about 2:24 mean.
  - Claude Sonnet 4.5 ranged 6:25–20:45, with the highest variance and 3–4x the cost.
  - Human reference times: 18 min (expert) and 1:22:05 (average player).
- Key findings — [arXiv HTML](https://arxiv.org/html/2603.15563):
  - "Without a harness, raw frontier VLMs achieve effectively 0% task completion."
  - "Common CLI-agent architectures fail to maintain coherence over thousands of sequential decisions."
- Winners — [arXiv HTML](https://arxiv.org/html/2603.15563):
  - Heatz won with 40:13, using Scripted Policy Distillation: LLM task decomposition, then scripted policies, then a neural-net imitation policy, then RL.
  - Second place, Hamburg PokeRunners, used pure recurrent PPO.
  - Fetched summary's units are ambiguous: it gives Gemini 3 Flash ~2:24 but the winner 40:13, so the baseline figures may be in hours. Verify against the paper.

**Gemini Plays Pokemon (Joel Zhang)**
- Blue was completed in May 2025, Yellow Legacy hard mode in August 2025 (Elite Four with no lost battle), and Crystal in November 2025. — [arXiv HTML 2605.09998](https://arxiv.org/html/2605.09998)
- In Yellow Legacy, Elite Four attempts were Lorelei 18, Bruno 20, Agatha 18 and Lance 19; Champion was beaten on attempt 4. — [arXiv HTML](https://arxiv.org/html/2605.09998)
- Over 14 checkpoints, the self-written `battle_strategist_agent` cycled between growth and simplification, ending in a rewrite into a `master_battle_agent`. — [arXiv HTML](https://arxiv.org/html/2605.09998)
- Gemini 3 Pro reached comparable early milestones with about half the turns and about 60% fewer tokens than Gemini 2.5 Pro. — [arXiv HTML](https://arxiv.org/html/2605.09998)
- In Crystal, the harness let agents define their own code tools and sub-agents. Gemini 3 Pro used `define_tool` to write `press_sequence` and get around a mixed-input restriction. — [search summary of Gemini 3 vs 2.5 Crystal piece](https://youmind.com/es-419/landing/x-viral-articles/gemini-3-pro-pokemon-benchmark) (secondary source)
- The early Blue harness extracted text from RAM because Gemini struggled to read the Game Boy screen. It also included pathfinding tools, notes and context cleanup. — [dbreunig](https://www.dbreunig.com/2025/06/17/an-agentic-case-study-playing-pokémon-with-gemini.html); [TechCrunch](https://techcrunch.com/2025/05/03/googles-gemini-has-beaten-pokemon-blue-with-a-little-help)

**Claude Plays Pokemon (David Hershey, Anthropic)**
- CPP keeps a simple, hands-off harness.
- For Opus 4.5, the Navigator gained Surf, spin-tile and teleport handling, plus gate side-entrances, and memory went back to multi-file memory that Claude manages itself. — [Julian Bradshaw / LessWrong-AF](https://www.alignmentforum.org/users/julian-bradshaw)
- CPP still had not beaten Red "more than half a year after other companies' models succeeded". The date of that statement is unclear, roughly early 2026. — [same](https://www.alignmentforum.org/users/julian-bradshaw)
- Background on how CPP was built: [Latent Space](https://www.latent.space/p/how-claude-plays-pokemon-was-made).

**Hierarchical Self-Improvement (Tailin Zhou, arXiv 2608.08466, Aug 9 2026)**
- Per-task-family harnesses are hot-swapped through a fixed injection seam and rewritten from environment feedback.
- Gains: BabyAI +39.3%, Crafter +33.0%, TextWorld +25.0%, MiniHack +15.0%; held-out scores 0.98–1.00.
- "On tasks exceeding the model's capability, harness evolution provided no improvement."
- No Pokemon. — [arXiv](https://arxiv.org/abs/2608.08466)

### Inferences
- Voyager-style skill libraries, Reflexion-style verbal memory and ADAS-style agent design all appear in CH as the skills, memory and sub-agent passes. CH's distinctive choice is being reset-free and mid-episode, rather than learning across episodes with resets.
- Two independent 2026 papers, CH and HSI, report the same capability floor: harness self-evolution amplifies strong models and does not rescue weak ones.

### Gaps
- I did not fetch the original Voyager, ADAS or Reflexion papers. The mapping above is my own characterization.
- I found no primary GPP write-up on `define_agent`/`define_tool` semantics, only secondary sources and the CH paper.
- I found no 2026 Claude-specific self-evolving Pokemon harness results.

## 3. Game-agnostic vs per-game components; could a self-learning harness discover RAM layouts or build tools for an unknown romhack such as Pokemon Unbound?

### Takeaway
CH's "minimal interface" is not game-agnostic. The ASCII map and `get_game_state` come from thousands of lines of hand-written, per-game RAM readers and decompilation-derived map data. Only the Refiner loop, stores, skill sandbox and prompts are reusable. CH has no tool for raw memory reads, so as shipped it cannot discover RAM layouts. For Unbound you would need to supply or bootstrap the state and map layer yourself.

### Cited Findings
- Game-specific code: [repo tree](https://github.com/sethkarten/continual-harness)
  - Emerald: `pokemon_env/memory_reader.py` is 5,125 lines of hard-coded addresses (e.g. `SAVE_BLOCK1_BASE = 0x02025734`, `PLAYER_BADGES = 0x02025748`), marked "DO NOT MODIFY for submissions".
  - Emerald maps come from Porymap / pokeemerald decompilation data (`utils/mapping/*`, about 7k lines).
- The Red port (`docs/pokemon_red_integration.md`) needed: [pokemon_red_integration.md](https://github.com/sethkarten/continual-harness/blob/main/docs/pokemon_red_integration.md)
  - `red_emulator.py` (827 lines, PyBoy, 48 milestones).
  - `red_memory_reader.py` (790 lines, "23 hardcoded memory addresses").
  - `red_map_reader.py` (804 lines, live NPCs from RAM plus preprocessed collision maps).
  - `map_preprocess.py` (1,087 lines), converting the pokered ASM decompilation into 224 JSON maps.
  - `map_overrides.py` (549 lines), with manual fixes for Mt. Moon, Rock Tunnel, Silph Co., etc.
  - Red-specific prompts.
  - Game selection runs through a `GAME_TYPE` env var.
- Skill and sub-agent code only sees `get_game_state`, `get_map_data` and `press_buttons`. There is no memory-peek tool. — [PokeAgent.py](https://github.com/sethkarten/continual-harness/blob/main/agents/PokeAgent.py)
- `utils/anticheat.py` (375 lines) and milestone trackers are also per-game. — repo tree
- The paper says the residual gap to H_expert "concentrates in dialogue-heavy gym interiors and multi-turn battle strategy, components Continual Harness does not yet synthesize reliably". — [arXiv HTML](https://arxiv.org/html/2605.09998)

### Inferences
- **Engine reuse**: Unbound is a FireRed (GBA) romhack, so the mGBA path (`EmeraldEmulator`) is the closer base than PyBoy. FireRed's RAM layout differs from Emerald's, though, and Unbound's custom engine expansions (from my background knowledge, not verified here: CFRU/DPE-based, expanded species, moves and items) likely move or extend party, bag and save-block structures. The Emerald reader cannot be reused as is.
- **Map layer**: no public decompilation exists for Unbound (not verified here). The Porymap/pokered-style preprocessed map pipeline therefore cannot be replicated. Collision data would have to come from runtime RAM (the map grid/metatile buffer in EWRAM) or from vision.
- **Feasibility of self-discovery**: a self-learning harness could plausibly discover RAM layouts if given a `read_memory(addr, len)` / RAM-diff / search tool, e.g. by pressing a button, diffing RAM and correlating with screen changes. This is the kind of reusable skill CH's skill pass is designed to keep. CH as shipped does not offer such a tool. Adding one, and adding it to `_ALWAYS_AVAILABLE_TOOLS`, is a small change.
- **Recommended Unbound setup**:
  - Hand-seed a minimal FireRed RAM reader: position, map bank/number, party HP, battle flag, dialog flag. Community FireRed RAM maps exist.
  - Let the model expand it via evolved skills.
  - Use CH-style periodic refinement for navigation, memory and battle sub-agents.
- **Model fit**: on capability-floor grounds, Fable 5.1 or Opus 5.5 (frontier-class) should land on the "Pro" side of the Pareto curve. That is an extrapolation, since no Claude CH numbers were found.

### Gaps
- I did not verify Unbound's engine internals (CFRU vs DPE, RAM offsets, decomp availability) against primary sources.
- I found no published work in which an LLM agent autonomously reverse-engineered a Pokemon RAM map.

## 4. Reported failure modes and cost/token usage of long runs

### Takeaway
The main failure modes are:
- Tool and schema mismatch loops lasting hundreds or thousands of turns, during which the agent stops creating tools once it has been stalled long enough.
- Unused memory.
- Abandoned inherited sub-agents in bootstrap-updating runs.
- Skill duplication.
- Drift in the prompt itself, with step-specific objectives and praise baked in.
- No gain from refinement below a capability floor.

Reported costs are about $110–$215 per 2-gym Emerald segment on Gemini 3 Pro and $30–$42 on Flash.

### Cited Findings
- GPP Power Plant loop, Aug 29 2025: 1,003 turns (about 3.5 hours).
  - The agent wrote an autopress tool, but its JSON output lacked the required button field.
  - Its reasoning claimed progress while the environment stayed static.
  - Tool generation happened mostly "within the first 50–200 turns of encountering a new bottleneck. Beyond 500 turns in a stall, the agent ceased tool creation". — [arXiv HTML](https://arxiv.org/html/2605.09998)
- In CH, "most authored entries sit unused": the memory reference rate is low. — [arXiv HTML](https://arxiv.org/html/2605.09998)
- In Red bootstrap-updating runs, agents "collapse their sub-agent budget to a handful of calls and the few calls they make cite IDs not present in the bootstrap" (6.4% ± 5.7 inheritance). The paper's conclusion: "The harness rather than the episode is the transferable unit." — [arXiv HTML](https://arxiv.org/html/2605.09998)
- Skill duplication is visible in the shipped Red bootstrap, which has 13 overlapping BFS navigation skills. — [bootstrap skills.json](https://github.com/sethkarten/continual-harness/tree/main/PokemonRed-GBC/bootstrap_source)
- The evolved prompt carries stale, step-specific objectives. It also includes a self-patch telling the agent to trust memory over "outdated prompt objectives": "Prompts update slowly!" — [EVOLVED_ORCHESTRATOR_POLICY.md](https://github.com/sethkarten/continual-harness/tree/main/PokemonRed-GBC/bootstrap_source)
- Costs:
  - Emerald, Gemini 3 Pro: H_CH $130 median; H_min $215; bootstrap variants $110–$140.
  - Gemini 3 Flash: $30–$42.
  - Assumes 25% cached input. — [arXiv HTML](https://arxiv.org/html/2605.09998)
- In the PokeAgent baselines, Claude Sonnet 4.5 had the highest variance and 3–4x the cost of other models. — [arXiv HTML 2603.15563](https://arxiv.org/html/2603.15563)
- Metrics are logged per step: tokens, cost and actions go to `.pokeagent_cache/{run_id}/cumulative_metrics.json`. — [README](https://github.com/sethkarten/continual-harness)
- GPP Blue with Gemini 2.5 Pro took 37 days. — [search summary / cryptopolitan](https://www.cryptopolitan.com/googles-gemini-just-beat-pokemon-blue/)

### Inferences
- For a long Unbound run, plan for these mitigations:
  - Dedupe and consolidate skills, e.g. a Refiner instruction to merge near-duplicate skills.
  - Strip step-specific objectives out of the evolved system prompt; keep them in an objectives store.
  - Watchdogs that force refinement or a tool rebuild when the agent stalls.
  - Schema validation on self-written tools.
- Expect a full-game run with a frontier Claude model to cost thousands of dollars without aggressive caching. This is extrapolation.

### Gaps
- No full-game cost figures exist for CH. GPP full-run token and cost totals were not found in primary sources.
