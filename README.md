# ClaudeUnbound

Getting Claude (Fable 5.1 / Opus 5.5) to play Pokémon Unbound, a CFRU-based FireRed romhack, on its own.

- [Research report](docs/research.md): existing harnesses, what changes from FireRed to Unbound, recommended architecture, phased plan, cost, risks.
- [Research notes](docs/research-notes/): source notes behind the report.
- [Gameplay policy](docs/gameplay-policy.md): how Claude should play (exploration, battles, missions, memory).
- [RAM addresses](docs/addresses.md): verified Unbound RAM map.

## Bridge

Load `bridge/probe.lua` in mGBA 0.10+ (Tools → Scripting → File → Load script). It serves the emulator on 127.0.0.1:8888. Then, from `bridge/`:

- `python state.py`: current mode, map, position, party, battle and dialog
- `python state.py press UP`: press a key and report what changed
- `python probe.py save|load PATH`, `python probe.py autosave ../saves 18000`: savestates and 5-minute rolling backups

Work is tracked as issues, grouped by phase milestone.

No ROMs live in this repo. Bring your own legally dumped US FireRed 1.0 ROM and the official Unbound patch.
