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
from probe import Probe  # noqa: E402
from state import get_state  # noqa: E402

CLAUDE = shutil.which("claude") or os.path.expanduser(r"~\.local\bin\claude.exe")
CONTEXT_LIMIT = 160_000  # rotate to a fresh session past this (tokens re-read every turn)
MAIN_MODEL = "claude-sonnet-5-5"  # the router: escalates to Opus 5.5 / Fable 5.1 subagents
TOOLS = ["mcp__unbound", "Read", "Write", "Edit", "Glob", "Grep", "Task", "Agent"]
MEMORY_SEED = {"objectives.md": "# Objectives\n\n- Goal: earn the first badge (Dresco Town gym).\n- Next: find out where I am and what the current mission says.\n",
               "learnings.md": "# Learnings\n\n"}
FIRST = "Start playing. Read memory/ first, then get_state."
NEXT = ("Continue playing toward the goal. Keep going for a good stretch (~100 actions) before you stop; "
        "update memory/objectives.md before you do. If you have earned the first badge, say GOAL REACHED.")


def setup(ws, fresh, bootstrap):
    os.makedirs(os.path.join(ws, "memory"), exist_ok=True)
    shutil.copy(os.path.join(REPO, "agent", "CLAUDE.md"), os.path.join(ws, "CLAUDE.md"))
    if bootstrap:
        shutil.copytree(os.path.join(bootstrap, "memory"), os.path.join(ws, "memory"), dirs_exist_ok=True)
    for name, text in MEMORY_SEED.items():
        path = os.path.join(ws, "memory", name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    with open(os.path.join(ws, "mcp.json"), "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"unbound": {"command": sys.executable,
                                              "args": [os.path.join(REPO, "bridge", "mcp_server.py")],
                                              "env": {"UNBOUND_LOG": os.path.join(ws, "log.jsonl")}}}}, f)
    if fresh:
        subprocess.run(["taskkill", "/IM", "mGBA.exe", "/F"], capture_output=True)
        time.sleep(2)
        sav = os.path.join(REPO, "run", "Unbound.sav")
        if os.path.exists(sav):
            os.replace(sav, sav + f".{int(time.time())}.bak")
        launch.launch(os.path.join(REPO, "run", "baseline.ss1"))
    elif not launch.serving():
        # The emulator went down: resume from the newest autosave, not the last in-game save
        # (losing 40 minutes of play to a closed emulator is how this was learned).
        saves = sorted(glob.glob(os.path.join(ws, "autosaves", "*.ss1")), key=os.path.getmtime)
        launch.launch(saves[-1] if saves else None)
        print("relaunched mGBA from", saves[-1] if saves else "the in-game save")
    # Rolling savestate every 5 minutes of game time, last 12 kept (bridge-side, runs between chunks too).
    os.makedirs(os.path.join(ws, "autosaves"), exist_ok=True)
    Probe().autosave(os.path.join(ws, "autosaves"), 18000, 12)


def chunk(ws, first):
    # Re-read every chunk, so the router model can change mid-run without restarting the runner.
    override = os.path.join(ws, "model.txt")
    model = open(override).read().strip() if os.path.exists(override) else MAIN_MODEL
    print(f"  model: {model}")
    args = [CLAUDE, "-p", FIRST if first else NEXT, "--model", model,
            "--mcp-config", "mcp.json", "--strict-mcp-config",
            "--agents", open(os.path.join(REPO, "agent", "agents.json"), encoding="utf-8").read(),
            "--allowedTools", *TOOLS, "--output-format", "stream-json", "--verbose"]
    if not first:
        args.insert(3, "--continue")
    os.makedirs(os.path.join(ws, "transcripts"), exist_ok=True)
    started = time.time()
    result = None
    with open(os.path.join(ws, "transcripts", f"{int(started)}.jsonl"), "w", encoding="utf-8") as out:
        proc = subprocess.Popen(args, cwd=ws, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace")
        context = 0
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
                return {"rotated": True, "result": f"rotated at {context} context tokens"}, time.time() - started
            if ev.get("type") == "assistant":
                u = ev["message"].get("usage") or {}
                context = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_read_input_tokens",
                                                          "cache_creation_input_tokens"))
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
    ap.add_argument("--budget-usd", type=float, default=float("inf"), help="pause when API-equivalent cost passes this")
    ap.add_argument("--goal-badges", type=int, default=1)
    ap.add_argument("--max-chunks", type=int, default=1000)
    a = ap.parse_args()
    if a.fresh and os.path.exists(os.path.join(a.workspace, "transcripts")):
        sys.exit(f"{a.workspace} already has a run; pick a new --workspace for a fresh run")
    setup(a.workspace, a.fresh, a.bootstrap_from)
    usage_log = os.path.join(a.workspace, "usage.jsonl")
    spent = sum(json.loads(l).get("cost_usd") or 0 for l in open(usage_log, encoding="utf-8")) if os.path.exists(usage_log) else 0
    first = a.fresh or a.new_session or not os.path.exists(usage_log)
    for n in range(a.max_chunks):
        print(f"chunk {n}: {'start' if first else 'continue'} (spent ${spent:.2f} API-equivalent)")
        res, secs = chunk(a.workspace, first)
        text = str(res.get("result", ""))
        wait = limit_wait(text) if res.get("is_error") else None
        entry = {"t": round(time.time()), "chunk": n, "secs": round(secs), "turns": res.get("num_turns"),
                 "is_error": res.get("is_error"), "usage": res.get("usage"), "cost_usd": res.get("total_cost_usd", 0),
                 "models": res.get("modelUsage"), "milestone": milestone(), "note": text[-300:]}
        with open(usage_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        spent += entry["cost_usd"] or 0
        if wait:
            print(f"usage window exhausted; waiting {wait / 60:.0f} min")
            time.sleep(wait)
            continue
        first = bool(res.get("rotated"))  # a rotated chunk continues as a fresh session
        if entry["milestone"].get("badges", 0) >= a.goal_badges or "GOAL REACHED" in text:
            print("goal reached:", entry["milestone"])
            return
        if spent > a.budget_usd:
            sys.exit(f"budget alarm: ${spent:.2f} API-equivalent > ${a.budget_usd}")
    print("max chunks reached")


if __name__ == "__main__":
    main()
