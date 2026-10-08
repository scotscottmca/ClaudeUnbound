"""Harness-run background reviewers (user, 2026-10-08): learning and verification run in parallel and never
block play.

- watcher: every WATCH_EVERY actions, Haiku reads the recent stretch and returns at most 2 actionable notes, or nothing.
- verifier: every VERIFY_EVERY actions, Sonnet checks recent actions, state and objectives.md: OK or one correction.
- curator: at a context rotation (agent/run.py, game idle) and on a new badge, Sonnet tidies memory/ with file
  tools only. Nothing is lost: any line that vanished is appended to memory/archive.md by the harness itself.
- hygiene(): drops a harness note emitted verbatim in the last DEDUPE_WINDOW actions.

Each call is a `claude -p` subprocess in a daemon thread, with a timeout; a failure is logged and dropped. Results
are queued and delivered as harness notes on the agent's next action, tagged with the step they refer to.
Hot reload re-imports this file, so the queues, history and busy flags live in RT: a module object in sys.modules
without __file__, which mcp_server's reload leaves alone. One call per kind at a time, so no threads pile up.
Self-check: python watcher.py (fake claude, temp dirs).
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types

CLAUDE = os.environ.get("UNBOUND_CLAUDE") or shutil.which("claude") or os.path.expanduser(r"~\.local\bin\claude.exe")
MODELS = {"watcher": "claude-haiku-5-5", "verifier": "claude-sonnet-5-5", "curator": "claude-sonnet-5-5"}
TIMEOUT = {"watcher": 90, "verifier": 150, "curator": 240}
WATCH_EVERY, VERIFY_EVERY = 10, 20
DEDUPE_WINDOW = 10
# Never deduped: WATCHDOG and prompts that need an answer; ITEM/MISSED already fire once per item, door or visit.
DEDUPE_EXEMPT = ("WATCHDOG", "VERIFY before answering", "FORCED SWITCH", "ITEM", "MISSED")
HARNESS_OWNED = {"todo.md", "archive.md", "operator.md"}  # the curator never edits these; todo.md and operator.md are put back
FILE_BUDGET, OBJECTIVES_BUDGET = 8000, 2000  # characters

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
    "curator": "You curate the memory files of an AI agent playing Pokemon Unbound. Work only on the .md files in "
               "the current directory, with Read/Write/Edit/Glob. NEVER delete information: whatever you remove "
               "from a file, append it verbatim to archive.md under a heading '## <what> (archived)'. Never edit "
               "todo.md or operator.md (the operator's hints: pinned) and never rewrite archive.md (append only). Tasks: 1) merge "
               "duplicate entries; 2) fold resolved TODOs and done objectives into one short 'Done: ...' line; "
               "3) mark beliefs that look stale or contradicted with '(stale?)'; 4) keep each file under "
               f"{FILE_BUDGET} characters by archiving the least useful detail; 5) objectives.md: under "
               f"{OBJECTIVES_BUDGET} characters, a tight 'Now' (1-3 items) and 'Next' (up to 5) list. Be quick: "
               "about a minute. Finish with one line saying what you changed.",
}


def enabled(ws):
    """Only in a runner workspace (it has memory/), and not when switched off (UNBOUND_WATCHER=off)."""
    return os.environ.get("UNBOUND_WATCHER", "on") != "off" and os.path.isdir(os.path.join(ws, "memory"))


# --- prompt material ---------------------------------------------------------------------

def recent(log_path, n):
    """The last N agent actions from log.jsonl, one short line each."""
    try:
        with open(log_path, "rb") as f:
            f.seek(max(0, os.path.getsize(log_path) - 120_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    out = []
    for ln in lines:
        try:
            d = json.loads(ln)
        except ValueError:
            continue
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
    try:
        with open(os.path.join(ws, "usage.jsonl"), "a", encoding="utf-8") as f:
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
    if step and step % VERIFY_EVERY == 0:
        spawn("verifier", review, "verifier", step, s, ws)
    b = s.get("badges") if isinstance(s, dict) else None
    if isinstance(b, int):
        if RT.badges is not None and b > RT.badges:
            spawn("curator", curate, ws, f"badge {b} won", brief(s), step)
        RT.badges = b


def drain(log_fn=None):
    """Main thread: write queued log lines, return queued notes as harness note strings."""
    while RT.logs:
        e = RT.logs.pop(0)
        if log_fn:
            log_fn(e)
    out = []
    while RT.inbox:
        kind, step, text = RT.inbox.pop(0)
        out.append(f"WATCHER (step {step}): {text}" if kind == "watcher" else f"VERIFIER (as of step {step}): {text}")
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


# --- curator -----------------------------------------------------------------------------

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
                f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M')}: dropped from {n} by the curator (kept by the harness)\n"
                        + "\n".join(v) + "\n")
    return sum(map(len, lost.values()))


def curate(ws, reason, context="", step=None, direct=False):
    """Tidy WS/memory with the curator model; whatever happens, nothing in memory/ is lost."""
    mem = os.path.join(ws, "memory")
    before = snapshot(mem)
    pinned = {n: open(os.path.join(mem, n), encoding="utf-8").read() for n in ("todo.md", "operator.md")
              if os.path.exists(os.path.join(mem, n))}
    sizes = ", ".join(f"{n} {len(t)}" for n, t in before.items())
    entry = {"step": step, "harness_call": "curator", "model": MODELS["curator"], "reason": reason}
    try:
        text, meta = ask("curator", f"Curate memory now ({reason}). Files and sizes in characters: {sizes}.\n"
                                    f"Game state:\n{context}", cwd=mem, tools=("Read", "Write", "Edit", "Glob"))
        entry.update(meta, note=" ".join(text.split())[:600] if text else "")
    except Exception as e:
        entry["error"] = repr(e)[:300]
    try:
        entry["archived_lines"] = archive_lost(mem, before)
        for n, t in pinned.items():
            if open(os.path.join(mem, n), encoding="utf-8").read() != t:
                open(os.path.join(mem, n), "w", encoding="utf-8").write(t)  # harness-owned: put it back
    except OSError as e:
        entry["error"] = (entry.get("error", "") + f" archive: {e!r}").strip()
    record(ws, entry, direct)
    return entry


if __name__ == "__main__":  # offline self-check with a fake claude
    import tempfile
    tmp = tempfile.mkdtemp(prefix="watcher-check-")
    fake = os.path.join(tmp, "fake_claude.py")
    with open(fake, "w") as f:
        f.write("import json, os, sys\nsys.stdin.read()\nm = sys.argv[sys.argv.index('--model') + 1]\n"
                "if 'sonnet' in m and '--tools' in sys.argv and sys.argv[sys.argv.index('--tools') + 1]:\n"
                "    open('objectives.md', 'w').write('# Objectives\\nNow: beat Vega\\n')\n"  # drops lines, no archive
                "r = 'NOTE: heal Ion' if 'haiku' in m else 'FIX: objectives are stale'\n"
                "print(json.dumps({'result': r, 'is_error': False, 'total_cost_usd': 0.001, 'usage': {'output_tokens': 5}}))\n")
    CLAUDE = fake
    ws = os.path.join(tmp, "ws")
    os.makedirs(os.path.join(ws, "memory"))
    with open(os.path.join(ws, "memory", "objectives.md"), "w") as f:
        f.write("# Objectives\nNow: beat Vega\n- old: reach Crater Town\n")
    with open(os.path.join(ws, "memory", "todo.md"), "w") as f:
        f.write("harness owned\n")
    with open(os.path.join(ws, "log.jsonl"), "w") as f:
        f.write(json.dumps({"step": 20, "tool": "walk_to", "args": {"x": 1, "y": 2}, "result": "done",
                            "now": {"mode": "overworld", "map": "X", "pos": [1, 2]}, "harness": []}) + "\n")
    s = {"mode": "overworld", "map": {"name": "X"}, "pos": [1, 2], "badges": 1, "party": []}
    tick(20, s, os.path.join(ws, "log.jsonl"))
    for _ in range(100):
        if not RT.busy:
            break
        time.sleep(0.1)
    logged = []
    got = drain(logged.append)
    assert sorted(got) == ["VERIFIER (as of step 20): objectives are stale", "WATCHER (step 20): heal Ion"], got
    assert {e["harness_call"] for e in logged} == {"watcher", "verifier"} and all("cost_usd" in e for e in logged), logged
    e = curate(ws, "test", direct=True)
    assert e["archived_lines"] == 1, e
    assert "- old: reach Crater Town" in open(os.path.join(ws, "memory", "archive.md")).read()
    assert open(os.path.join(ws, "memory", "todo.md")).read() == "harness owned\n"
    kinds = [json.loads(ln)["kind"] for ln in open(os.path.join(ws, "usage.jsonl"))]
    assert sorted(kinds) == ["curator", "verifier", "watcher"], kinds
    assert hygiene(30, ["A", "WATCHDOG: x"]) == ["A", "WATCHDOG: x"]
    assert hygiene(31, ["A", "WATCHDOG: x", "B"]) == ["WATCHDOG: x", "B"]
    assert hygiene(42, ["A"]) == ["A"]
    print("watcher self-check ok")
