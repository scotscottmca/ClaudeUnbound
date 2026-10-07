"""MCP server (stdio) exposing the bridge to Claude Code. Stdlib only.

    claude --mcp-config '{"mcpServers":{"unbound":{"command":"python","args":["<repo>/bridge/mcp_server.py"]}}}'

Every action is logged to run/log.jsonl. Tool results carry the harness's notes to the agent:
watchdog warnings (no progress), self-learning checks (every LEARN_EVERY actions) and
escalation hints for the model router (#37).
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import traceback

import bot
import milestones
import world as W
from probe import Probe
from state import TEXT_PRINTERS, get_state, press, raw

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.normpath(os.path.join(HERE, "..", "run"))
STATES = os.path.join(RUN, "states")
LOG = os.environ.get("UNBOUND_LOG") or os.path.join(RUN, "log.jsonl")
LEARN_EVERY = 40  # actions between self-learning checks (asked for every 25-50 steps)
STALL_AFTER = 15  # actions with no change in map/position/mode/dialog
TRAINER = 0x8  # gBattleTypeFlags bit
KEYS = ["A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT", "L", "R"]

p = None
steps = 0
tracker = milestones.Tracker(os.path.join(os.path.dirname(LOG), "milestones.jsonl"))
last_fingerprint, unchanged, watchdog_fired = None, 0, 0
battle_seen = False


def fingerprint(s):
    return (s["map"]["group"], s["map"]["num"], tuple(s["pos"]), s["mode"], s.get("dialog"),
            json.dumps(s.get("battle", {}).get("battlers")))


def summary(s):
    return {"mode": s["mode"], "map": s["map"]["name"], "pos": s["pos"], "badges": s["badges"],
            "party": [f"{m['name']} {m['hp']}" for m in s["party"]]}


def notes(s):
    """Harness messages appended to every action's result."""
    global last_fingerprint, unchanged, watchdog_fired, battle_seen
    out = []
    fp = fingerprint(s)
    unchanged = unchanged + 1 if fp == last_fingerprint else 0
    last_fingerprint = fp
    if unchanged >= STALL_AFTER:
        watchdog_fired += 1
        unchanged = 0
        out.append(f"WATCHDOG: nothing has changed for {STALL_AFTER} actions. Stop and reflect: take a "
                   "screenshot, re-read your objectives, try something different, or load_state the last "
                   "good save." + (" ESCALATE to the expert subagent: the watchdog has fired repeatedly."
                                   if watchdog_fired >= 2 else ""))
    if steps and steps % LEARN_EVERY == 0:
        out.append(f"LEARNING CHECK (action {steps}): review what happened since the last check. Record "
                   "new facts in memory/, add a learnings.md entry for anything that failed or surprised "
                   "you (what happened, root cause, rule), merge duplicates, and drop objectives that are "
                   "done. Keep it short.")
    in_battle = s["mode"] == "battle"
    if in_battle and not battle_seen:
        flags = int(s["battle"]["flags"], 16)
        foes = [b for b in s["battle"]["battlers"] if b["side"] == "opponent"]
        mine = [b for b in s["battle"]["battlers"] if b["side"] == "player"]
        if flags & TRAINER:
            strong = foes and mine and max(f["level"] for f in foes) >= max(m["level"] for m in mine)
            out.append("ESCALATE to the expert subagent: trainer battle against an equal or higher level foe."
                       if strong else
                       "ESCALATE to the strategist subagent: trainer battle. Ask it for a plan, then execute it.")
    battle_seen = in_battle
    return out


def log(entry):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": round(time.time(), 1), **entry}, ensure_ascii=False) + "\n")


def screenshot():
    path = os.path.join(tempfile.gettempdir(), "unbound-shot.png")
    p.shot(path)
    with open(path, "rb") as f:
        return {"type": "image", "data": base64.b64encode(f.read()).decode(), "mimeType": "image/png"}


def view():
    w = W.read_world(p)
    out = {"viewport": W.viewport(w), **{k: w[k] for k in ("npcs", "warps", "signs", "connections")}}
    # Exploration aid: doors and exits leading to maps never visited yet (#15's fog of war, map level).
    out["unvisited"] = [f"{x['to']} via {('warp at (%d, %d)' % (x['x'], x['y'])) if 'x' in x else x['direction'] + ' edge'}"
                        for x in w["warps"] + w["connections"] if tuple(x["to_map"]) not in tracker.seen_maps]
    return out


# --- tools ---------------------------------------------------------------------------------

def t_get_state(_):
    return {**get_state(p), "map_view": view()}


def t_get_screenshot(_):
    return screenshot()


def t_press_buttons(a):
    out = []
    for key in a["buttons"]:
        key = key.upper()
        if key not in KEYS:
            raise ValueError(f"unknown button {key}; use {KEYS}")
        t = press(p, key, a.get("hold_frames", 4), a.get("wait_frames", 16))
        out.append({"key": key, "moved": t["moved"], "changed": t["changed"]})
    return out


def t_advance_dialog(a):
    """A through dialog, collecting every box; stops before answering a question or when stuck."""
    seen = []
    for _ in range(a.get("max_presses", 30)):
        s = get_state(p)
        if s["mode"] != "dialog":
            break
        text = s.get("dialog", "")
        if not seen or seen[-1] != text:
            seen.append(text)
        if text.rstrip().endswith("?") and seen.count(text) == 1 and len(seen) > 1 and a.get("stop_on_question", True):
            break  # a question: the agent should choose the answer itself
        before = p.range(TEXT_PRINTERS, 4)
        p.press("A", 4)
        p.step(20)
        if seen.count(text) > 3 and p.range(TEXT_PRINTERS, 4) == before:
            break  # A isn't advancing: probably a Yes/No or choice menu
    return {"boxes": seen, "now": raw(p)["mode"]}


def run_bot(fn, *args):
    buf = io.StringIO()
    result = "done"
    with contextlib.redirect_stdout(buf):  # stdout is the MCP channel
        try:
            fn(*args)
        except SystemExit as e:
            result = str(e)
    return {"result": result, "log_tail": buf.getvalue().splitlines()[-12:]}


def t_walk_to(a):
    target = (a["x"], a["y"])
    goal = {target}
    w = W.read_world(p)
    if bot.plan(w, goal, set()) is None:
        # A wall, NPC or sign: go next to it and face it (that's how you talk to or read something).
        goal = {(target[0] + dx, target[1] + dy) for dx, dy in bot.DIRS.values()}
        print_note = f"({target[0]}, {target[1]}) isn't walkable; going next to it and facing it"
    else:
        print_note = None

    def walk():
        if print_note:
            print(print_note)
        for i in range(a.get("max_steps", 60)):
            s = get_state(p)
            if tuple(s["pos"]) in goal:
                if tuple(s["pos"]) != target:
                    dx, dy = target[0] - s["pos"][0], target[1] - s["pos"][1]
                    face = next(k for k, d in bot.DIRS.items() if d == (dx, dy))
                    if s.get("facing") != face.lower():
                        press(p, face)
                print(f"arrived at {s['pos']}, facing {target}" if tuple(s["pos"]) != target else f"arrived at {s['pos']}")
                return
            if s["mode"] != "overworld":
                raise SystemExit(f"stopped: mode is {s['mode']}")
            w = W.read_world(p)
            path = bot.plan(w, goal, set())
            if not path:
                raise SystemExit(f"no path from {w['player']} to {sorted(goal)[0]}")
            t = press(p, path[0])
            if not t["moved"] and t["changed"] != ["facing"]:
                t = press(p, path[0])
                if not t["moved"]:
                    raise SystemExit(f"blocked going {path[0]} from {w['player']}")
        raise SystemExit("max_steps reached")
    return run_bot(walk)


def t_travel_to(a):
    bot.MAX_STEPS = a.get("max_steps", 300)
    if a.get("on_wild_battle", "stop") == "stop":
        def stop_on_battle(_p):
            raise SystemExit("stopped: wild battle started")
        old, bot.battle = bot.battle, stop_on_battle
        try:
            return run_bot(bot.go, p, a["map"])
        finally:
            bot.battle = old
    return run_bot(bot.go, p, a["map"])


def t_save_state(a):
    os.makedirs(STATES, exist_ok=True)
    p.save(os.path.join(STATES, a["name"] + ".ss1"))
    return {"saved": a["name"]}


def t_load_state(a):
    p.load(os.path.join(STATES, a["name"] + ".ss1"))
    p.step(2)
    return {"loaded": a["name"]}


def t_read_memory(a):
    return {"addr": hex(a["addr"]), "hex": p.range(a["addr"], min(a["length"], 0x1000)).hex(" ")}


S = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
TOOLS = {
    "get_state": (t_get_state, "Current game state: mode (overworld/battle/dialog/other), map, position, "
                  "facing, badges, money, party, battle details, current dialog box, and map_view: the 15x10 "
                  "viewport grid (@ you, N NPC/object, T trainer, . walkable, # blocked, G tall grass, "
                  "~ water, W waterfall, I ice, F forced movement, D warp/door, S sign, : walkable but another "
                  "level, ^v<> ledge) plus NPC, warp, sign and connection lists. Coordinates are map tiles.",
                  S({}), False),
    "get_screenshot": (t_get_screenshot, "Screenshot of the game screen (240x160).", S({}), False),
    "press_buttons": (t_press_buttons, "Press buttons in order. Each press reports whether you moved and what "
                      "changed. A direction you aren't facing turns you first; press it again to step.",
                      S({"buttons": {"type": "array", "items": {"type": "string", "enum": KEYS}},
                         "hold_frames": {"type": "integer"}, "wait_frames": {"type": "integer"}}, ["buttons"]), True),
    "advance_dialog": (t_advance_dialog, "Press A through dialog and return every text box seen. Stops at a "
                       "question so you can choose the answer, or when A stops advancing (a menu).",
                       S({"max_presses": {"type": "integer"}, "stop_on_question": {"type": "boolean"}}), True),
    "walk_to": (t_walk_to, "Walk to tile (x, y) on the current map by the shortest safe path. If (x, y) is "
                "an NPC, sign or wall, walks next to it and faces it, ready to press A. Stops at battles, "
                "dialog, or when blocked.",
                S({"x": {"type": "integer"}, "y": {"type": "integer"}, "max_steps": {"type": "integer"}},
                  ["x", "y"]), True),
    "travel_to": (t_travel_to, "Travel to the named map (e.g. 'Route 2') across maps via doors and edges. "
                  "Stops when a wild battle starts unless on_wild_battle='flee'. Story-blocked paths are "
                  "routed around; if none is open it stops and says so.",
                  S({"map": {"type": "string"}, "on_wild_battle": {"type": "string", "enum": ["stop", "flee"]},
                     "max_steps": {"type": "integer"}}, ["map"]), True),
    "save_state": (t_save_state, "Save an emulator savestate under a name (for rollback).",
                   S({"name": {"type": "string"}}, ["name"]), False),
    "load_state": (t_load_state, "Load a savestate saved with save_state.",
                   S({"name": {"type": "string"}}, ["name"]), True),
    "read_memory": (t_read_memory, "Read up to 4096 bytes of GBA memory (hex). For discovering RAM by "
                    "diffing: read, act, read again. Use docs/addresses.md knowledge sparingly.",
                    S({"addr": {"type": "integer"}, "length": {"type": "integer"}}, ["addr", "length"]), False),
}


def call(name, args):
    global steps, p
    fn, _, _, is_action = TOOLS[name]
    try:
        result = fn(args)
    except (ConnectionError, OSError, RuntimeError) as e:
        if "connection" not in repr(e).lower() and not isinstance(e, OSError):
            raise
        p = Probe()  # mGBA restarted: reconnect once and retry
        result = fn(args)
    content = [result] if isinstance(result, dict) and result.get("type") == "image" else \
        [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
    if is_action:
        steps += 1
        s = get_state(p)
        msgs = notes(s)
        try:
            for e in tracker.update(s, steps):
                msgs.append("MILESTONE: " + json.dumps(e, ensure_ascii=False))
        except Exception as e:  # never let bookkeeping break a tool
            log({"step": steps, "error": f"milestones: {e!r}"})
        content.append({"type": "text", "text": json.dumps({"now": summary(s), "harness": msgs},
                                                          ensure_ascii=False)})
        log({"step": steps, "tool": name, "args": args, "now": summary(s), "harness": msgs})
    else:
        log({"step": steps, "tool": name, "args": args})
    return content


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "unbound", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": sch} for n, (_, d, sch, _) in TOOLS.items()]}
    elif method == "tools/call":
        try:
            result = {"content": call(msg["params"]["name"], msg["params"].get("arguments") or {})}
        except Exception as e:
            log({"step": steps, "tool": msg["params"]["name"], "error": repr(e)})
            result = {"content": [{"type": "text", "text": f"error: {e!r}\n{traceback.format_exc()[-800:]}"}],
                      "isError": True}
    elif method == "ping":
        result = {}
    elif mid is None:
        return None  # notification
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    global p
    p = Probe()
    for line in sys.stdin:
        if line.strip():
            reply = handle(json.loads(line))
            if reply is not None:
                sys.stdout.write(json.dumps(reply) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
