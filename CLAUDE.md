# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A harness for Claude to play Pokémon Unbound 2.1.1.1 (a CFRU-based FireRed romhack) autonomously. Plan, architecture rationale and phase table live in `docs/research.md`; work is tracked as GitHub issues grouped by phase milestone, and commits/PRs reference the issue number (e.g. `(#8)`).

**Read `docs/learnings.md` before building or playing**, and add an entry whenever something fails or an assumption proves false. Its core rule: vanilla FireRed/CFRU knowledge is a hypothesis on Unbound. Verify with a cheap experiment (RAM diff, walk test, screenshot) before building on it. `docs/gameplay-policy.md` defines how the agent should play (full exploration, every mission, rename every capture, record opponents; the unboundwiki.com corpus may be consulted).

## Running

No build, test suite or linter. Python scripts in `bridge/` are run directly, from inside `bridge/` (they import each other as top-level modules).

- `python bridge/launch.py [STATE]`: start the mGBA dev build (0.11+, needs `--script`; path from the `MGBA` env var) with `probe.lua`, unless something already serves 127.0.0.1:8888. The build's portable `config.ini` needs `[override.BPRE]` `savetype=FLASH1M` and `hardware=1`, and `[ports.qt]` `audioSync=0` `videoSync=0` (with sync on, an instance started while the remote desktop session is disconnected never runs a frame, so the bridge accepts no clients). On mGBA 0.10, load `bridge/probe.lua` by hand via Tools → Scripting.
- `python state.py` → state JSON; `python state.py press UP [FRAMES] [SETTLE]` → traced press (before/after snapshot, `moved`, `changed`).
- `python world.py [full]` → collision grid (viewport or whole map) plus NPC/warp/sign/connection lists.
- `python probe.py read32|range|dump|diff|step|press|shot|save|load|autosave ...` → raw bridge access; `dump` + `diff` is the standard way to find new RAM addresses.
- `python tables.py [ROM]` → regenerates `names.json` from the ROM in `rom/`.
- `python bot.py "Bellin Town" "Route 2"` → Phase 1 exit test: scripted walker using only bridge output.

ROMs, saves and savestates are gitignored and never committed. `rom/` holds the patched ROM; `run/` is the agent's own copy (`Unbound.gba`, `baseline.ss1` fresh-start state, `Unbound.sav`) so it never touches a hand-played save; `saves/` holds autosave backups.

## Architecture

Layered per `docs/research.md`: thin, verified state layer + deterministic tools, with the model supplying policy. Phases 0–1 (ground truth, bridge) are what exists; the MCP tool surface and agent loop (Phase 2) are not built yet.

- **`probe.lua`** runs inside mGBA: a line protocol on port 8888, one reply line per command, `err ...` on failure. Frame-based commands (`step`, `press`) are pending until done; **only one client may drive the emulator at a time**, and a second client's frame command gets `err busy` (reads and `shot` still go through). After an interrupted run, kill leftover client processes before starting new ones.
- **`probe.py`** `Probe` is the Python client every other module uses. `range` is chunked at 0x1000 to keep reply lines small.
- **`state.py`** holds the verified RAM constants and `get_state()`. Mode (`overworld`/`battle`/`dialog`/`other`) is derived from `gMain.callback2`, `sLockFieldControls` (the only start-menu signal) and text-printer activity, not from `gBattleTypeFlags`, which is never cleared after battle. Party data is CFRU's unencrypted layout; use `gPlayerPartyCount`, not the save block copy. `press()` diffs a small snapshot rather than the screen (weather animates every frame).
- **`world.py`** reads the live map layout (`gBackupMapLayout`, 7-tile border) and metatile behaviors into a grid that accounts for elevation, ledges, water, ice, forced movement and warps; map headers come from an XOR-obfuscated group table in ROM.
- **`tables.py`/`names.json`**: species/move/ability/item/map-section names extracted from the ROM. Unbound has its own ability numbering; each table is checked against known entries so a different ROM fails loudly.
- **`bot.py`**: elevation-aware Dijkstra over the grid, flees wild battles, logs every step, and stops with a screenshot on a stall or an unrecognised screen instead of guessing.

Every RAM/ROM address must be recorded in `docs/addresses.md` with its status (verified / plausible / pending) and evidence. Don't use an unverified address as if it were verified.

Autonomous loops must log each action and have a stall detector, must never press keys blind in an unrecognised state (forced prompts ignore B), and should check the lead Pokémon's HP before entering grass.
