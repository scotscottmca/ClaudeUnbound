# ClaudeUnbound

Getting Claude (Fable 5.1 / Opus 5.5) to play Pokémon Unbound, a CFRU-based FireRed romhack, on its own.

- [Research report](docs/research.md): existing harnesses, what changes from FireRed to Unbound, recommended architecture, phased plan, cost, risks.
- [Research notes](docs/research-notes/): source notes behind the report.
- [Gameplay policy](docs/gameplay-policy.md): how Claude should play (exploration, battles, missions, memory).
- [RAM addresses](docs/addresses.md): verified Unbound RAM map.

## Bridge

The agent's run uses its own copy of the game in `run/` (gitignored): `run/Unbound.gba` and `run/baseline.ss1`, the fresh-start savestate from #1. Its in-game save (`run/Unbound.sav`) never touches a hand-played save.

`python bridge/launch.py [STATE]` starts an mGBA development build (0.11, which supports `--script`; path in the `MGBA` env var) with the bridge script loaded, unless the bridge is already up. Settings for that build live in its own portable `config.ini` and need the `[override.BPRE]` entries `savetype=FLASH1M` and `hardware=1`. With mGBA 0.10, load `bridge/probe.lua` by hand (Tools → Scripting → File → Load script). Either way the bridge serves 127.0.0.1:8888. Then, from `bridge/`:

- `python state.py`: current mode, map, position, party, battle and dialog
- `python state.py press UP`: press a key and report what changed
- `python probe.py save|load PATH`, `python probe.py autosave ../saves 18000`: savestates and 5-minute rolling backups

## Wiki

A local, searchable copy of three sections of [unboundwiki.com](https://unboundwiki.com/) lives in `wiki/` (gitignored; regenerate it): `pokemon/` (where to find each species, abilities, evolutions, moves), `items/` and `locations/`. Nothing else is crawled or indexed, deliberately: no walkthrough, missions, gyms or misc-info, because the agent works out the story and missions itself. `ALLOWED_SECTIONS` in `bridge/wiki.py` enforces this, and `read()` refuses other URLs. Standard library only:

- `python bridge/wiki.py crawl`: fetch every sitemap page in those sections into `wiki/pages/<slug>.json` (`{url, title, section, text}`, tables as `|` rows). One request per second; resumable, cached pages are skipped and failures retried on the next run.
- `python bridge/wiki.py index`: build the SQLite FTS5 index `wiki/index.sqlite`
- `python bridge/wiki.py search "Snorunt abilities" [N]`: top N pages with URL, title and snippet
- `python bridge/wiki.py read pokemon/snorunt`: a page's text (full URL, path or slug)

`search(query, n)` and `read(url_or_slug)` in `bridge/wiki.py` are the functions for the MCP tools.

Work is tracked as issues, grouped by phase milestone.

No ROMs live in this repo. Bring your own legally dumped US FireRed 1.0 ROM and the official Unbound patch.
