"""Build names.json (species, moves, abilities, items, map sections) from the Unbound 2.1.1.1 ROM.

    python tables.py [ROM]      # default: the .gba in ../rom

Addresses were found by scanning the ROM (see docs/addresses.md). Each table is checked
against known names, so a different ROM fails loudly instead of producing junk.
"""
import glob
import json
import os
import struct
import sys

from state import decode

ROM_BASE = 0x08000000
# name: (ROM address, entry size, name width, count, {index: expected name})
TABLES = {
    "species": (0x0966A98C, 11, 11, 1294, {1: "Bulbasaur", 246: "Larvitar", 346: "Snorunt", 794: "Inkay"}),
    "moves": (0x08A40A10, 13, 13, 923, {1: "Pound", 43: "Leer", 88: "Rock Throw", 310: "Astonish"}),
    "abilities": (0x08A36398, 17, 17, 293, {39: "Inner Focus", 62: "Guts", 191: "Contrary"}),
    "items": (0x08876200, 44, 14, 729, {1: "Master Ball", 44: "Berry Juice"}),
}
MAPSEC_NAMES = 0x083F1CAC  # u32 pointers, mapsec 0x58 + index
MAPSEC_FIRST, MAPSEC_COUNT = 0x58, 109
MAPSEC_EXPECT = {0x59: "Bellin Town", 0x65: "Route 1", 0x85: "Shadow Base"}


def build(rom):
    out = {}
    for name, (addr, size, width, count, expect) in TABLES.items():
        o = addr - ROM_BASE
        out[name] = [decode(rom[o + i * size: o + i * size + width]) for i in range(count)]
        for i, want in expect.items():
            if out[name][i] != want:
                sys.exit(f"{name}[{i}] is {out[name][i]!r}, expected {want!r}: wrong ROM or table moved")
    out["mapsecs"] = {}
    for i in range(MAPSEC_COUNT):
        ptr = struct.unpack("<I", rom[MAPSEC_NAMES - ROM_BASE + 4 * i:][:4])[0] - ROM_BASE
        out["mapsecs"][MAPSEC_FIRST + i] = decode(rom[ptr:ptr + 40])
    for sec, want in MAPSEC_EXPECT.items():
        if out["mapsecs"][sec] != want:
            sys.exit(f"mapsec {sec:#x} is {out['mapsecs'][sec]!r}, expected {want!r}")
    return out


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if sys.argv[1:] else glob.glob(os.path.join(here, "..", "rom", "*.gba"))[0]
    with open(path, "rb") as f:
        names = build(f.read())
    with open(os.path.join(here, "names.json"), "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=0)
    print({k: len(v) for k, v in names.items()})
