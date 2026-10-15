# Operator runbook

How the **operator session** runs the ClaudeUnbound project: a Claude Code session that watches the playing agent,
catches harness bugs, raises and resolves their GitHub issues, and ships fixes by hot reload. It is not the agent
that plays the game (that one runs inside `agent/run.py`; see `agent/CLAUDE.md`).

The operator session runs on **Haiku 5.5** and routes real work through three subagents (`.claude/agents/`):

| Role | Model | Used for |
|---|---|---|
| operator (this session) | Haiku 5.5 | watching, triage, routine actions, issues, commits |
| `ops-verifier` | Sonnet 5.5 | checks every triage, every change before commit, every "verified live" claim |
| `ops-engineer` | Opus 5.5 | root-causes and fixes harness bugs, builds tools, writes regression tests |
| `ops-expert` | Fable 5.1 | last escalation: twice-rejected work, novel reverse engineering, agent design |

Current state, open work and the next steps are in **[docs/handoff.md](handoff.md)**. Read it after this file.

---

## 1. Starting a new operator session (for the human)

1. Open the Claude desktop app, **Code** tab, and start a new session in the folder `D:\Repos\ClaudeUnbound`.
2. In the session's model picker choose **Haiku 5.5**. (The subagents choose their own models from their files; you
   don't set them.)
3. Paste this as the first message:

   > You are the ClaudeUnbound operator. Read docs/operator-runbook.md and docs/handoff.md, then do the
   > "first actions" in section 2 of the runbook and tell me the state of the run.

4. Talk to it as you did before: hints for the agent, requests for changes, questions. It follows section 3 for
   anything that changes code.

The operator's memory (your preferences and standing rules) lives in
`C:\Users\Parka8111\.claude\projects\D--Repos-ClaudeUnbound\memory\` and is loaded automatically in every session
of this folder; project rules are in `CLAUDE.md`, also loaded automatically.

---

## 2. First actions of every operator session

1. Read `docs/handoff.md`, `CLAUDE.md` and the last ~30 rows of `docs/learnings.md`.
2. Check what is running (one PowerShell call):
   ```powershell
   Get-Process mGBA -ErrorAction SilentlyContinue | Select Id, StartTime
   Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'agent.run\.py|ui\\server\.py' } | Select ProcessId, CommandLine
   ```
   Expect exactly one mGBA, at most one runner, one spectator. Never start a second mGBA.
3. If a run is active, arm the monitor (section 6) and report: badges, map, step, cost, anything abnormal.
4. List open issues: `gh issue list --state open`.

---

## 3. The loop: judge, verify, escalate, verify, ship, confirm

Every alert or request that may change **code or the agent's instructions** goes through this loop. Routine actions
take the fast path (section 4).

```
alert / request
  -> 1. operator JUDGES     (reads the evidence, writes a triage)
  -> 2. ops-verifier        (triage: is it real, is the cause supported, who should act?)
        REJECTED -> gather the missing evidence, back to 1
        APPROVED, operator can handle it -> fast path
        APPROVED, needs code -> 3
  -> 3. ESCALATE            ops-engineer (Opus) by default; ops-expert (Fable) if the verifier marks it novel/hard
  -> 4. engineer/expert     does the work, returns ROOT CAUSE / CHANGE / TESTS / LIVE CHECK / RISKS / ISSUE TEXT
  -> 5. ops-verifier        (change: reviews the diff, runs tests, checks the rules)
        REJECTED -> back to the same worker with the objections (attempt 2)
        REJECTED twice (Opus) -> ops-expert with the full history
        REJECTED twice (Fable) -> STOP: report to the human with a summary
        APPROVED -> 6
  -> 6. operator SHIPS      opens the issue (ISSUE TEXT), commits "(#N)", pushes; the MCP server hot-reloads
  -> 7. CONFIRM LIVE        on the next real occurrence (LIVE CHECK), gather the log evidence;
                            ops-verifier checks the live claim; then close the issue with that evidence
```

### Writing the triage (step 1)
Keep it short and evidential:
```
ALERT: <the monitor line or the human's words>
EVIDENCE: <log.jsonl steps and results, harness notes, positions, what the agent's memory says>
READING: harness bug | agent behaviour (puzzle/decision) | infrastructure (process, emulator)
CAUSE (suspected): <...>
PROPOSED: <fast-path action | escalate to ops-engineer | ops-expert>, because <...>
```
Get evidence cheaply first: the last 20-40 entries of `log.jsonl` (step, tool, args, result, now), the console log
tail, `bridge/world.py`/`bot.describe_levels` for map questions, read-only bridge reads.

### Calling a subagent
Use the Agent tool with `subagent_type` = `ops-verifier`, `ops-engineer` or `ops-expert`. Give it everything it
needs in the prompt (it does not see this conversation): the triage, the evidence, file paths, and for a retry the
previous attempt's summary and the verifier's objections.

### Agent behaviour vs harness bug
A WATCHDOG note is not a bug by itself. The agent loops while working a puzzle (rides, warps, hops) and that is
fine if it keeps reaching new tiles or maps. It is a **harness bug** when a tool misreports (e.g. "no path" where a
path exists, a warp described as an exit that isn't, a crash, wrong state), or the agent lacks information it
cannot get (that is a tool/design gap: escalate to ops-expert). When it is the agent being stuck on a puzzle, the
human may give a hint (section 5); don't solve puzzles for it yourself.

---

## 4. Fast path (no loop needed)

The operator does these directly:
- arm / re-arm the monitor; report progress;
- relay the human's hints into the workspace's `operator.md` (section 5);
- start, stop, resume the runner and spectator when the human asks (section 7);
- comment on issues; close an issue whose live verification the ops-verifier approved;
- answer questions from logs and docs.

Anything that edits code, `agent/CLAUDE.md`, `agent/agents.json` or docs that change behaviour goes through the loop.

---

## 5. Rules (hard)

**Emulator and run**
- Only one mGBA, the live one on port 8888. Start it only with `python bridge/launch.py [STATE]` (it starts mGBA
  detached through WMI so it outlives this session, and refuses to start a second).
- Never restart mGBA, reload a savestate or restart the agent's session to verify a fix. Fixes are verified on the
  next real occurrence. (Exceptions only when the human asks.)
- The agent never rolls back (no savestates to get unstuck). The game speed stays at 2x (`launch.py`'s limiter).
- Only one client may drive the emulator (frame commands). While the runner plays, everything else only reads.
- Launch long-lived processes detached: `python bridge/launch.py --detach NAME [--min] COMMAND...`. Processes
  started from a Claude Code shell die when the app updates (it happened, #151).

**Work discipline**
- Issue per change: every fix or feature has a GitHub issue with symptom/evidence, root cause, fix, verification;
  commits reference it "(#N)"; issues close with the live evidence. The human writes about the project from them.
- Commits end with `Co-Authored-By: Claude <model> <noreply@anthropic.com>` per the session's attribution reminder.
- Write Python with the Edit/Write tools, not shell heredocs (backslashes and `\n` got mangled repeatedly).
- Gate commits on `python tests/regress.py` exiting 0 (check `$?` directly, not through a pipe).
- Record RAM/ROM facts in `docs/addresses.md` (status + evidence) and failures/false assumptions in
  `docs/learnings.md`.

**The playing agent's information rules**
- Wiki: `wiki_search`/`wiki_read` cover only pokemon/items/locations. The walkthrough is a last resort behind the
  harness gate (`wiki_walkthrough`, #153/#160): 150 actions without progress (new map, badge, or a new operator hint
  with information, #182),
  2+ watchdogs, strategist and expert consulted. Nothing from the walkthrough may enter `memory/` (the harness
  deletes copied lines). Don't hand walkthrough content to the agent any other way.
- Operator hints: append a line to `<workspace>\operator.md` (e.g. `D:\ClaudeUnboundRuns\full1\operator.md`). The
  harness copies it into the agent's `memory/operator.md` (pinned) and announces new lines as `OPERATOR HINT` in the
  agent's next tool result (#154). A new hint restarts the walkthrough gate's clock, unless every line of it only
  redirects (it says stop, give up, abandon, for later, move on, or names the walkthrough; #182). Use the human's words.
  With no query the walkthrough serves an outline (order of places, badge and HM gates, no routes; #181), built
  offline by `python bridge/wiki.py outline` into the gitignored `wiki/outline.json`.
- Rival name: Copilot.

**Cost**
- Runner budget is per launch (`--budget-usd`, default $50) and it stops itself after 3 chunks without a game
  action (#150). Costs in usage.jsonl are per-session running totals; use `agent/run.py`'s `spent_so_far()`.
- The operator itself: don't poll with sleeps; use the monitor (it wakes you). Keep replies short.

---

## 6. Watching a run

Arm the quiet monitor with the Monitor tool (30-minute maximum; re-arm on expiry):
```
python -u ops/watch_run.py D:\ClaudeUnboundRuns\<workspace>
```
It prints only: runner alarms/tracebacks/stops, `ERROR`s from log.jsonl, `WATCHDOG` notes, `ALERT` lines (a third
watchdog on one map within 200 actions, with the agent's loop, #171), failed hot reloads,
badges, and `RUNNER STOPPED` when no runner process is left. Each line is an alert for section 3.

Useful reads:
- progress: last line of `log.jsonl` with `"map_id"` (step, map, position, badges);
- the agent's own reasoning: the console log tail (`<workspace>.console.log`);
- cost: `python -c "import sys; sys.path.insert(0,'agent'); import run; print(run.spent_so_far(r'<ws>\usage.jsonl'))"`;
- the spectator page: http://127.0.0.1:8765/ (the human watches it).

Other operator tools in `ops/`: `stalls.py` (samples the frame clock: does the game itself stall?),
`record_demo.py` (records a human's play: positions, objects, keys; used for the Crater gym demo, #134).

---

## 7. Commands

Run from `D:\Repos\ClaudeUnbound`.

| What | Command |
|---|---|
| start mGBA (if none) | `python bridge/launch.py` (optionally a savestate path) |
| resume a run | `python bridge/launch.py --detach runner --min cmd /c "python -u agent\run.py --workspace D:\ClaudeUnboundRuns\full1 --goal-badges 8 >> D:\ClaudeUnboundRuns\full1.console.log 2>&1"` |
| new Expert run | see docs/handoff.md, "Starting the Expert run" |
| spectator | `python bridge/launch.py --detach spectator --min python D:\Repos\ClaudeUnbound\ui\server.py --workspace D:\ClaudeUnboundRuns\<ws> --port 8765` |
| stop the runner | stop the `agent/run.py` python process and its `claude.exe` child (`--mcp-config` in its command line); leave mGBA |
| offline tests | `python tests/regress.py` |
| game state now | `python bridge/state.py` (read only) |

---

## 8. Where things are

| Path | What |
|---|---|
| `bridge/` | the harness: bridge client, state, world, planner, MCP tools (hot-reloaded) |
| `agent/CLAUDE.md`, `agent/agents.json`, `agent/run.py` | the playing agent's instructions, its subagents, the runner |
| `ops/` | operator scripts (monitor, stall sampler, demo recorder) |
| `.claude/agents/ops-*.md` | the operator's subagents |
| `docs/learnings.md`, `docs/addresses.md`, `docs/gym-mechanics.md` | what has been learned, every address, gym mechanics |
| `docs/handoff.md` | current state and next steps |
| `D:\ClaudeUnboundRuns\<ws>\` | a run: memory/, log.jsonl, usage.jsonl, transcripts/, operator.md, run.json |
