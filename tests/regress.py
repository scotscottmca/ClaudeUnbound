"""Optional regression sweep over today's fixes. Fixes are verified in live play; this is a safety net.

    python tests/regress.py [FILTER...]              # offline checks only (no emulator), the default
    python tests/regress.py --emulator [FILTER...]   # also the fixture cases, ONLY when no mGBA is running

FILTER keeps the cases whose name contains it. --emulator starts its own minimized mGBA on port 8890 from a
copy of probe.lua and of the ROM (mGBA writes the .sav next to the ROM), loads a fixture per case, and stops
only that mGBA. It refuses while any mGBA runs: one mGBA at a time, ever. Fixtures are read only.

    UNBOUND_FIXTURES   savestates (default D:\\ClaudeUnboundRuns\\fixtures)
    UNBOUND_ROM        ROM to copy (default run/Unbound.gba, or the main checkout's from a worktree)
"""
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
def curator_archives_never_deletes():
    import watcher
    root = tempfile.mkdtemp(dir=TMP)
    fake = os.path.join(root, "fake_claude.py")  # "curates" by rewriting a file, dropping a line, archiving nothing
    open(fake, "w").write("import json, sys\nsys.stdin.read()\nopen('team.md', 'w').write('# Team\\nIon\\n')\n"
                          "open('todo.md', 'w').write('curator touched it\\n')\n"
                          "print(json.dumps({'result': 'merged team', 'total_cost_usd': 0.01}))\n")
    mem = os.path.join(root, "ws", "memory")
    os.makedirs(mem)
    open(os.path.join(mem, "team.md"), "w").write("# Team\nIon\n- Batty: Lv12, released? no, boxed\n")
    open(os.path.join(mem, "todo.md"), "w").write("- [ ] read sign\n")
    old = watcher.CLAUDE
    watcher.CLAUDE = fake
    try:
        e = watcher.curate(os.path.dirname(mem), "test", direct=True)
    finally:
        watcher.CLAUDE = old
    assert e["archived_lines"] == 1 and e["note"] == "merged team", e
    assert "- Batty: Lv12, released? no, boxed" in open(os.path.join(mem, "archive.md")).read()
    assert open(os.path.join(mem, "todo.md")).read() == "- [ ] read sign\n"  # harness-owned: restored
    assert '"harness_call": "curator"' in open(os.path.join(root, "ws", "log.jsonl")).read()
    assert '"kind": "curator"' in open(os.path.join(root, "ws", "usage.jsonl")).read()


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
