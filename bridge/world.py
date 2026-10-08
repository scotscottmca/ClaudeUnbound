"""Collision grid, NPCs, warps, signs and connections from the live map (see docs/addresses.md).

    python world.py          # viewport + lists
    python world.py full     # whole-map grid
"""
import json
import os
import struct
import sys

from probe import Probe
from state import MAP_HEADER, NAMES, OBJECT_EVENTS

VMAP = 0x03005040  # gBackupMapLayout: s32 width, s32 height, u16 *map (map + 7-tile border each side)
MAP_GROUPS = 0x08B70498  # u32 per group, XOR-obfuscated with MAP_GROUPS_KEY, -> u32 header pointers
MAP_GROUPS_KEY = 0x00B749DE
PRIMARY_METATILES = 640
BORDER_X, BORDER_Y = 7, 7  # VMap is 15 wider and 14 taller than the map

FACING = {1: "down", 2: "up", 3: "left", 4: "right"}
CONNECTION = {1: "south", 2: "north", 3: "west", 4: "east", 5: "dive", 6: "emerge"}
LEDGE = {0x38: ">", 0x39: "<", 0x3A: "^", 0x3B: "v"}
WATER = {0x10, 0x11, 0x12, 0x15, 0x1A, 0x1B}
ICE = {0x23, 0x26, 0x27}
FORCED = set(range(0x40, 0x48)) | set(range(0x50, 0x59))
WARP = set(range(0x60, 0x70)) | {0x71}
ITEM_BALL = 92  # object graphics id of an item on the ground (verified: Route 2 (8,28)/(17,27) match the Poke Ball sprites on screen)
HOP = 0x7F  # Unbound: a gap you hop over sideways, LEFT/RIGHT land two tiles on (Grim Woods (7,33), (9,33))
LEGEND = {"@": "you", "N": "NPC/object", "o": "item on the ground (walk_to it to pick it up)", "T": "trainer", ".": "walkable", "#": "blocked", "G": "tall grass",
          "~": "water (Surf)", "W": "waterfall", "I": "ice", "F": "forced movement", "D": "warp/door",
          "S": "sign", ":": "walkable, but on another level (reach it via stairs or a ramp)", "^v<>": "ledge, jump in that direction", "=": "gap, hop over it left or right",
          " ": "outside the map"}


def u32(p, addr):
    return struct.unpack("<I", p.range(addr, 4))[0]


class RomFile:
    """Reads ROM addresses from the cartridge file: map headers are static, so the map graph
    doesn't need the emulator (through the socket it cost a frame per read, ~12 s per 64 maps)."""
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()

    def range(self, addr, n):
        if not 0x08000000 <= addr < 0x08000000 + len(self.data):
            raise ValueError(f"{addr:#x} is not a ROM address")
        return self.data[addr - 0x08000000: addr - 0x08000000 + n]

    def read8(self, addr):
        return self.range(addr, 1)[0]


_rom = None


def rom():
    """The run's ROM file, loaded on first use (so importing world doesn't need it)."""
    global _rom
    if _rom is None:
        _rom = RomFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "run", "Unbound.gba"))
    return _rom


def header_of(_p, group, num):
    """ROM map header address, via Unbound's XOR-obfuscated map-group table."""
    p = rom()
    return u32(p, (u32(p, MAP_GROUPS + 4 * group) ^ MAP_GROUPS_KEY) + 4 * num)


def map_name(_p, group, num):
    return NAMES["mapsecs"][str(rom().read8(header_of(None, group, num) + 0x14))]


_links = {}


def map_links(_p, group, num):
    """Maps you can walk to in one hop from (group, num): warps and connections, from the ROM."""
    p = rom()
    if (group, num) not in _links:
        here = rom_world(group, num)
        out = set()
        events = u32(p, header_of(p, group, num) + 4)
        n_warp, warp_ptr = p.range(events, 4)[1], u32(p, events + 8)
        for i in range(n_warp):
            x, y, _, _, wnum, wgroup = struct.unpack("<hhBBBB", p.range(warp_ptr + 8 * i, 8))
            if (wgroup, wnum) != (0x7F, 0x7F) and not _buried(here, x, y):  # 0x7F: dynamic, decided at runtime
                out.add((wgroup, wnum))
        out |= {tuple(c["to_map"]) for c in here["connections"] if _walkable_seam(here, c)}
        _links[(group, num)] = out
    return _links[(group, num)]


def seam(w, c):
    """[((x, y) on this map, (x, y) on the other map)] for each tile pair across connection C of world W."""
    p = rom()
    ow, oh = struct.unpack("<ii", p.range(u32(p, header_of(p, *c["to_map"])), 8))
    off, d = c["offset"], c["direction"]
    if d in ("north", "south"):
        y, oy = (w["height"] - 1, 0) if d == "south" else (0, oh - 1)
        return [((x, y), (x - off, oy)) for x in range(max(0, off), min(w["width"], off + ow))]
    if d in ("east", "west"):
        x, ox = (w["width"] - 1, 0) if d == "east" else (0, ow - 1)
        return [((x, y), (ox, y - off)) for y in range(max(0, off), min(w["height"], off + oh))]
    return []  # dive/emerge


def _buried(w, x, y):
    """A warp event inside solid rock (it and every neighbour have collision) can't be walked into: Route 4's
    (112,7)/(113,7) to KBT Expressway, and the (0,0) placeholders. Scripts may still warp you by its ID."""
    near = [(x + dx, y + dy) for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
            if 0 <= x + dx < w["width"] and 0 <= y + dy < w["height"]]
    return (x, y) in near and all(w["tile"](*t)[1] for t in near)


def _walkable_seam(here, c):
    """Can you walk across connection C (from HERE, a rom_world) between the two maps' main areas?
    Route 4 -> Route 5 can't: Route 4's side of that seam is 5 tiles of shore in a lake walled off from the
    rest of Route 4, so route() must go round. Water seams count as closed (the planner doesn't surf).
    ponytail: authored layout only; a map script that setmetatiles a seam open at runtime isn't seen."""
    import bot  # bot imports world
    there = rom_world(*c["to_map"])

    def open_(w, t):  # walkable, and not a pocket smaller than bot.POCKET
        beh, col, elev = w["tile"](*t)
        if col or beh in bot.AVOID:
            return False
        seen = set()
        # A bridge tile (15) keeps whatever level you walked on with: start unconstrained (0), like stairs.
        bot.plan(dict(w, player=list(t), elevation=0 if elev == 15 else elev, npcs=[]), set(), set(),
                 visit=seen, limit=bot.POCKET)
        return len(seen) >= bot.POCKET
    return any(open_(here, a) and open_(there, b) for a, b in seam(here, c))


def doors(group, num):
    """[(x, y, (group, num))] for the map's warps, from the ROM header (dynamic warps left out)."""
    p = rom()
    events = u32(p, header_of(p, group, num) + 4)
    n, ptr = p.range(events, 4)[1], u32(p, events + 8)
    out = []
    for i in range(n):
        x, y, _, _, wnum, wgroup = struct.unpack("<hhBBBB", p.range(ptr + 8 * i, 8))
        if (wgroup, wnum) != (0x7F, 0x7F):
            out.append((x, y, (wgroup, wnum)))
    return out


def route(p, start, target_name, closed=(), max_maps=400):
    """Shortest list of maps from START (group, num) to any map named TARGET_NAME, or None.
    CLOSED: maps known to be unreachable for now (story gates the ROM can't tell us about)."""
    prev, queue = {start: None}, [start]
    while queue and len(prev) < max_maps:
        here = queue.pop(0)
        if here != start and map_name(p, *here) == target_name:
            hops = []
            while here != start:
                hops.append(here)
                here = prev[here]
            return hops[::-1]
        links = map_links(p, *here)
        if len(links) > 20 and here != start:
            continue  # hub maps (e.g. 4/9 links to every town) aren't walkable shortcuts
        for nxt in sorted(links):
            if nxt not in prev and nxt not in closed:
                prev[nxt] = here
                queue.append(nxt)
    return None


def read_world(p):
    for attempt in range(8):  # mid map transition the header changes before the VMap is rebuilt
        header = p.range(MAP_HEADER, 0x1C)
        layout, events, _, connections = struct.unpack("<IIII", header[:16])
        w, h, _, _, prim, sec = struct.unpack("<iiIIII", p.range(layout, 24))
        vw, vh, vptr = struct.unpack("<iiI", p.range(VMAP, 12))
        if (vw, vh) == (w + 15, h + 14):
            break
        p.step(10)
    else:
        raise ValueError(f"VMap {vw}x{vh} doesn't match layout {w}x{h}")
    blocks = struct.unpack(f"<{vw * vh}H", p.range(vptr, vw * vh * 2))
    tile = _tiler(p, prim, sec, lambda x, y: blocks[(y + BORDER_Y) * vw + x + BORDER_X])
    npcs, player, player_elev = objects(p)
    return _world(p, w, h, tile, events, connections, npcs, player, player_elev)


def objects(p):
    """(npcs, player (x, y), player elevation) from the live object events: one read, cheap enough to poll.
    Only objects near the camera are live; the game despawns the rest. Trainers carry their sight range
    (+0x1D, tiles straight ahead) and movement type (+0x06); see docs/addresses.md, Objects."""
    npcs, player, player_elev = [], None, 0
    evs = p.range(OBJECT_EVENTS, 16 * 0x24)
    for i in range(16):
        ev = evs[i * 0x24:(i + 1) * 0x24]
        if not ev[0] & 1:
            continue
        x, y = (c - 7 for c in struct.unpack("<hh", ev[0x10:0x14]))
        if ev[8] == 0xFF:
            player, player_elev = (x, y), ev[0x0B] & 0xF
            continue
        npcs.append({"id": ev[8], "x": x, "y": y, "facing": FACING.get(ev[0x18] & 0xF),
                     "trainer": bool(ev[7]), "graphics": ev[5], **({"item": True} if ev[5] == ITEM_BALL else {}),
                     **({"sight": ev[0x1D], "movement": ev[6], **({"sees_all": True} if ev[7] == 2 else {})}
                        if ev[7] else {})})
    return npcs, player, player_elev


def rom_world(group, num, start=None, elevation=None):
    """read_world's dict for map (GROUP, NUM) from the ROM alone: the layout's block map as authored
    (map scripts that set metatiles at runtime aren't applied), object events at their initial
    positions, PLAYER = START (or None) on ELEVATION (default: the start tile's)."""
    p = rom()
    layout, events, _, connections = struct.unpack("<IIII", p.range(header_of(p, group, num), 16))
    w, h, _, mapdata, prim, sec = struct.unpack("<iiIIII", p.range(layout, 24))
    blocks = struct.unpack(f"<{w * h}H", p.range(mapdata, w * h * 2))
    tile = _tiler(p, prim, sec, lambda x, y: blocks[y * w + x])
    n_obj, objs = p.range(events, 1)[0], u32(p, events + 4)
    npcs = []
    for i in range(n_obj):  # ObjectEventTemplate, 24 bytes: localId, graphicsId, kind, _, x, y, ..., trainerType @12
        lid, gfx, _, _, x, y = struct.unpack("<BBBBhh", p.range(objs + 24 * i, 8))
        trainer = struct.unpack("<H", p.range(objs + 24 * i + 12, 2))[0]
        npcs.append({"id": lid, "x": x, "y": y, "facing": None, "trainer": bool(trainer), "graphics": gfx,
                     **({"item": True} if gfx == ITEM_BALL else {})})
    if start and elevation is None:
        elevation = tile(*start)[2]
        elevation = 0 if elevation == 15 else elevation  # a bridge keeps your level: unknown here, so unconstrained
    return _world(p, w, h, tile, events, connections, npcs, tuple(start) if start else None, elevation or 0)


def _tiler(p, prim, sec, block):
    """tile(x, y) -> (behavior, collision, elevation) for a block map: metatile id in bits 0-9,
    collision 10-11, elevation 12-15; behaviors from the tilesets' attribute tables."""
    attrs = (struct.unpack(f"<{PRIMARY_METATILES}I", p.range(u32(p, prim + 0x14), PRIMARY_METATILES * 4)),
             struct.unpack("<384I", p.range(u32(p, sec + 0x14), 384 * 4)))

    def tile(x, y):
        b = block(x, y)
        mt = b & 0x3FF
        a = attrs[0][mt] if mt < PRIMARY_METATILES else attrs[1][mt - PRIMARY_METATILES]
        return a & 0x1FF, (b >> 10) & 3, b >> 12
    return tile


def _world(p, w, h, tile, events, connections, npcs, player, player_elev):
    _, n_warp, _, n_bg = p.range(events, 4)
    _, warp_ptr, _, bg_ptr = struct.unpack("<IIII", p.range(events + 4, 16))
    warps = []
    for i in range(n_warp):
        x, y, _, _, num, group = struct.unpack("<hhBBBB", p.range(warp_ptr + 8 * i, 8))
        # (0x7F, 0x7F) is a dynamic warp (Hidden Grotto's exits): back to where you came from; no header to name.
        to = "where you came from" if (group, num) == (0x7F, 0x7F) else map_name(p, group, num)
        warps.append({"x": x, "y": y, "to": to, "to_map": [group, num]})
    signs = []
    for i in range(n_bg):
        x, y, _, kind = struct.unpack("<HHBB", p.range(bg_ptr + 12 * i, 6))
        if kind < 5:  # 7 = hidden item, 8 = secret base
            # 0: readable from any side; 1-4: only while facing up/down/right/left (most signs: up).
            signs.append({"x": x, "y": y, "read_facing": [None, "up", "down", "right", "left"][kind]})
    conns = []
    if connections:
        count, ptr = struct.unpack("<iI", p.range(connections, 8))
        for i in range(count):
            d, _, _, _, offset, group, num = struct.unpack("<BBBBiBB", p.range(ptr + 12 * i, 10))
            if d not in CONNECTION:  # Dresco Gym lists a direction-0 entry: not a walkable connection
                continue
            conns.append({"direction": CONNECTION[d], "to": map_name(p, group, num), "to_map": [group, num],
                          "offset": offset})

    special = {(s["x"], s["y"]): "S" for s in signs}
    special |= {(wp["x"], wp["y"]): "D" for wp in warps}
    special |= {(n["x"], n["y"]): "T" if n["trainer"] else "o" if n.get("item") else "N" for n in npcs}
    if player:
        special[player] = "@"

    def char(x, y):
        if (x, y) in special:
            return special[(x, y)]
        if not (0 <= x < w and 0 <= y < h):
            return " "
        beh, col, elev = tile(x, y)
        if beh in LEDGE:
            return LEDGE[beh]
        if beh == HOP:
            return "="
        if col:
            return "#"
        # Gen 3 blocks a step onto a different elevation unless either side is 0 (stairs/ramps,
        # which reset yours) or the tile is 15 (bridges). Relative to where the player stands now.
        if player_elev and elev not in (0, 15, player_elev):
            return ":"
        return ("~" if beh in WATER else "W" if beh == 0x13 else "I" if beh in ICE else "F" if beh in FORCED
                else "G" if beh == 0x02 else "D" if beh in WARP else ".")

    return {"width": w, "height": h, "player": list(player) if player else None, "elevation": player_elev, "tile": tile, "char": char,
            "npcs": npcs, "warps": warps, "signs": signs, "connections": conns}


def grid(world, x0, y0, x1, y1):
    return ["".join(world["char"](x, y) for x in range(x0, x1)) for y in range(y0, y1)]


def viewport(world):
    """The 15x10 tiles on screen; the player is drawn at column 7, row 4."""
    px, py = world["player"]
    return grid(world, px - 7, py - 4, px + 8, py + 6)


def full_map(world):
    return grid(world, 0, 0, world["width"], world["height"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    world = read_world(Probe())
    rows = full_map(world) if sys.argv[1:2] == ["full"] else viewport(world)
    print("\n".join(rows))
    print(json.dumps({k: world[k] for k in ("player", "npcs", "warps", "signs", "connections")}, ensure_ascii=False))
