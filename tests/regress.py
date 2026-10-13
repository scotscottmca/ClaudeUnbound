"""Optional regression sweep over today's fixes. Fixes are verified in live play; this is a safety net.

    python tests/regress.py [FILTER...]              # offline checks only (no emulator), the default
    python tests/regress.py --emulator [FILTER...]   # also the fixture cases, ONLY when no mGBA is running

FILTER keeps the cases whose name contains it. --emulator starts its own minimized mGBA on port 8890 from a
copy of probe.lua and of the ROM (mGBA writes the .sav next to the ROM), loads a fixture per case, and stops
only that mGBA. It refuses while any mGBA runs: one mGBA at a time, ever. Fixtures are read only.

    UNBOUND_FIXTURES   savestates (default D:\\ClaudeUnboundRuns\\fixtures)
    UNBOUND_ROM        ROM to copy (default run/Unbound.gba, or the main checkout's from a worktree)
"""
import contextlib
import io
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import traceback
import types

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BRIDGE = os.path.join(REPO, "bridge")
sys.path[:0] = [BRIDGE, os.path.join(REPO, "agent")]
TMP = tempfile.mkdtemp(prefix="unbound-regress-")
os.environ["UNBOUND_LOG"] = os.path.join(TMP, "log.jsonl")  # mcp_server logs (and tracks milestones) here, not run/
sys.stdout.reconfigure(encoding="utf-8")

import battle  # noqa: E402
import bot  # noqa: E402
import items  # noqa: E402
import launch  # noqa: E402
import mcp_server as M  # noqa: E402
import naming  # noqa: E402
import world as W  # noqa: E402
from probe import Probe  # noqa: E402
from state import BATTLE_MONS, G_MAIN, PLAYER_PARTY, PLAYER_PARTY_COUNT, decode, get_state, raw  # noqa: E402

PORT = 8890
FIX = os.environ.get("UNBOUND_FIXTURES", r"D:\ClaudeUnboundRuns\fixtures")
_main_checkout = os.path.dirname(os.path.normpath(
    subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO,
                   capture_output=True, text=True).stdout.strip() or os.path.join(REPO, ".git")))
ROM = os.environ.get("UNBOUND_ROM") or next(
    (r for r in (os.path.join(REPO, "run", "Unbound.gba"), os.path.join(_main_checkout, "run", "Unbound.gba"))
     if os.path.exists(r)), os.path.join(REPO, "run", "Unbound.gba"))
p = None  # Probe on the spare emulator


def fix(name):
    return os.path.join(FIX, name)


def load(name):
    p.load(fix(name))
    p.step(2)


def refused(fn, *args, why):
    """FN(*ARGS) must stop with SystemExit mentioning WHY."""
    try:
        out = fn(*args)
    except SystemExit as e:
        assert why in str(e), e
        return
    raise AssertionError(f"not refused: {out!r}")


def party_names():
    n = p.read8(PLAYER_PARTY_COUNT)
    return [decode(p.range(PLAYER_PARTY + 100 * i + 8, 10)) for i in range(n)]


# --- emulator ----------------------------------------------------------------------------

def start_emulator(first_state):
    """Minimized mGBA serving PORT; returns its PID."""
    # User rule: only one mGBA may ever run (the live game). Refuse while any is up.
    if "mGBA.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq mGBA.exe"], capture_output=True, text=True).stdout:
        sys.exit("an mGBA is already running: --emulator only runs when none is (one mGBA at a time)")
    lua = open(os.path.join(BRIDGE, "probe.lua"), encoding="utf-8").read()
    assert "local PORT = 8888\n" in lua, "probe.lua's PORT line changed: update start_emulator"
    script = os.path.join(TMP, "probe.lua")
    open(script, "w", encoding="utf-8").write(lua.replace("local PORT = 8888\n", f"local PORT = {PORT}\n"))
    rom = os.path.join(TMP, "Unbound.gba")
    shutil.copy(ROM, rom)
    subprocess.run(["cmd", "/c", "start", "", "/min", launch.MGBA, *launch.SPEED, "--script", script,
                    "-t", first_state, rom])
    pid = None
    for _ in range(60):
        time.sleep(1)
        if pid is None:  # the mGBA whose command line names our temp dir: never the live one
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_Process -Filter \"Name='mGBA.exe'\" | "
                                  "ForEach-Object { \"$($_.ProcessId) $($_.CommandLine)\" }"],
                                 capture_output=True, text=True).stdout
            pid = next((int(line.split()[0]) for line in out.splitlines() if TMP in line), None)
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=5) as s:
                s.sendall(b"step 1\n")
                if s.recv(64).startswith(b"ok") and pid:
                    return pid
        except OSError:
            pass
    stop_emulator(pid)
    sys.exit("the spare mGBA didn't serve frames within 60 s (disconnected remote desktop session?)")


def stop_emulator(pid):
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


# --- cases -------------------------------------------------------------------------------

CASES = []  # (name, needs the emulator, fn)


def case(emu):
    return lambda fn: CASES.append((fn.__name__, emu, fn)) or fn


def self_check(*args):
    """Run a bridge module's own __main__ self-check; it must exit 0."""
    r = subprocess.run([sys.executable, *args], cwd=BRIDGE, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]


class Mem(dict):
    """Fake emulator memory for offline checks: unset bytes read 0."""
    def range(self, a, n): return bytes(self.get(a + i, 0) for i in range(n))
    def read8(self, a): return self.range(a, 1)[0]
    def read32(self, a): return int.from_bytes(self.range(a, 4), "little")
    def put(self, a, data): self.update({a + i: b for i, b in enumerate(data)})


@case(emu=False)
def moves_self_check():
    import moves  # its __main__ self-check, run in-process so it reads ROM (moves.py looks only in run/)
    moves._rom = open(ROM, "rb").read()
    src = open(moves.__file__, encoding="utf-8").read().split('if __name__ == "__main__":\n')[1]
    exec(textwrap.dedent(src), vars(moves))


@case(emu=False)
def notes():
    s = {"mode": "overworld", "map": {"group": 1, "num": 1, "name": "X"}, "pos": [0, 0],
         "party": [{"name": "Ion", "hp": "0/40"}, {"name": "Batty", "hp": "9/40"}]}
    M.p = Mem()
    M.p.put(G_MAIN + 4, battle.CB2_BATTLE_PARTY.to_bytes(4, "little"))
    assert any("LOW HP: your lead Batty" in n for n in M.notes(s))  # lead = first not fainted, at <=25%
    s["party"][1]["hp"] = "11/40"
    assert not any("LOW HP" in n for n in M.notes(s))
    s["mode"] = "other"  # on the battle party screen: forced only if one of your battlers is at 0 HP
    M.p.put(BATTLE_MONS, (1).to_bytes(2, "little"))  # battler 0: a species, HP +0x28 still 0
    assert any("FORCED SWITCH" in n for n in M.notes(s))
    M.p.put(BATTLE_MONS + 0x28, (12).to_bytes(2, "little"))  # opened for a Potion or a chosen switch
    assert not any("FORCED SWITCH" in n for n in M.notes(s))


@case(emu=False)
def watcher_drain_dedupe():
    import watcher
    s = {"mode": "other", "map": {"group": 1, "num": 1, "name": "X"}, "pos": [0, 0], "party": [{"name": "Ion", "hp": "9/40"}]}
    M.p = Mem()
    watcher.RT.seen.clear()
    M.steps = 100
    watcher.RT.inbox.append(("watcher", 100, "the sign at (3,4) is unread"))
    watcher.RT.logs.append({"step": 100, "harness_call": "watcher", "model": "m", "note": "x"})
    out = M.notes(s)
    assert "WATCHER (step 100): the sign at (3,4) is unread" in out and not watcher.RT.logs, out
    watcher.RT.inbox.append(("verifier", 100, "objectives stale"))
    M.steps = 101
    assert M.notes(s) == ["VERIFIER (as of step 100): objectives stale"]
    watcher.RT.inbox.append(("watcher", 100, "the sign at (3,4) is unread"))  # same text within 10 actions
    M.steps = 105
    assert M.notes(s) == []
    assert watcher.hygiene(106, ["WATCHDOG: a", "ITEM: b"]) == watcher.hygiene(107, ["WATCHDOG: a", "ITEM: b"])
    watcher.RT.inbox.append(("watcher", 100, "the sign at (3,4) is unread"))
    M.steps = 111  # older than the window: delivered again
    assert len(M.notes(s)) == 1
    assert not any(n.startswith("VERIFY (") for n in M.notes(s))  # the routine VERIFY note is gone


@case(emu=False)
def memory_guard():
    # No curator model: the harness archives whatever the agent deletes from memory/, keeps the operator's hints
    # pinned, and nags (once per NAG_EVERY actions) about a file over budget.
    import watcher
    ws = os.path.join(tempfile.mkdtemp(dir=TMP), "ws")
    mem = os.path.join(ws, "memory")
    os.makedirs(mem)
    open(os.path.join(mem, "team.md"), "w").write("# Team\nIon\n- Batty: Lv12, boxed\n")
    open(os.path.join(ws, "operator.md"), "w").write("- gym hint\n")
    watcher.RT.mem, watcher.RT.nagged = None, {}
    watcher.guard(ws, 1)
    assert open(os.path.join(mem, "operator.md")).read() == "- gym hint\n"
    open(os.path.join(mem, "team.md"), "w").write("# Team\nIon\n" + "y" * watcher.FILE_BUDGET)  # Batty line gone
    open(os.path.join(mem, "operator.md"), "w").write("")
    watcher.guard(ws, 2)
    assert "- Batty: Lv12, boxed" in open(os.path.join(mem, "archive.md")).read()
    assert open(os.path.join(mem, "operator.md")).read() == "- gym hint\n"
    notes = watcher.drain()
    assert len(notes) == 1 and notes[0].startswith("MEMORY: team.md is"), notes
    watcher.guard(ws, 3)
    assert watcher.drain() == [] and watcher.guard(ws, 2 + watcher.NAG_EVERY) is None and len(watcher.drain()) == 1
    # Walkthrough excerpts (last resort, #153): a memory line copied from one is deleted, never archived; own notes stay.
    watcher.forbid(ws, "Ride the Lapras on the north pad, then hop the lily pads east to reach the leader.")
    open(os.path.join(mem, "objectives.md"), "w").write("- ride the Lapras on the north pad then east\n- tested: UP from (4,26) hops\n")
    watcher.guard(ws, 100)
    kept = open(os.path.join(mem, "objectives.md")).read()
    assert "Lapras" not in kept and "tested: UP" in kept, kept
    assert "Lapras on the north" not in open(os.path.join(mem, "archive.md")).read()
    assert any(n.startswith("MEMORY: deleted 1 line(s) copied from the walkthrough") for n in watcher.drain())
    watcher.RT.mem = None


@case(emu=False)
def press_buttons_string():
    keys, real = [], M.press
    M.press = lambda _p, key, *a: keys.append(key) or {"moved": False, "changed": []}
    try:
        M.t_press_buttons({"buttons": "UP, a"})
        M.t_press_buttons({"buttons": "A"})
        M.t_press_buttons({"buttons": ["b"]})
    finally:
        M.press = real
    assert keys == ["UP", "A", "A", "B"], keys


@case(emu=False)
def bad_tool_args():
    # #170: missing or malformed arguments get a readable message naming the argument and its form, not a KeyError;
    # press_buttons takes the agent's "command" alias; nothing is pressed when any key is bad.
    import json
    keys, real, wiki_real = [], M.press, M.wiki
    M.press = lambda _p, key, *a: keys.append(key) or {"moved": False, "changed": []}
    read = []
    M.wiki = types.SimpleNamespace(read=lambda page: read.append(page) or {"text": "page text"},
                                   search=lambda q, n: [{"url": "https://unboundwiki.com/items/hm01/"}])

    def bad(fn, a, want):
        try:
            fn(a)
        except M.BadArgs as e:
            assert want in str(e), e
            return
        raise AssertionError(f"{fn.__name__}({a}) not refused")
    try:
        M.t_press_buttons({"command": "RIGHT"})
        M.t_press_buttons({"button": ["up"]})
        bad(M.t_press_buttons, {}, "needs 'buttons'")
        bad(M.t_press_buttons, {"buttons": ["A", "E"]}, "unknown button(s) E")
        assert keys == ["RIGHT", "UP"], keys  # the A before the bad E was not pressed
        bad(M.t_walk_to, {}, "walk_to needs 'x' and 'y'")
        bad(M.t_walk_to, {"x": "left", "y": 3}, "integer tile coordinates")
        bad(M.t_sneak_to, {"x": 3}, "sneak_to needs 'x' and 'y'")
        bad(M.t_wiki_read, {"type_url": "Crater Town"}, "wiki_read needs 'page'")
        M.t_wiki_read({"query": "https://unboundwiki.com/locations/fallshore-city/"})
        M.t_wiki_read({"url": "https://unboundwiki.com/locations/crater-town/", "page": "2"})
        assert read == ["https://unboundwiki.com/locations/fallshore-city/",
                        "https://unboundwiki.com/locations/crater-town/"], read

        def missing(page):
            raise KeyError(f"no cached page for {page!r}")
        M.wiki.read = missing
        bad(M.t_wiki_read, {"url": "https://unboundwiki.com/items/key-items/hm01-cut/"}, "items/hm01/")
        # Through the MCP handler: the message alone, flagged as an error, no traceback, no action counted.
        M.p, M.verify_due, steps = Mem(), 0, M.steps
        r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "press_buttons", "arguments": {"keys_to_press": "A"}}})["result"]
        assert r["isError"] and "needs 'buttons'" in r["content"][0]["text"] and "Traceback" not in r["content"][0]["text"], r
        assert M.steps == steps
        last = json.loads(open(M.LOG, encoding="utf-8").read().splitlines()[-1])
        assert "bad_args" in last and "error" not in last, last
    finally:
        M.press, M.wiki = real, wiki_real


@case(emu=False)
def watchdog_escalation():
    # #171: the third WATCHDOG on one map within DOG_WINDOW actions names the loop (the last two actions) and logs an
    # operator alert; other maps and older notes don't count; nothing is blocked, only the text changes.
    import json
    M.dogs.clear()
    M.watchdog_fired = 0
    M.last_actions = [["walk_to", {"x": 3, "y": 4}], ["press_buttons", {"buttons": ["A"]}]]
    s = {"map": {"group": 3, "num": 5, "name": "Route 5"}, "pos": [3, 4]}
    other = {"map": {"group": 1, "num": 2, "name": "Dresco Town"}, "pos": [0, 0]}
    got = []
    for step, where in ((100, s), (110, s), (115, other), (120, s)):
        M.steps = step
        got.append(M.watchdog(where, "advice."))
    assert got[0] == "WATCHDOG: advice." and got[1].startswith("WATCHDOG: advice. ESCALATE"), got
    assert got[2].startswith("WATCHDOG: advice."), got  # Dresco's first
    assert got[3].startswith("WATCHDOG (#3 on Route 5 (3/5)") and \
        'walk_to {"x": 3, "y": 4} then press_buttons {"buttons": ["A"]}' in got[3] and "different" in got[3], got[3]
    last = json.loads(open(M.LOG, encoding="utf-8").read().splitlines()[-1])
    assert "operator_alert" in last and "Route 5" in last["operator_alert"], last
    M.steps = 120 + M.DOG_WINDOW  # the earlier two have aged out of the window
    assert M.watchdog(s, "advice.").startswith("WATCHDOG: advice."), M.dogs
    # The stall watchdog in notes() goes through it too.
    M.p = Mem()
    st = {"mode": "other", "map": s["map"], "pos": [3, 4], "party": [{"name": "Ion", "hp": "40/40"}]}
    M.dogs["3/5"] = [M.steps - 2, M.steps - 1]
    M.last_map, M.last_fingerprint, M.unchanged = (3, 5), M.fingerprint(st), M.STALL_AFTER - 1
    assert any(n.startswith("WATCHDOG (#") and "nothing has changed" in n for n in M.notes(st)), M.dogs
    M.dogs.clear()
    M.watchdog_fired = 0


@case(emu=False)
def verifier_cadence():
    # #172: the verifier runs every VERIFY_EVERY (40) actions, and only when something happened since its last call:
    # a harness note other than the routine LEARNING CHECK / VERIFIER ones, a map change, or a battle ending.
    import json
    import watcher
    ws = os.path.join(tempfile.mkdtemp(dir=TMP), "ws")
    os.makedirs(os.path.join(ws, "memory"))
    lp = os.path.join(ws, "log.jsonl")

    def write(entries):
        open(lp, "w").write("".join(json.dumps({"tool": "walk_to", "harness": [], **e}) + "\n" for e in entries))

    def now(mode="overworld", m=(3, 5)):
        return {"mode": mode, "map": "R", "map_id": list(m), "pos": [1, 1]}
    quiet = [{"step": i, "now": now()} for i in range(1, 41)]
    quiet[39]["harness"] = ["LEARNING CHECK (action 40): ...", "VERIFIER (as of step 0): x"]
    write(quiet)
    assert not watcher.eventful(lp, 0)
    write(quiet + [{"step": 41, "now": now(), "harness": ["MILESTONE: {}"]}])
    assert watcher.eventful(lp, 0) and not watcher.eventful(lp, 41)
    write(quiet + [{"step": 41, "now": now(m=(3, 6))}])
    assert watcher.eventful(lp, 0) and not watcher.eventful(lp, 41)
    write(quiet[:20] + [{"step": 21, "now": now("battle")}, {"step": 22, "now": now("battle")}])
    assert not watcher.eventful(lp, 0)  # a battle starting is not a result yet
    write(quiet[:20] + [{"step": 21, "now": now("battle")}, {"step": 22, "now": now()}])
    assert watcher.eventful(lp, 0)
    spawned, real = [], watcher.spawn
    watcher.spawn = lambda kind, *a: spawned.append((kind, a[2])) or True
    try:
        watcher.RT.verified = 0
        watcher.tick(20, {}, lp)  # step 20: the watcher only
        write(quiet)
        watcher.tick(40, {}, lp)  # nothing happened: skipped
        assert spawned == [("watcher", 20), ("watcher", 40)], spawned
        write(quiet + [{"step": 45, "now": now(), "harness": ["WATCHDOG: x"]}] +
              [{"step": i, "now": now()} for i in range(46, 81)])
        watcher.tick(80, {}, lp)  # the step-45 watchdog, since the last verification (0): runs
        assert ("verifier", 80) in spawned and watcher.RT.verified == 80, spawned
        watcher.tick(120, {}, lp)  # nothing after 80
        assert [k for k in spawned if k[0] == "verifier"] == [("verifier", 80)], spawned
    finally:
        watcher.spawn, watcher.RT.verified = real, 0
        watcher.RT.mem = None
    self_check("watcher.py")


@case(emu=False)
def runner_goal_and_bootstrap():
    import run
    assert run.goal_text(1) == "the first badge" and "8 badges" in run.NEXT.format(goal=run.goal_text(8))
    root = tempfile.mkdtemp(dir=TMP)  # stand-in repo: setup() must not touch run/ or kill any mGBA
    os.makedirs(os.path.join(root, "agent"))
    shutil.copy(os.path.join(REPO, "agent", "CLAUDE.md"), os.path.join(root, "agent"))
    old = os.path.join(root, "old", "memory")
    os.makedirs(old)
    for name in ("objectives.md", "team.md", "items.md", "npcs.md"):
        open(os.path.join(old, name), "w").write("old run")
    saved = run.REPO, run.subprocess, run.launch, run.Probe, run.time
    run.REPO, run.subprocess, run.time = root, types.SimpleNamespace(run=lambda *a, **k: None), \
        types.SimpleNamespace(sleep=lambda s: None)
    run.launch = types.SimpleNamespace(launch=lambda *a: None, serving=lambda: True)
    run.Probe = lambda: types.SimpleNamespace(autosave=lambda *a: None)
    try:
        ws = os.path.join(root, "ws")
        run.setup(ws, True, os.path.dirname(old), 3)
    finally:
        run.REPO, run.subprocess, run.launch, run.Probe, run.time = saved
    mem = os.path.join(ws, "memory")
    assert sorted(os.listdir(mem)) == ["learnings.md", "npcs.md", "objectives.md"], os.listdir(mem)
    assert "3 badges" in open(os.path.join(mem, "objectives.md")).read()


@case(emu=False)
def planner_synthetic():
    def world(tiles, player, elev):  # tiles: {(x, y): (behavior, collision, elevation)}, the rest walls
        return {"width": 5, "height": 5, "player": player, "elevation": elev, "npcs": [],
                "tile": lambda x, y: tiles.get((x, y), (0, 1, 3))}
    # Frozen Heights' sideways stairs: RIGHT on 0xB4 moves up-right, LEFT on 0xB5 down-left.
    assert bot.plan(world({(0, 1): (0xB4, 0, 3), (1, 0): (0xB5, 0, 3)}, (0, 1), 3), {(1, 0)}, set()) == ["RIGHT"]
    assert bot.plan(world({(0, 1): (0xB4, 0, 3), (1, 0): (0xB5, 0, 3)}, (1, 0), 3), {(0, 1)}, set()) == ["LEFT"]
    # A ledge lands on another elevation (Grim Woods (16,25), 3 -> 5).
    assert bot.plan(world({(0, 0): (0, 0, 3), (0, 1): (0x3B, 0, 3), (0, 2): (0, 0, 5)}, (0, 0), 3),
                    {(0, 2)}, set()) == ["DOWN"]
    # A 0x7F gap is hopped sideways, never entered.
    gap = {(0, 0): (0, 0, 3), (1, 0): (W.HOP, 0, 1), (2, 0): (0, 0, 3)}
    assert bot.plan(world(gap, (0, 0), 3), {(2, 0)}, set()) == ["RIGHT"]
    assert bot.plan(world(gap, (0, 0), 3), {(1, 0)}, set()) is None


class PatrolGame:
    """Frame-stepped stand-in for a patrol corridor (modelled on Crater Town gym, measured read-only): one guard
    walking back and forth a tile per 16 frames and turning at its ends in the same step, the player (8 frames a
    tile, 8 more to turn), and the game's sight check on every frame the player isn't mid-step. Reads cost a frame,
    as over the socket. CAUGHT marks a catch; LOG is (frame, player, guard) per frame.
    OTHERS adds guards ({"id", "g": (x, y, facing), "ends", "loads": pos -> bool}): one with LOADS is off screen,
    missing from the object list, until LOADS(player position) first holds, but walks and sees all along."""
    SB1 = 0x0202552C

    def __init__(self, tiles, player, guard, ends, sight=1, others=(), size=(16, 4)):
        self.tiles, self.pos, self.facing, self.sight, self.size = tiles, player, "up", sight, size
        self.guards = [{"id": 7, "g": guard, "ends": ends}] + [dict(o) for o in others]
        self.f = self.gt = self.hold = self.moving = self.turning = 0
        self.held, self.caught, self.log = None, False, []

    @property
    def g(self):
        return self.guards[0]["g"]

    def loaded(self):
        for o in self.guards:
            o["shown"] = o.get("shown") or "loads" not in o or o["loads"](self.pos)
        return [o for o in self.guards if o["shown"]]

    def open(self, t):
        return t in self.tiles

    def sees(self):
        for o in self.guards:
            x, y, f = o["g"]
            dx, dy = bot.DIRS[f.upper()]
            for i in range(1, self.sight + 1):
                t = (x + dx * i, y + dy * i)
                if not self.open(t):
                    break
                if t == self.pos:
                    return True
        return False

    def frame(self):
        self.f += 1
        self.gt += 1
        if self.gt == 16:
            self.gt = 0
            for o in self.guards:
                x, y, f = o["g"]
                dx, dy = bot.DIRS[f.upper()]
                taken = {self.pos} | {q["g"][:2] for q in self.guards if q is not o}
                # Vanilla WalkBackAndForth: turns at its ends; walks in place while something stands in its way.
                if (x, y) == o["ends"][f] or not self.open((x + dx, y + dy)):
                    f, dx, dy = bot.OPPOSITE[f], -dx, -dy
                nxt = (x + dx, y + dy)
                o["g"] = (*nxt, f) if self.open(nxt) and nxt not in taken else (x, y, f)
        if self.moving:
            self.moving -= 1
        elif self.turning:
            self.turning -= 1
        if self.hold > 0 and not self.moving and not self.turning:
            if self.facing != self.held.lower():
                self.facing, self.turning = self.held.lower(), 8
            else:
                dx, dy = bot.DIRS[self.held]
                nxt = (self.pos[0] + dx, self.pos[1] + dy)
                if self.open(nxt) and nxt not in {o["g"][:2] for o in self.guards}:
                    self.pos, self.moving = nxt, 8
        self.hold = max(self.hold - 1, 0)
        if not self.moving and self.sees():
            self.caught = True
        self.log.append((self.f, self.pos, self.g))

    # Probe surface used by bot.sneak / bot.stride
    def read32(self, a):
        self.frame()
        return self.f if a == bot.CLOCK else self.SB1

    def range(self, a, n):
        self.frame()
        if a == self.SB1:
            return struct.pack("<hhbb", *self.pos, 6, 2)[:n]
        if a == self.SB1 + 4:
            return bytes([6, 2])[:n]
        if a == W.OBJECT_EVENTS + 0x18:
            return bytes([{v: k for k, v in W.FACING.items()}[self.facing]])
        raise AssertionError(hex(a))

    def step(self, n):
        for _ in range(n):
            self.frame()

    def press(self, key, n):
        self.held, self.hold = key, n
        self.step(n)


def sneak_with(game, target, templates=(), run=None, **kw):
    """Run bot.sneak on GAME with the world and mode reads pointed at it, and TEMPLATES as the map's object templates
    (rom_world npcs). Returns (SystemExit text or None, output)."""
    def world(_p=None):
        return {"width": game.size[0], "height": game.size[1], "player": list(game.pos), "elevation": 3, "warps": [],
                "signs": [], "connections": [], "tile": lambda x, y: (0, 0 if game.open((x, y)) else 1, 3),
                "npcs": [{"id": o["id"], "x": o["g"][0], "y": o["g"][1], "facing": o["g"][2], "trainer": True,
                          "graphics": 22, "sight": getattr(game, "shown", game.sight), "movement": 0x1B}
                         for o in game.loaded()]}
    saved = W.read_world, W.objects, bot.raw, bot.get_state, W.rom_world
    W.read_world = world
    W.rom_world = lambda g, n: {"npcs": list(templates)}
    # Reads cost what they do over the socket, a frame each: objects() is one, raw() four.
    W.objects = lambda _p: game.step(1) or (world()["npcs"], game.pos, 3)
    bot.raw = lambda _p: game.step(4) or {"mode": "other" if game.caught else "overworld"}
    bot.get_state = lambda _p: {"pos": list(game.pos), "dialog": "Gotcha!" if game.caught else None}
    bot.TURNS.clear()
    bot.SEEDED.clear()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            run(game) if run else bot.sneak(game, target, **kw)
        return None, buf.getvalue()
    except SystemExit as e:
        return str(e), buf.getvalue()
    finally:
        W.read_world, W.objects, bot.raw, bot.get_state, W.rom_world = saved


@case(emu=False)
def sneak_to_patrol():
    # A corridor (row 1, x 0..14) patrolled by a sight-1 guard between x 4 and 11; the player starts in a side
    # tile at its east end (14,0), with a safe strip of alcoves below the corridor at (5..8,2), and must reach
    # (1,1) at the far west end. Walking straight along the row meets the guard head on.
    tiles = {(x, 1) for x in range(15)} | {(14, 0)} | {(x, 2) for x in range(5, 9)}
    ends = {"left": (4, 1), "right": (11, 1)}
    for guard in ((7, 1, "right"), (4, 1, "right"), (10, 1, "left")):
        game = PatrolGame(tiles, (14, 0), guard, ends)
        err, out = sneak_with(game, (1, 1))
        assert err is None and game.pos == (1, 1) and not game.caught, (guard, err, out[-1500:])
        assert "waiting" in out, out  # it waited for a gap, learning where the guard turns
        assert bot.TURNS[(6, 2, 7)] == ends, bot.TURNS
        assert any(pos[1] == 2 for _, pos, _ in game.log), out  # and used the alcoves to let it pass
        print(f"  guard from {guard}: arrived on frame {game.f}; " + out.strip().splitlines()[-1])
    assert "safe tile" in out, out  # here the plan ran straight along the row: an alcove was chosen as a waypoint
    # Predictions held: at every frame the guard's sight never covered the player (checked by the game itself),
    # and the player reached the far end. A plain walk along the row is caught: the scenario is a real test.
    naive = PatrolGame(tiles, (14, 0), (7, 1, "right"), ends)
    for key in ["DOWN"] + ["LEFT"] * 13:
        bot.stride(naive, [key], naive.facing)
        if naive.caught:
            break
    assert naive.caught, naive.pos
    # Caught anyway (a watcher the RAM doesn't show as one): sneak stops and says so, pressing nothing more.
    game = PatrolGame(tiles, (14, 0), (7, 1, "right"), ends)
    game.shown = 0
    err, out = sneak_with(game, (1, 1), max_wait=400)
    assert game.caught and err and "caught" in err and "Gotcha!" in err, (err, out[-800:])


@case(emu=False)
def patrol_phase_prediction():
    # Given its turning points, a few reads across one of its steps pin a walker's phase to the frame: then its
    # tile and facing are predicted exactly, every frame for two whole cycles, with no further reads.
    ends = {"left": (4, 1), "right": (11, 1)}
    game = PatrolGame({(x, 1) for x in range(15)}, (0, 0), (7, 1, "right"), ends)
    m = bot.Patrol(ends)
    for _ in range(17):
        game.step(1)
        assert m.sync(game.f, *game.g) or m.ref, game.g
    assert m.ref[1] == m.ref[2], m.ref  # the frame its step began, exactly
    wrong = 0
    for _ in range(2 * m.period * bot.WATCHER_FRAMES):
        game.step(1)
        wrong += m.states(game.f, game.f) != {game.g}
    assert wrong == 0, wrong
    assert not m.sync(game.f, 9, 1, "left") and bot.Patrol(ends).index(12, 1, "right") is None  # contradictions


def gym(player, g7, g8=None, loads=lambda pos: pos[0] <= 17 and 18 <= pos[1] <= 34, ends7=((9, 27), (18, 27))):
    """PatrolGame on Crater Town gym (6/2) as the ROM lays it out, with guard 7 patrolling row 27 x 9..18 (seen in
    RAM; ENDS7 to differ from its template) and, if G8, guard 8 on x 1..8 (vanilla WalkBackAndForth from its template
    (8,27) range 7; unverified). Guard 8 is off screen until LOADS(player) (vanilla's spawn window for its template).
    Returns (game, the map's watcher templates)."""
    W._rom = W.RomFile(ROM)
    g = W.rom_world(6, 2)
    tiles = {(x, y) for x in range(g["width"]) for y in range(g["height"]) if not g["tile"](x, y)[1]}
    others = [{"id": 8, "g": g8, "ends": {"left": (1, 27), "right": (8, 27)}, "loads": loads}] if g8 else []
    game = PatrolGame(tiles, player, g7, {"left": ends7[0], "right": ends7[1]}, others=others,
                      size=(g["width"], g["height"]))
    return game, [n for n in g["npcs"] if n.get("sight") and (g8 or n["id"] != 8)]


def stood(game, tiles):
    """The most consecutive frames the player stood on one of TILES."""
    best = run = 0
    for i, (_, pos, _) in enumerate(game.log):
        run = run + 1 if i and pos == game.log[i - 1][1] else 1
        if pos in tiles:
            best = max(best, run)
    return best


ROW27 = {(x, 27) for x in range(8, 20)}  # guard 7's sight over its patrol


@case(emu=False)
def sneak_to_gym_crossing():
    # #130 (log step 1891): from (20,22) to the alcove (13,28) the only way runs 7 tiles along the watched row 27.
    # It waits on a safe tile for the exact frame the whole crossing is clear, then crosses without stopping on the
    # row (the corner at (13,27) costs ~30 frames, inside the predicted window).
    waits = 0
    for g7 in ((18, 27, "left"), (12, 27, "right"), (9, 27, "right"), (15, 27, "left")):
        game, templates = gym((20, 22), g7)
        err, out = sneak_with(game, (13, 28), templates)
        assert err is None and game.pos == (13, 28) and not game.caught, (g7, err, out[-1200:])
        assert stood(game, ROW27) <= bot.CORNER[1], (g7, stood(game, ROW27), out[-1200:])
        waits += "the crossing is clear in" in out
        assert "id 7: patrol seeded from its template" in out, out[:600]
    assert waits, "never waited for a window"
    # A guard that doesn't patrol as its template says (x 11..16): the seed is contradicted, it falls back to the
    # pessimistic model and re-learns the turning points by watching, and still isn't caught.
    game, templates = gym((20, 22), (14, 27, "left"), ends7=((11, 27), (16, 27)))
    err, out = sneak_with(game, (13, 28), templates, max_wait=4000)
    assert not game.caught and "broke its predicted patrol" in out, (err, out[-1500:])
    assert bot.TURNS[(6, 2, 7)] == {"left": (11, 27), "right": (16, 27)}, bot.TURNS
    # Both guards on screen and modelled: from (13,28) across both patrols to the alcove (4,28).
    game, templates = gym((13, 28), (12, 27, "right"), (5, 27, "left"))
    err, out = sneak_with(game, (4, 28), templates)
    assert err is None and game.pos == (4, 28) and not game.caught, (err, out[-1200:])


@case(emu=False)
def sneak_to_gym_unloaded_guard():
    # #130: guard 8 isn't in RAM until the player is near its start (8,27), so live reads can't see it. Its template
    # stands in for it. A back-and-forth walker patrols one side of its start (x 1..8 for guard 8, seen live only
    # there), so it doesn't block the crossing to (13,28): the tool crosses safely past guard 7. Further west, where
    # the patrols meet, it waits on a safe tile rather than walk into either guard.
    for g7, g8 in (((18, 27, "left"), (8, 27, "left")), ((12, 27, "right"), (5, 27, "left"))):
        game, templates = gym((20, 22), g7, g8)
        err, out = sneak_with(game, (13, 28), templates)
        assert not game.caught and (err is None and game.pos == (13, 28)), (err, out[-800:])
        game, templates = gym((20, 22), g7, g8)
        err, out = sneak_with(game, (5, 28), templates)
        assert not game.caught and err and "a safe tile" in err, (err, out[-800:])


@case(emu=False)
def sneak_to_gym_start_watched():
    # #130 (log step 1895): standing on the watched row at (17,27) with the guard coming, the old tool said "every
    # tile around is about to be watched" and stayed put, and was caught. Now it steps off at once to a safe tile
    # it can reach in time (either way), and never pauses on the row.
    for g7 in ((14, 27, "left"), (12, 27, "right"), (9, 27, "left"), (16, 27, "left")):
        game, templates = gym((17, 27), g7, (3, 27, "right"))
        err, out = sneak_with(game, (13, 28), templates, max_wait=3000)
        left = next(f for f, pos, _ in game.log if pos != (17, 27))
        assert not game.caught and err is None and game.pos == (13, 28), (g7, err, out[-1200:])
        assert left <= 24 and stood(game, ROW27 - {(17, 27)}) <= bot.CORNER[1], (g7, left, out[-1200:])


@case(emu=False)
def sneak_to_shadowing():
    # A long corridor (row 1, x 0..24) with one guard patrolling x 2..22; the target alcove (12,2) lies along it.
    # Sight is 1 tile ahead and the player is twice as fast, so the way is to slip in behind the guard as it walks
    # away and follow it, leaving the row before it turns: the timed crossing finds that window.
    tiles = {(x, 1) for x in range(25)} | {(24, 0), (12, 2)}
    for g in ((22, 1, "left"), (10, 1, "right"), (5, 1, "left")):
        game = PatrolGame(tiles, (24, 0), g, {"left": (2, 1), "right": (22, 1)}, size=(25, 3))
        err, out = sneak_with(game, (12, 2))
        assert err is None and game.pos == (12, 2) and not game.caught, (g, err, out[-1200:])
        behind = [p[0] - q[0] for _, p, q in game.log if p[1] == 1 and q[2] == "left" and p[0] > q[0]]
        assert behind and min(behind) <= 2, (g, behind[:20])  # right on its heels
        assert "LEFTx12" in out, out[-800:]  # in one go


@case(emu=False)
def route_rom():
    W._rom, W._links = W.RomFile(ROM), {}
    # Route 4's seam with Route 5 is 5 tiles of shore walled off in a lake, and its KBT Expressway warps
    # (112,7)/(113,7) sit in solid rock: route() must go round, and the first hop must be walkable.
    assert W._buried(W.rom_world(3, 72), 112, 7)
    hops = W.route(None, (3, 72), "Route 5")
    assert hops and hops[0] == (3, 71) and hops[-1] == (3, 73), hops
    for start in ((53, 34), (114, 25)):
        w = W.rom_world(3, 72, start)
        goals, key = bot.exit_to(w, hops[0])
        assert key == "RIGHT" and bot.plan(w, goals, set()) is not None, (start, key)  # (114,25) is on the edge: []
    # exit_to keeps to the stretch of edge that borders the target (Route 13 has x >= 32 of that south edge).
    assert max(x for x, _ in bot.exit_to(W.rom_world(3, 72), (3, 73))[0]) == 31


@case(emu=False)
def watch_area():
    # Watching from an alcove below a patrolled corridor: it reports the guard's real span, turning points and repeat
    # period (14 steps of 16 frames), and lists the alcoves, not the corridor, as unseen. Watching from the corridor
    # gets the player caught, and it says so.
    tiles = {(x, 1) for x in range(15)} | {(x, 2) for x in range(5, 9)}
    game = PatrolGame(tiles, (6, 2), (7, 1, "right"), {"left": (4, 1), "right": (11, 1)})
    err, out = sneak_with(game, None, run=lambda g: bot.watch(g, frames=600, radius=8))
    assert err is None and not game.caught, (err, out)
    assert "walked x 4..11, y 1..1" in out and "(11, 1)" in out and "(4, 1)" in out, out
    rep = int(out.split("repeats every ~")[1].split()[0])
    assert abs(rep - 14 * 16) <= 8, out
    hide = out.split("nearest first: ")[1].split("\n")[0]
    # sight 1, turning at x 4 and 11: x 3..12 of the corridor is seen, its far ends and the alcoves aren't
    assert all(t in hide for t in ("(5, 2)", "(1, 1)", "(13, 1)")), out
    assert not any(t in hide for t in ("(3, 1)", "(6, 1)", "(12, 1)")), out
    game = PatrolGame(tiles, (6, 1), (9, 1, "left"), {"left": (4, 1), "right": (11, 1)})
    err, out = sneak_with(game, None, run=lambda g: bot.watch(g, frames=600))
    assert game.caught and err and "a watcher saw this tile" in err, (err, out)


@case(emu=False)
def runner_cost_tally():
    # claude -p reports a resumed session's running total, not the chunk's cost (#150): count each chunk's increase
    # once, a drop as a new session, an errored zero-cost chunk as nothing, harness calls as they are.
    import json
    import run
    p = os.path.join(tempfile.mkdtemp(dir=TMP), "usage.jsonl")
    rows = [{"chunk": 0, "cost_usd": 1.0}, {"chunk": 1, "cost_usd": 2.0}, {"chunk": 2, "cost_usd": 0, "is_error": True},
            {"chunk": 3, "cost_usd": 3.0}, {"kind": "watcher", "cost_usd": 0.1}, {"chunk": 4, "cost_usd": 0.5},
            {"chunk": 5, "cost_usd": 0.75, "session_start": True, "chunk_cost_usd": 0.75}]
    open(p, "w").write("".join(json.dumps(r) + "\n" for r in rows))
    assert abs(run.spent_so_far(p) - (3.0 + 0.1 + 0.5 + 0.75)) < 1e-9, run.spent_so_far(p)


@case(emu=False)
def runner_escalation_cap():
    # #173: strategist/expert calls are logged to usage.jsonl with their reason, cost nothing in the tallies, and one
    # expert call per badge count caps the expert. #175: entering another town (not a building in it) rotates.
    import run
    ws = tempfile.mkdtemp(dir=TMP)
    p = os.path.join(ws, "usage.jsonl")
    open(p, "w").write('{"chunk": 0, "cost_usd": 1.0}\n')
    assert run.escalations(ws, "expert", 2) == 0
    run.log_escalation(ws, {"subagent_type": "expert", "description": "Gym 3", "prompt": "lost twice to Mirskle"}, 2)
    run.log_escalation(ws, {"subagent_type": "strategist", "description": "route", "prompt": "where next"}, 2)
    assert run.escalations(ws, "expert", 2) == 1 and run.escalations(ws, "expert", 3) == 0, open(p).read()
    assert run.escalations(ws, "strategist", 2) == 1 and run.escalations(ws, "expert", None) == 0
    assert "lost twice" in open(p).read() and abs(run.spent_so_far(p) - 1.0) < 1e-9, run.spent_so_far(p)
    assert run.new_town("Route 2", "Bellin Town") and run.new_town("", "Frozen Heights")
    assert not run.new_town("Bellin Town", "Bellin Town") and not run.new_town("Bellin Town", "Route 2")


@case(emu=False)
def runner_rotation():
    # #179: past CONTEXT_LIMIT the player's session rotates, but only in the overworld (never battle, dialog or a
    # menu, "other"), and only after a player tool result (now is {} otherwise). The #175 town rule still applies.
    import run
    big, mid = run.CONTEXT_LIMIT + 1, run.TOWN_ROTATE_MIN + 1
    ow = {"mode": "overworld", "map": "Route 2"}
    assert run.CONTEXT_LIMIT == 80_000 and run.rotate_reason(big, ow, "Route 2") == "context"
    assert run.rotate_reason(run.CONTEXT_LIMIT, ow, "Route 2") is None and run.rotate_reason(mid, ow, "Route 2") is None
    for mode in ("battle", "dialog", "other"):
        assert run.rotate_reason(big, dict(ow, mode=mode), "Route 2") is None, mode
        assert run.rotate_reason(mid, {"mode": mode, "map": "Bellin Town"}, "Route 2") is None, mode
    assert run.rotate_reason(big, {}, "Route 2") is None  # between the player's own tool results
    assert run.rotate_reason(mid, {"mode": "overworld", "map": "Bellin Town"}, "Route 2") == "town"
    assert run.rotate_reason(run.TOWN_ROTATE_MIN, {"mode": "overworld", "map": "Bellin Town"}, "Route 2") is None


@case(emu=False)
def stats_self_check():
    import stats
    stats._selftest()


@case(emu=False)
def map_levels():
    # A level-4 bridge (row 1) over a level-3 pad path (column 2, crossing under it on a level-15 tile): two regions,
    # and the pads' region says it isn't enterable on foot from the bridge.
    def tile(x, y):
        if y == 1:
            return (0, 0, 15 if x == 2 else 4)
        if x == 2 and y in (0, 2, 3):
            return (0, 0, 3)
        return (0x11, 1, 1)  # water
    w = {"width": 5, "height": 4, "player": [0, 1], "elevation": 4, "npcs": [], "warps": [], "tile": tile}
    rid, regs, links = bot.regions(w)
    assert rid[(0, 1)] == rid[(4, 1)] != rid[(2, 2)] and rid[(2, 0)] == rid[(2, 3)], rid
    text = bot.describe_levels(w, (2, 3))
    assert "No walking route" in text and "NOT enterable on foot" in text, text


@case(emu=False)
def planner_no_move():
    # A move the game refused (walk_to learns it per map) is planned around, not retried.
    w = {"width": 3, "height": 2, "player": [0, 0], "elevation": 3, "npcs": [], "tile": lambda x, y: (0, 0, 3)}
    assert bot.plan(w, {(2, 0)}, set()) == ["RIGHT", "RIGHT"]
    w["no_move"] = {(0, 0, "RIGHT")}
    assert bot.plan(w, {(2, 0)}, set()) == ["DOWN", "RIGHT", "RIGHT", "UP"]


@case(emu=False)
def walk_sequence_guard():
    # Crater gym id 11 (0x24, walk sequence right-down-up-left, home (24,6), range x4 y3), as recorded in the
    # user's demo: a 14-step loop. The tiles the user waited on are safe; the one they were caught on isn't.
    W._rom, W._links = W.RomFile(ROM), {}
    w = W.rom_world(6, 2)
    t = next(n for n in w["npcs"] if n["id"] == 11)
    cyc = bot.sequence_cycle(w, dict(t, home=(t["x"], t["y"])))
    assert len(cyc) == 14 and (28, 9, "down") in cyc and (24, 6, "left") in cyc and (23, 6, "left") not in cyc, cyc
    live = dict(t, home=(t["x"], t["y"]), x=26, y=6, facing="right")
    for watched in (bot.danger(dict(w, npcs=[live]), bot.SWEEP), bot.unseen(w, [t])):
        assert not watched & {(22, 6), (26, 7), (28, 12)} and (23, 6) in watched


@case(emu=True)
def bridge_reads_while_step_pending():  # #58
    a = socket.create_connection(("127.0.0.1", PORT))
    a.sendall(b"step 600\n")  # 5 s at 120 fps
    time.sleep(0.3)
    b = Probe(port=PORT)
    b.read32(G_MAIN)
    b.shot(os.path.join(TMP, "shot.png"))
    try:
        b.step(1)
        raise AssertionError("a second client's step wasn't refused")
    except RuntimeError as e:
        assert "busy" in str(e), e
    a.settimeout(0)
    try:
        raise AssertionError(f"step finished early: {a.recv(64)!r}")
    except BlockingIOError:
        pass
    a.settimeout(30)
    assert a.recv(64).startswith(b"ok")
    a.close()
    b.f.close()


@case(emu=True)
def naming():
    for state in ("nickname_screen.ss1", "nickname_after_capture.ss1"):  # the second: heap struct moved
        load(state)
        assert naming.type_name(p, "Iron Man") == "Iron Man"
        for _ in range(60):
            if p.read32(G_MAIN + 4) != naming.NAMING_CB2 and "Iron Man" in party_names():
                break
            p.step(10)
        assert p.read32(G_MAIN + 4) != naming.NAMING_CB2, f"{state}: still on the naming screen"
        assert "Iron Man" in party_names(), f"{state}: party {party_names()}"


@case(emu=True)
def throw_ball():
    load("wild_battle_prethrow.ss1")
    refused(battle.throw_ball, p, "Great Ball", why="no 'Great Ball'")
    out = battle.throw_ball(p, "Poké Ball")
    assert "caught" in out or "broke free" in out, out
    load("trainer_battle_riolu.ss1")
    refused(battle.throw_ball, p, "Poké Ball", why="trainer battle")


@case(emu=True)
def switch_to():
    load("forced_switch_cursor_fail.ss1")  # five Pokemon: slots 2-4 used to be unreachable
    for slot in (1, 2, 3, 4, 0):
        assert battle.party_cursor_to(p, slot), f"cursor didn't reach slot {slot}"
    load("forced_switch_cursor_fail.ss1")  # Makuhita 51/51 and Makuhita 22/56: the first that can fight
    out = battle.switch_to(p, "Makuhita")
    hp, mx = struct.unpack("<HxxH", p.range(BATTLE_MONS + 0x28, 6))
    assert out.startswith("sent in Makuhita") and (hp, mx) == (51, 51), (out, hp, mx)


@case(emu=True)
def use_item():
    self_check("items.py", fix("overworld_items.ss1"), fix("wild_battle_prethrow.ss1"), str(PORT))


@case(emu=True)
def advance_dialog_battle():
    M.p = p
    load("wild_battle_makuhita.ss1")
    r = M.t_advance_dialog({})
    assert r["battle"] == "a question is waiting" and "nickname" in r["boxes"][-1], r
    load("wild_battle_prethrow.ss1")  # "What will Ion do?" is the action menu's prompt, not a question
    r = M.t_advance_dialog({})
    assert r["battle"] == "your menu is up", r


@case(emu=True)
def planner_grim_woods():
    M.p = p
    load("grim_woods.ss1")  # east side, a wild battle about to end with a level-up and a move to learn
    for _ in range(6):
        if raw(p)["mode"] != "battle":
            break
        r = M.t_advance_dialog({})
        if r["battle"] == "a question is waiting":  # "Delete a move ...?" No (B); "Stop learning ...?" Yes (A)
            p.press("B" if "Delete" in r["boxes"][-1] else "A", 4)
            p.step(30)
    for _ in range(60):
        if raw(p)["mode"] == "overworld":
            break
        p.step(10)
    assert raw(p)["mode"] == "overworld", raw(p)["mode"]
    w = W.read_world(p)
    assert w["player"][0] > 15 and bot.plan(w, {(2, 12)}, set()), w["player"]  # ledge-elevation and 0x7F hops


# --- runner ------------------------------------------------------------------------------

def main(args):
    global p
    emulator = "--emulator" in args
    words = [a for a in args if a != "--emulator"]
    chosen = [c for c in CASES if (not words or any(w in c[0] for w in words)) and (emulator or not c[1])]
    if not chosen:
        sys.exit(f"no case matches {words}; cases: {[c[0] for c in CASES]}")
    pid = None
    if any(emu for _, emu, _ in chosen):
        W._rom = W.RomFile(ROM)  # world.py looks for run/Unbound.gba next to the bridge, absent in a worktree
        pid = start_emulator(fix("wild_battle_prethrow.ss1"))
        p = Probe(port=PORT)
    failed = []
    try:
        for name, _, fn in chosen:
            t = time.time()
            try:
                fn()
                print(f"PASS {name} ({time.time() - t:.0f} s)", flush=True)
            except Exception as e:  # SystemExit too: a tool refusing is a failure here
                failed.append(name)
                print(f"FAIL {name}: {e!r}\n{traceback.format_exc(limit=-3)}", flush=True)
            except SystemExit as e:
                failed.append(name)
                print(f"FAIL {name}: SystemExit({e})", flush=True)
    finally:
        stop_emulator(pid)
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"{len(chosen) - len(failed)}/{len(chosen)} passed" + (f"; failed: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
