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
import struct
import sys

from probe import Probe
from state import CB2_OVERWORLD, SB1_PTR, get_state, press, raw
import world as W

DIRS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}
EDGE = {"north": "UP", "south": "DOWN", "west": "LEFT", "east": "RIGHT"}
LEDGE_DIR = {0x38: "RIGHT", 0x39: "LEFT", 0x3A: "UP", 0x3B: "DOWN"}
# Warp behavior -> keys that trigger it from on top (arrow warps 0x62-0x65, door 0x69).
WARP_KEYS = {0x62: ["RIGHT"], 0x63: ["LEFT"], 0x64: ["UP"], 0x65: ["DOWN"], 0x69: ["UP", "DOWN"]}
TILE_FRAMES = 8  # Unbound walks a tile in 8 frames when the key is held (measured)
SLIDE_ICE = 0x23  # slides you; thin (0x26) and cracked (0x27) ice are puzzles, still avoided
AVOID = W.WATER | (W.ICE - {SLIDE_ICE}) | W.FORCED | {0x13}
# Unbound's sideways stairs move you diagonally. Verified in Frozen Heights: RIGHT on 0xB4 (12,22) lands on
# (13,21), LEFT on 0xB5 (13,21) back on (12,22). Other orientations are unverified.
SIDE_STAIRS = {(0xB4, "RIGHT"): (1, -1), (0xB5, "LEFT"): (-1, 1)}
MAX_STEPS = 600
POCKET = 30  # an arrival area this small (tiles reachable) is a dead end, not the place itself
DEAD_EDGES_FILE = None  # set by the MCP server: map-edge tiles learned to lead into a pocket
DEAD_EDGES = set()


def load_dead_edges(path):
    global DEAD_EDGES_FILE, DEAD_EDGES
    DEAD_EDGES_FILE = path
    DEAD_EDGES = set(json.load(open(path))) if os.path.exists(path) else set()


def _note_dead_edge(key):
    DEAD_EDGES.add(key)
    if DEAD_EDGES_FILE:
        with open(DEAD_EDGES_FILE, "w") as f:
            json.dump(sorted(DEAD_EDGES), f)


def reachable(w):
    """How many tiles the player can walk to from here (a small number means a dead-end pocket)."""
    seen = set()
    plan(w, set(), set(), visit=seen)
    return len(seen)


def plan(w, goals, blocked, grass_cost=8, visit=None, limit=None):
    """Cheapest key sequence from the player to any goal tile. State is (x, y, elevation).
    VISIT, if given, collects every tile the search reached (stopping once it holds LIMIT)."""
    # NPCs wander: only one next to the player is a wall; the rest just cost extra.
    px, py = w["player"]
    npcs = {(n["x"], n["y"]) for n in w["npcs"]}
    occupied = {t for t in npcs if abs(t[0] - px) + abs(t[1] - py) <= 1} | blocked
    # State carries the last direction so a small turn penalty picks straight routes among equal
    # ones: long straight runs are what stride() walks smoothly in one held press.
    start = (*w["player"], w["elevation"], None)
    dist, prev = {start: 0}, {}
    queue = [(0, start)]
    while queue:
        d, (x, y, e, last) = heapq.heappop(queue)
        if (x, y) in goals:
            path, s = [], (x, y, e, last)
            while s != start:
                s, key = prev[s]
                path.append(key)
            return path[::-1]
        if d > dist[(x, y, e, last)]:
            continue
        if visit is not None:
            visit.add((x, y))
            if limit and len(visit) >= limit:
                return None
        here = w["tile"](x, y)[0]
        for key, (dx, dy) in DIRS.items():
            dx, dy = SIDE_STAIRS.get((here, key), (dx, dy))
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w["width"] and 0 <= ny < w["height"]) or (nx, ny) in occupied:
                continue
            beh, col, elev = w["tile"](nx, ny)
            jump = beh in LEDGE_DIR or (beh == W.HOP and key in ("LEFT", "RIGHT"))
            if jump:
                if beh in LEDGE_DIR and LEDGE_DIR[beh] != key:
                    continue
                nx, ny = nx + dx, ny + dy  # a jump lands two tiles on
                if not (0 <= nx < w["width"] and 0 <= ny < w["height"]) or (nx, ny) in occupied:
                    continue
                beh, col, elev = w["tile"](nx, ny)
            # A jump lands on any level and takes the landing tile's (Grim Woods: ledge (16,25) 3 -> 5).
            if col or beh in AVOID or (not jump and e and elev not in (0, 15, e)):
                continue
            ne = e if elev == 15 else elev
            # Ice: you keep sliding until the next tile is blocked or you reach ground that isn't ice.
            while beh == SLIDE_ICE:
                sx, sy = nx + dx, ny + dy
                if not (0 <= sx < w["width"] and 0 <= sy < w["height"]) or (sx, sy) in occupied:
                    break
                sbeh, scol, selev = w["tile"](sx, sy)
                if scol or sbeh in AVOID or sbeh in LEDGE_DIR or (ne and selev not in (0, 15, ne)):
                    break
                nx, ny, beh = sx, sy, sbeh
                ne = ne if selev == 15 else selev
            cost = (d + (grass_cost if beh == 0x02 else 1) + (30 if (nx, ny) in npcs else 0)
                    + (0.1 if last and key != last else 0))
            state = (nx, ny, ne, key)
            if cost < dist.get(state, 1 << 30):
                dist[state], prev[state] = cost, ((x, y, e, last), key)
                heapq.heappush(queue, (cost, state))
    return None


def stride(p, path, facing, max_tiles=8):
    """Walk the straight run at the start of PATH in one held press, instead of a tap and a re-plan
    per tile. Returns tiles moved along the path, or -1 if the player ended up off the plan (a ledge
    jump, an ice slide, forced movement) and should re-plan."""
    key, n = path[0], 1
    while n < min(len(path), max_tiles) and path[n] == key:
        n += 1
    sb1 = p.read32(SB1_PTR)
    start = p.range(sb1, 6)
    # Measured on Unbound: 8 frames a tile (vanilla is 16) and 8 more to turn first. Release
    # 4 frames before the next step would start.
    p.press(key, TILE_FRAMES * n - 4 + (0 if facing == key.lower() else TILE_FRAMES))
    pos = p.range(sb1, 6)
    for _ in range(40):  # let the last step (or a slide or jump) finish
        p.step(6)
        now = p.range(sb1, 6)
        if now == pos:
            break
        pos = now
    x0, y0, g0, m0 = struct.unpack("<hhbb", start)
    x1, y1, g1, m1 = struct.unpack("<hhbb", pos)
    if (g1, m1) != (g0, m0):
        return n  # walked off the map edge or through a warp
    dx, dy = DIRS[key]
    along, across = (x1 - x0) * dx + (y1 - y0) * dy, (x1 - x0) * dy + (y1 - y0) * dx
    return -1 if across or along < 0 or along > n else along


def exit_to(w, target):
    """Goal tiles and the final key that leaves the map toward TARGET, a [group, num] map ID."""
    for c in w["connections"]:
        if c["to_map"] == list(target) and c["direction"] in EDGE:
            # Only the stretch of edge that borders TARGET: Route 4's south edge is Route 5 for x < 32, Route 13 after.
            return {here for here, _ in W.seam(w, c)}, EDGE[c["direction"]]
    warps = {(wp["x"], wp["y"]) for wp in w["warps"] if wp["to_map"] == list(target)}
    # A wide exit mat can list a warp event per tile while only one has a warp behavior: Dresco Town
    # (7,4) has events at (7..9,18) but only (8,18) is a south arrow (0x65); the others are plain floor.
    live = {t for t in warps if w["tile"](*t)[0] in W.WARP}
    warps = live or warps
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


def go(p, target, reroute=True):
    blocked, last, still, unknown, path, recent = set(), None, 0, 0, [], collections.deque(maxlen=20)
    hops, last_next, closed, warp_try, crossed = [], None, set(), 0, None
    for step in range(MAX_STEPS):
        s = get_state(p)
        here = (s["map"]["group"], s["map"]["num"])
        if crossed and here != crossed[0] and s["mode"] == "overworld":
            # Just crossed a map edge: a tiny reachable area means a dead-end pocket ("in the town's
            # map, but not actually in the town"). Learn the edge and don't count it as arriving.
            room = reachable(W.read_world(p))
            if room < POCKET:
                # Confirm after settling: a crossing into a cutscene once measured a false pocket on Route 1
                # (530 tiles reachable a moment later), which would have closed the route for good.
                p.step(30)
                room = reachable(W.read_world(p)) if raw(p)["mode"] == "overworld" else POCKET
            if room < POCKET:
                (g, n), (ex, ey), _ = crossed
                _note_dead_edge(f"{g},{n},{ex},{ey}")
                msg = (f"that edge from {W.map_name(p, g, n)} ({ex}, {ey}) leads into a dead-end pocket of "
                       f"{s['map']['name']} ({room} tiles reachable). Learned: it's avoided from now on.")
                if not reroute:
                    raise SystemExit(f"stopped: {msg} Step back out (the way you came) and travel again.")
                print(f"{step}: {msg}")
                press(p, {"DOWN": "UP", "UP": "DOWN", "LEFT": "RIGHT", "RIGHT": "LEFT"}[crossed[2]])
                crossed = None
                continue
            crossed = None
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
        if here not in hops:  # first step, or knocked off the route (e.g. whited out)
            hops = [here] + (W.route(p, here, target, closed) or stop(p, f"no open map route to {target}"))
            print(f"{step}: route {' > '.join(W.map_name(p, *h) + str(list(h)) for h in hops)}")
            path, blocked = [], set()
        nxt = hops[hops.index(here) + 1]
        if nxt != last_next:
            path, blocked, last_next, warp_try = [], set(), nxt, 0
        r = raw(p)
        if r["mode"] == "battle" or r["cb2"] == CB2_BATTLE_PARTY:
            print(f"{step}: battle -> leaving")
            battle(p)  # keep the plan: a battle doesn't change the map, and re-planning with
            continue    # post-battle HP flipped the grass cost and sent the bot back the way it came
        if r["mode"] == "dialog" or (r["mode"] == "other" and r["cb2"] == hex(CB2_OVERWORLD)):
            if not reroute:  # the agent's tools: a script took over (story gate, NPC, event); its call
                raise SystemExit(f"stopped: a script or dialog started at {s['map']['name']} {s['pos']} "
                                 "(a story event, NPC or sign). Read it (advance_dialog) and decide; walking "
                                 "the same way again will likely trigger it again.")
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
            dead = {(int(k.split(",")[2]), int(k.split(",")[3])) for k in DEAD_EDGES
                    if k.startswith(f"{here[0]},{here[1]},")}
            path = plan(w, goals - blocked - dead, blocked, grass_cost=100 if weak else 8)
            if path is None:
                # Story gates (e.g. an invisible blocker on a cave mouth) close a hop the ROM
                # graph thinks is open: close it and route around.
                print(f"{step}: can't reach {W.map_name(p, *nxt)}{list(nxt)} from {w['player']}; closing it")
                if not reroute:  # let the caller (the model) decide instead of a long silent detour
                    raise SystemExit(f"blocked: can't get from {s['map']['name']} {w['player']} to "
                                     f"{W.map_name(p, *nxt)} {list(nxt)}: something is in the way (a story gate, an "
                                     "object, a one-way ledge). Look at the map, talk to people or explore to open "
                                     "it, or travel somewhere else.")
                closed.add(nxt)
                hops = []
                continue
            print(f"{step}: plan {len(path)} steps: {''.join(k[0] for k in path)}")
        if path:
            moved = stride(p, path, s.get("facing"))
            print(f"{step}: {s['map']['name']} {w['player']} {path[0]}x{min(len(path), 8)} -> moved {moved}")
            if moved > 0:
                del path[:moved]
            elif moved < 0:
                path = []  # off the plan (ledge, ice, forced movement): re-plan from where we are
            elif raw(p)["mode"] == "overworld":
                x, y = w["player"]
                dx, dy = DIRS[path[0]]
                blocked.add((x + dx, y + dy))  # held the key and didn't move: something is there
                print(f"{step}: blocked {(x + dx, y + dy)}")
                path = []
            continue
        key = final
        if key is None:
            # On a warp that didn't fire: warps trigger when you walk *into* them. Arrow warps say which
            # way; building doors go UP; exit mats and the rest usually DOWN.
            beh = w["tile"](*w["player"])[0]
            tries = WARP_KEYS.get(beh, ["DOWN", "UP", "LEFT", "RIGHT"])
            key = tries[warp_try % len(tries)]
            warp_try += 1
            if warp_try > 4:
                stop(p, "standing on the warp but it didn't trigger in any direction")
        if final:
            crossed = (here, tuple(w["player"]), key)
        t = press(p, key)
        if not final and not t["moved"] and t["after"]["mode"] == "other" and t["after"]["locked"]:
            # An arrow warp locks the field and fades out without moving you, and press() returns
            # mid-fade. Wait for the warp to finish instead of reading the lock as a script.
            for _ in range(20):
                p.step(10)
                if raw(p)["mode"] != "other":
                    break
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
