# ClaudeUnbound

An autonomous harness for Claude to play Pokémon Unbound, a CFRU-based FireRed romhack. A player model (Haiku 5.5) plays the game through deterministic tools that read live RAM and drive the emulator. Subagents handle hard decisions: Sonnet 5.5 for strategy and verification, Fable 5.1 as a capped expert, and Opus 5.5 to refine memory.

## Status

- **Phases 0–3** of the [research plan](docs/research.md) are done: ground truth, a verified bridge, the agent and its tools, and Unbound hardening. Phase 3's exit test (badges 1–3) was met.
- **Vanilla run** (`full1`): 4 badges in 6,477 actions.
- **Expert run** (`expert1`, Expert difficulty): 3 badges in about 32,000 steps. It's parked for now.
- **Phase 4** (self-refinement across runs) is partly done; **Phase 5** (the Champion) is not reached.

Work is tracked as GitHub issues, grouped by phase milestone. The [handoff](docs/handoff.md) has the current state and open work.

## Layout

| Path | What it is |
|---|---|
| `bridge/` | The harness: the mGBA bridge (`probe.lua`), state and world readers, names, the pathfinder (`bot.py`), the MCP tool server (`mcp_server.py`), the watcher and verifier (`watcher.py`), and the walkthrough index (`wiki.py`) |
| `agent/` | The runner (`run.py`), the player's instructions (`CLAUDE.md`, with detail in `reference.md`), and the subagent definitions (`agents.json`) |
| `ui/` | The spectator: a read-only page on port 8765 showing the agent's reasoning, model router, party, memory and learnings |
| `ops/` | The operator's tools: the run monitor (`watch_run.py`) and a readiness check (`verify.py`) |
| `docs/` | Research, gameplay policy, addresses, learnings, the operator runbook, and the handoff |
| `tests/` | `regress.py`, the offline regression suite (run it after touching shared helpers) |

## How the model is used

- **Player:** Haiku 5.5, the default for every action. Its context is rebuilt in sessions that rotate at 80k tokens, or on entering a new town.
- **Verifier** (Sonnet 5.5): checks irreversible choices before the player makes them. The harness also runs routine checks in the background.
- **Strategist** (Sonnet 5.5): consulted for routing, hints, team and move choices, close battles and puzzles. It was Opus until 14 Oct 2026.
- **Expert** (Fable 5.1): at most once per gym, after two failed attempts at the same goal and after the strategist. The cap is enforced per badge count; see the limits below.
- **Refiner** (Opus 5.5): updates `memory/` at each learning check and critiques the approach.
- **Watcher** (Haiku 5.5, low effort): every 10 actions, at most two notes.

The routing rules are in `agent/agents.json`, `agent/run.py` (`MAIN_MODEL`, `PLAYER_EFFORT`, the expert cap) and the "Model tiers" section of `agent/CLAUDE.md`.

**Known limits:** the expert cap is checked once per chunk, so two expert calls inside one chunk aren't blocked. The Expert run logged nine expert calls, and at least two of them were for the same gym after the cap was in place. The cause isn't confirmed.

## Running a run

The run uses its own copy of the game in `run/` (gitignored): `run/Unbound.gba`, and `run/baseline.ss1` for a Vanilla start or `run/baseline_expert.ss1` for Expert. Its in-game save never touches a hand-played save.

1. **Start the emulator and bridge:** `python bridge/launch.py [STATE]` starts an mGBA development build (0.11, with `--script`; the path comes from the `MGBA` env var) with the bridge loaded, unless the bridge is already up. The build's portable `config.ini` needs `[override.BPRE]` with `savetype=FLASH1M` and `hardware=1`. With mGBA 0.10, load `bridge/probe.lua` by hand. The bridge serves `127.0.0.1:8888`.
2. **Start the runner** (detached, so it outlives the shell that started it):
   `python bridge/launch.py --detach runner --min cmd /c "python -u agent\run.py --workspace <WS> --goal-badges 8 --budget-usd 150 >> <WS>.console.log 2>&1"`.
   Use `--fresh --baseline run/baseline_expert.ss1 --difficulty expert` only for a new Expert game, and never on a run that already exists. Stopping the runner also means stopping its `claude.exe` child.
3. **Watch it:** `python ui/server.py --workspace <WS> --port 8765` for the spectator (read-only), and `python ops/watch_run.py <WS>` for the monitor's alerts.

Useful commands, run from `bridge/`:

- `python state.py`: current mode, map, position, party, battle and dialog
- `python state.py press UP`: press a key and report what changed
- `python probe.py save|load PATH`, `python probe.py autosave ../saves 18000`: savestates and rolling backups (for the operator; the agent has no load tool)

Offline tests: `python tests/regress.py` (about a second). Readiness checks for the pending live verifications: `python ops/verify.py`.

## Wiki

A local copy of [unboundwiki.com](https://unboundwiki.com/) lives in `wiki/` (gitignored; regenerate it). Two indexes are kept apart:

- **The regular index** covers `pokemon/`, `items/` and `locations/`: where to find each species, abilities, evolutions, moves and item details. `ALLOWED_SECTIONS` in `bridge/wiki.py` enforces that scope, and `read()` refuses other URLs.
- **The walkthrough** is a gated last resort. It's fetched separately (`crawl-lastresort`) and indexed by section (`index-lastresort`), and the outline (`outline`) gives the order of towns and caves with their badge and HM gates, without routes. The agent calls it only when it's stuck and the gate allows.

Commands (standard library only; one request per second, resumable):

- `python bridge/wiki.py crawl` and `python bridge/wiki.py index`: the regular index into `wiki/index.sqlite`
- `python bridge/wiki.py search "Snorunt abilities" [N]`: top N pages with URL, title and snippet
- `python bridge/wiki.py read pokemon/snorunt`: a page's text (full URL, path or slug)
- `python bridge/wiki.py crawl-lastresort`, `index-lastresort`, `outline`: the walkthrough and outline

## Documentation

- [Research report](docs/research.md): the spec, the phases and their exit tests, the architecture and risks
- [Gameplay policy](docs/gameplay-policy.md): how the player should play
- [Learnings](docs/learnings.md): failures, their causes and the rules they taught
- [RAM addresses](docs/addresses.md): the verified Unbound RAM map
- [Operator runbook](docs/operator-runbook.md) and [handoff](docs/handoff.md): how the run is supervised, and the current state
- [Gym mechanics](docs/gym-mechanics.md) and [bootstrap report](docs/bootstrap-report.md)
- [Research notes](docs/research-notes/): the source notes behind the report

## Rules that matter

- Only one emulator runs at a time, on port 8888. Fixes ship by hot reload and are verified on the next real occurrence.
- No savestate rollback during a run. The agent plays its way out of a stall.
- No ROMs live in this repo. Bring your own legally dumped US FireRed 1.0 ROM and the official Unbound patch.
