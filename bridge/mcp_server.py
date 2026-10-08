"""MCP server (stdio) exposing the bridge to Claude Code. Stdlib only.

    claude --mcp-config '{"mcpServers":{"unbound":{"command":"python","args":["<repo>/bridge/mcp_server.py"]}}}'

Every action is logged to run/log.jsonl. Tool results carry the harness's notes to the agent:
watchdog warnings (no progress), self-learning checks (every LEARN_EVERY actions) and
escalation hints for the model router (#37).
"""
import base64
import collections
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import time
import traceback

import bot
import battle
import milestones
import moves
import naming
import wiki
import world as W
from probe import Probe
from state import G_MAIN, get_state, press, raw

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.normpath(os.path.join(HERE, "..", "run"))
STATES = os.path.join(RUN, "states")
LOG = os.environ.get("UNBOUND_LOG") or os.path.join(RUN, "log.jsonl")
VERIFY_EVERY = 20  # actions between Sonnet verification checks
VERIFY_GRACE = 3  # actions allowed after a VERIFY note before game actions are blocked
verify_due = 0  # action number when verification became due (0: none pending)
last_prompt = None  # irreversible prompt already flagged
last_verified = -99  # action number of the last recorded verification
IRREVERSIBLE = ("forget", "forgot", "delete", "make room", "release", "toss", "throw away", "discard", "give up", "stop learning")  # not "overwrite": the in-game save prompt; savestates cover it
LEARN_EVERY = 40  # actions between self-learning checks (asked for every 25-50 steps)
STALL_AFTER = 15  # actions with no change in map/position/mode/dialog
TRAINER = 0x8  # gBattleTypeFlags bit
WILD_RANDOM = 0x4  # gBattleTypeFlags of an ordinary random wild battle (verified on Snorunt, Vanillite)
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
battle_seen = False


def fingerprint(s):
    return (s["map"]["group"], s["map"]["num"], tuple(s["pos"]), s["mode"], s.get("dialog"),
            json.dumps(s.get("battle", {}).get("battlers")), (s.get("battle") or {}).get("text"))


def summary(s):
    return {"mode": s["mode"], "map": s["map"]["name"], "pos": s["pos"], "badges": s["badges"],
            "party": [f"{m['name']} {m['hp']}" for m in s["party"]]}


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
                   "screenshot, re-read your objectives, try something different, or load_state the last "
                   "good save." + (" ESCALATE to the expert subagent: the watchdog has fired repeatedly."
                                   if watchdog_fired >= 2 else ""))
    spot = (s["map"]["group"], s["map"]["num"], tuple(s["pos"]))
    if s["mode"] == "overworld" and (not arrivals or arrivals[-1] != spot):
        arrivals.append(spot)
        if arrivals.count(spot) >= 4:  # moving, so the no-change watchdog can't see it
            watchdog_fired += 1
            arrivals.clear()
            out.append(f"WATCHDOG: you keep coming back to {s['map']['name']} {s['pos']} (4 times in the last 20 "
                       "moves): you're going in circles. Stop. Re-read memory/map_notes.md and objectives.md for "
                       "this place, take a screenshot, and pick a genuinely different route or goal."
                       + (" ESCALATE to the expert subagent: the watchdog has fired repeatedly."
                          if watchdog_fired >= 2 else ""))
    global verify_due
    if steps and steps % VERIFY_EVERY == 0 and steps % LEARN_EVERY:
        verify_due = verify_due or steps
        out.append(f"VERIFY (action {steps}): ask the verifier subagent to check the last stretch against the game "
                   "state: what you did, what you believe, what you plan next. Follow its corrections.")
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
    if raw(p)["cb2"] == hex(battle.CB2_BATTLE_PARTY) and s["mode"] != "battle":
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
        if not flags & TRAINER and flags != WILD_RANDOM:
            # Random grass/cave encounters read exactly 0x4; scripted ones (e.g. Binacle on Route 2,
            # 0x20004) carry extra bits. The user's rule: always catch these.
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
    for key in a["buttons"]:
        key = key.upper()
        if key == "WAIT":  # the agent asked for this: let a cutscene or animation play out
            p.step(30)
            out.append({"key": "WAIT", "frames": 30})
            continue
        if key not in KEYS:
            raise ValueError(f"unknown button {key}; use {KEYS + ['WAIT']}")
        t = press(p, key, a.get("hold_frames", 4), a.get("wait_frames", 16))
        out.append({"key": key, "moved": t["moved"], "changed": t["changed"]})
    return out


def t_advance_dialog(a):
    """A through dialog, collecting every box; stops before answering a question or when stuck."""
    seen, waited = [], 0
    if raw(p)["mode"] == "battle":  # battle messages: A through them until a menu, a question or the end
        b, _ = battle.wait_for_menu(p, seen=seen)
        mode = raw(p)["mode"]
        if b is None and mode == "battle" and not seen:  # a Yes/No question: its text is already finished
            seen.append((get_state(p).get("battle") or {}).get("text"))
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
        for i in range(a.get("max_steps", 200)):
            s = get_state(p)
            if s["mode"] != "overworld":
                raise SystemExit(f"stopped: mode is {s['mode']}")
            w = W.read_world(p)
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
                raise SystemExit(f"no path from {w['player']} to {t}" + (" or any tile next to it" if interact or wall else "")
                                 + " (it may be behind a one-way ledge, on another level, or blocked)")
            if bot.stride(p, path, s.get("facing")) == 0 and raw(p)["mode"] == "overworld":
                raise SystemExit(f"blocked going {path[0]} from {w['player']}")
        raise SystemExit("max_steps reached")
    return run_bot(walk)


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


def t_save_state(a):
    os.makedirs(STATES, exist_ok=True)
    name = a.get("name") or time.strftime("save-%Y%m%d-%H%M%S")  # the default tier forgets the name
    p.save(os.path.join(STATES, name + ".ss1"))
    return {"saved": name}


def t_load_state(a):
    """Rolls the game back: irreversible. Named only, and only right after the verifier approved it
    (an unnamed default once rolled the run back two hours)."""
    global verify_due
    names = sorted(f[:-4] for f in os.listdir(STATES) if f.endswith(".ss1")) if os.path.isdir(STATES) else []
    name = a.get("name")
    if name not in names:
        raise ValueError(f"name one of your savestates: {names}")
    if steps - last_verified > 3:
        verify_due = verify_due or steps
        return {"result": "NOT LOADED: loading a savestate throws away everything since it was saved. Ask the "
                          "verifier subagent to approve this rollback, then call load_state again."}
    p.load(os.path.join(STATES, name + ".ss1"))
    p.step(2)
    return {"loaded": name}


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


def t_run_away(a):
    if len(a.get("reason", "").strip()) < 10:
        return {"result": "NOT RUN: wild Pokemon are battled and caught. Run only if you may lose the fight: "
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


def t_wiki_read(a):
    page = a.get("page") or a.get("url") or a.get("slug")  # the agent reaches for "url" (search returns urls)
    if not page:
        raise ValueError("pass the page's url (from wiki_search) as 'page'")
    text = wiki.read(page)["text"]
    return {"page": page, "text": text[:12000] + (" [truncated]" if len(text) > 12000 else "")}


S = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
TOOLS = {
    "get_state": (t_get_state, "Current game state: mode (overworld/battle/dialog/other), map, position, "
                  "facing, badges, money, party, battle details, current dialog box, and map_view: the 15x10 "
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
    "travel_to": (t_travel_to, "Travel to the named map (e.g. 'Route 2') across maps via doors and edges. "
                  "Stops when a wild battle starts (battle it). If the way is blocked (a "
                  "story gate, an object, a one-way ledge) it stops and says where, so you can decide.",
                  S({"map": {"type": "string"},
                     "max_steps": {"type": "integer"}}, ["map"]), True),
    "save_state": (t_save_state, "Save an emulator savestate under a name (for rollback).",
                   S({"name": {"type": "string"}}), False),
    "load_state": (t_load_state, "Roll back to a named savestate. Irreversible: needs the verifier's approval first.",
                   S({"name": {"type": "string"}}), True),
    "wiki_search": (t_wiki_search, "Search the local unboundwiki copy. It covers only Pokémon (where to find "
                    "them, types, abilities, evolutions, moves), items and locations (towns, routes, their items, "
                    "trainers, wild Pokémon). No walkthrough or missions: work those out yourself.",
                    S({"query": {"type": "string"}, "n": {"type": "integer"}}, ["query"]), False),
    "wiki_read": (t_wiki_read, "Read a wiki page found with wiki_search (pass its url).",
                  S({"page": {"type": "string", "description": "the url from wiki_search"}}, ["page"]), False),
    "fight": (t_fight, "In battle: use a move by name (e.g. 'Water Gun'). Opens Fight, picks the move, "
              "confirms (default target in double battles), and waits for your next turn. Stops and says so "
              "when text or a prompt (level-up, learning a move) needs you.",
              S({"move": {"type": "string"}}, ["move"]), True),
    "switch_to": (t_switch_to, "In battle: send in a party member by name, from the forced 'Choose a Pokemon' "
                  "screen (B can't cancel that one) or from your battle menu.",
                  S({"pokemon": {"type": "string"}}, ["pokemon"]), True),
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
