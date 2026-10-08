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
    """Maps reachable in one hop from (group, num): connections and warps, from the ROM header."""
    p = rom()
    if (group, num) not in _links:
        header = header_of(p, group, num)
        events, _, connections = struct.unpack("<III", p.range(header + 4, 12))
        out = set()
        n_warp = p.range(events, 4)[1]
        warp_ptr = u32(p, events + 8)
        for i in range(n_warp):
            _, _, _, _, wnum, wgroup = struct.unpack("<hhBBBB", p.range(warp_ptr + 8 * i, 8))
            if (wgroup, wnum) != (0x7F, 0x7F):  # dynamic warp: destination decided at runtime
                out.add((wgroup, wnum))
        if connections:
            count, ptr = struct.unpack("<iI", p.range(connections, 8))
            for i in range(count):
                _, _, _, _, _, cgroup, cnum = struct.unpack("<BBBBiBB", p.range(ptr + 12 * i, 10))
                out.add((cgroup, cnum))
        _links[(group, num)] = out
    return _links[(group, num)]


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
    attrs = (struct.unpack(f"<{PRIMARY_METATILES}I", p.range(u32(p, prim + 0x14), PRIMARY_METATILES * 4)),
             struct.unpack("<384I", p.range(u32(p, sec + 0x14), 384 * 4)))

    def tile(x, y):  # map coords -> (behavior, collision, elevation)
        b = blocks[(y + BORDER_Y) * vw + x + BORDER_X]
        mt = b & 0x3FF
        a = attrs[0][mt] if mt < PRIMARY_METATILES else attrs[1][mt - PRIMARY_METATILES]
        return a & 0x1FF, (b >> 10) & 3, b >> 12

    n_obj, n_warp, _, n_bg = p.range(events, 4)
    _, warp_ptr, _, bg_ptr = struct.unpack("<IIII", p.range(events + 4, 16))
    warps = []
    for i in range(n_warp):
        x, y, _, _, num, group = struct.unpack("<hhBBBB", p.range(warp_ptr + 8 * i, 8))
        warps.append({"x": x, "y": y, "to": map_name(p, group, num), "to_map": [group, num]})
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

    npcs, player = [], None
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
                     "trainer": bool(ev[7]), "graphics": ev[5], **({"item": True} if ev[5] == ITEM_BALL else {})})

    special = {(s["x"], s["y"]): "S" for s in signs}
    special |= {(wp["x"], wp["y"]): "D" for wp in warps}
    special |= {(n["x"], n["y"]): "T" if n["trainer"] else "o" if n.get("item") else "N" for n in npcs}
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

    return {"width": w, "height": h, "player": list(player), "elevation": player_elev, "tile": tile, "char": char,
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
