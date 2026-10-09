"""MCP server (stdio) exposing the bridge to Claude Code. Stdlib only.

    claude --mcp-config '{"mcpServers":{"unbound":{"command":"python","args":["<repo>/bridge/mcp_server.py"]}}}'

Every action is logged to run/log.jsonl. Tool results carry the harness's notes to the agent:
watchdog warnings (no progress), self-learning checks (every LEARN_EVERY actions) and
escalation hints for the model router (#37).

Hot reload: before each tool call, serve() re-imports every bridge module (this file included) if any
bridge/*.py changed, so fixes land without restarting the agent's session. The runtime state (counters,
watchdog, verification gate) is persisted to server_state.json next to the log after every call and
restored on import. A module that fails to import leaves the previous code running and says so.
"""
import base64
import collections
import contextlib
import difflib
import glob
import importlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import traceback

import bot
import battle
import items
import milestones
import moves
import naming
import state as state_mod
import watcher
import wiki
import world as W
from probe import Probe
from state import BATTLE_MONS, G_MAIN, get_state, press, raw

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.normpath(os.path.join(HERE, "..", "run"))
STATES = os.path.join(RUN, "states")
LOG = os.environ.get("UNBOUND_LOG") or os.path.join(RUN, "log.jsonl")
VERIFY_GRACE = 3  # actions allowed after a VERIFY note before game actions are blocked
verify_due = 0  # action number when verification became due (0: none pending)
last_prompt = None  # irreversible prompt already flagged
last_verified = -99  # action number of the last recorded verification
IRREVERSIBLE = ("forget", "forgot", "delete", "make room", "release", "toss", "throw away", "discard", "give up", "stop learning")  # not "overwrite": the in-game save prompt; savestates cover it
LEARN_EVERY = 40  # actions between self-learning checks (asked for every 25-50 steps)
STALL_AFTER = 15  # actions with no change in map/position/mode/dialog
TRAINER = 0x8  # gBattleTypeFlags bit
WILD_RANDOM = 0x4  # gBattleTypeFlags of an ordinary random wild battle (verified on Snorunt, Vanillite)
SCRIPTED = 0x20000  # set on scripted/static encounters (Binacle, Route 2: 0x20004); not on random ones
KEYS = ["A", "B", "START", "SELECT", "UP", "DOWN", "LEFT", "RIGHT", "L", "R"]

p = None
steps = 0
tracker = milestones.Tracker(os.path.join(os.path.dirname(LOG), "milestones.jsonl"))
bot.load_dead_edges(os.path.join(os.path.dirname(LOG), "dead_edges.json"))
arrivals = collections.deque(maxlen=20)  # (map, pos) each time the player ends an action somewhere new
TALKED = os.path.join(os.path.dirname(LOG), "npcs_talked.json")  # "group,num,localId" of NPCs talked to
talked = set(json.load(open(TALKED))) if os.path.exists(TALKED) else set()


def note_talk(s):
    """Text just started: if the player faces an adjacent NPC or sign, remember it (talk/read once)."""
    w = W.read_world(p)
    dx, dy = bot.DIRS[s["facing"].upper()] if s.get("facing") else (0, 0)
    target = (w["player"][0] + dx, w["player"][1] + dy)
    # NPCs are keyed by their ID (they move); signs by position.
    keys = [f"{s['map']['group']},{s['map']['num']},{n['id']}" for n in w["npcs"] if (n["x"], n["y"]) == target]
    keys += [f"{s['map']['group']},{s['map']['num']},sign@{x['x']},{x['y']}" for x in w["signs"] if (x["x"], x["y"]) == target]
    if set(keys) - talked:
        talked.update(keys)
        with open(TALKED, "w") as f:
            json.dump(sorted(talked), f)
last_fingerprint, unchanged, watchdog_fired = None, 0, 0
last_map = None  # (group, num) after the previous action, for the UNEXPLORED note
items_noted = set()  # object ids of ground items already pointed out on this visit
doors_flagged = set()  # (map, x, y) doors already named in an UNEXPLORED note
items_close = set()  # object ids of ground items already pointed out at close range on this visit
last_obs = None  # what the observers saw on the current map at the last overworld action
TODO = os.path.join(os.path.dirname(LOG), "todo.json")  # harness-kept to-do list, rendered to memory/todo.md


def _todo_load():
    try:
        return json.load(open(TODO, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _todo_save(t):
    with open(TODO, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=0)
    md = os.path.join(os.path.dirname(LOG), "memory", "todo.md")
    if os.path.isdir(os.path.dirname(md)):
        lines = ["# To do (kept by the harness: entries disappear once resolved)", ""]
        lines += [f"- {v}" for v in sorted(t.values())] or ["- nothing pending"]
        with open(md, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


def todo_add(o):
    """Things left behind on a map (items, NPCs, signs) and doors never entered."""
    t = _todo_load()
    g, n = o["map"]
    for x, y in o["items"]:
        t[f"item:{g},{n}:{x},{y}"] = f"{o['name']} ({g},{n}): item on the ground at ({x},{y})"
    for x, y in o["npcs"]:
        t[f"npc:{g},{n}:{x},{y}"] = f"{o['name']} ({g},{n}): talk to the NPC near ({x},{y})"
    for x, y in o["signs"]:
        t[f"sign:{g},{n}:{x},{y}"] = f"{o['name']} ({g},{n}): read the sign at ({x},{y})"
    _todo_save(t)


def todo_resolve(o):
    """Drop entries for this map that are done: the item is gone, the NPC talked to, the sign read."""
    t = _todo_load()
    g, n = o["map"]
    keep = {f"item:{g},{n}:{x},{y}" for x, y in o["items"]} | {f"sign:{g},{n}:{x},{y}" for x, y in o["signs"]}
    keep |= {f"npc:{g},{n}:{x},{y}" for x, y in o["npcs"]}
    here = f":{g},{n}:"
    gone = [k for k in t if here in k and k not in keep and not k.startswith("npc:")]
    # NPCs wander, so their positions drift: an NPC entry clears only when no untalked NPC is left on the map.
    if not o["npcs"]:
        gone += [k for k in t if here in k and k.startswith("npc:")]
    # A door is done once the map behind it has been visited.
    gone += [k for k in t if k.startswith("door:") and tuple(map(int, k.split("|")[1].split(","))) in tracker.seen_maps]
    if gone:
        for k in gone:
            t.pop(k, None)
        _todo_save(t)
battle_seen = False


def fingerprint(s):  # a string, so it compares equal after a save/restore
    return json.dumps([s["map"]["group"], s["map"]["num"], s["pos"], s["mode"], s.get("dialog"),
                       s.get("battle", {}).get("battlers"), (s.get("battle") or {}).get("text")])


# Runtime state that must survive a hot reload (and a server restart): saved after every call.
STATE_FILE = os.path.join(os.path.dirname(LOG), "server_state.json")
PERSIST = ("steps", "verify_due", "last_verified", "last_prompt", "last_fingerprint", "unchanged",
           "watchdog_fired", "battle_seen")


def persist():
    d = {k: globals()[k] for k in PERSIST}
    d["arrivals"] = list(arrivals)
    with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)


def restore():
    if os.path.exists(STATE_FILE):
        d = json.load(open(STATE_FILE, encoding="utf-8"))
        globals().update({k: d[k] for k in PERSIST if k in d})
        arrivals.extend((g, n, tuple(xy)) for g, n, xy in d.get("arrivals", []))


REPO_INSTRUCTIONS = os.path.join(HERE, "..", "agent", "CLAUDE.md")


def sync_instructions():
    """agent/CLAUDE.md changed in the repo: copy it into the workspace (where the runner put the agent's
    CLAUDE.md) and tell the agent which sections changed. Returns harness notes."""
    ws_copy = os.path.join(os.path.dirname(LOG), "CLAUDE.md")
    if not os.path.exists(ws_copy):  # not a runner workspace
        return []
    old = open(ws_copy, encoding="utf-8").read().splitlines()
    new = open(REPO_INSTRUCTIONS, encoding="utf-8").read().splitlines()
    if old == new:
        return []
    heads = []
    for tag, _i1, _i2, j1, _j2 in difflib.SequenceMatcher(None, old, new).get_opcodes():
        if tag != "equal":
            h = next((l.lstrip("# ") for l in reversed(new[:j1 + 1]) if l.startswith("#")), "top")
            if h not in heads:
                heads.append(h)
    shutil.copy(REPO_INSTRUCTIONS, ws_copy)
    return [f"INSTRUCTIONS UPDATED: re-read CLAUDE.md (changed: {', '.join(heads)})"]


def summary(s):
    # map_id tells apart maps that share a name (a cave's floors: Frost Mountain is 50/0 and 50/1)
    return {"mode": s["mode"], "map": s["map"]["name"], "map_id": [s["map"]["group"], s["map"]["num"]], "pos": s["pos"],
            "badges": s["badges"],
            "party": [f"{m['name']} {m['hp']}" for m in s["party"]]}


def own_battler_fainted():
    """One of your battlers (0, or 2 in a double) is a Pokemon at 0 HP: gBattleMons species +0, HP +0x28."""
    for b in (0, 2):
        species, = struct.unpack("<H", p.range(BATTLE_MONS + b * 0x58, 2))
        hp, = struct.unpack("<H", p.range(BATTLE_MONS + b * 0x58 + 0x28, 2))
        if species and not hp:
            return True
    return False


def notes(s):
    """Harness messages appended to every action's result."""
    global last_fingerprint, unchanged, watchdog_fired, battle_seen
    out = []
    if p.read32(G_MAIN + 4) == naming.NAMING_CB2:
        out.append("NAMING SCREEN: use type_name(name) to type the name and confirm; don't walk the keyboard.")
    fp = fingerprint(s)
    unchanged = unchanged + 1 if fp == last_fingerprint else 0
    last_fingerprint = fp
    if unchanged >= STALL_AFTER:
        watchdog_fired += 1
        unchanged = 0
        out.append(f"WATCHDOG: nothing has changed for {STALL_AFTER} actions. Stop and reflect: take a "
                   "screenshot, re-read your objectives and try something different. Rolling back to a savestate "
                   "is not allowed: work your way out." + (" ESCALATE to the expert subagent: the watchdog has fired repeatedly."
                                   if watchdog_fired >= 2 else ""))
    global last_map
    here = (s["map"]["group"], s["map"]["num"])
    if last_map and here != last_map:
        # Leaving a map with doors never entered: the full run walked past 12 buildings (missions, a trade)
        # although get_state lists unvisited exits (docs/bootstrap-report.md). Say so once, on the way out.
        try:
            ds = W.doors(*last_map)
            # Walking into one of this map's own buildings is exploring, not leaving (first live fire: Bellin).
            skipped = [] if here in {d for _, _, d in ds} else \
                [(x, y) for x, y, dest in ds if dest not in tracker.seen_maps and (last_map, x, y) not in doors_flagged]
            doors_flagged.update((last_map, x, y) for x, y in skipped)  # once per door: Dresco (1,9) repeated every exit
            if skipped:
                t = _todo_load()
                for x, y, dest in ds:
                    if (x, y) in skipped:
                        t[f"door:{last_map[0]},{last_map[1]}:{x},{y}|{dest[0]},{dest[1]}"] = \
                            f"{W.map_name(None, *last_map)} {tuple(last_map)}: enter the door at ({x},{y})"
                _todo_save(t)
        except Exception:  # ROM read for a map header: hints only
            skipped = []
        if skipped:
            out.append(f"UNEXPLORED: you left {W.map_name(None, *last_map)} with {len(skipped)} door(s) never entered "
                       f"at {', '.join(f'({x},{y})' for x, y in skipped[:8])}. Policy: enter every building and talk "
                       "to everyone once. Go back unless something stops you (a story gate, a locked door).")
    global last_obs
    if here != last_map:
        items_noted.clear()  # a new visit: mention this map's items again
        items_close.clear()
        if last_obs and last_obs["map"] == last_map:  # leaving: what was left behind on the map just left
            o, parts = last_obs, []
            for kind, label in (("items", "item(s) on the ground"), ("npcs", "NPC(s) not talked to"),
                                ("signs", "sign(s) not read")):
                if o[kind]:
                    parts.append(f"{len(o[kind])} {label} at {', '.join(f'({x},{y})' for x, y in o[kind][:6])}")
            if parts:
                out.append(f"MISSED on {o['name']}: {'; '.join(parts)}. Added to memory/todo.md: go back now, or "
                           "pick them up when you pass again.")
                todo_add(o)
    last_map = here
    if s["mode"] == "overworld":
        # Observers, every action (user, 2026-10-08: learning as real-time as possible).
        try:
            w = W.read_world(p)
            px, py = w["player"]
            items = []
            for n in w["npcs"]:
                if not n.get("item"):
                    continue
                near = {(n["x"] + dx, n["y"] + dy) for dx, dy in bot.DIRS.values()}
                if bot.plan(w, near, set()) is None:
                    continue
                items.append((n["x"], n["y"]))
                dx, dy = n["x"] - px, n["y"] - py
                if n["id"] not in items_noted:
                    items_noted.add(n["id"])
                    out.append(f"ITEM: an item on the ground at ({n['x']},{n['y']}) ('o' on the map) is reachable: "
                               "walk_to it to pick it up.")
                elif abs(dx) + abs(dy) <= 4 and n["id"] not in items_close:  # walking past it
                    items_close.add(n["id"])
                    where = ", ".join(f"{abs(v)} {d}" for v, d in ((dx, "right" if dx > 0 else "left"),
                                                                    (dy, "down" if dy > 0 else "up")) if v)
                    out.append(f"ITEM {where} of you at ({n['x']},{n['y']}): pick it up while you're here.")
            g, num = here
            npcs = [(n["x"], n["y"]) for n in w["npcs"] if not n.get("item") and f"{g},{num},{n['id']}" not in talked]
            signs = [(x["x"], x["y"]) for x in w["signs"] if f"{g},{num},sign@{x['x']},{x['y']}" not in talked]
            last_obs = {"map": here, "name": s["map"]["name"], "items": items, "npcs": npcs, "signs": signs}
            todo_resolve(last_obs)
        except Exception:  # hints only
            pass
    lead = next((m for m in s["party"] if not m["hp"].startswith("0/")), None)
    if s["mode"] == "overworld" and lead:
        hp, top = map(int, lead["hp"].split("/"))
        if hp * 4 <= top:  # the agent once walked deeper into Icicle Cave with its lead at 6/37
            out.append(f"LOW HP: your lead {lead['name']} is at {lead['hp']}. Heal (a potion, or a Pokemon Center / "
                       "home) before more grass or caves, or put a healthy Pokemon first.")
    spot = (s["map"]["group"], s["map"]["num"], tuple(s["pos"]))
    if s["mode"] == "overworld" and (not arrivals or arrivals[-1] != spot):
        arrivals.append(spot)
        if arrivals.count(spot) >= 4:  # moving, so the no-change watchdog can't see it
            watchdog_fired += 1
            arrivals.clear()
            out.append(f"WATCHDOG: you keep coming back to {s['map']['name']} (map {s['map']['group']}/{s['map']['num']}) {s['pos']} (4 times in the last 20 "
                       "moves): you're going in circles. Stop. Re-read memory/map_notes.md and objectives.md for "
                       "this place, take a screenshot, and pick a genuinely different route or goal."
                       + (" ESCALATE to the expert subagent: the watchdog has fired repeatedly."
                          if watchdog_fired >= 2 else ""))
    global verify_due
    # Routine verification is harness-run now (watcher.py, user 2026-10-08); only irreversible prompts gate actions.
    # Battle prompts too: "Delete a move?" when learning a fifth move happens inside battle.
    text = (s.get("dialog") or (s.get("battle") or {}).get("text") or "").lower()
    global last_prompt
    if s["mode"] in ("dialog", "battle") and text.rstrip().endswith("?") and any(w in text for w in IRREVERSIBLE):
        verify_due = verify_due or steps
        if text != last_prompt:  # once per prompt: repeating it every action only costs context
            out.append("VERIFY before answering: this looks irreversible. Ask the verifier subagent to approve your "
                       "answer first.")
        last_prompt = text
    else:
        last_prompt = None
    # The battle party screen also opens for an item (a Potion) or a voluntary switch; it's forced only when one
    # of your battlers (0, or 2 in a double) has fainted.
    if raw(p)["cb2"] == hex(battle.CB2_BATTLE_PARTY) and s["mode"] != "battle" and own_battler_fainted():
        alive = [m["name"] for m in s["party"] if not m["hp"].startswith("0/")]
        out.append(f"FORCED SWITCH: the game is waiting for a replacement and B can't cancel it. Call "
                   f"switch_to with one of {alive} (not one already in battle).")
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
        if not flags & TRAINER and flags & SCRIPTED and not all(f.get("caught") for f in foes):
            # Random encounters are 0x4 (plus 0x1 double / 0x400000 with a partner: 0x400005 in Cinder Volcano,
            # a false "special" once); scripted ones (Binacle on Route 2) carry 0x20000. Always catch these,
            # unless the species is already owned (user rule: don't re-catch).
            out.append("SPECIAL ENCOUNTER (not a random wild Pokemon): it may never appear again. Catch it: "
                       "weaken it without knocking it out (status moves help), then throw balls.")
        if flags & TRAINER and foes and mine:
            # Only spend a stronger model where it matters: the agent rightly ignored the note for an
            # easy trainer, and a note it learns to ignore is worse than none.
            gap = max(f["level"] for f in foes) - max(m["level"] for m in mine)
            if gap >= 0:
                out.append("ESCALATE to the expert subagent: trainer battle against an equal or higher level foe.")
            elif gap >= -2:
                out.append("ESCALATE to the strategist subagent: trainer battle against a close-level foe. "
                           "Ask it for a plan, then execute it.")
    # One escalation per battle: switching Pokemon opens the party screen (not the battle callback),
    # which used to reset this and re-fire the note several times in one fight.
    battle_seen = True if in_battle else (False if s["mode"] == "overworld" else battle_seen)
    try:  # background watcher/verifier results, then drop notes repeated within ~10 actions
        out = watcher.hygiene(steps, out + watcher.drain(log))
    except Exception as e:  # hints only
        log({"step": steps, "error": f"watcher drain: {e!r}"})
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
    g, n = struct.unpack("<bb", p.range(p.read32(0x03005008) + 4, 2))  # SaveBlock1 location: group, num
    out["npcs"] = [{**x, "talked": f"{g},{n},{x['id']}" in talked} for x in w["npcs"]]
    out["signs"] = [{**x, "read": f"{g},{n},sign@{x['x']},{x['y']}" in talked} for x in w["signs"]]
    # Exploration aid: doors and exits leading to maps never visited yet (#15's fog of war, map level).
    out["unvisited"] = [f"{x['to']} via {('warp at (%d, %d)' % (x['x'], x['y'])) if 'x' in x else x['direction'] + ' edge'}"
                        for x in w["warps"] + w["connections"] if tuple(x["to_map"]) not in tracker.seen_maps]
    return out


# --- tools ---------------------------------------------------------------------------------

def t_get_state(_):
    s = get_state(p)
    try:
        mv = view()
    except ValueError as e:  # the map is still loading (or a special screen): state without the map view
        mv = {"unavailable": str(e)}
    if s.get("battle"):
        try:
            s["battle"]["matchups"] = moves.matchups(s)
        except Exception as e:  # hints only: never break get_state
            s["battle"]["matchups"] = f"unavailable: {e!r}"
    if p.read32(G_MAIN + 4) == naming.NAMING_CB2:
        s["naming_screen"] = {"typed": naming.text(p), "how": "type_name(name)"}
    return {**s, "map_view": mv}


def t_get_screenshot(_):
    return screenshot()


def t_press_buttons(a):
    out = []
    buttons = a["buttons"]
    if isinstance(buttons, str):  # "A" or "UP, A": a bare string used to be split into letters
        buttons = [b for b in buttons.replace(",", " ").split()]
    for key in buttons:
        key = key.upper()
        if key == "WAIT":  # the agent asked for this: let a cutscene or animation play out
            p.step(30)
            out.append({"key": "WAIT", "frames": 30})
            continue
        if key not in KEYS:
            raise ValueError(f"unknown button {key}; use {KEYS + ['WAIT']}")
        t = press(p, key, a.get("hold_frames", 4), a.get("wait_frames", 16))
        out.append({"key": key, "moved": t["moved"], "changed": t["changed"],
                    **({"party_cursor": t["after"]["party_cursor"]} if "party_cursor" in t.get("after", {}) else {})})
    return out


def t_advance_dialog(a):
    """A through dialog, collecting every box; stops before answering a question or when stuck."""
    seen, waited = [], 0
    if raw(p)["mode"] == "battle":  # battle messages: A through them until a menu, a question or the end
        for _ in range(a.get("max_presses", 30)):
            b, _ = battle.wait_for_menu(p, frames=240, seen=seen)
            mode = raw(p)["mode"]
            if b is not None or mode != "battle":
                break
            text = ((get_state(p).get("battle") or {}).get("text") or "").strip()
            if text.startswith("What will"):  # "What will Ion do?": your action menu is coming up
                p.step(20)
                continue
            if text.endswith("?"):  # a Yes/No question: the agent answers it
                if not seen or seen[-1] != text:
                    seen.append(text)
                break
            # Not a question: a box that waits for A without an active printer (level-up stats, "You defeated ...")
            p.press("A", 4)
            p.step(20)
        mode = raw(p)["mode"]
        return {"boxes": seen, "now": mode,
                "battle": "your menu is up" if b is not None else "battle over" if mode != "battle" else "a question is waiting"}
    for _ in range(a.get("max_presses", 30) + 16):
        s = get_state(p)
        if s["mode"] != "dialog":
            if raw(p)["script"] and waited < 240:  # a cutscene still running: text may be coming
                p.step(15)
                waited += 15
                continue
            break
        waited = 0
        text = s.get("dialog", "")
        if not seen or seen[-1] != text:
            seen.append(text)
        if text.rstrip().endswith("?") and seen.count(text) == 1 and len(seen) > 1 and a.get("stop_on_question", True):
            break  # a question: the agent should choose the answer itself
        before = raw(p)["printer"][0:4]
        p.press("A", 4)
        p.step(20)
        if seen.count(text) > 3 and raw(p)["printer"][0:4] == before:
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
    w = W.read_world(p)
    npc_id = next((n["id"] for n in w["npcs"] if (n["x"], n["y"]) == target), None)
    sign = next((x for x in w["signs"] if (x["x"], x["y"]) == target), None)
    interact = npc_id is not None or sign is not None  # walking up to someone/something is to talk/read
    wall = not interact and bot.plan(w, {target}, set()) is None

    def goal_for(w):
        """(where the thing is now, tiles to stand on). NPCs are followed by ID: they wander."""
        t = target
        if npc_id is not None:
            n = next((n for n in w["npcs"] if n["id"] == npc_id), None)
            if n is None:
                raise SystemExit(f"that NPC (id {npc_id}) is no longer on this map")
            t = (n["x"], n["y"])
        if sign and sign["read_facing"]:  # signs read from one side only (most: from below, facing up)
            dx, dy = bot.DIRS[sign["read_facing"].upper()]
            return t, {(t[0] - dx, t[1] - dy)}
        if interact or wall:
            return t, {(t[0] + dx, t[1] + dy) for dx, dy in bot.DIRS.values()}
        return t, {t}

    def walk():
        refused = 0
        for i in range(a.get("max_steps", 200)):
            s = get_state(p)
            if s["mode"] != "overworld":
                raise SystemExit(f"stopped: mode is {s['mode']}")
            w = W.read_world(p)
            here_map = (s["map"]["group"], s["map"]["num"])
            w["no_move"] = bot.NO_MOVE.get(here_map, set())
            t, goal = goal_for(w)
            if tuple(s["pos"]) in goal:
                if tuple(s["pos"]) != t:
                    face = next(k for k, d in bot.DIRS.items() if d == (t[0] - s["pos"][0], t[1] - s["pos"][1]))
                    if s.get("facing") != face.lower():
                        press(p, face)  # a short tap only turns
                    if interact:
                        if raw(p)["mode"] != "overworld":
                            # Walking into a sign reads it (FireRed): the turn already opened it. Pressing A
                            # now would close it before anyone reads it.
                            print(f"next to {t}; turning to it opened it")
                            return
                        p.step(10)  # the last step's animation outlasts the position update
                        p.press("A", 4)  # then at once, before a wandering NPC can step away
                        p.step(30)
                        print(f"next to {t}, facing it, pressed A")
                        return
                print(f"arrived at {s['pos']}" + (f", facing {t}" if tuple(s["pos"]) != t else ""))
                return
            path = bot.plan(w, goal, set())
            if not path:
                why = ""
                try:  # which level/region the target is on, and how that region is entered
                    why = "\n" + "\n".join(bot.describe_levels(w, t).splitlines()[:4])
                except Exception:
                    pass
                raise SystemExit(f"no path from {w['player']} to {t}" + (" or any tile next to it" if interact or wall else "")
                                 + " (it may be behind a one-way ledge, on another level, or blocked)" + why)
            if bot.stride(p, path, s.get("facing")) == 0 and raw(p)["mode"] == "overworld":
                # The game refused a move the planner thought open (an unmodelled tile, an invisible block):
                # remember it for this map and plan around it, rather than stop and have the same move retried.
                refused += 1
                to = bot.landing(w, *w["player"], path[0])
                if not any(abs(n["x"] - to[0]) + abs(n["y"] - to[1]) <= 1 for n in w["npcs"]):  # an NPC: just in the way
                    bot.NO_MOVE.setdefault(here_map, set()).add((*w["player"], path[0]))
                print(f"blocked going {path[0]} from {w['player']} (tile behavior 0x{w['tile'](*w['player'])[0]:X}): "
                      "remembered, planning around it")
                if refused >= 3:
                    raise SystemExit(f"blocked going {path[0]} from {w['player']}, and around it {refused} times")
        raise SystemExit("max_steps reached")
    return run_bot(walk)


def _menu_tool(fn, *args):
    """A menu tool that returns a sentence (or refuses with SystemExit): the sentence is the result."""
    try:
        return {"result": fn(p, *args)}
    except SystemExit as e:
        return {"result": str(e)}


def t_give_item(a):
    import party_menu
    return _menu_tool(party_menu.give_item, a["item"], a["pokemon"], bool(a.get("replace")))


def t_take_item(a):
    import party_menu
    return _menu_tool(party_menu.take_item, a["pokemon"])


def t_reorder_party(a):
    import party_menu
    return _menu_tool(party_menu.reorder_party, a["pokemon"], a["position"])


def t_pc_deposit(a):
    import pc
    return _menu_tool(pc.pc_deposit, a["pokemon"], a.get("box"))


def t_pc_withdraw(a):
    import pc
    return _menu_tool(pc.pc_withdraw, a["box"], a["slot"])


def t_pc_swap(a):
    import pc
    return _menu_tool(pc.pc_swap, a["pokemon"], a["box"], a["slot"])


def t_buy(a):
    import shop
    return _menu_tool(shop.buy, a["item"], int(a.get("quantity", 1)))


def t_fly(a):
    import fly
    return _menu_tool(fly.fly, a["destination"])


def t_use_on(a):
    import items
    return _menu_tool(items.use_on, a["item"], a["pokemon"])


def t_team_details(a):
    import stats
    n = p.read8(state_mod.PLAYER_PARTY_COUNT)
    raw = p.range(state_mod.PLAYER_PARTY, 100 * n)
    badges = state_mod.get_state(p)["badges"]
    cap = stats.level_cap(badges)
    party = [stats.detail(raw[k * 100:(k + 1) * 100]) for k in range(n)]
    at = [m["name"] for m in party if cap and m["level"] >= cap]
    return {"party": party,
            "level_cap": (f"{cap} ({stats.DIFFICULTY} difficulty, {badges} badges)" + (
                f"; at or over it: {', '.join(at)} (they gain almost no EXP now: train the others, or win the next badge)"
                if at else "")) if cap else f"none ({stats.DIFFICULTY} difficulty: Capped Exp. Share is off)",
            "rules": "Every 4 EVs in a stat = +1 at level 100 (about +1 per 4 EVs scaled by level/100 now). Max 510 EVs "
                     "in total, 252 in one stat. Defeating a Pokemon gives every party member its EV yield (Exp. Share). "
                     "Nature: +10% to one stat, -10% to another. IVs 0-31 are fixed per Pokemon."}


def t_pc_boxes(a):
    import stats
    bx = stats.boxes(p)
    return {"boxes": {f"Box {k}": [f"{slot}: {m['name']} ({m['species']} Lv{m['level']}, {'/'.join(m['types'])}; "
                                   f"{m['nature']}; moves {', '.join(m['moves'])}" + (f"; holds {m['item']}" if m["item"] else "")
                                   + f"; IVs {m['ivs']}; EVs {m['evs']})" for slot, m in v] for k, v in sorted(bx.items())},
            "note": "Read-only list of your PC boxes (boxes 1-19). Swapping team members needs the PC at a Pokemon Center."}


def t_map_levels(a):
    w = W.read_world(p)
    target = (a["x"], a["y"]) if "x" in a and "y" in a else None
    return {"regions": bot.describe_levels(w, target).splitlines()}


def t_sneak_to(a):
    return run_bot(bot.sneak, p, (a["x"], a["y"]), a.get("max_steps", 80), a.get("max_wait_frames", 2400))


def t_watch_area(a):
    return run_bot(bot.watch, p, a.get("frames", 480), 4, a.get("radius", 10))


def t_travel_to(a):
    bot.MAX_STEPS = a.get("max_steps", 300)
    # Every wild Pokemon is battled (user rule, 2026-10-08): stop and hand the battle to the agent, never flee.
    def stop_on_battle(_p):
        raise SystemExit("stopped: wild battle started. Battle it, and catch it if you have Poke Balls.")
    old, bot.battle = bot.battle, stop_on_battle
    try:
        return run_bot(bot.go, p, a["map"], False)
    finally:
        bot.battle = old


def t_fight(a):
    try:
        return {"result": battle.fight(p, a["move"])}
    except SystemExit as e:
        return {"result": str(e)}


def t_switch_to(a):
    try:
        return {"result": battle.switch_to(p, a["pokemon"] if "pokemon" in a else a.get("name", ""))}
    except SystemExit as e:
        return {"result": str(e)}


def t_throw_ball(a):
    try:
        return {"result": battle.throw_ball(p, a.get("ball") or "Poké Ball")}
    except SystemExit as e:
        return {"result": str(e)}


def t_use_item(a):
    try:
        return {"result": items.use_item(p, a.get("item", ""), a.get("pokemon") or a.get("name", ""))}
    except SystemExit as e:
        return {"result": str(e)}


def t_run_away(a):
    foe = struct.unpack("<H", p.range(BATTLE_MONS + 0x58, 2))[0]
    if foe and state_mod.caught(p, foe):  # already caught: fleeing is fine (user rule, 2026-10-08)
        a = {**a, "reason": a.get("reason") or "already caught this species"}
    if len(a.get("reason", "").strip()) < 10:
        return {"result": "NOT RUN: wild Pokemon you haven't caught are battled and caught. Run only if you may lose the fight: "
                          "call run_away again with reason explaining why (HP, levels, type matchup)."}
    log({"step": steps, "run_away_reason": a["reason"][:300]})
    try:
        return {"result": battle.run(p)}
    except SystemExit as e:
        return {"result": str(e)}


def t_type_name(a):
    try:
        return {"typed": naming.type_name(p, a["name"])}
    except (RuntimeError, ValueError) as e:
        return {"result": str(e)}


def t_record_verification(a):
    """Called by the verifier subagent after checking; clears the verification gate."""
    global verify_due, last_verified
    verify_due, last_verified = 0, steps
    log({"step": steps, "verification": a.get("verdict", "")[:500]})
    return {"recorded": True}


def t_read_memory(a):
    return {"addr": hex(a["addr"]), "hex": p.range(a["addr"], min(a["length"], 0x1000)).hex(" ")}


def t_wiki_search(a):
    return wiki.search(a["query"], a.get("n", 5))


# Last resort (user, 2026-10-09): the walkthrough may be read only when really stuck and escalation failed, and
# nothing from it may go into memory/ (watcher.guard deletes copied lines). The gate below is what "really stuck" means.
STUCK_ACTIONS, STUCK_WATCHDOGS = 150, 2


def stuck_evidence():
    """(unmet conditions, facts) for the walkthrough gate: no progress (new map, badge, or a new operator hint) for STUCK_ACTIONS actions,
    STUCK_WATCHDOGS watchdog notes since, and both the strategist and the expert consulted since (transcripts)."""
    ws = os.path.dirname(LOG)
    progress_step, progress_t = 0, 0.0
    if os.path.exists(tracker.path):
        for line in open(tracker.path, encoding="utf-8"):
            e = json.loads(line)
            if e["kind"] in ("map", "badge"):
                progress_step, progress_t = e.get("step") or 0, e.get("t") or 0.0
    hint = os.path.join(ws, "operator.md")  # a new operator hint is a fresh start: try it before the walkthrough
    if os.path.exists(hint) and os.path.getmtime(hint) > progress_t:
        progress_t = os.path.getmtime(hint)
        with open(LOG, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'\{"t": ([0-9.]+), "step": (\d+)', line)
                if m and float(m.group(1)) >= progress_t:
                    progress_step = int(m.group(2))
                    break
            else:
                progress_step = steps
    dogs = 0
    with open(LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "WATCHDOG" in line:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if (e.get("step") or 0) > progress_step and any(n.startswith("WATCHDOG") for n in e.get("harness") or []):
                    dogs += 1
    asked = set()
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(progress_t))
    for f in glob.glob(os.path.join(ws, "transcripts", "*.jsonl")):
        if os.path.getmtime(f) < progress_t:
            continue
        for line in open(f, encoding="utf-8", errors="replace"):
            if '"name":"Agent"' not in line or '"subagent_type"' not in line:
                continue
            m = re.search(r'"timestamp":"([^"]+)"', line)
            if m and m.group(1) >= since:
                asked |= {k for k in ("strategist", "expert") if f'"subagent_type":"{k}"' in line}
    facts = {"actions_since_progress": steps - progress_step, "watchdogs_since_progress": dogs,
             "consulted_since_progress": sorted(asked)}
    unmet = ([f"{STUCK_ACTIONS} actions without progress (a new map or a badge): {steps - progress_step} so far"]
             if steps - progress_step < STUCK_ACTIONS else []) + \
            ([f"{STUCK_WATCHDOGS} WATCHDOG notes since your last progress: {dogs} so far"] if dogs < STUCK_WATCHDOGS else []) + \
            [f"ask the {k} subagent (with your notes) first" for k in ("strategist", "expert") if k not in asked]
    return unmet, facts


def t_wiki_walkthrough(a):
    reason = (a.get("reason") or "").strip()
    unmet, facts = stuck_evidence()
    if len(reason) < 40:
        unmet.append("say in 'reason' what you tried, and what the strategist and the expert said")
    if unmet:
        return {"refused": "the walkthrough is a last resort, for when you are really stuck and escalation failed. "
                           "Not yet: " + "; ".join(unmet) + ".", **facts}
    # Served from the per-section index (#160): with no query, the sections about where you are (puzzle and
    # step-by-step headings first); a query narrows or redirects it. Whole sections, never keyword fragments (#159).
    place = state_mod.get_state(p)["map"]["name"]
    query = (a.get("query") or "").strip()
    secs = wiki.sections_for(None if query else place, query)
    if not secs:
        return {"result": f"nothing in the walkthrough about {place!r}" + (f" or {query!r}" if query else "")
                          + "; try a query (a place, person or puzzle name)", **facts}
    text = "\n\n".join(secs)
    watcher.forbid(os.path.dirname(LOG), text)  # memory/ may not keep anything from it
    log({"step": steps, "walkthrough": query or f"(here: {place})", "reason": reason[:300],
         "sections": [t.split("\n", 1)[0] for t in secs], **facts})
    return {"sections": secs,
            "rule": "Use this to get unstuck now. Do NOT write anything from it into memory/ (the harness deletes such "
                    "lines). Record only what you then verify yourself in play, in your own words."}


def t_wiki_read(a):
    page = a.get("page") or a.get("url") or a.get("slug")  # the agent reaches for "url" (search returns urls)
    if not page:
        raise ValueError("pass the page's url (from wiki_search) as 'page'")
    text = wiki.read(page)["text"]
    return {"page": page, "text": text[:12000] + (" [truncated]" if len(text) > 12000 else "")}


S = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
TOOLS = {
    "get_state": (t_get_state, "Current game state: mode (overworld/battle/dialog/other), map, position, "
                  "facing, badges, money, party (in your team order; only while the in-battle party screen "
                  "is open, in that screen's order, which puts the Pokemon in battle first), battle "
                  "details, current dialog box, and map_view: the 15x10 "
                  "viewport grid (@ you, N NPC/object, T trainer, . walkable, # blocked, G tall grass, "
                  "~ water, W waterfall, I ice (slides you), F forced movement, D warp/door, S sign or other "
                  "interactable (doors, locks, objects: read it to find out), : walkable but another "
                  "level, ^v<> ledge) plus NPC, warp, sign and connection lists. Coordinates are map tiles.",
                  S({}), False),
    "get_screenshot": (t_get_screenshot, "Screenshot of the game screen (240x160).", S({}), False),
    "press_buttons": (t_press_buttons, "Press buttons in order. Each press reports whether you moved and what "
                      "changed. A direction you aren't facing turns you first; press it again to step. "
                      "\"WAIT\" presses nothing for half a second (let a cutscene or animation play out).",
                      S({"buttons": {"type": "array", "items": {"type": "string", "enum": KEYS + ["WAIT"]}},
                         "hold_frames": {"type": "integer"}, "wait_frames": {"type": "integer"}}, ["buttons"]), True),
    "advance_dialog": (t_advance_dialog, "Press A through dialog and return every text box seen. Stops at a "
                       "question so you can choose the answer, or when A stops advancing (a menu).",
                       S({"max_presses": {"type": "integer"}, "stop_on_question": {"type": "boolean"}}), True),
    "walk_to": (t_walk_to, "Walk to tile (x, y) on the current map by the shortest safe path. If (x, y) is "
                "an NPC or sign, walks up to it (following a wandering NPC), faces it and presses A to talk or "
                "read; a wall: walks next to it. Stops at battles, "
                "dialog, or when blocked.",
                S({"x": {"type": "integer"}, "y": {"type": "integer"}, "max_steps": {"type": "integer"}},
                  ["x", "y"]), True),
    "give_item": (t_give_item, "Give a party member an item from the bag (Items pocket) to hold, in one call (overworld). "
                  "If it already holds something it refuses, unless replace=true (the old item goes back to the bag). "
                  "Held items matter: type boosters (Mystic Water, Miracle Seed...), Eviolite, Leftovers, Choice items, "
                  "the Macho Brace (doubles EVs gained). Verifies the result.",
                  S({"item": {"type": "string"}, "pokemon": {"type": "string", "description": "nickname"},
                     "replace": {"type": "boolean"}}, ["item", "pokemon"]), True),
    "take_item": (t_take_item, "Take a party member's held item back into the bag (overworld). Verifies the result.",
                  S({"pokemon": {"type": "string", "description": "nickname"}}, ["pokemon"]), True),
    "reorder_party": (t_reorder_party, "Move a party member to a position (1 = the lead, who starts every battle) by "
                      "swapping it with whoever is there (overworld). Verifies the new order.",
                      S({"pokemon": {"type": "string", "description": "nickname"}, "position": {"type": "integer"}},
                        ["pokemon", "position"]), True),
    "fly": (t_fly, "Fly to a town or city you have visited, in one call, from outdoors (a town, city or route). Needs "
            "HM02 in the TM Case and a party Pokemon that COULD learn Fly (it doesn't have to know it). Refuses a place "
            "you haven't visited yet. Use it for any long trip back: a Center, a Mart, an earlier town, a gym.",
            S({"destination": {"type": "string", "description": "e.g. 'Dresco Town'"}}, ["destination"]), True),
    "use_on": (t_use_on, "Overworld: use a vitamin (HP Up, Protein, Iron, Carbos, Calcium, Zinc: +EVs in one stat), an "
               "evolution stone, or a Rare Candy on a party member, in one call. Refuses when it would do nothing (EVs "
               "full) and verifies the effect. An evolution or a 'learn a new move?' question is left to you. "
               "(Healing items: use_item.)",
               S({"item": {"type": "string"}, "pokemon": {"type": "string", "description": "nickname"}}, ["item", "pokemon"]), True),
    "buy": (t_buy, "In a Poke Mart: buy QUANTITY (1-99) of ITEM in one call. Walks to the clerk, checks the item is "
            "stocked (lists what is if not) and that you can afford it, confirms, and reports the new count and money.",
            S({"item": {"type": "string"}, "quantity": {"type": "integer"}}, ["item"]), True),
    "pc_swap": (t_pc_swap, "At a Pokemon Center: put party member POKEMON into the PC and take the Pokemon in BOX/SLOT "
                "(as pc_boxes lists them) into the party, in one call. Walks to the Center's PC itself. Verifies the "
                "result. Use it to rebuild the team for the next gym or after a loss.",
                S({"pokemon": {"type": "string", "description": "party nickname to store"}, "box": {"type": "integer"},
                   "slot": {"type": "integer"}}, ["pokemon", "box", "slot"]), True),
    "pc_deposit": (t_pc_deposit, "At a Pokemon Center: store a party member in the PC (box: optional, default the first "
                   "box with room). Walks to the PC itself; verifies the result.",
                   S({"pokemon": {"type": "string"}, "box": {"type": "integer"}}, ["pokemon"]), True),
    "pc_withdraw": (t_pc_withdraw, "At a Pokemon Center: take the Pokemon in BOX/SLOT (as pc_boxes lists them) into the "
                    "party (needs a free party slot). Walks to the PC itself; verifies the result.",
                    S({"box": {"type": "integer"}, "slot": {"type": "integer"}}, ["box", "slot"]), True),
    "team_details": (t_team_details, "Your party's training detail: nature (which stat it raises/lowers), real stats, "
                     "base stats, EVs per stat with the total used of 510, and IVs. Use it to plan EV training (in battle, "
                     "get_state shows each foe's ev_yield), choose leads and held items, and compare team members.",
                     S({}), False),
    "pc_boxes": (t_pc_boxes, "List the Pokemon in your PC boxes (no need to be at a PC): name, species, level, types, "
                 "nature, moves, held item, IVs and EVs. Use it to plan team changes: which boxed Pokemon counters the "
                 "next gym or a team that beat you.", S({}), False),
    "map_levels": (t_map_levels, "Explain this map's levels: it splits the map into regions you can walk around in (bridges, "
                   "walkways and lower paths such as lily pads are separate regions even where they overlap on screen), "
                   "with each region's level, extent, warps, objects at its edge (a Lapras or a person may carry you across) "
                   "and the one-way links between them. Give x, y to be told which region a tile is in and how that region is "
                   "entered. Use it whenever walk_to says 'no path' or you can't see how to get somewhere on the same map.",
                   S({"x": {"type": "integer"}, "y": {"type": "integer"}}), False),
    "sneak_to": (t_sneak_to, "Walk to tile (x, y) on this map without being seen by watchers (trainers and guards, "
                 "including ones patrolling back and forth). Plans around fixed sight lines; learns each patroller's "
                 "turning points and step timing by watching, then crosses watched ground from one safe tile to the "
                 "next only in a window where every tile of the crossing stays unseen (waiting the exact frames for "
                 "it), and never stops on a watched tile. Watchers off screen count as watching their whole patrol "
                 "until they appear. Stops if a script or battle starts (caught), or when the way stays watched, and "
                 "says which watcher. Use it where patrolling watchers send you back when they spot you; walk_to "
                 "elsewhere.",
                 S({"x": {"type": "integer"}, "y": {"type": "integer"}, "max_steps": {"type": "integer"},
                    "max_wait_frames": {"type": "integer"}}, ["x", "y"]), True),
    "watch_area": (t_watch_area, "Stand still and observe for FRAMES frames (default 480, ~8 s of game time; "
                   "use at least one full cycle of the slowest mover), then report how every nearby object really "
                   "moves: tiles walked, facings, where it turned, how often its pattern repeats, and for watchers "
                   "(trainers/guards with a sight range) which tiles they looked at; plus the reachable tiles no "
                   "watcher saw (hiding spots). Use it before any area where being seen, timing or moving objects "
                   "matter, and again after failing there, from a safe tile. Stops if you get spotted while watching.",
                   S({"frames": {"type": "integer"}, "radius": {"type": "integer"}}, []), True),
    "travel_to": (t_travel_to, "Travel to the named map (e.g. 'Route 2') across maps via doors and edges. "
                  "Stops when a wild battle starts (battle it). If the way is blocked (a "
                  "story gate, an object, a one-way ledge) it stops and says where, so you can decide.",
                  S({"map": {"type": "string"},
                     "max_steps": {"type": "integer"}}, ["map"]), True),
    "wiki_search": (t_wiki_search, "Search the local unboundwiki copy. It covers only Pokémon (where to find "
                    "them, types, abilities, evolutions, moves), items and locations (towns, routes, their items, "
                    "trainers, wild Pokémon). No walkthrough or missions: work those out yourself.",
                    S({"query": {"type": "string"}, "n": {"type": "integer"}}, ["query"]), False),
    "wiki_walkthrough": (t_wiki_walkthrough, "LAST RESORT, only when really stuck: escalation to the strategist and "
                         "the expert failed, the watchdog keeps firing and you have made no progress for a long time. Searches "
                         "the game's walkthrough (indexed by section) and returns the sections about where you are (or your query). The harness refuses until that is "
                         "true and says what is missing. Nothing from it may be written to memory/: the harness deletes "
                         "such lines.",
                         S({"query": {"type": "string", "description": "optional: a place, person or puzzle, e.g. 'Fallshore gym "
                                      "Lapras'. Leave it out to get the sections about where you are now."},
                            "reason": {"type": "string", "description": "what you tried, and what the strategist and the expert said"}},
                           ["reason"]), False),
    "wiki_read": (t_wiki_read, "Read a wiki page found with wiki_search (pass its url).",
                  S({"page": {"type": "string", "description": "the url from wiki_search"}}, ["page"]), False),
    "fight": (t_fight, "In battle: use a move by name (e.g. 'Water Gun'). Opens Fight, picks the move, "
              "confirms (default target in double battles), and waits for your next turn. Stops and says so "
              "when text or a prompt (level-up, learning a move) needs you.",
              S({"move": {"type": "string"}}, ["move"]), True),
    "switch_to": (t_switch_to, "In battle: send in a party member by name, from the forced 'Choose a Pokemon' "
                  "screen (B can't cancel that one) or from your battle menu.",
                  S({"pokemon": {"type": "string"}}, ["pokemon"]), True),
    "throw_ball": (t_throw_ball, "In a wild battle: throw a ball by name (e.g. 'Poké Ball') from the bag and "
                   "follow it to 'caught' (stops at the nickname question) or 'broke free' (your next turn).",
                   S({"ball": {"type": "string"}}, ["ball"]), True),
    "use_item": (t_use_item, "Use a healing item (Potion, Revive, Antidote, Full Restore...) from the bag on a "
                 "party member by name, in the overworld or at your battle menu (uses up your turn). Reports HP "
                 "before and after; refuses if the item would do nothing.",
                 S({"item": {"type": "string"}, "pokemon": {"type": "string"}}, ["item", "pokemon"]), True),
    "type_name": (t_type_name, "On a naming screen (nickname, rival): clear the box, type the name (letters "
                  "and spaces) and confirm. Answer the 'Is this name OK?' question that follows yourself.",
                  S({"name": {"type": "string"}}, ["name"]), True),
    "run_away": (t_run_away, "In a wild battle: choose Run. Only if you may lose the fight; give the reason.",
                 S({"reason": {"type": "string"}}, ["reason"]), True),
    "record_verification": (t_record_verification, "For the verifier subagent only: record your verdict after "
                            "checking the playing agent. Clears the verification gate.",
                            S({"verdict": {"type": "string"}}, ["verdict"]), False),
    "read_memory": (t_read_memory, "Read up to 4096 bytes of GBA memory (hex). For discovering RAM by "
                    "diffing: read, act, read again. Use docs/addresses.md knowledge sparingly.",
                    S({"addr": {"type": "integer"}, "length": {"type": "integer"}}, ["addr", "length"]), False),
}


def call(name, args):
    global steps, p
    fn, _, _, is_action = TOOLS[name]
    if is_action and verify_due and steps - verify_due >= VERIFY_GRACE:
        # The default tier ignored VERIFY notes (gym-1 run, Haiku 5.5): a note it can skip is only a
        # suggestion, so game actions wait until the verifier subagent records a check.
        msg = (f"BLOCKED: verification pending since action {verify_due}. Consult the verifier subagent (Agent "
               "tool, subagent_type 'verifier') with what you did, believe and plan; it records the check. Read-only "
               "tools still work.")
        log({"step": steps, "tool": name, "args": args, "blocked": True})
        return [{"type": "text", "text": msg}]
    mode_before = None
    try:
        mode_before = raw(p)["mode"] if is_action else None
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
        if s["mode"] == "dialog" and mode_before != "dialog":
            try:
                note_talk(s)
            except Exception as e:
                log({"step": steps, "error": f"note_talk: {e!r}"})
        try:
            for e in tracker.update(s, steps):
                msgs.append("MILESTONE: " + json.dumps(e, ensure_ascii=False))
        except Exception as e:  # never let bookkeeping break a tool
            log({"step": steps, "error": f"milestones: {e!r}"})
        content.append({"type": "text", "text": json.dumps({"now": summary(s), "harness": msgs},
                                                          ensure_ascii=False)})
        brief = result.get("result", result) if isinstance(result, dict) else result
        log({"step": steps, "tool": name, "args": args, "result": json.dumps(brief, ensure_ascii=False)[:300],
             "now": summary(s), "harness": msgs})
        try:
            watcher.tick(steps, s, LOG)  # every ~10/20 actions: background watcher/verifier; memory guard every action
        except Exception as e:
            log({"step": steps, "error": f"watcher tick: {e!r}"})
    else:
        log({"step": steps, "tool": name, "args": args})
    return content


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        result = {"protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {"listChanged": True}}, "serverInfo": {"name": "unbound", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": sch} for n, (_, d, sch, _) in TOOLS.items()]}
    elif method == "tools/call":
        try:
            result = {"content": call(msg["params"]["name"], msg["params"].get("arguments") or {})}
        except Exception as e:
            log({"step": steps, "tool": msg["params"]["name"], "error": repr(e)})
            result = {"content": [{"type": "text", "text": f"error: {e!r}\n{traceback.format_exc()[-800:]}"}],
                      "isError": True}
        try:
            persist()
        except OSError as e:
            log({"step": steps, "error": f"persist: {e!r}"})
    elif method == "ping":
        result = {}
    elif mid is None:
        return None  # notification
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


restore()


def bridge_modules():
    """Loaded modules that live in bridge/ (the running __main__ copy excluded: it only holds the loop)."""
    return {n: m for n, m in sys.modules.items() if n != "__main__" and getattr(m, "__file__", None)
            and os.path.dirname(os.path.abspath(m.__file__)) == HERE}


def reload_bridge(mod, changed):
    """Re-import every bridge module from scratch (so `from state import ...` bindings refresh too).
    Returns (the module to serve with, harness note). On any import error the old modules stay."""
    names = ", ".join("bridge/" + os.path.basename(f) for f in changed)
    old = bridge_modules()
    for n in old:
        del sys.modules[n]
    try:
        new = importlib.import_module("mcp_server")
    except BaseException as e:  # SyntaxError, a NameError at import, even SystemExit: keep serving
        for n in bridge_modules():
            del sys.modules[n]
        sys.modules.update(old)
        return mod, f"HARNESS UPDATE FAILED: {names}: {type(e).__name__}: {e}. Still running the previous code."
    new.p = mod.p  # keep the emulator connection
    return new, f"HARNESS UPDATED: {names} reloaded"


def serve():
    """The stdio loop: the one part that never reloads (it holds the pipes). Everything else is looked up
    on the newest mcp_server module, re-imported whenever a bridge/*.py file changes."""
    import mcp_server as mod  # this file as a module, apart from __main__, so it can be replaced
    mod.p = Probe()
    mtimes = {f: os.path.getmtime(f) for f in glob.glob(os.path.join(HERE, "*.py"))}
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        notes = []
        if msg.get("method") == "tools/call":
            now = {f: os.path.getmtime(f) for f in glob.glob(os.path.join(HERE, "*.py"))}
            changed = sorted(f for f in now if mtimes.get(f) != now[f])
            mtimes = now  # a failed reload is reported once, and retried on the next change
            if changed:
                tools = set(mod.TOOLS)
                mod, note = reload_bridge(mod, changed)
                notes.append(note)
                mod.log({"step": mod.steps, "harness_reload": note})
                if set(mod.TOOLS) != tools:  # Claude Code re-fetches tools/list on this
                    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}) + "\n")
            try:
                notes += mod.sync_instructions()
            except Exception as e:
                notes.append(f"INSTRUCTIONS SYNC FAILED: {e!r}")
        reply = mod.handle(msg)
        if reply is not None:
            if notes:
                reply.setdefault("result", {}).setdefault("content", []).append({"type": "text", "text": "\n".join(notes)})
            sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
