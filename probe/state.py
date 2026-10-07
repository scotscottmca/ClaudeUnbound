"""One-shot readout of verified Unbound RAM (see docs/addresses.md). Needs probe.lua running.

    python state.py
"""
import struct
import sys

from probe import Probe

G_MAIN = 0x030030F0
SB1_PTR = 0x03005008
SB2_PTR = 0x0300500C
OBJECT_EVENTS = 0x02036E38  # 16 x 0x24, player is localId 0xFF
PLAYER_PARTY_COUNT = 0x02024029
PLAYER_PARTY = 0x02024284  # 6 x 100, unencrypted on CFRU
BATTLE_TYPE_FLAGS = 0x02022B4C
BATTLE_MONS = 0x02023BE4  # 4 x 0x58
TEXT_PRINTERS = 0x02020034  # 0x24 each
STRING_VAR4 = 0x02021D18
DISPLAYED_STRING_BATTLE = 0x0202298C
CB2_OVERWORLD = 0x080565B5
CB2_BATTLE = 0x08011101  # BattleMainCB2

FACING = {1: "down", 2: "up", 3: "left", 4: "right"}
# Gen 3 English charmap, enough for dialog and names.
CHARS = {0x00: " ", 0x1B: "é", 0x2D: "&", 0x34: "Lv", 0x35: "=", 0x36: ";", 0x5C: "(", 0x5D: ")",
         0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xAF: "·", 0xB0: "…", 0xB1: "“", 0xB2: "”",
         0xB3: "‘", 0xB4: "'", 0xB5: "♂", 0xB6: "♀", 0xB7: "$", 0xB8: ",", 0xB9: "×", 0xBA: "/",
         0xEF: "▶", 0xF0: ":", 0xFA: "\n", 0xFB: "\n\n", 0xFE: "\n"}
CHARS |= {0xA1 + i: str(i) for i in range(10)}
CHARS |= {0xBB + i: chr(ord("A") + i) for i in range(26)}
CHARS |= {0xD5 + i: chr(ord("a") + i) for i in range(26)}
# Argument byte counts for 0xFC control codes (pokefirered charmap); unknown codes assume 1.
FC_ARGS = {0x04: 3, 0x07: 0, 0x09: 0, 0x0A: 0, 0x0B: 2, 0x0F: 0, 0x10: 2, 0x15: 0, 0x16: 0, 0x17: 0, 0x18: 0}


def decode(data):
    out, i = [], 0
    while i < len(data) and data[i] != 0xFF:
        b = data[i]
        if b == 0xFC:
            i += 1 + FC_ARGS.get(data[i + 1] if i + 1 < len(data) else 0, 1)
        elif b == 0xFD:
            out.append("{var}")
            i += 1
        else:
            out.append(CHARS.get(b, "?"))
        i += 1
    return "".join(out)


def read_state(p):
    main = p.range(G_MAIN, 0x8)
    cb1, cb2 = struct.unpack("<II", main)
    sb1 = p.read32(SB1_PTR)
    x, y, group, num = struct.unpack("<hhbb", p.range(sb1, 6))
    s = {"cb1": hex(cb1), "cb2": hex(cb2), "map": (group, num), "pos": (x, y)}

    for i in range(16):
        ev = p.range(OBJECT_EVENTS + i * 0x24, 0x24)
        if ev[0] & 1 and ev[8] == 0xFF:
            s["facing"] = FACING.get(ev[0x18] & 0xF, ev[0x18] & 0xF)
            s["obj_coords"] = struct.unpack("<hh", ev[0x10:0x14])
            break

    s["trainer"] = decode(p.range(p.read32(SB2_PTR), 8))
    count = p.read8(PLAYER_PARTY_COUNT)  # SaveBlock1's copy only updates on save
    party = p.range(PLAYER_PARTY, 100 * min(count, 6))
    s["party"] = []
    for i in range(min(count, 6)):
        m = party[i * 100:(i + 1) * 100]
        species, item = struct.unpack("<HH", m[0x20:0x24])
        s["party"].append({
            "nick": decode(m[0x08:0x12]), "species": species, "item": item,
            "level": m[0x54], "hp": struct.unpack("<HH", m[0x56:0x5A]),
            "moves": struct.unpack("<4H", m[0x2C:0x34]), "pp": tuple(m[0x34:0x38]),
            "status": struct.unpack("<I", m[0x50:0x54])[0],
        })

    in_battle = cb2 == CB2_BATTLE
    if in_battle:  # gBattleTypeFlags stays set after battle, so gate on the callback
        s["battle_flags"] = hex(p.read32(BATTLE_TYPE_FLAGS))
        s["battlers"] = []
        for i in range(4):
            b = p.range(BATTLE_MONS + i * 0x58, 0x58)
            hp, level, _, max_hp = struct.unpack("<HBBH", b[0x28:0x2E])
            s["battlers"].append({"species": struct.unpack("<H", b[0:2])[0], "level": level, "ability": b[0x20],
                                  "hp": (hp, max_hp), "nick": decode(b[0x30:0x3B])})
        s["battle_text"] = decode(p.range(DISPLAYED_STRING_BATTLE, 0x100))

    printer = p.range(TEXT_PRINTERS, 0x24)
    s["printer0_active"] = printer[0x1B]
    s["dialog"] = decode(p.range(STRING_VAR4, 0x200))
    s["mode"] = ("battle" if in_battle else "dialog" if printer[0x1B]
                 else "overworld" if cb2 == CB2_OVERWORLD else "other")
    return s


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for k, v in read_state(Probe()).items():
        print(f"{k:15} {v}")
