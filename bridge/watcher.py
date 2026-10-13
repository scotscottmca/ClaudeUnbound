"""Harness-run background reviewers (user, 2026-10-08): learning and verification run in parallel and never
block play.

- watcher: every WATCH_EVERY actions, Haiku reads the recent stretch and returns at most 2 actionable notes, or nothing.
- verifier: every VERIFY_EVERY actions, if anything happened since its last call (eventful()), Sonnet checks recent
  actions, state and objectives.md: OK or one correction.
- memory guard (no model; the curator model it replaced cost ~11% of a run for housekeeping): after each action,
  any line the agent removed from memory/ is appended to memory/archive.md, memory/operator.md is copied from the
  operator's <workspace>/operator.md, and a file over its budget gets a MEMORY note asking the agent to condense it.
- hygiene(): drops a harness note emitted verbatim in the last DEDUPE_WINDOW actions.

Each call is a `claude -p` subprocess in a daemon thread, with a timeout; a failure is logged and dropped. Results
are queued and delivered as harness notes on the agent's next action, tagged with the step they refer to.
Hot reload re-imports this file, so the queues, history and busy flags live in RT: a module object in sys.modules
without __file__, which mcp_server's reload leaves alone. One call per kind at a time, so no threads pile up.
Self-check: python watcher.py (fake claude, temp dirs).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import types

CLAUDE = os.environ.get("UNBOUND_CLAUDE") or shutil.which("claude") or os.path.expanduser(r"~\.local\bin\claude.exe")
MODELS = {"watcher": "claude-haiku-5-5", "verifier": "claude-sonnet-5-5"}
TIMEOUT = {"watcher": 90, "verifier": 150}
# Thinking effort per call (#177: the watcher's output, ~0.40M tokens a run, was nearly all thinking for <=2 notes).
EFFORT = {"watcher": "low"}
WATCH_EVERY, VERIFY_EVERY = 10, 40
DEDUPE_WINDOW = 10
# Never deduped: WATCHDOG and prompts that need an answer; ITEM/MISSED already fire once per item, door or visit.
DEDUPE_EXEMPT = ("WATCHDOG", "VERIFY before answering", "FORCED SWITCH", "ITEM", "MISSED")
HARNESS_OWNED = {"todo.md", "archive.md", "operator.md"}  # written by the harness, not the agent
NAG_EVERY = 25  # actions between MEMORY notes about the same oversized file
# characters; the other files went 8000 -> 5000 (#175: memory is re-read every chunk; trimmed lines go to archive.md)
FILE_BUDGET, OBJECTIVES_BUDGET = 5000, 2000

RT = sys.modules.get("_unbound_watcher_rt")
if RT is None:
    RT = sys.modules["_unbound_watcher_rt"] = types.ModuleType("_unbound_watcher_rt")
    RT.inbox = []  # (kind, step, text) awaiting delivery
    RT.logs = []  # log.jsonl entries from worker threads, written by the main thread in drain()
    RT.busy = set()  # kinds with a call in flight
    RT.seen = {}  # harness note -> step it was last emitted
    RT.badges = None

POLICY = ("Policy: explore every building; talk to each NPC and read each sign once; record facts in memory/; "
          "heal before grass or caves; cure status and restock at Marts; battle and catch new wild species; rename "
          "captures; use type matchups and switch; record opponents and items.")
SYSTEM = {
    "watcher": "You watch an AI agent playing Pokemon Unbound (a FireRed romhack) and catch actionable mistakes. "
               + POLICY + " Reply NONE, or at most 2 lines, each 'NOTE: <under 25 words>', concrete (name the place, "
               "Pokemon, item or coordinates) and actionable now. No praise, no restating what it already does. "
               "When unsure, NONE.",
    "verifier": "You verify an AI agent playing Pokemon Unbound (a FireRed romhack) against the game state. "
                + POLICY + " Look for beliefs the state contradicts, loops or wasted actions, policy misses, and "
                "objectives that are done or wrong. Reply exactly OK if nothing needs correcting, else one line "
                "'FIX: <concrete correction, under 40 words>'.",
}


def enabled(ws):
    """Only in a runner workspace (it has memory/), and not when switched off (UNBOUND_WATCHER=off)."""
    return os.environ.get("UNBOUND_WATCHER", "on") != "off" and os.path.isdir(os.path.join(ws, "memory"))


# --- prompt material ---------------------------------------------------------------------

def tail(log_path):
    """The parsed entries of log.jsonl's last 120 kB."""
    try:
        with open(log_path, "rb") as f:
            f.seek(max(0, os.path.getsize(log_path) - 120_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


ROUTINE = ("LEARNING CHECK", "VERIFIER")  # notes that come every stretch (or from the verifier itself): not news


def eventful(log_path, since):
    """Anything for the verifier to judge after step SINCE (#172): a harness note (milestone, watchdog, watcher note,
    item, low HP...), a map change, or a battle ending."""
    prev = None
    for d in tail(log_path):
        now = d.get("now")
        if "tool" not in d or not isinstance(now, dict):
            continue
        key = (json.dumps(now.get("map_id") or now.get("map")), now.get("mode"))
        if (d.get("step") or 0) > since:
            if any(not str(h).startswith(ROUTINE) for h in d.get("harness") or []):
                return True
            if prev and (key[0] != prev[0] or (prev[1] == "battle" and key[1] != "battle")):
                return True
        prev = key
    return False


def recent(log_path, n):
    """The last N agent actions from log.jsonl, one short line each."""
    out = []
    for d in tail(log_path):
        if "tool" not in d or d.get("tool") in ("get_state", "get_screenshot"):
            continue
        now = d.get("now") or {}
        out.append(f"{d.get('step')} {d['tool']} {json.dumps(d.get('args'), ensure_ascii=False)[:80]}"
                   + (f" -> {str(d['result'])[:160]}" if "result" in d else "")
                   + (f" | {now.get('mode')} {now.get('map')} {now.get('pos')}" if now else "")
                   + (f" | harness: {'; '.join(h[:90] for h in d['harness'])}" if d.get("harness") else ""))
    return "\n".join(out[-n:])


def brief(s):
    """get_state condensed (no map view, no screenshot)."""
    if not isinstance(s, dict):
        return str(s)[:600]
    party = [f"{m.get('name')} ({m.get('species')} Lv{m.get('level')}) {m.get('hp')}"
             + (f" {m['status']}" if m.get("status") else "") + (f" @{m['item']}" if m.get("item") else "")
             + (f" [{', '.join(m['moves'])}]" if m.get("moves") else "") for m in s.get("party", [])]
    bag = {k: v for k, v in (s.get("bag") or {}).items() if v}
    b = s.get("battle") or {}
    lines = [f"mode {s.get('mode')}, map {(s.get('map') or {}).get('name')} {s.get('pos')}, badges {s.get('badges')}, "
             f"money {s.get('money')}", "party: " + "; ".join(party), "bag: " + json.dumps(bag, ensure_ascii=False)[:500]]
    if s.get("dialog"):
        lines.append("dialog: " + str(s["dialog"])[:200])
    if b:
        lines.append("battle: " + "; ".join(f"{x.get('side')} {x.get('name')} Lv{x.get('level')} {x.get('hp')}"
                                             for x in b.get("battlers", [])) + f" | {str(b.get('text') or '')[:120]}")
    return "\n".join(lines)


def objectives(ws):
    try:
        return open(os.path.join(ws, "memory", "objectives.md"), encoding="utf-8", errors="replace").read()[:2500]
    except OSError:
        return "(none)"


# --- calls -------------------------------------------------------------------------------

def ask(kind, prompt, cwd=None, tools=()):
    """One `claude -p` call. Returns (text, meta). Raises on failure or timeout."""
    args = ([sys.executable] if CLAUDE.endswith(".py") else []) + [
        CLAUDE, "-p", "--model", MODELS[kind], "--output-format", "json", "--no-session-persistence",
        "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "", "--restricted",
        "--system-prompt", SYSTEM[kind], "--tools", ",".join(tools)]
    if kind in EFFORT:
        args += ["--effort", EFFORT[kind]]
    if tools:
        args += ["--allowedTools", *tools]
    t0 = time.time()
    r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=TIMEOUT[kind], cwd=cwd or os.path.dirname(os.path.abspath(__file__)),
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = json.loads(r.stdout)  # the CLI prints one JSON object (also on API errors)
    if out.get("is_error") or r.returncode:
        raise RuntimeError(f"exit {r.returncode}: {str(out.get('result'))[:200]}")
    u = out.get("usage") or {}
    meta = {"secs": round(time.time() - t0, 1), "cost_usd": out.get("total_cost_usd"),
            "tokens": {k: u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens", "output_tokens")},
            "models": out.get("modelUsage")}
    return str(out.get("result") or "").strip(), meta


def record(ws, entry, direct=False):
    """Usage line now; the log.jsonl line queued for the main thread (or written now, from the runner)."""
    entry = {"t": round(time.time(), 1), **entry}
    try:  # one writer at a time: two threads appending at once on Windows lost a line (the self-check's flake)
        with RT.__dict__.setdefault("usage_lock", threading.Lock()), \
                open(os.path.join(ws, "usage.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(entry["t"]), "kind": entry["harness_call"], "model": entry.get("model"),
                                "secs": entry.get("secs"), "cost_usd": entry.get("cost_usd") or 0,
                                "usage": entry.get("tokens"), "models": entry.pop("models", None)}) + "\n")
    except OSError:
        pass
    entry.pop("models", None)
    if direct:
        with open(os.path.join(ws, "log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    else:
        RT.logs.append(entry)


def review(kind, step, s, ws):
    """Watcher or verifier: build the prompt, ask, queue any note."""
    n = 12 if kind == "watcher" else 20
    prompt = (f"Recent actions (step, tool, args -> result | after | harness notes):\n"
              f"{recent(os.path.join(ws, 'log.jsonl'), n)}\n\nState now (step {step}):\n{brief(s)}\n\n"
              f"memory/objectives.md:\n{objectives(ws)}")
    entry = {"step": step, "harness_call": kind, "model": MODELS[kind]}
    try:
        text, meta = ask(kind, prompt)
        entry.update(meta)
        if kind == "watcher":
            notes = [ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.strip().upper().startswith("NOTE:")][:2]
        else:
            fix = next((ln for ln in text.splitlines() if ln.strip().upper().startswith("FIX:")), None)
            notes = [fix.split(":", 1)[1].strip()] if fix else []
        entry["note"] = " | ".join(notes) or ("OK" if kind == "verifier" else "")
        RT.inbox.extend((kind, step, x) for x in notes if x)
    except Exception as e:  # never reaches play: logged and dropped
        entry["error"] = repr(e)[:300]
    record(ws, entry)


def spawn(kind, fn, *args):
    if kind in RT.busy:  # the previous call of this kind is still running: skip, don't queue
        return False
    RT.busy.add(kind)

    def run():
        try:
            fn(*args)
        finally:
            RT.busy.discard(kind)
    threading.Thread(target=run, daemon=True, name=f"harness-{kind}").start()
    return True


def tick(step, s, log_path):
    """After each agent action (main thread; returns at once)."""
    ws = os.path.dirname(os.path.abspath(log_path))
    if not enabled(ws):
        return
    if step and step % WATCH_EVERY == 0:
        spawn("watcher", review, "watcher", step, s, ws)
    # Every VERIFY_EVERY actions, and only if something happened since the last verification (#172: at every 20
    # it was 334 calls, ~8% of a run's cost). A skipped stretch is judged with the next one.
    if step and step % VERIFY_EVERY == 0 and eventful(log_path, getattr(RT, "verified", 0)):
        if spawn("verifier", review, "verifier", step, s, ws):
            RT.verified = step
    guard(ws, step)


def drain(log_fn=None):
    """Main thread: write queued log lines, return queued notes as harness note strings."""
    while RT.logs:
        e = RT.logs.pop(0)
        if log_fn:
            log_fn(e)
    out = []
    while RT.inbox:
        kind, step, text = RT.inbox.pop(0)
        out.append(f"WATCHER (step {step}): {text}" if kind == "watcher" else f"VERIFIER (as of step {step}): {text}"
                   if kind == "verifier" else f"OPERATOR HINT (new, pinned in memory/operator.md; true, act on it): {text}"
                   if kind == "operator" else f"MEMORY: {text}")
    return out


def hygiene(step, msgs):
    """Drop a note emitted verbatim in the last DEDUPE_WINDOW actions (exempt prefixes always pass)."""
    out = []
    for m in msgs:
        if not m.startswith(DEDUPE_EXEMPT) and (m in out or step - RT.seen.get(m, -10**9) <= DEDUPE_WINDOW):
            continue
        RT.seen[m] = step
        out.append(m)
    for m in [m for m, t in RT.seen.items() if step - t > DEDUPE_WINDOW]:
        del RT.seen[m]
    return out


# --- memory guard -----------------------------------------------------------------------------

def snapshot(mem):
    out = {}
    for name in sorted(os.listdir(mem)):
        if name.endswith(".md") and name not in HARNESS_OWNED:
            out[name] = open(os.path.join(mem, name), encoding="utf-8", errors="replace").read()
    return out


def archive_lost(mem, before):
    """Every non-blank line of BEFORE found nowhere in memory/ any more is appended to archive.md. Returns the count."""
    arch = os.path.join(mem, "archive.md")
    have = list(snapshot(mem).values()) + [open(arch, encoding="utf-8").read() if os.path.exists(arch) else ""]
    keep = {ln.strip() for t in have for ln in t.splitlines()}
    lost = {n: [ln for ln in t.splitlines() if ln.strip() and ln.strip() not in keep] for n, t in before.items()}
    lost = {n: v for n, v in lost.items() if v}
    if lost:
        with open(arch, "a", encoding="utf-8") as f:
            for n, v in lost.items():
                f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}: dropped from {n} (kept by the harness)\n"
                        + "\n".join(v) + "\n")
    return sum(map(len, lost.values()))


FORBIDDEN = "walkthrough_seen.txt"  # in the workspace, outside memory/: every walkthrough excerpt the agent was shown
SHINGLE = 5  # a memory line sharing a run of this many words with an excerpt counts as copied from it


def shingles(text):
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def forbid(ws, text):
    """Record a walkthrough excerpt shown to the agent: guard() deletes memory lines copied from it (user rule:
    nothing gleaned from the walkthrough may be written to memory)."""
    with open(os.path.join(ws, FORBIDDEN), "a", encoding="utf-8") as f:
        f.write(text + "\n\n")


def purge_forbidden(ws, old, step):
    """Delete lines newly written to memory/ (not in the OLD snapshot) that copy a walkthrough excerpt; archive.md's
    new tail too. Returns the number deleted. ponytail: catches copying, not paraphrase; the agent is told the rule."""
    src = os.path.join(ws, FORBIDDEN)
    if not os.path.exists(src):
        return 0
    if getattr(RT, "forbidden_mtime", None) != os.path.getmtime(src):
        RT.forbidden, RT.forbidden_mtime = shingles(open(src, encoding="utf-8").read()), os.path.getmtime(src)
    mem, gone = os.path.join(ws, "memory"), 0
    for name in sorted(os.listdir(mem)):
        if not name.endswith(".md") or name in ("operator.md", "todo.md"):
            continue
        path = os.path.join(mem, name)
        text = open(path, encoding="utf-8", errors="replace").read()
        before = set((old or {}).get(name, "").splitlines()) if name != "archive.md" else \
            set(text[:getattr(RT, "archive_len", len(text))].splitlines())
        keep = [ln for ln in text.splitlines() if ln in before or not (shingles(ln) & RT.forbidden)]
        if len(keep) < len(text.splitlines()):
            gone += len(text.splitlines()) - len(keep)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(keep) + ("\n" if text.endswith("\n") else ""))
    arch = os.path.join(mem, "archive.md")
    RT.archive_len = os.path.getsize(arch) if os.path.exists(arch) else 0
    if gone:
        RT.inbox.append(("memory", step, f"deleted {gone} line(s) copied from the walkthrough. Nothing from it may be "
                         "written to memory/ (operator rule): record only what you verify yourself in play, in your own words."))
    return gone


def guard(ws, step=0):
    """Main thread, after each action: nothing the agent deletes from memory/ is lost, the operator's hints stay
    pinned, and an oversized file gets one MEMORY note per NAG_EVERY actions.
    ponytail: a line the agent merely edits (a count) is archived in its old form too; the archive is never read in
    play, so noise there is harmless."""
    mem = os.path.join(ws, "memory")
    try:
        src, dst = os.path.join(ws, "operator.md"), os.path.join(mem, "operator.md")
        if os.path.exists(src):
            want = open(src, encoding="utf-8").read()
            if not os.path.exists(dst) or open(dst, encoding="utf-8").read() != want:
                open(dst, "w", encoding="utf-8").write(want)
            hints = {ln for ln in want.splitlines() if ln.strip() and not ln.startswith("#")}
            if getattr(RT, "hints", None) is None:
                RT.hints = hints  # first look: these are read at session start
            new = sorted(hints - RT.hints, key=want.index)
            if new:  # a hint added mid-session reaches the agent now, not only at its next session start
                RT.inbox.append(("operator", step, " | ".join(new)))
                RT.hints |= hints
        if getattr(RT, "mem", None) is not None:
            archive_lost(mem, RT.mem)
        purge_forbidden(ws, getattr(RT, "mem", None), step)  # before the snapshot: a deleted copy is never archived
        RT.mem = now = snapshot(mem)
        nagged = RT.__dict__.setdefault("nagged", {})
        for name, text in now.items():
            budget = OBJECTIVES_BUDGET if name == "objectives.md" else FILE_BUDGET
            if len(text) > budget and step - nagged.get(name, -10**9) >= NAG_EVERY:
                nagged[name] = step
                RT.inbox.append(("memory", step, f"{name} is {len(text)} characters (budget {budget}): condense it "
                                 "now. Merge duplicates, fold done items into one 'Done:' line, drop detail you won't "
                                 "need. Deleted lines are archived automatically (memory/archive.md)."))
    except OSError as e:
        RT.logs.append({"step": step, "error": f"memory guard: {e!r}"})


if __name__ == "__main__":  # offline self-check with a fake claude
    import tempfile
    tmp = tempfile.mkdtemp(prefix="watcher-check-")
    fake = os.path.join(tmp, "fake_claude.py")
    with open(fake, "w") as f:
        # the effort flag is checked too (#177): low for the watcher, none (the CLI default) for the verifier
        f.write("import json, os, sys\nsys.stdin.read()\nm = sys.argv[sys.argv.index('--model') + 1]\n"
                "e = sys.argv[sys.argv.index('--effort') + 1] if '--effort' in sys.argv else None\n"
                "r = ('NOTE: heal Ion' if e == 'low' else 'NOTE: wrong effort') if 'haiku' in m else "
                "('FIX: objectives are stale' if e is None else 'FIX: wrong effort')\n"
                "print(json.dumps({'result': r, 'is_error': False, 'total_cost_usd': 0.001, 'usage': {'output_tokens': 5}}))\n")
    CLAUDE = fake
    ws = os.path.join(tmp, "ws")
    os.makedirs(os.path.join(ws, "memory"))
    with open(os.path.join(ws, "memory", "objectives.md"), "w") as f:
        f.write("# Objectives\nNow: beat Vega\n- old: reach Crater Town\n")
    with open(os.path.join(ws, "memory", "todo.md"), "w") as f:
        f.write("harness owned\n")
    V = VERIFY_EVERY
    with open(os.path.join(ws, "log.jsonl"), "w") as f:
        f.write(json.dumps({"step": V, "tool": "walk_to", "args": {"x": 1, "y": 2}, "result": "done",
                            "now": {"mode": "overworld", "map": "X", "pos": [1, 2]}, "harness": ["ITEM: x"]}) + "\n")
    s = {"mode": "overworld", "map": {"name": "X"}, "pos": [1, 2], "badges": 1, "party": []}
    tick(V, s, os.path.join(ws, "log.jsonl"))
    for _ in range(100):
        if not RT.busy:
            break
        time.sleep(0.1)
    logged = []
    got = drain(logged.append)
    assert sorted(got) == [f"VERIFIER (as of step {V}): objectives are stale", f"WATCHER (step {V}): heal Ion"], got
    assert {e["harness_call"] for e in logged} == {"watcher", "verifier"} and all("cost_usd" in e for e in logged), logged
    kinds = [json.loads(ln)["kind"] for ln in open(os.path.join(ws, "usage.jsonl"))]
    assert sorted(kinds) == ["verifier", "watcher"], kinds
    # memory guard: the agent drops a line and tampers with the pinned hints; objectives.md outgrows its budget
    with open(os.path.join(ws, "operator.md"), "w") as f:
        f.write("- hint\n")
    with open(os.path.join(ws, "memory", "objectives.md"), "w") as f:
        f.write("# Objectives\nNow: beat Vega\n" + "x" * OBJECTIVES_BUDGET + "\n")
    with open(os.path.join(ws, "memory", "operator.md"), "w") as f:
        f.write("agent was here\n")
    guard(ws, 21)
    assert "- old: reach Crater Town" in open(os.path.join(ws, "memory", "archive.md")).read()
    assert open(os.path.join(ws, "memory", "operator.md")).read() == "- hint\n"
    got = drain()
    assert len(got) == 1 and got[0].startswith("MEMORY: objectives.md is "), got
    guard(ws, 22)
    assert drain() == []  # not again until NAG_EVERY actions later
    assert hygiene(30, ["A", "WATCHDOG: x"]) == ["A", "WATCHDOG: x"]
    assert hygiene(31, ["A", "WATCHDOG: x", "B"]) == ["WATCHDOG: x", "B"]
    assert hygiene(42, ["A"]) == ["A"]
    print("watcher self-check ok")
