# LLM Harnesses for Pokemon FireRed / Gen 3 GBA (research as of 2026-10-07)

Method note: Clad3815/gpt-play-pokemon-firered was cloned (shallow, HEAD commit 2026-02-15 "Fix readme") and its source was read directly. Every "[repo: path]" citation below points to https://github.com/Clad3815/gpt-play-pokemon-firered at that commit. Other harnesses come from web sources, with dates given.

## Q1. Clad3815/gpt-play-pokemon-firered: architecture, emulator, RAM reading, observations, tools, pathfinding, memory, models, cost/results

### Takeaway
It is a 4-layer harness: mGBA + Lua socket server, a Python FastAPI "bridge" (~20k LOC) that reads RAM, a Node.js OpenAI agent loop, and a web dashboard. All RAM and ROM access goes through symbol names looked up in the pret/pokefirered decomp `.sym` file, so it is tied to the vanilla FireRed USA v1.0 build (MD5 e26ee0d44e809351c8ce2d73c7400cdd). The model calls a single tool, `execute_action`. Its actions are key presses (including a macro, `a_until_end_of_dialog`), pathfinding, minimap markers, memory, objectives and console restart. Pathfinding is unusual: a separate GPT call runs in an OpenAI code-interpreter container and maintains its own Python pathfinding code from one call to the next.

### Cited Findings
**Stack and layers**
- Layers: mGBA + Lua script (socket bridge) → `firered_mgba_bridge.py` (FastAPI, reads memory, sends inputs) → `server/index.js` (Node.js AI loop) → `frontend/` (dashboard: logs, minimap, inventory, team, objectives). The bridge endpoints are `/requestData`, `/minimapSnapshot`, `/sendCommands` and `/restartConsole`. — [repo: README.md](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Only "Pokemon - FireRed Version (USA)" is supported (MD5 `e26ee0d44e809351c8ce2d73c7400cdd`). The license is CC BY-NC 4.0, so commercial use is not allowed. — [repo: README.md, LICENSE](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Languages: Python (bridge, ~20k LOC; `firered_bridge/ui/menus.py` alone is 5,510 lines), JS (agent ~6k LOC), Lua (952 lines). Python deps are only fastapi, uvicorn, pydantic, python-dotenv and requests. — [repo: requirements.txt; wc of sources](https://github.com/Clad3815/gpt-play-pokemon-firered)
- The Lua side (`mgba/scripts/FireRedBridgeSocketServer.lua`) uses the mGBA scripting API: `emu:read8/16/32` and `emu:readRange` for memory, `emu:screenshot(file)`, `emu:saveStateFile`, `emu:reset`, `emu:addKeys/clearKeys`, and frame-scheduled key events keyed off `emu:currentFrame()`. It listens on port 8888 (8888–8896 are scanned). An HTTP transport is the fallback. — [repo: mgba/scripts/FireRedBridgeSocketServer.lua, .env.example](https://github.com/Clad3815/gpt-play-pokemon-firered)
- The Lua script also implements movement control in-emulator. Before stepping it checks `gMain.callback2` (overworld), `sLockFieldControls`, the in-battle bit, and `gPlayerAvatar` prevent-step/running state, and it reads object-event x/y/facing so each step can be verified (`canUseOverworldControl`, `readPlayerAvatarSnapshot`). — [repo: Lua script lines ~431–500](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Savestates are backed up automatically every 300 s, and the last 50 are kept (`FIRERED_SAVESTATE_BACKUP_*`). — [repo: .env.example](https://github.com/Clad3815/gpt-play-pokemon-firered)

**RAM/ROM reading**
- The repo ships `pokefirered.sym` (50,807 lines, the symbol map from pret's decomp build). The pret/pokefirered git submodule is optional. `firered_bridge/memory/symbols.py` parses the sym file, and `sym_addr(name, size=, near=, fallback=)` resolves addresses. A missing symbol returns 0 silently unless `FIRERED_BRIDGE_STRICT_SYMBOLS=1`. — [repo: firered_bridge/memory/symbols.py, .gitmodules](https://github.com/Clad3815/gpt-play-pokemon-firered)
- `constants/addresses.py` (909 lines) resolves dozens of symbols. Examples:
  - Data: `gBagPockets`, `gPlayerAvatar`, `gMain`+0x439 (inBattle bit 0x02), `gSaveBlock1Ptr`/`gSaveBlock2Ptr`, `gPlayerParty`, `gPlayerPartyCount`, `gMapHeader`, `gObjectEvents`
  - Text: `gStringVar1-4`, `sTextPrinters` (struct size 0x24), `gDisplayedStringBattle`
  - Battle: `gBattleMons` (0x58 per battler), `gBattleTypeFlags`, `gActionSelectionCursor`, `gMoveSelectionCursor`, `gBattlerControllerFuncs`
  - ROM tables: `gSpeciesInfo`, `gBattleMoves`, `gMoveDescriptionPointers`, `gItems`
  - Hard-coded struct offsets, e.g. `SB1_OBJECT_EVENT_TEMPLATES_OFFSET = 0x08E0`, `SB1_GAME_STATS_OFFSET = 0x1200`, `NUM_DEX_FLAG_BYTES = 0x34`, `FLAG_HIDE_SS_ANNE = 0x087`
  — [repo: firered_bridge/constants/addresses.py](https://github.com/Clad3815/gpt-play-pokemon-firered)
- UI state is inferred from function pointers. The bridge compares `gMain.callback2` and the active task funcs against symbol addresses such as `CB2_Overworld`, `CB2_BagMenuRun`, `Task_StartMenuHandleInput`, `HandleInputChooseAction`, `HandleInputChooseMove`, `CB2_RegionMap` (fly map), `CB2_NamingScreen`, `Task_OakSpeech_*`, the TM Case tasks, the Pokedex tasks and the Quest Log. It does not use OCR or vision for menu detection. — [repo: constants/addresses.py; ui/*.py](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Party decoding is the standard Gen 3 scheme: 100-byte party structs, XOR decryption with PID^OTID, substructure order `SUBSTRUCTURE_ORDER[pid % 24]`, and EV/IV extraction. Types and abilities are read from the ROM `gSpeciesInfo` table at `species_id * SPECIES_INFO_SIZE + offset`. — [repo: firered_bridge/player/party.py](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Name tables are static JSON. `game_data_firered/mappings.json` holds MAP_NAME_TABLE (group/num → name), EVENT_OBJECT_NAME, ABILITY_NAME, ITEM_NAME, MOVE_NAME and SPECIES_NAME, all with vanilla ids. `metatile_behaviors.json` maps behavior ids to names. — [repo: game_data_firered/](https://github.com/Clad3815/gpt-play-pokemon-firered)
- The map comes from the live RAM map layout, not from ROM map files. `world/map_read.py` reads the main/backup map layout tiles and the metatile attributes from the tileset pointers (behavior = attr & 0x1FF). `world/collision.py`, `viewport.py` and `events.py` build collision, the viewport and NPC/warp lists. — [repo: firered_bridge/world/](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Text uses the Gen 3 charmap: 0xFF terminator, with 0xFC/0xFD control codes handled. Dialog is read from `sTextPrinters` and the gStringVar buffers. — [repo: firered_bridge/text/encoding.py, text_printer.py](https://github.com/Clad3815/gpt-play-pokemon-firered)

**What the model sees**
- Each turn's vision payload is "raw screenshot x3 + optional overlay in overworld". The overlay is an SVG grid drawn over the 15x10 metatile GBA screen, with per-tile codes and coordinates rendered by `sharp`. In caves and gyms the grid shrinks to the reduced-visibility area. — [repo: server/src/core/gameLoop.js L259; services/screenshotService.js](https://github.com/Clad3815/gpt-play-pokemon-firered)
- The text state is `<extracted_ram_data>`: map name, coordinates, facing, visible tiles, party/HP/status/moves/PP, money, items and badges. The prompt says to treat RAM as "authoritative". There is also a `<memory>` block, objectives, the last summary and the last self-criticism, plus countdowns to the next criticism and the next summary. — [repo: server/prompts/game.txt §3; gameLoop.js L228–251](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Fog-of-war minimap: one JSON grid per map is persisted, with `null` for undiscovered tiles. Unexplored tiles render as "❓" in the minimap text. The prompt has an anti-loop protocol ("Explore Before Backtracking", "Why ❓ Tiles Matter") and an "Exploration ROI" rule. — [repo: firered_bridge/fog_of_war.py; state/builders.py L404; game.txt §9–10](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Context retention is set by config: the last 10 user messages keep images, the last 4 keep detailed data, the last 1 keeps the minimap, memory and Pokedex, and the last 5 keep the view-map. Tool results are kept in full for 6 turns and partially for 20. — [repo: server/src/config.js history block](https://github.com/Clad3815/gpt-play-pokemon-firered)

**Tools / action space**
- There is exactly one function tool, `execute_action` (strict JSON schema). Its arguments are `step_details`, `actions[]`, `chat_message` and `avatar_emotion` (stream persona). The action union is:
  - `key_press`: up/down/left/right/a/b/start/select, `a_until_end_of_dialog`, and `face_*` to turn in place
  - `add_marker` / `delete_marker`: per-map emoji+label markers, bounds-checked, with the NPC uid attached automatically
  - `write_memory` / `delete_memory`: key-value pairs with prefixes such as `tips_`, `quest_`, `boss_`
  - `update_objectives`: primary, secondary, third and others, each with a short and a long description
  - `path_to_location` (x, y, map_id, explanation)
  - `restart_console`: reload the last in-game save; must be the only action in the call

  — [repo: server/src/ai/tools.js L38–560; game.txt §4](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Guardrails: at most one key_press per turn; `start` cannot be combined with other keys; an empty action list is an error; markers are rejected during dialog. — [repo: tools.js handleToolCall](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Key-press results return a "trace" (before/after state, dialog transcript, wait status) formatted as markdown, so the model sees what each press did. — [repo: tools.js summarizeTracePayloadMarkdown ~L300–460](https://github.com/Clad3815/gpt-play-pokemon-firered)

**Pathfinding**
- `path_to_location` is meant for moves of more than 20 tiles or complex paths. It starts a separate OpenAI Responses call (`OPENAI_MODEL_PATHFINDING`, default gpt-5.2, effort high, prompt `prompts/path_finding.txt`, 455 lines) with an OpenAI code-interpreter container. The minimap grid JSON and the last working Python code (`server/tmp/temp_full_working_code.py`) are uploaded to the container. The sub-model must return a key sequence and may update the Python file, with instructions to "never delete existing code… only enhance". If dialog is detected, `a_until_end_of_dialog` is prepended. — [repo: tools.js L940–1330; config.js](https://github.com/Clad3815/gpt-play-pokemon-firered)

**Memory / reflection**
- Persistent state lives in `server/gpt_data/`: history, memory, objectives, markers, counters, summaries/all_summaries, progress_steps, map_visits, badges_log, token/time usage, last_criticism. — [repo: README.md](https://github.com/Clad3815/gpt-play-pokemon-firered)
- A self-criticism pass runs every 55 assistant steps (763-line prompt with an "outcome-bias guardrail" and a "do not invent mistakes" rule). A summary runs every 120 steps or at the 250k-token limit, at reasoning effort xhigh. Summaries are rolled up once enough accumulate (`summary_rollup.txt`). — [repo: config.js; prompts/self_criticism.txt; gameLoop.js L290–660](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Progress milestones are triggered by vanilla event flags, badges and map visits, e.g. `EVENT_GOT_STARTER`, `EVENT_SS_ANNE_LEFT`, `EVENT_BEAT_ROCKET_HIDEOUT_GIOVANNI`, `CERULEAN_CITY`. — [repo: server/progress_steps.json](https://github.com/Clad3815/gpt-play-pokemon-firered)
- The prompt is 1,300 lines and covers Gen 3 damage, a team-audit routine, save/load policy, maze navigation, menu cursor behavior, move-learning and TM decisions, nickname rules and battle strategy (type matchups, switching, setup, status, priority). — [repo: server/prompts/game.txt](https://github.com/Clad3815/gpt-play-pokemon-firered)

**Models and cost**
- The default model is gpt-5.2 at reasoning effort high (xhigh for summaries), with `service_tier=priority` and a 15-minute timeout. Price table in code: gpt-5.2 $1.75 in / $0.175 cached / $14 out per Mtok. The code also prices gpt-5.1, gpt-5, gpt-4.1, o4-mini and o3. — [repo: server/src/config.js, server/.env.example](https://github.com/Clad3815/gpt-play-pokemon-firered)
- Clad3815's earlier streams (GPT_Plays_Pokemon on Twitch): o3 finished Red in 18,184 steps and GPT-5 in 6,470 steps (Aug 2025). GPT-5 finished Crystal in 9,517 steps against 27,040 for o3. Clad3815 credits fewer hallucinations, better spatial reasoning (o3 "tried to walk through walls") and better goal planning. — [TechRadar](https://www.techradar.com/ai-platforms-assistants/chatgpt/gpt-5-just-completed-pokemon-red-in-a-new-world-record-time-claude-gemini-and-chatgpt-o3-arent-even-close); [36kr](https://www.36kr.com/p/3440506883577476); [Gigazine o3 stream, May 2025](https://wbgsv0a.gigazine.net/gsc_news/en/20250528-openai-o3-pokemon)

### Inferences
- The token tracker and cost code show that cost was a live concern. With gpt-5.2 at high effort, priority tier, a 250k-token context and three screenshots per step, a full run would plausibly cost thousands of dollars, but there is no published figure.
- Code-interpreter pathfinding is fragile and slow. For a port, a deterministic BFS/A* over the collision grid the bridge already builds is the simpler choice, and it is what PokeAgent and Claude's navigator do.
- The most valuable reusable parts are `world/` (RAM map-layout reading plus metatile behaviors), `text/`, the party decryption, the Lua control loop and the overall loop design (memory, objectives, markers, critic, summary).

### Gaps
- No public results were found for the FireRed run itself (finished or not, steps, hours, cost). The repo has no results section, and searches turned up nothing. The Twitch channel or Clad3815's X posts would be the place to check.
- The prompts were not read end to end (game.txt 1,300 lines, path_finding.txt 455 lines). Only the section headers and §3–4 were read.

## Q2. Other FireRed/Emerald/Gen 3 harnesses and their design

### Takeaway
The other harnesses use the same pattern: screenshot, RAM-derived text state, a walkability grid or minimap, a pathfinder (deterministic A*/BFS or an LLM sub-agent), persistent notes/objectives, and periodic summarization. PokeAgent (Emerald) is the most reusable open-source Gen 3 reference: mGBA Python bindings, a pokeemerald-symbol memory reader, porymap data and an MCP tool server. By 2026, frontier models need much less scaffolding. Anthropic says Claude Fable 5 beat FireRed with a minimal vision-only harness (June 2026).

### Cited Findings
- **PokeAgent Challenge (NeurIPS 2025; paper arXiv 2603.15563, Mar 2026)**
  - Two tracks: competitive battling, and an RPG speedrun of Emerald.
  - The speedrun baseline is an orchestrator with "MCP tools (A* pathfinding, button inputs, knowledge retrieval)" and sub-agents for battle, self-reflection, gym puzzles and objective verification, plus automatic context compaction.
  - Exposed state: party species, levels, status and HP. "Puzzle states, dynamic obstacles, items, and movesets are not exposed."
  - Baselines: Gemini 3 Flash ~2:24 mean, Claude Sonnet 4.5 6:25–20:45. Humans: 18 min (expert speedrunner), 1:22:05 (average).
  - Winner Heatz used "Scripted Policy Distillation" (LLM subgoals → scripted policies → imitation learning + RL) and finished in 40:13.
  - "Without a harness, raw frontier VLMs achieve effectively 0% task completion."
  — [arXiv 2603.15563](https://arxiv.org/html/2603.15563); [UT RPL page](https://rpl.cs.utexas.edu/publications/2025/04/01/karten-neurips25-pokeagent/)
- **PokeAgent starter kit (sethkarten/pokeagent-speedrun)**
  - Emulators: Emerald runs on mGBA Python bindings (`pokemon_env/emulator.py`, EmeraldEmulator). Red runs on PyBoy.
  - `pokemon_env/memory_reader.py` (PokemonEmeraldReader) reads RAM via pokeemerald decomp symbols and is marked "DO NOT MODIFY for submissions".
  - `pokemon_env/porymap/` holds pokeemerald map and tileset data. `utils/mapping/` has an ascii_map_loader, map_formatter, map_stitcher and porymap_json_builder.
  - Observations: frames, an ASCII map and structured state. Actions: `press_buttons`.
  - Tools via `agents/tools/registry.py` (A*, type chart, damage calculator). Sub-agents live in `agents/subagents/`. Memory is `knowledge_base.json`, and objectives come from `agents/objectives/`.
  - Serving: a FastAPI headless server with `POST /mcp/*` endpoints for external CLI agents. A `--game red|emerald` flag selects the game.
  — [GitHub pokeagent-speedrun](https://github.com/sethkarten/pokeagent-speedrun)
- **Gemini Plays Pokemon (Joel Z, independent; Blue, then others)**
  - Inputs: screenshots, RAM data and a text minimap with fog of war.
  - The pathfinder is a Gemini sub-agent prompted to "mentally simulate" BFS and check the path against the map. A separate puzzle-solver sub-agent handles puzzles.
  - Gemini 2.5 Pro finished Blue in about 813 hours.
  — [Gemini 2.5 tech report](https://arxiv.org/pdf/2507.06261); [LessWrong, 2025-04-19](https://www.lesswrong.com/posts/7mqp8uRnnPdbBzJZE/is-gemini-now-better-than-claude-at-pokemon); [nriglobe](https://nriglobe.com/technology/google-gemini-2-5-pro-beats-pokemon-blue-in-813-hours-how-it-stacks-up-against-other-ai-models/)
- **Claude Plays Pokemon (David Hershey, Anthropic; Red from Feb 2025)**
  - Screenshot with a walkable-tile grid overlay.
  - A navigator tool that walks to a requested coordinate.
  - A knowledge base and context summarization/cleanup.
  - A "Critic Claude" that reviews progress.
  — [LessWrong 2025-04-19](https://www.lesswrong.com/posts/7mqp8uRnnPdbBzJZE/is-gemini-now-better-than-claude-at-pokemon); [Latent Space 2025-03-04](https://www.latent.space/p/how-claude-plays-pokemon-was-made)
- Changes to Claude's harness from model to model included Surf navigation support, marking non-navigable tiles, and gate side entrances. — [Anthropic blog search snippet](https://claude.com/blog/harnessing-claudes-intelligence)
- Anthropic, 2026-04-02: Claude uses a memory folder. Sonnet 3.5 treated memory as transcription and had 31 files, with duplicates, after 14k steps, while still stuck in the second town. Opus 4.6 had 10 organized files, 3 badges and a learnings file at the same step count. Later models need less scaffolding, and assumptions about what a model cannot do "should be tested". — [Claude blog: Harnessing Claude's intelligence](https://claude.com/blog/harnessing-claudes-intelligence)
- Anthropic, 2026-06-09 (via Shacknews): Claude Fable 5 beat FireRed with "a minimal, vision-only harness" (no maps, navigation aids or extra state). Earlier Claude models struggled with FireRed "even with harnesses that gave them additional helpful tools". Steps and cost were not disclosed. — [Shacknews](https://www.shacknews.com/article/149574/claude-ai-pokemon-firered-fable-5)

### Inferences
- Anthropic's own FireRed harness for pre-Fable models (the "complex helper harness") is not public. The Clad3815 repo and PokeAgent are the best open-source references.
- If a Fable-5-class model is available, an Unbound port could start vision-first, with a thin RAM layer (position, map id, party, dialog/battle flags). Only port FireRed-symbol-heavy UI detection where failures show up.

### Gaps
- The public PokeAgent memory_reader.py source was not inspected line by line. Its exact Emerald addresses and symbol approach were not verified beyond the README description.
- No public source for Anthropic's FireRed harness was found. Joel Z's harness is also not fully open-source (no repo found).

## Q3. What depends on vanilla FireRed and would break on Unbound (CFRU)

### Takeaway
The Clad3815 bridge is about as FireRed-specific as a harness gets. Every address comes from the vanilla decomp `.sym`, UI state is detected by matching function pointers, and names come from static vanilla-id JSON tables. CFRU inserts new code in free space, repoints and expands the species, move, item and ability tables, replaces the battle engine, expands the save block and flags/vars, and adds new menus. The portable parts are the generic Gen 3 pieces: the mGBA I/O, the charmap, the party encryption, and map/metatile reading through RAM pointers.

### Cited Findings
- CFRU inserts code at a configurable free-space offset (`OFFSET_TO_PUT` in `scripts/make.py`) and redirects vanilla code through `repoints`, `routinepointers` and `hooks` files. Linking uses `BPRE.ld`. — [CFRU GitHub](https://github.com/Skeli789/Complete-Fire-Red-Upgrade)
- CFRU expands species (Gen 8 via Dynamic-Pokemon-Expansion), moves, abilities and items, and up to 25 PC boxes. It replaces battle mechanics (Mega Evolution, Z-Moves, terrain, Totem Pokemon, new AI), adds save-block expansion and expanded flags/vars, and changes menus: a configurable start menu, a DexNav-style Pokedex, party-screen item handling and a scrollable summary screen. — [CFRU GitHub](https://github.com/Skeli789/Complete-Fire-Red-Upgrade)
- Specific vanilla dependencies in the Clad3815 code:
  - `gSpeciesInfo` indexed as `species*SIZE`, which breaks when the table is repointed or its entry size changes
  - `NUM_DEX_FLAG_BYTES = 0x34` (386 species)
  - Battle structs: `gBattleMons` 0x58 per battler, `HandleInputChooseAction` and the move-selection cursors
  - SaveBlock1 offsets 0x08E0 and 0x1200, and flag/var reads through `gSaveBlock1Ptr`
  - Start-menu action ids 0–8 and the `sStartMenuOrder` symbols
  - Bag with 3 pockets (`BAG_MENU_NUM_POCKETS = 3`), TM Case and Pokedex task symbols
  - Static `mappings.json` name tables and the vanilla `progress_steps.json` event flags
  — [repo: constants/addresses.py, player/party.py, mappings.json, progress_steps.json](https://github.com/Clad3815/gpt-play-pokemon-firered)
- `sym_addr` returns 0 for a missing symbol unless strict mode is on, so on a modified ROM wrong or zero addresses fail silently instead of crashing. — [repo: memory/symbols.py](https://github.com/Clad3815/gpt-play-pokemon-firered)

### Inferences
- **Probably survives on Unbound.** Unbound runs on FireRed BPRE, so the vanilla EWRAM/IWRAM globals that CFRU does not move should keep their addresses: `gMain`, `gPlayerAvatar`, `gObjectEvents`, `gMapHeader`, the backup map layout, `gSaveBlock1Ptr`/`gSaveBlock2Ptr`, `gPlayerParty`, `sTextPrinters` and `gStringVar*`. So should the 100-byte party struct and its encryption. This needs verification on the actual ROM, for example by checking known values while the game is running.
- **Likely breaks:**
  - ROM tables. Species, moves, items and abilities are repointed and expanded, so the names in `mappings.json` and the type/ability lookups will be wrong for ids above the vanilla range.
  - Battle UI detection. CFRU replaces large parts of the battle engine.
  - Start menu, bag, Pokedex and summary-screen detection. These are reworked menus whose callbacks live at CFRU free-space addresses absent from `pokefirered.sym`.
  - Flag/var ids and save-block offsets.
  - Progress milestones and the map name table (Unbound is a new region, Borrius).
- **Port path:** keep the generic layers. Rebuild the tables by reading them from the Unbound ROM, with addresses taken from CFRU/DPE sources or community data. Swap the callback-pointer UI detection for coarser signals (overworld vs battle vs dialog vs other menu, plus screenshots) and let a vision model handle menus.

### Gaps
- No public Unbound-specific RAM/ROM map or symbol file was found in this pass (Unbound is closed-source). Whether CFRU's save-block expansion moves `gPlayerParty` or other EWRAM globals was not confirmed.

## Q4. Known LLM failure modes and the harness features that addressed them

### Takeaway
The recurring failures are navigation (walking into walls, getting lost in mazes, hallucinating map layouts), loops and spinning, menu misreads, poor notes, and losing context over thousands of steps. The fixes that recur across harnesses are text minimaps with fog of war, coordinate pathfinders, explored/unexplored markers with anti-loop rules, periodic critics and summaries, and curated memory/objectives. Stronger models reduce the need for each of these.

### Cited Findings
- Gemini and Claude are both "easily distracted, lost, confused", navigate mazes badly, mismanage inventory and hallucinate map layouts. Joel Z changed the prompts to "discourage planning paths between maps" after spotting hallucinated paths. Text minimaps are a "significant advantage" because models read the Pokemon screen poorly. — [LessWrong 2025-04-19](https://www.lesswrong.com/posts/7mqp8uRnnPdbBzJZE/is-gemini-now-better-than-claude-at-pokemon)
- o3 "tried to walk through walls" and got lost in complex areas. GPT-5's gains came from fewer hallucinations and longer error-free action sequences. — [36kr summary of Clad3815](https://www.36kr.com/p/3440506883577476)
- Memory as transcription (Sonnet 3.5: 31 files, duplicates, stuck in the second town) compared with curated learnings files (Opus 4.6). — [Claude blog 2026-04-02](https://claude.com/blog/harnessing-claudes-intelligence)
- CLI-agent architectures "struggle to maintain coherence over the thousands of sequential decisions". PokeAgent added objective-verification and reflection sub-agents and context compaction. — [arXiv 2603.15563](https://arxiv.org/html/2603.15563)
- Clad3815 countermeasures in code:
  - ❓ fog-of-war tiles and an "Anti-Loop Protocol: Explore Before Backtracking"
  - Markers for entrances and exits and an "Entrance/Exit Protocol", plus a maze-navigation section
  - A critic every 55 steps with an outcome-bias guardrail
  - An `a_until_end_of_dialog` macro, which removes much of the A-mashing that eats steps
  - Per-press traces showing whether a step actually moved the player
  - `face_*` keys to turn without moving
  - `restart_console` to recover from bad states
  - "Boss dossier" memory entries
  — [repo: game.txt §9–13, tools.js, self_criticism.txt](https://github.com/Clad3815/gpt-play-pokemon-firered)

### Inferences
- Unbound will be harder on all of these. Its maps are new and not in model pretraining, so the models can lean on walkthrough knowledge far less than in FireRed. It has many more puzzles, a mission system and higher difficulty settings, so fog-of-war maps, markers and a deterministic pathfinder matter more there than in vanilla FireRed.

### Gaps
- No quantitative ablations (feature X → Y fewer steps) were found for any harness apart from PokeAgent's harness/no-harness contrast.
