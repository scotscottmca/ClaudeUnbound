"""Operator verification checks: one line per pending issue, PASS / FAIL / PENDING with a reason. Safe at any time:
offline checks read files and run the offline tests; live checks only read (ReadOnlyProbe on the bridge, GET on the
spectator, process list, the workspace's logs). Never steps, presses, loads or saves.

    python ops/verify.py [WORKSPACE]    # default D:/ClaudeUnboundRuns/expert1; exit 1 if any check FAILs
"""
import ast
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.normpath(sys.argv[1] if len(sys.argv) > 1 else "D:/ClaudeUnboundRuns/expert1")
sys.path[:0] = [os.path.join(REPO, "bridge"), os.path.join(REPO, "agent"), os.path.join(REPO, "ui")]
results = []


def check(issue, name):
    def wrap(fn):
        try:
            status, why = fn()
        except Exception as e:  # a check that crashes is a FAIL with the error, never a crashed script
            status, why = "FAIL", f"{type(e).__name__}: {e}"
        results.append(status)
        print(f"{status:7} {issue:9} {name}: {why}", flush=True)
    return wrap


def text(rel):
    return open(os.path.join(REPO, rel), encoding="utf-8").read()


def ok(cond, good, bad):
    return ("PASS", good) if cond else ("FAIL", bad)


def powershell(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                          timeout=20).stdout.strip()


# ---------------------------------------------------------------- offline
reg = subprocess.run([sys.executable, os.path.join(REPO, "tests", "regress.py")], capture_output=True, text=True,
                     timeout=50, cwd=REPO, encoding="utf-8", errors="replace")
passed = set(re.findall(r"^PASS (\w+)", reg.stdout, re.M))
reg_summary = (reg.stdout.strip().splitlines() or ["no output"])[-1]


def case(name):
    return ok(name in passed, f"regress case {name} passes", f"regress case {name} not passing ({reg_summary})")


def runner_alive_src():
    tree = ast.parse(text("ops/watch_run.py"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "runner_alive")
    return ast.get_source_segment(text("ops/watch_run.py"), fn)


@check("#169", "runner_alive wraps the match in @(...).Count")
def _():
    src = runner_alive_src()
    return ok("@(Get-CimInstance" in src and ").Count" in src, "one match counts as 1 (PS 5.1 bare CimInstance)",
              "runner_alive no longer uses @(...).Count")


@check("#170", "offline regress suite")
def _():
    return ok(reg.returncode == 0, f"exit 0, {reg_summary}", f"exit {reg.returncode}, {reg_summary}")


@check("#170", "BadArgs path")
def _():
    s = text("bridge/mcp_server.py")
    if not ("class BadArgs" in s and '"bad_args"' in s):
        return "FAIL", "class BadArgs or the bad_args log row is missing from mcp_server.py"
    return case("bad_tool_args")


check("#171", "watchdog escalation")(lambda: case("watchdog_escalation"))
check("#172", "verifier cadence")(lambda: case("verifier_cadence"))


@check("#173", "escalation cap")
def _():
    exp = json.loads(text("agent/agents.json"))["expert"].get("effort")
    if exp != "medium":
        return "FAIL", f"agents.json expert effort is {exp!r}, not medium"
    return case("runner_escalation_cap")


@check("#174", "run.py passes --effort")
def _():
    s = text("agent/run.py")
    m = re.search(r'^PLAYER_EFFORT = "(\w+)"', s, re.M)
    return ok('"--effort", effort' in s and m, f"--effort passed, PLAYER_EFFORT {m and m.group(1)}",
              "--effort or PLAYER_EFFORT missing in run.py")


@check("#175", "REFERENCE.md copy, FILE_BUDGET 5000")
def _():
    import watcher
    s = text("agent/run.py")
    return ok('"reference.md"' in s and '"REFERENCE.md"' in s and watcher.FILE_BUDGET == 5000,
              "run.py copies reference.md -> REFERENCE.md; FILE_BUDGET 5000",
              f"copy present: {'REFERENCE.md' in s}; FILE_BUDGET {watcher.FILE_BUDGET}")


@check("#176", "agent/CLAUDE.md screenshot rule")
def _():
    return ok("screenshots only when the state can't answer" in text("agent/CLAUDE.md"), "rule present",
              "'screenshots only when the state can't answer' not found")


@check("#177", "watcher effort low")
def _():
    import watcher
    r = subprocess.run([sys.executable, os.path.join(REPO, "bridge", "watcher.py")], capture_output=True, text=True,
                       timeout=30, cwd=os.path.join(REPO, "bridge"))
    return ok(watcher.EFFORT.get("watcher") == "low" and r.returncode == 0 and "self-check ok" in r.stdout,
              "EFFORT watcher=low, watcher.py self-check ok",
              f"EFFORT {watcher.EFFORT}, self-check exit {r.returncode}: {(r.stdout + r.stderr).strip()[-150:]}")


@check("#178", "expert effort medium")
def _():
    exp = json.loads(text("agent/agents.json"))["expert"].get("effort")
    return ok(exp == "medium", "agents.json expert effort medium", f"expert effort {exp!r}")


check("#179", "rotate_reason")(lambda: case("runner_rotation"))


@check("#180", "--setting-sources project,local")
def _():
    return ok('"--setting-sources", "project,local"' in text("agent/run.py"), "in run.py's claude args",
              "not found in run.py")


# ---------------------------------------------------------------- live, read only
probe = None


def live():
    global probe
    if probe is None:
        from server import ReadOnlyProbe  # ui/server.py: refuses anything but read8/16/32/range
        probe = ReadOnlyProbe(int(os.environ.get("UNBOUND_PORT", 8888)))
    return probe


def difficulty():
    try:
        return json.load(open(os.path.join(WS, "run.json"))).get("difficulty", "vanilla")
    except OSError:
        return "vanilla"


def party_raw():
    import state
    n = live().read8(state.PLAYER_PARTY_COUNT)
    return n, live().range(state.PLAYER_PARTY, 100 * n) if n else b""


@check("#162", "team_details level cap")
def _():
    import state
    import stats
    stats.DIFFICULTY = difficulty()  # what the runner sets through UNBOUND_DIFFICULTY for this workspace
    n, raw = party_raw()
    if not n:
        return "PENDING", "no party"
    badges = state.get_state(live())["badges"]
    cap = stats.level_cap(badges)
    lv = [stats.detail(raw[k * 100:(k + 1) * 100])["level"] for k in range(n)]
    if stats.DIFFICULTY in ("difficult", "expert", "insane"):
        return ok(cap == stats.CAPS["expert"][min(badges, 8)],
                  f"level_cap {cap} ({stats.DIFFICULTY}, {badges} badges); party levels {lv}",
                  f"level_cap {cap} for {stats.DIFFICULTY} with {badges} badges")
    return ok(cap is None, f"none ({stats.DIFFICULTY}); party levels {lv}", f"cap {cap} on {stats.DIFFICULTY}")


@check("#156", "stats.detail on the live party")
def _():
    import stats
    n, raw = party_raw()
    if not n:
        return "PENDING", "no party"
    d = [stats.detail(raw[k * 100:(k + 1) * 100]) for k in range(n)]
    return ok(all(m["stats"] and m["nature"] for m in d), f"{n} members, e.g. {d[0]['name']}: {d[0]['stats']}",
              "a member has no stats/nature")


@check("#157", "stats.boxes (pc_boxes reader)")
def _():
    import stats
    bx = stats.boxes(live())
    total = sum(len(v) for v in bx.values())
    if not total:
        return "PENDING", "boxes read, all empty (nothing deposited yet)"
    first = next(iter(bx.values()))[0][1]
    return "PASS", f"{total} Pokemon in boxes {sorted(bx)}, e.g. {first['name']} ({first['species']} Lv{first['level']})"


@check("#167/#168", "spectator /events party stats")
def _():
    with urllib.request.urlopen("http://127.0.0.1:8765/events", timeout=5) as r:
        for line in r:
            if line.startswith(b"data: "):
                snap = json.loads(line[6:])
                break
        else:
            return "FAIL", "no data line"
    party = (snap.get("party") or {}).get("party") or []
    if not party:
        return "PENDING", "spectator snapshot has no party yet (bridge not live in the UI?)"
    labels = re.search(r"const STATN = (\[.*?\])", open(os.path.join(REPO, "ui", "index.html"), encoding="utf-8").read())
    names = json.loads(labels.group(1)) if labels else []
    good = all(len(m.get("stats") or []) == 6 for m in party) and {"Atk", "Def", "Spe"} <= set(names)
    return ok(good, f"{len(party)} members with 6 stats ({'/'.join(names)}), e.g. {party[0].get('name')} {party[0]['stats']}",
              f"stats missing: {[m.get('stats') for m in party]}, labels {names}")


@check("#169", "runner/monitor processes")
def _():
    out = powershell("Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | ForEach-Object { $_.CommandLine }")
    runners = len(re.findall(r"agent[\\/]run\.py", out))
    monitors = len(re.findall(r"watch_run\.py", out))
    ns = {"subprocess": subprocess}
    exec(runner_alive_src(), ns)
    alive = ns["runner_alive"]()
    return ok(alive == (runners > 0), f"{runners} agent/run.py, {monitors} watch_run.py; runner_alive() {alive}",
              f"runner_alive() {alive} but {runners} agent/run.py processes")


def rows(name):
    path = os.path.join(WS, name)
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def logcount(issue, label, n, where):
    check(issue, f"log {label}")(lambda: ("PASS", f"{n} in {where}") if n else
                                 ("PENDING", f"0 in {where}: awaits the next run's occurrence"))


usage, log = rows("usage.jsonl"), rows("log.jsonl")
# Transcripts are not counted: one subagent call repeats its subagent_type across stream events (thousands per run).
logcount("#173", "escalation", sum(r.get("kind") == "escalation" for r in usage), "usage.jsonl")
logcount("#179", "rotated", sum(bool(r.get("rotated")) for r in usage), "usage.jsonl")
logcount("#170", "bad_args", sum("bad_args" in r for r in log), "log.jsonl")
logcount("#171", "operator_alert", sum("operator_alert" in r for r in log), "log.jsonl")

print(f"{results.count('PASS')} PASS, {results.count('FAIL')} FAIL, {results.count('PENDING')} PENDING")
sys.exit(1 if "FAIL" in results else 0)
