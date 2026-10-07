"""Phase 1 exit test (#9): walk to a named map using only bridge output, no model.

    python bot.py "Bellin Town" "Route 2"     # visit each map in order

Plans over the live grid each step (elevation-aware Dijkstra, ledges one-way, grass costly,
ice/water/NPCs avoided; grass too while the lead is under 1/3 HP), leaves through a connection or
warp to the target, flees wild battles. Logs every step; stops with a screenshot on a stall or an
unknown screen instead of guessing (docs/learnings.md rules 2 and 3).
"""
import collections
import heapq
import json
import os
import sys

from probe import Probe
from state import CB2_OVERWORLD, get_state, press, raw
import world as W

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
EDGE = {"north": "UP", "south": "DOWN", "west": "LEFT", "east": "RIGHT"}
LEDGE_DIR = {0x38: "RIGHT", 0x39: "LEFT", 0x3A: "UP", 0x3B: "DOWN"}
AVOID = W.WATER | W.ICE | W.FORCED | {0x13}
MAX_STEPS = 600


def plan(w, goals, blocked, grass_cost=8):
    """Cheapest key sequence from the player to any goal tile. State is (x, y, elevation)."""
    # NPCs wander: only one next to the player is a wall; the rest just cost extra.
    px, py = w["player"]
    npcs = {(n["x"], n["y"]) for n in w["npcs"]}
    occupied = {t for t in npcs if abs(t[0] - px) + abs(t[1] - py) <= 1} | blocked
    start = (*w["player"], w["elevation"])
    dist, prev = {start: 0}, {}
    queue = [(0, start)]
    while queue:
        d, (x, y, e) = heapq.heappop(queue)
        if (x, y) in goals:
            path, s = [], (x, y, e)
            while s != start:
                s, key = prev[s]
                path.append(key)
            return path[::-1]
        if d > dist[(x, y, e)]:
            continue
        for key, (dx, dy) in DIRS.items():
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w["width"] and 0 <= ny < w["height"]) or (nx, ny) in occupied:
                continue
            beh, col, elev = w["tile"](nx, ny)
            if beh in LEDGE_DIR:
                if LEDGE_DIR[beh] != key:
                    continue
                nx, ny = nx + dx, ny + dy  # a ledge jump lands two tiles on
                if not (0 <= nx < w["width"] and 0 <= ny < w["height"]) or (nx, ny) in occupied:
                    continue
                beh, col, elev = w["tile"](nx, ny)
            if col or beh in AVOID or (e and elev not in (0, 15, e)):
                continue
            ne = e if elev == 15 else elev
            cost = d + (grass_cost if beh == 0x02 else 1) + (30 if (nx, ny) in npcs else 0)
            if cost < dist.get((nx, ny, ne), 1 << 30):
                dist[(nx, ny, ne)], prev[(nx, ny, ne)] = cost, ((x, y, e), key)
                heapq.heappush(queue, (cost, (nx, ny, ne)))
    return None


def exit_to(w, target):
    """Goal tiles and the final key that leaves the map toward TARGET, a [group, num] map ID."""
    for c in w["connections"]:
        if c["to_map"] == list(target):
            key = EDGE[c["direction"]]
            dx, dy = DIRS[key]
            edge = [(x, w["height"] - 1 if dy > 0 else 0) for x in range(w["width"])] if dy else \
                   [(w["width"] - 1 if dx > 0 else 0, y) for y in range(w["height"])]
            return set(edge), key
    warps = {(wp["x"], wp["y"]) for wp in w["warps"] if wp["to_map"] == list(target)}
    if warps:
        return warps, None
    raise SystemExit(f"no connection or warp to {target!r} from here")


CONTROLLER = 0x03004FE0  # gBattlerControllerFuncs[0]
ACTION_MENU, MOVE_MENU = 0x0802E439, 0x0802EA11
ACTION_CURSOR = 0x02023FF8  # 0 Fight, 1 Cube, 2 Pokemon, 3 Run
CB2_BATTLE_PARTY = "0x811eba1"  # "Choose a Pokemon" inside battle
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "saves")


def stop(p, why):
    """Learnings rule 2/3: don't guess, stop with evidence."""
    path = os.path.join(SHOTS, "bot-stop.png")
    p.shot(path)
    raise SystemExit(f"{why} (screenshot: {os.path.abspath(path)}; state: {json.dumps(get_state(p))})")


def battle(p):
    """Leave a wild battle: Run at the action menu (retrying, since escape odds depend on speed),
    back out of the move menu, send in the next healthy party member if the lead faints."""
    for _ in range(200):
        r = raw(p)
        if r["mode"] != "battle" and r["cb2"] != CB2_BATTLE_PARTY:
            return
        if r["cb2"] == CB2_BATTLE_PARTY:
            party = get_state(p)["party"]
            alive = [i for i, m in enumerate(party) if not m["hp"].startswith("0/")]
            if not alive:
                stop(p, "whole party fainted")
            # ponytail: assumes the cursor starts on slot 0 and slots 1+ run down the right column
            for _ in range(alive[0]):
                p.press("DOWN" if alive[0] > 1 else "RIGHT", 4); p.step(8)
            for key in ("A", "A"):  # choose, then "Send Out"
                p.press(key, 4); p.step(20)
            continue
        fn = p.read32(CONTROLLER)
        if fn == ACTION_MENU:
            cur = p.read8(ACTION_CURSOR)
            if cur in (0, 1): p.press("DOWN", 4); p.step(6)
            if p.read8(ACTION_CURSOR) == 2: p.press("RIGHT", 4); p.step(6)
            if p.read8(ACTION_CURSOR) != 3:
                stop(p, "couldn't put the cursor on Run")
            p.press("A", 4); p.step(30)
        elif fn == MOVE_MENU:
            p.press("B", 4); p.step(10)
        else:
            p.press("B", 4); p.step(15)  # advance battle text
    stop(p, "battle didn't end (trainer battle, or a prompt the bot doesn't know)")


def go(p, target):
    blocked, last, still, unknown, path, recent = set(), None, 0, 0, [], collections.deque(maxlen=20)
    hops, last_next, closed = [], None, set()
    for step in range(MAX_STEPS):
        s = get_state(p)
        where = (s["map"]["name"], tuple(s["pos"]), s["mode"], s.get("dialog"))
        still = still + 1 if where == last else 0
        last = where
        if still >= 8:
            stop(p, f"stalled at {where}")
        if where[2] == "overworld" and (not recent or recent[-1] != where[:2]):  # count arrivals only
            recent.append(where[:2])
            if recent.count(where[:2]) >= 4:
                stop(p, f"oscillating: {where[:2]} visited 4 times in the last {len(recent)} steps")
        if s["map"]["name"] == target:
            print(f"reached {target} at {s['pos']} after {step} steps")
            return
        here = (s["map"]["group"], s["map"]["num"])
        if here not in hops:  # first step, or knocked off the route (e.g. whited out)
            hops = [here] + (W.route(p, here, target, closed) or stop(p, f"no open map route to {target}"))
            print(f"{step}: route {' > '.join(W.map_name(p, *h) + str(list(h)) for h in hops)}")
            path, blocked = [], set()
        nxt = hops[hops.index(here) + 1]
        if nxt != last_next:
            path, blocked, last_next = [], set(), nxt
        r = raw(p)
        if r["mode"] == "battle" or r["cb2"] == CB2_BATTLE_PARTY:
            print(f"{step}: battle -> leaving")
            battle(p)  # keep the plan: a battle doesn't change the map, and re-planning with
            continue    # post-battle HP flipped the grass cost and sent the bot back the way it came
        if r["mode"] == "dialog" or (r["mode"] == "other" and r["cb2"] == hex(CB2_OVERWORLD)):
            print(f"{step}: {r['mode']} on the overworld -> B")
            press(p, "B")  # dialog box, start menu or a script lock: B closes or advances it
            continue
        if r["mode"] != "overworld":
            unknown += 1  # e.g. the encounter wipe: look again before doing anything
            if unknown > 8:
                stop(p, f"unknown screen (cb2 {r['cb2']})")
            p.step(15)
            continue
        unknown = 0
        w = W.read_world(p)
        goals, final = exit_to(w, nxt)
        if not path:
            # Commit to a plan until a step fails: re-planning every step let a wandering NPC
            # flip the route back and forth between two tiles.
            alive = [m for m in s["party"] if not m["hp"].startswith("0/")]
            lead = alive[0] if alive else None  # a fainted first slot isn't the lead
            weak = lead and int(lead["hp"].split("/")[0]) * 3 < int(lead["hp"].split("/")[1])
            path = plan(w, goals - blocked, blocked, grass_cost=100 if weak else 8)
            if path is None:
                # Story gates (e.g. an invisible blocker on a cave mouth) close a hop the ROM
                # graph thinks is open: close it and route around.
                print(f"{step}: can't reach {W.map_name(p, *nxt)}{list(nxt)} from {w['player']}; closing it")
                closed.add(nxt)
                hops = []
                continue
            print(f"{step}: plan {len(path)} steps: {''.join(k[0] for k in path)}")
        key = path[0] if path else final
        if key is None:
            stop(p, "standing on the warp but it didn't trigger")
        t = press(p, key)
        print(f"{step}: {s['map']['name']} {w['player']} {key} -> {t['after']['pos']} {t['changed']}")
        if t["moved"] and path:
            path.pop(0)
        if not t["moved"] and t["changed"] != ["facing"] and t["after"]["mode"] == "overworld":
            t = press(p, key)  # a first press can just turn the player
            if not t["moved"] and t["after"]["mode"] == "overworld":
                x, y = w["player"]
                dx, dy = DIRS[key]
                blocked.add((x, y) if not path else (x + dx, y + dy))  # dead edge tile, or an obstacle
                print(f"{step}: blocked {(x, y) if not path else (x + dx, y + dy)}")
                path = []
    stop(p, f"gave up after {MAX_STEPS} steps")


if __name__ == "__main__":
    p = Probe()
    for target in sys.argv[1:]:
        go(p, target)
