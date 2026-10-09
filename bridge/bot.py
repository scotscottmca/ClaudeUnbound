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
import types

from probe import Probe
from state import CB2_OVERWORLD, G_MAIN, SB1_PTR, get_state, press, raw
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
# Moves the game refused although the planner thought them open, per map: {(group, num): {(x, y, key)}}. Learned by
# walk_to (Crater Town (28,24) LEFT onto 0xB2, likely another sideways-stair variant) and planned around from then
# on. Kept in sys.modules so a hot reload doesn't forget them.
NO_MOVE = sys.modules.setdefault("_unbound_no_move", types.SimpleNamespace(maps={})).maps
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
            if (x, y, key) in w.get("no_move", ()):
                continue
            dx, dy = SIDE_STAIRS.get((here, key), (dx, dy))
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w["width"] and 0 <= ny < w["height"]) or (nx, ny) in occupied:
                continue
            beh, col, elev = w["tile"](nx, ny)
            jump = beh in LEDGE_DIR or beh == W.HOP
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


# --- sneaking past watchers (docs/gym-mechanics.md) ---------------------------------------------------------
# A trainer object (+0x07 != 0) sees SIGHT tiles straight ahead (+0x1D), stopped by a wall, and the game checks it
# every frame the player stands still: Crater Town gym's guard (sight 1) caught the player stepping in front of it
# ("Gotcha!", warped back), but not standing on its row 7-8 tiles ahead of it. Movement types are vanilla's.
FIXED_FACING = {0, 7, 8, 9, 10}  # none, face up/down/left/right (verified: object id 3 there is type 8, faces down)
BACK_AND_FORTH = {0x19, 0x1A, 0x1B, 0x1C}  # walk up/down, left/right (the guard: 0x1B, x 9..18 on row 27)
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
WATCHER_FRAMES = 16  # a patroller walks a tile per 16 frames (measured on the guard); the player takes 8
SNEAK_AHEAD = 2  # watcher steps of margin past a tile's exposure, for watchers not yet modelled exactly
SWEEP = 64  # watcher steps that count as "forever" when finding safe zones: a full cycle of a patrol up to 32 tiles
# Calibration knobs for the crossing timer (frames; each bridge read costs about one):
START = 5  # from the watcher read to the first step starting: the facing and clock reads, stride's two, the press
CORNER = (20, 40)  # a change of direction mid-crossing, turn included: stride settles, the loop re-reads (min, max)
MARGIN = 6  # frames of slack each side of a tile's exposure against an exactly modelled watcher
CLOCK = G_MAIN + 0x24  # gMain.vblankCounter2: the frame count each object read is stamped with
TURNS = {}  # (group, num, id) -> {facing: farthest tile it reached in that facing before turning}, learned
SEEDED = set()  # (group, num, id) whose TURNS were seeded from the template (once: a contradicted seed is re-learnt)
# Objects load about 11 tiles out from the player (Crater gym, user demo). A template whose start is well inside that
# and still isn't loaded is hidden by a flag (Crater gym id 10 at (15,6): never loaded, the player stood at (14,6)).
IN_VIEW = (9, 5)  # x, y: under the 11 and 6 seen loading
HIDDEN = set()  # (group, num, id). ponytail: never forgotten; a flag set later (an object appearing) re-adds it live
# Vanilla WalkBackAndForth: it sets off this way from its start and turns at the end of its movement range and back
# at its start, so it patrols start .. start +- range. Verified on guard 7 (0x1B, (18,27), range 9: x 9..18).
SET_OFF = {0x19: "up", 0x1A: "down", 0x1B: "left", 0x1C: "right"}
TEMPLATE_FACING = {7: "up", 8: "down", 9: "left", 10: "right"}  # vanilla FACE_* movement types
# Vanilla WALK_SEQUENCE_* (0x1D..0x34): four legs, in this order, round its movement range. Verified only for 0x24
# (Crater gym id 11, home (24,6), range x4 y3: right to 28, down to 9, up to 6, left to 24, 14 steps, 224 frames).
WALK_SEQUENCE = {mv: seq.split() for mv, seq in enumerate([
    "up right left down", "right left down up", "down up right left", "left down up right",
    "up left right down", "left right down up", "down up left right", "right down up left",
    "left up down right", "up down right left", "right left up down", "down right left up",
    "right up down left", "up down left right", "left right up down", "down left right up",
    "up left down right", "down right up left", "left down right up", "right up left down",
    "up right down left", "down left up right", "left up right down", "right down left up"], 0x1D)}


def sequence_cycle(w, n):
    """The (x, y, facing) after each step of walk-sequence watcher N (HOME, RANGE, movement), one full cycle. A leg
    ends at the edge of its movement range (or a wall); a leg undoing an earlier one ends back level with home, and
    the last leg ends at home, where the sequence restarts (vanilla MoveNextDirectionInSequence)."""
    seq, (x, y) = WALK_SEQUENCE[n["movement"]], n["home"]
    i, out, keys = 0, [], []
    while (x, y, i) not in keys and len(out) < 256:
        keys.append((x, y, i))
        for _ in range(4):
            if i == 3 and (x, y) == tuple(n["home"]):
                i = 0
            dx, dy = DIRS[seq[i].upper()]
            ax = 0 if dx else 1
            back = OPPOSITE[seq[i]] in seq[:i] and (x, y)[ax] == n["home"][ax] and i < 3
            if back or not _walkable(w, n, (x + dx, y + dy)):
                i = (i + 1) % 4
                continue
            break
        else:
            return None  # boxed in: it never moves
        x, y = x + dx, y + dy
        out.append((x, y, seq[i]))
    return out[keys.index((x, y, i)):] if (x, y, i) in keys else None


class Patrol:
    """Exact model of a walker on a fixed cycle of (x, y, facing) states, one per step of WATCHER_FRAMES: a
    back-and-forth walker whose two turning points are known (TURNS: {facing: tile}), whose cycle is (lo, minus),
    (lo+1, plus) .. (hi, plus), (hi-1, minus) .. (lo+1, minus); or a walk-sequence walker (CYCLE, from its template).
    One read gives the cycle index, and the frame its current step began to within the 16 frames it stays put;
    each later read narrows that frame (a read just after a step pins it). Then any future frame's state is known."""

    def __init__(self, turns=None, cycle=None):
        if cycle is None:
            minus, plus = ("left", "right") if "left" in turns else ("up", "down")
            lo, hi = turns[minus], turns[plus]
            ax = 0 if minus == "left" else 1
            span = hi[ax] - lo[ax]

            def at(v, f):
                t = list(lo)
                t[ax] += v
                return (*t, f)
            cycle = [at(0, minus)] + [at(v, plus) for v in range(1, span + 1)] + [at(v, minus) for v in range(span - 1, 0, -1)]
        self.cycle, self.period = cycle, len(cycle)
        self.at = {s: i for i, s in enumerate(cycle)}
        self.ref = None  # (cycle index, earliest and latest frame that state began)

    def index(self, x, y, f):
        return self.at.get((x, y, f))

    def state(self, c):
        return self.cycle[c % self.period]

    def sync(self, frame, x, y, f):
        """Fold in a read of (x, y, f) taken at FRAME. False if it contradicts the model (then re-anchored on it)."""
        c, first = self.index(x, y, f), self.ref is None
        if c is not None and not first:
            c0, early, late = self.ref
            for fr in (frame, frame - 1, frame + 1):  # a read stamped a frame off still fits
                ok = [t for t in range(early, late + 1)
                      if (c0 + (fr - t) // WATCHER_FRAMES - c) % self.period == 0]
                if ok:
                    self.ref = (c0, ok[0], ok[-1])
                    return True
        self.ref = None if c is None else (c, frame - WATCHER_FRAMES + 1, frame)
        return c is not None and first

    def states(self, a, b):
        """Every (x, y, facing) it may be in at some frame from A to B."""
        c0, early, late = self.ref
        return {self.state(c) for c in range(c0 + (a - late) // WATCHER_FRAMES,
                                             c0 + (b - early) // WATCHER_FRAMES + 1)}


def sight(w, x, y, face, rng):
    """Tiles a watcher at (x, y) facing FACE sees: up to RNG tiles straight ahead, stopped by a wall."""
    dx, dy = DIRS[face.upper()]
    out = set()
    for i in range(1, rng + 1):
        t = (x + dx * i, y + dy * i)
        if not (0 <= t[0] < w["width"] and 0 <= t[1] < w["height"]) or w["tile"](*t)[1]:
            break
        out.add(t)
    return out


def futures(w, n, ahead=SNEAK_AHEAD, turns=None, since=0):
    """Every (x, y, facing) watcher N may be in from its step SINCE to its step AHEAD (0 = now). A back-and-forth walker turns only where
    it was seen turning (TURNS: {facing: tile}); until then it may turn on any tile. Other movers may face or step
    any way. A watcher matched to its ROM template (HOME, RANGE) is kept inside its movement range box, the
    template's seed for where it can turn (guard 7 turns at 18 - 9 and 18: inside 18 +- 9)."""
    mv, turns = n.get("movement"), turns or {}

    def open_(t):
        return _walkable(w, n, t)

    def step(x, y, f):
        if mv in FIXED_FACING:
            return {(x, y, f)}
        if mv not in BACK_AND_FORTH:  # wanders, rotates, walks a sequence: any facing, a step any way
            return {(x, y, g) for g in OPPOSITE} | {(x + dx, y + dy, g.lower()) for g, (dx, dy) in DIRS.items()
                                                    if open_((x + dx, y + dy))}
        dx, dy = DIRS[f.upper()]
        # The guard turns and steps back in one go (measured: at (9,27) facing left, 2 frames later (10,27) right).
        back = {(x, y, OPPOSITE[f])} | ({(x - dx, y - dy, OPPOSITE[f])} if open_((x - dx, y - dy)) else set())
        if turns.get(f) == (x, y) or not open_((x + dx, y + dy)):
            return back
        return {(x + dx, y + dy, f)} | (set() if f in turns else back)

    if mv in WALK_SEQUENCE and n.get("home") and (cyc := sequence_cycle(w, n)):
        c = Patrol(cycle=cyc).index(n["x"], n["y"], n["facing"])
        if c is None:  # off its cycle (held up, or not this template's walker): anywhere on it
            return set(cyc) | {(n["x"], n["y"], n["facing"])}
        return {cyc[(c + i) % len(cyc)] for i in range(since, ahead + 1)}
    states = {(n["x"], n["y"], n["facing"])}
    seen = set(states) if since == 0 else set()
    for i in range(1, ahead + 1):
        states = {s for x, y, f in states for s in step(x, y, f)}
        if i >= since:
            seen |= states
    return seen


def _walkable(w, n, t):
    """Can watcher N step onto tile T: open, and inside its template's movement range box if it has one (and is
    inside it now; else the template doesn't describe this object)."""
    if n.get("home"):
        rx, ry, (hx, hy) = n["range"] & 0xF, n["range"] >> 4, n["home"]
        if abs(n["x"] - hx) <= rx and abs(n["y"] - hy) <= ry and (abs(t[0] - hx) > rx or abs(t[1] - hy) > ry):
            return False
    return 0 <= t[0] < w["width"] and 0 <= t[1] < w["height"] and not w["tile"](*t)[1]


def danger(w, ahead=SNEAK_AHEAD, turns_of=lambda n: None, since=0):
    """Tiles some watcher (a trainer object with a sight range) may see, or stand on, from its step SINCE to its
    step AHEAD. Standing counts: walking into a watcher's back stops you in its line."""
    out = set()
    for n in w["npcs"]:
        if n.get("sight") and n.get("facing"):
            out |= _view(w, n, futures(w, n, ahead, turns_of(n), since))
    return out


def _view(w, n, states):
    """Tiles watcher N sees or stands on from any of STATES."""
    out = set()
    for x, y, f in states:
        out.add((x, y))
        for g in (OPPOSITE if n.get("sees_all") else [f]):
            out |= sight(w, x, y, g, n["sight"])
    return out


def reach(w, n):
    """Tiles watcher template N (a rom_world object) may stand on: the open tiles its movement range lets it walk to
    from its starting position (range: x in the low nibble, y in the high)."""
    rx, ry = n["range"] & 0xF, n["range"] >> 4
    # A back-and-forth walker patrols one side of its start only, the way it sets off (start - range .. start for
    # 0x1B): guard 8 (8,27) range 7 was only ever seen at x 1..8, never east of its start. start +- range made an
    # unloaded guard 8 claim x 1..15 and block the gym's crossing (#130).
    side = SET_OFF.get(n.get("movement"))
    lo_x, hi_x = (n["x"] - rx, n["x"]) if side == "left" else (n["x"], n["x"] + rx) if side == "right" else (n["x"] - rx, n["x"] + rx)
    lo_y, hi_y = (n["y"] - ry, n["y"]) if side == "up" else (n["y"], n["y"] + ry) if side == "down" else (n["y"] - ry, n["y"] + ry)
    spots, todo = set(), [(n["x"], n["y"])]
    while todo:
        t = todo.pop()
        if t in spots or not (lo_x <= t[0] <= hi_x and lo_y <= t[1] <= hi_y):
            continue
        if spots and (not (0 <= t[0] < w["width"] and 0 <= t[1] < w["height"]) or w["tile"](*t)[1]):
            continue
        spots.add(t)
        todo += [(t[0] + dx, t[1] + dy) for dx, dy in DIRS.values()]
    return spots


def unseen(w, ghosts):
    """Tiles watchers that aren't loaded (off screen, so not in RAM) may see: from anywhere in their movement range,
    facing any way their movement type allows. Pessimistic until they load and are tracked live.
    ponytail: blocks a crossing that a ghost would only reach after loading (vanilla respawns objects at their
    template position); relax once that is verified on Unbound."""
    out = set()
    for n in ghosts:
        if n["movement"] in WALK_SEQUENCE and (cyc := sequence_cycle(w, dict(n, home=(n["x"], n["y"])))):
            out |= _view(w, n, set(cyc))
            continue
        mv, spots = n["movement"], reach(w, n)
        rx, ry = n["range"] & 0xF, n["range"] >> 4
        faces = (list(OPPOSITE) if n.get("sees_all") else [TEMPLATE_FACING[mv]] if mv in TEMPLATE_FACING
                 else ["left", "right"] if mv in BACK_AND_FORTH and not ry
                 else ["up", "down"] if mv in BACK_AND_FORTH and not rx else list(OPPOSITE))
        for x, y in spots:
            out.add((x, y))
            for f in faces:
                out |= sight(w, x, y, f, n["sight"])
    return out


def landing(w, x, y, key):
    """Where KEY from (x, y) puts the player: two tiles on over a ledge or a gap, else the next tile."""
    dx, dy = DIRS[key]
    beh = w["tile"](x + dx, y + dy)[0]
    jump = beh in LEDGE_DIR or beh == W.HOP
    return (x + 2 * dx, y + 2 * dy) if jump else (x + dx, y + dy)


def sneak(p, target, max_steps=80, max_wait=2400):
    """Walk to TARGET without entering any watcher's sight. Safe tiles are ones no watcher can ever see; the way
    between two of them is a crossing, entered only when the whole of it can be walked before any watcher (live, or
    off screen and assumed anywhere on its patrol) can see a tile of it, and never paused on: if a crossing turns
    bad midway (a watcher came on screen), it goes back to the last safe tile at once. Static sight lines are
    planned around. Stops on a script, battle or dialog (caught) and says so; never presses anything but direction
    keys in the overworld."""
    w = W.read_world(p)  # tiles don't change; objects are polled with W.objects (one read)
    g, num = struct.unpack("<bb", p.range(p.read32(SB1_PTR) + 4, 2))
    target = tuple(target)
    # Watchers off screen aren't in RAM: their templates (matched to live objects by local id) stand in for them.
    templates = [n for n in W.rom_world(g, num)["npcs"] if n.get("sight")]
    by_id, models, last = {n["id"]: n for n in templates}, {}, {}

    def watch(npcs, here, now):  # learn turning points: where a walker flipped facing between two reads
        for n in npcs:
            if not n.get("sight") or n.get("movement") not in BACK_AND_FORTH:
                continue
            key = (g, num, n["id"])
            t = TURNS.setdefault(key, {})
            prev = last.get(key)
            if prev and prev[2] == OPPOSITE.get(n["facing"]):
                # It walked from P on to the turning point T and back to Q, turning and stepping back in one step:
                # 2T - P - Q steps along its old facing. The reads' frame stamps give the step count to within one,
                # and its parity picks which; failing that, T is at least a tile past Q and no nearer than P. A
                # walker also turns where something stands in its way (the player, another object): no turning point.
                dx, dy = DIRS[prev[2].upper()]
                along = lambda q: q[0] * dx + q[1] * dy  # noqa: E731
                p_, q_, d = along(prev), along((n["x"], n["y"])), now - prev[3]
                ks = [k for k in {d // WATCHER_FRAMES, -(-d // WATCHER_FRAMES)} if (k + p_ + q_) % 2 == 0]
                far = max(p_, q_ + 1, (ks[0] + p_ + q_) // 2 if len(ks) == 1 else p_)
                cap = 0  # no farther than it can walk: a wall, or its template's range
                while cap < far - p_ and _walkable(w, n, (prev[0] + dx * (cap + 1), prev[1] + dy * (cap + 1))):
                    cap += 1
                far = (prev[0] + dx * cap, prev[1] + dy * cap)
                old = t.get(prev[2])
                ahead = {(far[0] + dx * k, far[1] + dy * k) for k in (1, 2)}
                blocked = ahead & ({here} | {(m["x"], m["y"]) for m in npcs if m is not n})
                if not blocked and (old is None or along(far) > along(old)):
                    t[prev[2]] = far
            last[key] = (n["x"], n["y"], n["facing"], now)
        return lambda n: TURNS.get((g, num, n["id"]))

    waited, steps, path, safe_at, ladders, ghost_ids = 0, 0, None, None, {}, None
    while steps < max_steps:
        r = raw(p)
        if r["mode"] != "overworld":
            s = get_state(p)
            raise SystemExit(f"stopped: {r['mode']} at {s['pos']} after {steps} steps: a script, battle or dialog took over "
                             f"(caught by a watcher, or an event). Text: {s.get('dialog') or (s.get('battle') or {}).get('text')!r}. "
                             "Read it (advance_dialog) and see where you are before trying again.")
        now = p.read32(CLOCK) + 1  # the objects are read on the next frame
        npcs, player, elev = W.objects(p)
        for n in npcs:  # the template's start and movement range bound where a live watcher can walk
            t = by_id.get(n["id"])
            if t and n.get("sight"):
                n.update(home=(t["x"], t["y"]), range=t["range"])
        w = dict(w, npcs=npcs, player=list(player), elevation=elev)
        here = tuple(player)
        for n in npcs:
            if n.get("home") and n.get("movement") in SET_OFF and (g, num, n["id"]) not in SEEDED:
                SEEDED.add((g, num, n["id"]))
                if seed := _seed(w, n):
                    TURNS[(g, num, n["id"])] = seed
                    print(f"id {n['id']}: patrol seeded from its template, {seed} (until a read contradicts it)")
        turns_of = watch(npcs, here, now)
        for n in npcs:
            if n.get("movement") in WALK_SEQUENCE and n.get("home") and n.get("sight"):
                cyc = sequence_cycle(w, n)
                m = models.get(n["id"]) or (Patrol(cycle=cyc) if cyc else None)
                if m and m.sync(now, n["x"], n["y"], n["facing"]):
                    models[n["id"]] = m
                else:  # held up (by the player?) or off its cycle: unmodelled until a read re-anchors it
                    models.pop(n["id"], None)
                continue
            known = TURNS.get((g, num, n["id"]), {})
            both = {"left", "right"} <= set(known) or {"up", "down"} <= set(known)
            if n.get("movement") not in BACK_AND_FORTH or not both:
                models.pop(n["id"], None)
                continue
            m = models.get(n["id"]) or Patrol(known)
            if m.sync(now, n["x"], n["y"], n["facing"]):
                models[n["id"]] = m
                continue
            # Contradicted (held up by something, or the turning points were wrong): back to the pessimistic model
            # until it is seen turning at both ends again.
            models.pop(n["id"], None)
            TURNS[(g, num, n["id"])] = {}
            print(f"id {n['id']} at ({n['x']},{n['y']}) facing {n['facing']} broke its predicted patrol: "
                  "re-learning its turning points")
        seen = _seer(w, now, models, turns_of)
        live = {n["id"] for n in npcs}
        HIDDEN.update((g, num, n["id"]) for n in templates if n["id"] not in live
                      and abs(n["x"] - here[0]) <= IN_VIEW[0] and abs(n["y"] - here[1]) <= IN_VIEW[1])
        ghosts = [n for n in templates if n["id"] not in live and (g, num, n["id"]) not in HIDDEN]
        if [n["id"] for n in ghosts] != ghost_ids:  # a watcher came on screen (or went off): re-plan around it
            ghost_ids, path, ladders = [n["id"] for n in ghosts], None, {}
            lines = unseen(w, ghosts)
        # Safe tiles: no watcher can see them however long it walks (alcoves off a patrol corridor).
        sweep = danger(w, SWEEP, turns_of) | lines
        if here not in sweep:
            safe_at = here
        if here == target:
            if here in sweep:
                raise SystemExit(f"arrived at {here}, but a watcher can see this tile ({_who(w, here, ghosts, turns_of)}): "
                                 "you'll be caught if you stay. Move on to a safe tile with sneak_to.")
            print(f"arrived at {here} after {steps} steps, {waited} frames waiting")
            return
        if path is None:
            # Plan around sight lines that never move and the patrols of watchers off screen; patrollers are timed.
            static = (danger(dict(w, npcs=[n for n in npcs if n.get("movement") in FIXED_FACING])) | lines) - {target}
            path = plan(w, {target}, static) or plan(w, {target}, set()) or []
            if not path and here not in sweep:
                raise SystemExit(f"no path from {here} to {target}")
            print(f"plan {len(path)} steps: {''.join(k[0] for k in path)}")
        facing = W.FACING.get(p.range(W.OBJECT_EVENTS + 0x18, 1)[0] & 0xF)
        n, bad = _leg(w, here, path, sweep, seen, facing, lines) if path else (0, here)  # no way on: get off
        if here in sweep:
            # On a tile a watcher can see: never wait or stop here. Go on if the rest of the crossing is clear, else
            # back to the last safe tile (or the nearest one) at once, whatever the watchers do.
            if bad:
                # The last safe tile if the way back is clear, else the nearest safe tile whose way is, else the last
                # (or nearest) one anyway.
                near = sorted((z for z in {(x, y) for x in range(here[0] - 8, here[0] + 9)
                                           for y in range(here[1] - 8, here[1] + 9)} - sweep
                               if 0 <= z[0] < w["width"] and 0 <= z[1] < w["height"] and not w["tile"](*z)[1]),
                              key=lambda z: abs(z[0] - here[0]) + abs(z[1] - here[1]))
                routes = [r for z in ([safe_at] if safe_at else []) + near[:12] if (r := plan(w, {z}, set()))]
                back = next((r for r in routes if _leg(w, here, r, sweep, seen, facing, lines)[1] is None),
                            routes[0] if routes else None)
                if back:
                    end = _tiles(w, here, back)[-1]
                    print(f"{here} is watched and the way on isn't clear ({bad}): off it to the safe tile {end}")
                    path, n = back, len(back)
                elif not path:
                    raise SystemExit(f"stopped at {here}, a tile a watcher can see, with no safe tile in reach: "
                                     f"{_who(w, here, ghosts, turns_of)}. Move off it now.")
        else:
            # At rest on a safe tile: cross to the next one only if no tile on the way can be seen while the player is
            # on it; else to a nearer safe tile that is closer to the target; else wait here.
            if bad and (here, len(path)) not in ladders:  # only safe tiles nearer the target than this one
                ladders[here, len(path)] = _ladder(w, here, target, len(path), sweep, static)
            # Every watcher that matters modelled exactly: the first frame each way on (to the target, or to one of
            # the nearer safe tiles) is clear is known, so take the soonest and wait exactly that long (re-reading
            # shortly before, to re-sync). Else take one that is clear now, or poll.
            exact = all(n_["id"] in models or n_.get("movement") in FIXED_FACING for n_ in npcs if n_.get("sight"))
            cycle = max([m.period * WATCHER_FRAMES for m in models.values()], default=0) + 2 * MARGIN
            ways = [(path, None)] + [(alt, z) for z in ladders.get((here, len(path)), []) if bad
                                     if (alt := plan(w, {z}, static))]
            d, way, z = None, path, None
            for alt, zz in ways:
                first = next((dd for dd in range(0, cycle + 2, 2) if dd < (d if d is not None else 1 << 30)
                              and _leg(w, here, alt, sweep, seen, facing, lines, dd)[1] is None), None) if exact \
                    else (0 if _leg(w, here, alt, sweep, seen, facing, lines)[1] is None else None)
                if first is not None and (d is None or first < d):
                    d, way, z = first, alt, zz
            if z is not None:
                print(f"{here}: the way on is watched at {bad}; heading for the safe tile {z} first")
                path = way
                n, bad = _leg(w, here, path, sweep, seen, facing, lines)
            if d is None or d > 16:
                # Waiting doesn't bring an off-screen watcher on screen (only moving does): give up at once.
                bad = next((t for t in _tiles(w, here, path)[:n] if t in lines), bad)
                who = _who(w, bad, ghosts, turns_of)
                if bad in lines:
                    raise SystemExit(f"stopped at {here} (a safe tile): the way on crosses {bad}, watched by {who}. Waiting "
                                     "won't bring it on screen: sneak_to a safe tile nearer its start (within "
                                     f"{IN_VIEW[0]} tiles across, {IN_VIEW[1]} up/down). If it doesn't load there, it "
                                     "isn't on the map (hidden) and stops counting; if it does, it's tracked live.")
                if waited >= max_wait:
                    raise SystemExit(f"stopped at {here} (a safe tile) after waiting {waited} frames (~{waited / 60:.0f} s "
                                     f"of game time): the way on stayed watched at {bad} by {who or 'a watcher'}.")
                if exact and d is None and all(m.ref[2] - m.ref[1] <= 2 for m in models.values()):
                    raise SystemExit(f"stopped at {here} (a safe tile): no moment in a whole patrol cycle leaves the way "
                                     f"on unseen (it's watched at {bad} by {who or 'a watcher'}); waiting won't help. "
                                     "Try another safe tile or another way round.")
                step = d - 12 if d else 4
                if d:
                    print(f"{here}: the crossing is clear in {d} frames (watched at {bad} now); waiting")
                p.step(step)
                waited += step
                continue
            # The emulator runs on while this decides: count the frames that took, and wait only the rest.
            lag = p.read32(CLOCK) - now
            if lag > d and _leg(w, here, path, sweep, seen, facing, lines, lag)[1]:
                continue  # decided too slowly for that window: look again
            if d > lag:
                p.step(d - lag)
            waited += max(d - lag, 0)
            print(f"{here}: clear to {_tiles(w, here, path)[n - 1]} ({n} tiles)"
                  + (f" after waiting {waited} frames" if waited else ""))
        run, key = path[:n], path[0]
        tiles = _tiles(w, here, run)
        moved = stride(p, run, facing, max_tiles=len(run))  # the straight part of the crossing, in one held press
        steps += 1
        if moved > 0:
            print(f"{here} {key}x{moved} -> {tiles[moved - 1]}")
            del path[:moved]
        else:
            path = None  # blocked, or off the plan (a ledge, a slide): re-plan
        if not path:
            path = None
    raise SystemExit(f"stopped: max_steps ({max_steps}) reached")


def _seed(w, n):
    """Turning points for back-and-forth walker N from its template (HOME, RANGE, movement type), per SET_OFF; None
    if the stretch isn't all open (vanilla walks in place against a wall rather than turning)."""
    off = SET_OFF[n["movement"]]
    dx, dy = DIRS[off.upper()]
    r = n["range"] & 0xF if dx else n["range"] >> 4
    far = (n["home"][0] + dx * r, n["home"][1] + dy * r)
    if not r or not all(_walkable(w, {}, (n["home"][0] + dx * i, n["home"][1] + dy * i)) for i in range(r + 1)):
        return None
    return {off: far, OPPOSITE[off]: n["home"]}


def _who(w, tile, ghosts, turns_of):
    """Which watchers can ever see TILE, for the agent: live ones with where they are, off-screen ones with their
    patrol area."""
    out = [f"id {n['id']} at ({n['x']},{n['y']}) facing {n['facing']}, sight {n['sight']}"
           for n in w["npcs"] if n.get("sight") and tile in danger(dict(w, npcs=[n]), SWEEP, turns_of)]
    for n in ghosts:
        if tile in unseen(w, [n]):
            xs, ys = zip(*reach(w, n))
            out.append(f"id {n['id']} (off screen, so not tracked: its whole patrol area x {min(xs)}..{max(xs)}, "
                       f"y {min(ys)}..{max(ys)} counts as watched until it comes on screen)")
    return "; ".join(out)


def _tiles(w, here, path):
    out, t = [], here
    for k in path:
        t = landing(w, *t, k)
        out.append(t)
    return out


def _seer(w, now, models, turns_of):
    """seen(a, b): tiles some live watcher may see or stand on between A and B frames after the read at frame NOW.
    An exactly modelled patroller (Patrol) is looked up frame by frame, with MARGIN frames of slack; any other
    watcher is predicted step by step (futures), from a step before A to SNEAK_AHEAD steps after B."""
    def seen(a, b):
        out = set()
        for n in w["npcs"]:
            if n.get("sight") and n.get("facing"):
                m = models.get(n["id"])
                states = (m.states(now + a - MARGIN, now + b + MARGIN) if m else
                          futures(w, n, b // WATCHER_FRAMES + SNEAK_AHEAD, turns_of(n), max(0, a // WATCHER_FRAMES - 1)))
                out |= _view(w, n, states)
        return out
    return seen


def _leg(w, here, path, sweep, seen, facing=None, always=frozenset(), delay=0):
    """(tiles up to the next safe tile along PATH, the first of them a watcher may see, or stand on, while the
    player is there, or that is in ALWAYS (off-screen watchers' patrols); None if the whole crossing is clear),
    starting DELAY frames from now. The player starts after START frames plus a turn, walks a tile per TILE_FRAMES
    and stands on each corner tile for CORNER (min, max) frames. A tile is taken from the step onto it (a watcher
    there blocks the step) until the player steps off it, and must stay out of SEEN (a _seer) that whole span.
    HERE itself isn't checked: the player is leaving it."""
    tiles = _tiles(w, here, path)
    if tiles[0] not in sweep:  # safe ground first: walk all of it up to where the next crossing starts
        return next((i for i, t in enumerate(tiles) if t in sweep), len(tiles)), None
    n = next((i + 1 for i, t in enumerate(tiles) if t not in sweep), len(tiles))
    lo = hi = START + delay + (0 if facing == path[0].lower() else TILE_FRAMES)
    for i, tile in enumerate(tiles[:n]):
        lo, hi = lo + TILE_FRAMES, hi + TILE_FRAMES
        enter = lo - TILE_FRAMES
        if i + 1 < n and path[i + 1] != path[i]:
            lo, hi = lo + CORNER[0], hi + CORNER[1]
        if tile in always or tile in sweep and tile in seen(enter, hi):
            return n, tile
    return n, None


def _ladder(w, here, target, length, sweep, static):
    """Safe zones near HERE (out of every watcher's sweep) from which TARGET is nearer than LENGTH steps, nearest
    to the target first: places to wait on the way."""
    seen = set()
    plan(w, set(), set(), visit=seen, limit=600)
    out = []
    for z in seen - sweep - {here}:
        if abs(z[0] - here[0]) + abs(z[1] - here[1]) > 12:
            continue
        elev = w["tile"](*z)[2]
        to = plan(dict(w, player=list(z), elevation=0 if elev == 15 else elev), {target}, static)
        if to is not None and len(to) < length:
            out.append((len(to), z))
    return [z for _, z in sorted(out)]


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
    warps = live or {t for t in warps if w["tile"](*t)[0] != W.ARRIVAL_ONLY}  # an uncatalogued warp tile, never plain floor
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
        where = (here, tuple(s["pos"]), s["mode"], s.get("dialog"))  # by map id: floors share a name
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
            hops = [here] + (W.route(p, here, target, closed) or stop(p, f"no open map route to {target}" + (
                " (this map has no walk-out exit: its warps are arrival-only, on plain floor; it's left through "
                "a puzzle, a script or a person here)" if not W.map_links(p, *here) else "")))
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
        if r["mode"] == "other" and r["cb2"] == hex(CB2_OVERWORLD):
            # A warp's fade locks the field like a script does (Frost Mountain 50/1 (25,24) -> 50/0 was reported as
            # "a script started"): give it a second and see whether we arrived somewhere.
            for _ in range(8):
                p.step(8)
                if raw(p)["mode"] != "other":
                    break
            moved = get_state(p)
            if (moved["map"]["group"], moved["map"]["num"]) != here or raw(p)["mode"] == "overworld":
                continue
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


def watch(p, frames=480, every=4, radius=10):
    """Stand still FRAMES frames and report how every nearby object actually moves: per object the tiles it stood
    on, its facings, where it turned, and how long its pattern takes to repeat; for watchers (trainers with a sight
    range), every tile they were seen to look at or stand on. Then the open tiles within RADIUS that no watcher saw
    the whole time: candidate hiding spots. Empirical, so it covers movement types no model knows. Stops if a
    script or battle starts (the player was standing where a watcher looks)."""
    w = W.read_world(p)
    if raw(p)["mode"] != "overworld":
        raise SystemExit("not in the overworld: finish the dialog or battle first")
    hist, seen, here = {}, set(), None
    for _ in range(max(1, frames // every)):
        if raw(p)["mode"] != "overworld":
            raise SystemExit(f"stopped: a script or battle started while watching from {here}: a watcher saw this tile. "
                             "Read it (advance_dialog).")
        f = p.read32(CLOCK)
        npcs, here, _ = W.objects(p)
        for n in npcs:
            hist.setdefault(n["id"], []).append((f, n["x"], n["y"], n["facing"], n))
            if n.get("sight") and n.get("facing"):
                seen |= _view(w, n, {(n["x"], n["y"], n["facing"])})
        p.step(every)
    print(f"watched {frames} frames (~{frames / 60:.0f} s game time) from {here}")
    for i, h in sorted(hist.items()):
        n = h[-1][4]
        states = [(x, y, fc) for _, x, y, fc, _ in h]
        tiles = sorted({(x, y) for x, y, _ in states})
        turns = sorted({(x, y) for (x, y, a), (_, _, b) in zip(states, states[1:]) if a != b})
        rep = next((h[k][0] - h[0][0] for k in range(1, len(h)) if states[k] == states[0]
                    and any(s[:2] != states[0][:2] for s in states[1:k])), None)
        kind = (f"WATCHER sight {n['sight']}" if n.get("sight") else "trainer" if n.get("trainer") else "npc")
        xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
        print(f"id {i} ({kind}, movement 0x{n.get('movement') or 0:X}): "
              + ("did not move" if len(tiles) == 1 else f"walked x {min(xs)}..{max(xs)}, y {min(ys)}..{max(ys)} "
                 f"({len(tiles)} tiles)") + f", facings {sorted({fc for *_, fc in states if fc})}"
              + (f", turned at {turns[:8]}" if turns and len(tiles) > 1 else "")
              + (f", pattern repeats every ~{rep} frames" if rep else ", no full repeat seen (watch longer)")
              + f"; now ({n['x']},{n['y']}) facing {n['facing']}")
    walk = set()
    plan(dict(w, player=list(here)), set(), set(), visit=walk)  # every tile the player can walk to from here
    hide = sorted((t for t in walk - seen if abs(t[0] - here[0]) <= radius and abs(t[1] - here[1]) <= radius),
                  key=lambda t: abs(t[0] - here[0]) + abs(t[1] - here[1]))
    print(f"tiles no watcher looked at or stood on while watched, nearest first: {hide[:30]}")
    print("A tile next to a patrol path but off its line of sight is a hiding spot; a watcher only sees straight "
          "ahead, so walking behind one as it walks away is unseen too. Time crossings from the repeat period.")


def regions(w):
    """Split the map into regions: sets of tiles you can walk between both ways (ledges, hop gaps, ice and the
    level rules included; NPCs ignored). Returns (region of each tile, regions as tile sets, one-way links
    {region: regions reachable from it}). Levels matter: a bridge (level 4) over lily pads (level 3) is two regions
    even where they overlap on screen (Fallshore 14/15)."""
    tiles = [(x, y) for y in range(w["height"]) for x in range(w["width"])
             if not w["tile"](x, y)[1] and w["tile"](x, y)[2] not in (0, 15)]
    reach = {}
    for t in tiles:
        seen = set()
        plan(dict(w, player=list(t), elevation=w["tile"](*t)[2], npcs=[]), set(), set(), visit=seen)
        reach[t] = seen
    rid, regs = {}, []
    for t in tiles:
        if t in rid:
            continue
        r = {u for u in reach[t] if u in reach and t in reach[u]}
        for u in r:
            rid[u] = len(regs)
        regs.append(r)
    links = {i: {rid[u] for u in reach[next(iter(r))] if u in rid} - {i} for i, r in enumerate(regs)}
    return rid, regs, links


def describe_levels(w, target=None, limit=12):
    """Plain-language map of the regions for the agent: level, extent, warps inside, objects at the edge (a Lapras
    or a person may carry you across), one-way links. With TARGET, why it can't be walked to from here."""
    rid, regs, links = regions(w)
    here = tuple(w["player"])
    me = rid.get(here)
    if me is None:  # standing on a crossing tile (level 0/15): take the region of a neighbour you can reach
        me = next((rid[u] for u in sorted(rid, key=lambda u: abs(u[0] - here[0]) + abs(u[1] - here[1]))
                   if abs(u[0] - here[0]) + abs(u[1] - here[1]) <= 1), None)
    into = {i: {j for j, out in links.items() if i in out} for i in range(len(regs))}
    warps = {(wp["x"], wp["y"]): wp for wp in w["warps"]}
    big = sorted((i for i in range(len(regs)) if len(regs[i]) >= 3), key=lambda i: (i != me, -len(regs[i])))
    letter = {i: chr(65 + k) if k < 26 else f"R{k}" for k, i in enumerate(big)}
    name = lambda i: letter.get(i) or "tile " + " ".join(f"({x},{y})" for x, y in sorted(regs[i]))  # noqa: E731

    def line(i):
        r = regs[i]
        xs, ys = [t[0] for t in r], [t[1] for t in r]
        lv = sorted({w["tile"](*t)[2] for t in r})
        edge = sorted({(n["id"], n["x"], n["y"]) for n in w["npcs"] for t in r
                       if abs(n["x"] - t[0]) + abs(n["y"] - t[1]) == 1})
        ws = [f"({x},{y})->{warps[(x, y)]['to']}" + (" (arrival only: stepping on it does nothing)"
                                                     if w["tile"](x, y)[0] == W.ARRIVAL_ONLY else "")
              for (x, y) in sorted(warps) if (x, y) in r]
        return (f"Region {name(i)}{' (YOU)' if i == me else ''}: level {'/'.join(map(str, lv))}, {len(r)} tiles, x {min(xs)}..{max(xs)} "
                f"y {min(ys)}..{max(ys)}" + (f"; warps {', '.join(ws)}" if ws else "")
                + (f"; objects at its edge (talk/ride?): {', '.join(f'id {a} ({b},{c})' for a, b, c in edge)}" if edge else "")
                + (f"; walk on (one-way) to {', '.join(map(name, sorted(links[i])))}" if links[i] else "")
                + (f"; entered on foot only from {', '.join(map(name, sorted(into[i])))}" if into[i] else
                   "; NOT enterable on foot from any other region (a ride, a warp or a script gets you in)"))

    keep = ([me] if me is not None and me not in big else []) + big
    out = [line(i) for i in keep][:limit]
    if target is not None:
        t = tuple(target)
        tr = rid.get(t)
        if tr is None:
            out.insert(0, f"target {t}: not a standing tile (a wall, water, a gap or a crossing)")
        elif tr == me:
            out.insert(0, f"target {t} is in your region {name(me)}: walkable (something else blocked the walk)")
        else:
            path = tr in links.get(me, set())
            out.insert(0, f"target {t} is in region {name(tr)} (level {w['tile'](*t)[2]}); you are in region {name(me)}. "
                          + ("You can walk there one-way." if path else
                             f"No walking route from {name(me)} to {name(tr)}: see how {name(tr)} is entered below."))
            if tr not in keep[:limit]:
                out.append(line(tr))
    return "\n".join(out)
