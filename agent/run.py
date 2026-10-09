"""Run the Claude Code player agent against mGBA until the goal (first badge by default).

    python agent/run.py --fresh                 # new run from run/baseline.ss1
    python agent/run.py                         # resume the current run
    python agent/run.py --fresh --bootstrap-from D:/ClaudeUnboundRuns/gym1   # start with a previous run's memory (#22)

Each chunk is one `claude -p` invocation (resumed with --continue). To change the main (router) model
mid-run, write a model ID to <workspace>/model.txt; it's read at the start of every chunk. Per chunk it logs tokens, API-equivalent
cost, model breakdown and the milestone to <workspace>/usage.jsonl (#13), pauses when the usage window
is exhausted and resumes after the reset, and stops at the goal or the --budget-usd alarm.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(REPO, "bridge"))
import launch  # noqa: E402
import watcher  # noqa: E402
from probe import Probe  # noqa: E402
from state import get_state  # noqa: E402

CLAUDE = shutil.which("claude") or os.path.expanduser(r"~\.local\bin\claude.exe")
CONTEXT_LIMIT = 160_000  # rotate to a fresh session past this (tokens re-read every turn)
MAIN_MODEL = "claude-haiku-5-5"  # default tier; verified by Sonnet 5.5, escalates to Opus 5.5 then Fable 5.1
TOOLS = ["mcp__unbound", "Read", "Write", "Edit", "Glob", "Grep", "Task", "Agent"]
# Scheduling/waiting tools park the session in wall-clock time while the game runs on: the agent once called
# ScheduleWakeup(1200 s) to "wait for a gym guard's window" and sat idle for 20 minutes. Wait in game time (WAIT).
BLOCKED = ["ScheduleWakeup", "CronCreate", "CronDelete", "CronList", "Monitor", "RemoteTrigger", "PushNotification"]
# Describe a previous run's save, not this one: left out when bootstrapping (#22).
RUN_STATE = {"objectives.md", "team.md", "items.md", "operator.md"}
FIRST = "Start playing. Read memory/ first, then get_state."
BOOTSTRAP = (" memory/ carries knowledge from a previous run (maps, NPCs, opponents, missions, learnings). The game "
             "restarted from the beginning: anything there about progress or mission status describes that run, not this one.")
NEXT = ("Continue playing toward the goal. Keep going for a good stretch (~100 actions) before you stop; "
        "update memory/objectives.md before you do. If you have earned {goal}, say GOAL REACHED.")


def goal_text(badges):
    return "the first badge" if badges == 1 else f"{badges} badges"


def difficulty_of(ws, wanted=None):
    """The run's difficulty: WANTED (and remembered in WS/run.json), else what run.json says, else vanilla."""
    path = os.path.join(ws, "run.json")
    cfg = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    if wanted:
        cfg["difficulty"] = wanted
        os.makedirs(ws, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    return cfg.get("difficulty", "vanilla")


def setup(ws, fresh, bootstrap, goal_badges, reloaded=False, difficulty="vanilla", baseline=None):
    os.makedirs(os.path.join(ws, "memory"), exist_ok=True)
    shutil.copy(os.path.join(REPO, "agent", "CLAUDE.md"), os.path.join(ws, "CLAUDE.md"))
    if bootstrap and fresh:  # on a resume, memory/ is already this run's
        shutil.copytree(os.path.join(bootstrap, "memory"), os.path.join(ws, "memory"), dirs_exist_ok=True,
                        ignore=lambda _d, names: [n for n in names if n in RUN_STATE])
    seed = {"objectives.md": f"# Objectives\n\n- Goal: earn {goal_text(goal_badges)}.\n"
                             + (f"- Difficulty: {difficulty.upper()} (already set in Game Settings by the operator: Shift battle "
                                "style, 4 items per trainer battle, capped Exp. Share). Level caps apply: see team_details.\n"
                                if difficulty != "vanilla" else "")
                             + "- Next: find out where I am and what the current mission says.\n",
            "learnings.md": "# Learnings\n\n"}
    for name, text in seed.items():
        path = os.path.join(ws, "memory", name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    with open(os.path.join(ws, "mcp.json"), "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"unbound": {"command": sys.executable,
                                              "args": [os.path.join(REPO, "bridge", "mcp_server.py")],
                                              "env": {"UNBOUND_LOG": os.path.join(ws, "log.jsonl"),
                                                      "UNBOUND_DIFFICULTY": difficulty}}}}, f)
    if fresh:  # the only path that stops an emulator, and only on an explicit --fresh
        subprocess.run(["taskkill", "/IM", "mGBA.exe", "/F"], capture_output=True)
        time.sleep(2)
        sav = os.path.join(REPO, "run", "Unbound.sav")
        if os.path.exists(sav):
            os.replace(sav, sav + f".{int(time.time())}.bak")
        # baseline.ss1 starts past the intro on Vanilla (the difficulty is chosen in the intro): an Expert run needs
        # its own start state, made by the human (run/baseline_expert.ss1, #162).
        launch.launch(baseline or os.path.join(REPO, "run", "baseline.ss1"))
    elif not reloaded and not launch.mgba_running():  # reloaded: the runner re-exec'd itself, attach as is
        # The emulator went down: resume from the newest autosave, not the last in-game save
        # (losing 40 minutes of play to a closed emulator is how this was learned). A running one, even
        # paused or not serving, is never restarted: launch() attaches or refuses.
        saves = sorted(glob.glob(os.path.join(ws, "autosaves", "*.ss1")), key=os.path.getmtime)
        launch.launch(saves[-1] if saves else None)
        print("relaunched mGBA from", saves[-1] if saves else "the in-game save")
    # Rolling savestate every 18000 frames (bridge-side, runs between chunks too): at the 2x cap that's every
    # 2.5 minutes, so 240 kept (~10 MB) is ~10 hours to roll back through.
    os.makedirs(os.path.join(ws, "autosaves"), exist_ok=True)
    Probe().autosave(os.path.join(ws, "autosaves"), 18000, 240)


def chunk(ws, first, prompt_next, prompt_first=FIRST):
    # Refreshed every chunk: instruction fixes reach a long run without restarting the runner.
    shutil.copy(os.path.join(REPO, "agent", "CLAUDE.md"), os.path.join(ws, "CLAUDE.md"))
    # Re-read every chunk, so the router model can change mid-run without restarting the runner.
    override = os.path.join(ws, "model.txt")
    model = open(override).read().strip() if os.path.exists(override) else MAIN_MODEL
    print(f"  model: {model}")
    args = [CLAUDE, "-p", prompt_first if first else prompt_next, "--model", model,
            "--mcp-config", "mcp.json", "--strict-mcp-config",
            "--agents", open(os.path.join(REPO, "agent", "agents.json"), encoding="utf-8").read(),
            "--allowedTools", *TOOLS, "--disallowedTools", *BLOCKED, "--output-format", "stream-json", "--verbose"]
    if not first:
        args.insert(3, "--continue")
    os.makedirs(os.path.join(ws, "transcripts"), exist_ok=True)
    started = time.time()
    result = None
    with open(os.path.join(ws, "transcripts", f"{int(started)}.jsonl"), "w", encoding="utf-8") as out:
        proc = subprocess.Popen(args, cwd=ws, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace")
        context = 0
        tokens = {}  # model -> token counts, for chunks that end without a result event (rotation)
        for line in proc.stdout:
            out.write(line)
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "user" and context > CONTEXT_LIMIT and last_mode(ws) == "overworld":
                # Every turn re-reads the whole conversation (#54: ~300k tokens a turn after 400 actions).
                # Between actions and out of battle, end the chunk; the next one starts fresh from memory/.
                print(f"  context {context // 1000}k > {CONTEXT_LIMIT // 1000}k: rotating to a fresh session")
                proc.terminate()
                proc.wait()
                return ({"rotated": True, "result": f"rotated at {context} context tokens", "usage": tokens,
                         "total_cost_usd": None}, time.time() - started)
            if ev.get("type") == "assistant":
                u = ev["message"].get("usage") or {}
                context = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                          "cache_creation_input_tokens"))
                t = tokens.setdefault(ev["message"].get("model", "?"), {})
                for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"):
                    t[k] = t.get(k, 0) + (u.get(k, 0) or 0)
                for block in ev["message"].get("content", []):
                    if block.get("type") == "text" and block["text"].strip():
                        print("  agent:", block["text"].strip()[:300])
                    elif block.get("type") == "tool_use":
                        print("  tool:", block["name"].replace("mcp__unbound__", ""), json.dumps(block["input"])[:120])
            elif ev.get("type") == "result":
                result = ev
        proc.wait()
    return result or {"is_error": True, "result": f"no result (exit {proc.returncode})"}, time.time() - started


def last_mode(ws):
    """Mode after the agent's latest action, from the MCP action log ("" if unknown)."""
    try:
        with open(os.path.join(ws, "log.jsonl"), "rb") as f:
            f.seek(max(0, os.path.getsize(f.name) - 4000))
            lines = [l for l in f.read().decode("utf-8", "replace").splitlines() if '"now"' in l]
        return json.loads(lines[-1])["now"]["mode"] if lines else ""
    except (OSError, ValueError, KeyError):
        return ""


def chunk_cost(cost, prev):
    """A chunk's own cost from the session's running total COST (claude -p reports the whole resumed session's cost,
    not the chunk's: chunk 389 said $9.6197, chunk 390 $9.6304, i.e. $0.01). PREV is the running total after the
    session's previous chunk; a lower total means a new session. ponytail: a new session that is costlier than the
    old one's total at its first chunk is under-counted by that total; the runner marks session starts from now on."""
    return cost - prev if cost >= prev else cost


def spent_so_far(usage_log):
    """True API-equivalent spend so far: each chunk's own cost (chunk_cost), plus harness calls (additive)."""
    total, prev = 0.0, 0.0
    if os.path.exists(usage_log):
        for line in open(usage_log, encoding="utf-8"):
            e = json.loads(line)
            c = e.get("cost_usd") or 0
            if e.get("kind"):
                total += c
                continue
            if e.get("session_start"):
                prev = 0.0
            if "chunk_cost_usd" in e:
                total += e["chunk_cost_usd"]
            elif c:  # a chunk that errored reports no cost and doesn't end the session
                total += chunk_cost(c, prev)
            prev = c or prev
    return total


def actions(ws):
    """How many game actions the agent has taken (tool results in log.jsonl)."""
    try:
        with open(os.path.join(ws, "log.jsonl"), encoding="utf-8", errors="replace") as f:
            return sum('"result"' in line for line in f)
    except OSError:
        return 0


def milestone():
    try:
        s = get_state(Probe())
        return {"badges": s["badges"], "map": s["map"]["name"], "pos": s["pos"], "party": [m["hp"] for m in s["party"]]}
    except Exception as e:  # the emulator may be restarting
        return {"error": repr(e)}


def limit_wait(text):
    """Seconds to wait if the usage window is exhausted, else None."""
    if "limit" not in text.lower():
        return None
    m = re.search(r"\|(\d{10})", text)  # some versions print "...limit reached|<epoch>"
    return max(60, int(m.group(1)) - time.time() + 60) if m else 15 * 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default=os.environ.get("UNBOUND_WORKSPACE", r"D:\ClaudeUnboundRuns\current"))
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--bootstrap-from")
    ap.add_argument("--new-session", action="store_true",
                    help="start a new conversation (memory/ carries state) instead of --continue")
    ap.add_argument("--budget-usd", type=float, default=50.0,
                    help="stop when this launch's API-equivalent spend passes this (default $50; history doesn't count)")
    ap.add_argument("--idle-chunks", type=int, default=3,
                    help="stop when this many chunks in a row take no game action (the agent stopped playing)")
    ap.add_argument("--goal-badges", type=int, default=1)
    ap.add_argument("--baseline", help="start state for --fresh (default run/baseline.ss1, a Vanilla start; Expert: "
                    "run/baseline_expert.ss1)")
    ap.add_argument("--difficulty", choices=["vanilla", "difficult", "expert", "insane"],
                    help="the run's difficulty (remembered in the workspace's run.json; default: what it says, else vanilla)")
    ap.add_argument("--max-chunks", type=int, default=1000)
    ap.add_argument("--reloaded", action="store_true", help=argparse.SUPPRESS)  # set by the self-reload below
    a = ap.parse_args()
    if a.fresh and os.path.exists(os.path.join(a.workspace, "transcripts")):
        sys.exit(f"{a.workspace} already has a run; pick a new --workspace for a fresh run")
    difficulty = difficulty_of(a.workspace, a.difficulty)
    if a.fresh and difficulty != "vanilla" and not a.baseline:
        sys.exit(f"--difficulty {difficulty} needs --baseline: run/baseline.ss1 is past the intro on Vanilla")
    setup(a.workspace, a.fresh, a.bootstrap_from, a.goal_badges, a.reloaded, difficulty, a.baseline)
    usage_log = os.path.join(a.workspace, "usage.jsonl")
    spent = spent_so_far(usage_log)
    budget_end = spent + a.budget_usd  # per launch: a resumed run's history doesn't count against it
    session_total, idle = 0.0, 0
    first = a.fresh or a.new_session or not os.path.exists(usage_log)
    me = os.path.abspath(__file__)
    started = os.path.getmtime(me)
    for n in range(a.max_chunks):
        if os.path.getmtime(me) != started:
            # run.py changed: continue under the new code at this chunk boundary (never --fresh, never relaunching
            # mGBA). A child rather than os.execv: on Windows execv swaps the PID, so whoever watches the runner
            # would see it exit.
            print("run.py changed: reloading the runner", flush=True)
            args = [sys.executable, me, "--workspace", a.workspace, "--budget-usd", str(budget_end - spent),
                    "--idle-chunks", str(a.idle_chunks),
                    "--goal-badges", str(a.goal_badges), "--max-chunks", str(a.max_chunks - n), "--reloaded"]
            sys.exit(subprocess.call(args + (["--new-session"] if first else [])))
        print(f"chunk {n}: {'start' if first else 'continue'} (spent ${spent:.2f} API-equivalent)")
        if first:
            session_total = 0.0
        acted = actions(a.workspace)
        res, secs = chunk(a.workspace, first, NEXT.format(goal=goal_text(a.goal_badges)),
                          FIRST + (BOOTSTRAP if n == 0 and a.fresh and a.bootstrap_from else ""))
        text = str(res.get("result", ""))
        wait = limit_wait(text) if res.get("is_error") else None
        entry = {"t": round(time.time()), "chunk": n, "secs": round(secs), "turns": res.get("num_turns"),
                 "is_error": res.get("is_error"), "usage": res.get("usage"), "cost_usd": res.get("total_cost_usd", 0),
                 "models": res.get("modelUsage"), "milestone": milestone(), "note": text[-300:],
                 "session_start": first, "chunk_cost_usd": chunk_cost(res.get("total_cost_usd", 0) or 0, session_total)}
        session_total = res.get("total_cost_usd", 0) or session_total
        with open(usage_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        spent += entry["chunk_cost_usd"]
        idle = idle + 1 if actions(a.workspace) == acted else 0
        if wait:
            print(f"usage window exhausted; waiting {wait / 60:.0f} min")
            time.sleep(wait)
            continue
        first = bool(res.get("rotated"))  # a rotated chunk continues as a fresh session
        if entry["milestone"].get("badges", 0) >= a.goal_badges:  # badges only: "so no GOAL REACHED" once ended a run at 0 badges
            print("goal reached:", entry["milestone"])
            return
        if spent > budget_end:
            sys.exit(f"budget alarm: ${spent:.2f} API-equivalent spent, this launch's ${a.budget_usd} budget used up")
        if idle >= a.idle_chunks:
            # The agent stopped playing (e.g. "I'm stopping ... I need a hint"): resuming it every few seconds only
            # repeats that (390 chunks, step 6061, #150). Stop and leave it to the operator.
            sys.exit(f"stalled: {idle} chunks in a row without a game action; the agent said: {text[-300:]!r}")
    print("max chunks reached")


if __name__ == "__main__":
    # Redirected to a file, stdout is cp1252 on Windows: an agent message with "→" killed the runner (#147).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    main()
