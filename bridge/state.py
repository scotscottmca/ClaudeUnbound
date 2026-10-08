"""One-shot readout of verified Unbound RAM (see docs/addresses.md). Needs probe.lua running.

    python state.py                              # get_state JSON
    python state.py press UP [FRAMES] [SETTLE]   # traced press
"""
import json
import os
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
PARTY_SCREEN_CB2 = 0x0811EBA1  # party menu callback2 (battle and field; docs/addresses.md)
PARTY_MENU = 0x0203B0A0  # gPartyMenu: +9 cursor slot (grid 0 1 / 2 3 / 4 5, OK 6, Cancel 7)
PARTNER_BATTLE = 0x400000  # battle flag with an NPC partner (Cinder Volcano 0x40000d/0x400005); its team fills party slots 4-6
BATTLE_MONS = 0x02023BE4  # 4 x 0x58
SPECIES_TO_DEX = 0x09A41FEA  # ROM u16[species]: national dex number (found by matching 8 known species; docs/addresses.md)
DEX_OWNED = 0x38D  # SaveBlock1 offset: 0x7D bytes, bit n-1 = national dex n caught (docs/addresses.md)
TEXT_PRINTERS = 0x02020034  # 0x24 each, one per window
NUM_TEXT_PRINTERS = 32
SCRIPT_CONTEXT = 0x03000EB0  # sScriptContext1: stackDepth, mode (2 = native), pad, nativePtr
SCRIPT_WAIT_BUTTON = {0x0806951D, 0x08A0F275}  # natives a message box waits for A in (NPC msgbox, sign)
STRING_VAR4 = 0x02021D18
DISPLAYED_STRING_BATTLE = 0x0202298C
LOCK_FIELD_CONTROLS = 0x03000F9C  # u8, 1 while a script/menu/dialog holds the player
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


NAMES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "names.json"), encoding="utf-8"))
# Type IDs in ROM table order (0x08A4EAD4); 18-22 are unused.
TYPES = {0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison", 4: "Ground", 5: "Rock", 6: "Bug", 7: "Ghost",
         8: "Steel", 9: "???", 10: "Fire", 11: "Water", 12: "Grass", 13: "Electric", 14: "Psychic", 15: "Ice",
         16: "Dragon", 17: "Dark", 23: "Fairy"}
MAP_HEADER = 0x02036DFC
# Bag pockets: (address, slots) of u16 item ID + u16 count (#17). Main and key sizes match the
# save layout; the ball pocket's size isn't known yet, 50 is a guess that stops short of other data.
POCKETS = {"items": (0x0203BB20, 450), "key_items": (0x0203C228, 75), "poke_balls": (0x0203C354, 50)}
SB1_MONEY = 0x290  # u32, plain (SaveBlock2's XOR key is 0 on CFRU)
SB1_FLAGS = 0xEE0
FLAG_BADGE01 = 0x820  # vanilla FireRed; unverified on Unbound until the first badge


def status_name(st):
    if st & 7:
        return f"asleep ({st & 7} turns)"
    for bit, name in ((7, "badly poisoned"), (3, "poisoned"), (4, "burned"), (5, "frozen"), (6, "paralyzed")):
        if st & (1 << bit):
            return name
    return None


def moves(ids, pps):
    return {NAMES["moves"][m]: pp for m, pp in zip(ids, pps) if m}


def current_text(p, printer):
    """Text of the box printer 0 is on: from the last paragraph break before its cursor
    to the next one. ponytail: a 0xFB/0xFF inside a control code's argument would cut it short."""
    cur = struct.unpack("<I", printer[0:4])[0]
    if not printer[0x1B] and STRING_VAR4 <= cur < STRING_VAR4 + 0x400:
        # Finished message: its cursor sits just past gStringVar4's first 0xFF. Instant text (e.g. the
        # mission banner script on 3/71) prints through a temporary printer and leaves this cursor
        # stale, pointing into an older, longer message's leftovers; so go by the buffer, not the cursor.
        end = p.range(STRING_VAR4, 0x400).find(0xFF)
        cur = STRING_VAR4 + end + 1 if end >= 0 else cur
    data = p.range(cur - 0x100, 0x200)
    end = next((i for i in range(0xFF, 0x200) if data[i] in (0xFB, 0xFF)), 0x200)
    start = max((i for i in range(0, end) if data[i] in (0xFB, 0xFF)), default=-1) + 1
    if STRING_VAR4 <= cur < STRING_VAR4 + 0x400:  # most messages: never read back past the buffer's start
        start = max(start, STRING_VAR4 - (cur - 0x100))
    return decode(data[start:end]).strip()  # padding before a buffer decodes as spaces


def raw(p):
    """Fields the mode and press trace are built from."""
    cb1, cb2 = struct.unpack("<II", p.range(G_MAIN, 8))
    # One printer per window: NPC text uses window 0, but shops and other menus print in their own
    # windows (#57). The first active printer is the text on screen; printer 0 if none is active.
    printers = p.range(TEXT_PRINTERS, NUM_TEXT_PRINTERS * 0x24)
    active = [i for i in range(NUM_TEXT_PRINTERS) if printers[i * 0x24 + 0x1B]]
    i = active[0] if active else 0
    printer = printers[i * 0x24:(i + 1) * 0x24]
    locked = p.read8(LOCK_FIELD_CONTROLS)
    # A finished message waiting for A has no active printer: the script is parked in its
    # wait-for-button native routine instead.
    ctx = p.range(SCRIPT_CONTEXT, 8)
    waiting = ctx[1] == 2 and struct.unpack("<I", ctx[4:8])[0] in SCRIPT_WAIT_BUTTON
    mode = ("battle" if cb2 == CB2_BATTLE else "dialog" if active or waiting
            else "overworld" if cb2 == CB2_OVERWORLD and not locked else "other")
    return {"cb2": hex(cb2), "locked": locked, "printer": printer, "mode": mode, "script": ctx[1]}


def caught(p, species):
    """True if the Pokedex marks this species (internal id) as caught."""
    n = p.read16(SPECIES_TO_DEX + 2 * species)
    return bool(n) and bool(p.read8(p.read32(SB1_PTR) + DEX_OWNED + (n - 1) // 8) >> ((n - 1) % 8) & 1)


def get_state(p):
    r = raw(p)
    sb1 = p.read32(SB1_PTR)
    x, y, group, num = struct.unpack("<hhbb", p.range(sb1, 6))
    mapsec = p.read8(MAP_HEADER + 0x14)
    s = {"mode": r["mode"], "map": {"group": group, "num": num, "name": NAMES["mapsecs"][str(mapsec)]},
         "pos": [x, y]}
    events = p.range(OBJECT_EVENTS, 16 * 0x24)
    for i in range(16):
        ev = events[i * 0x24:(i + 1) * 0x24]
        if ev[0] & 1 and ev[8] == 0xFF:
            s["facing"] = FACING[ev[0x18] & 0xF]
            break
    flags = p.range(sb1 + SB1_FLAGS + FLAG_BADGE01 // 8, 1)[0]
    s["badges"] = bin(flags).count("1")
    s["money"] = p.read32(sb1 + SB1_MONEY)

    s["bag"] = {}
    for pocket, (addr, slots) in POCKETS.items():
        data = p.range(addr, slots * 4)
        items = {}
        for i in range(slots):
            item, qty = struct.unpack("<HH", data[i * 4:i * 4 + 4])
            if item and qty:
                items[NAMES["items"][item]] = items.get(NAMES["items"][item], 0) + qty
        s["bag"][pocket] = items

    count = p.read8(PLAYER_PARTY_COUNT)  # SaveBlock1's copy only updates on save
    if count > 6:
        raise ValueError(f"party count {count}")
    party = p.range(PLAYER_PARTY, 100 * count) if count else b""
    s["party"] = []
    for i in range(count):
        m = party[i * 100:(i + 1) * 100]
        species, item = struct.unpack("<HH", m[0x20:0x24])
        hp, max_hp = struct.unpack("<HH", m[0x56:0x5A])
        s["party"].append({
            "name": decode(m[0x08:0x12]), "species": NAMES["species"][species], "level": m[0x54],
            "hp": f"{hp}/{max_hp}", "status": status_name(struct.unpack("<I", m[0x50:0x54])[0]),
            "item": NAMES["items"][item] if item else None,
            "moves": moves(struct.unpack("<4H", m[0x2C:0x34]), m[0x34:0x38]),
        })
    if r["mode"] == "battle" and p.read32(BATTLE_TYPE_FLAGS) & PARTNER_BATTLE:
        for mon in s["party"][3:]:  # an NPC partner's team fills slots 4-6 for the battle (Cinder Volcano)
            mon["partner"] = True

    if r["mode"] == "battle":  # gBattleTypeFlags stays set after battle, so gate on the callback
        s["battle"] = {"flags": hex(p.read32(BATTLE_TYPE_FLAGS)), "battlers": []}
        for i in range(4):
            b = p.range(BATTLE_MONS + i * 0x58, 0x58)
            species = struct.unpack("<H", b[0:2])[0]
            if not species:
                continue
            hp, level, _, max_hp = struct.unpack("<HBBH", b[0x28:0x2E])
            types = [TYPES[b[0x21]]] + ([TYPES[b[0x22]]] if b[0x22] != b[0x21] else [])
            s["battle"]["battlers"].append({
                "side": "player" if i % 2 == 0 else "opponent", "name": decode(b[0x30:0x3B]),
                "species": NAMES["species"][species], "level": level, "hp": f"{hp}/{max_hp}",
                "types": types, "ability": NAMES["abilities"][b[0x20]],
                "status": status_name(struct.unpack("<I", b[0x4C:0x50])[0]),
                **({"moves": moves(struct.unpack("<4H", b[0x0C:0x14]), b[0x24:0x28])} if i % 2 == 0
                   else {"caught": caught(p, species)}),  # already caught: defeat it or run, don't re-catch
            })
        s["battle"]["text"] = decode(p.range(DISPLAYED_STRING_BATTLE, 0x100))
    if r["mode"] == "dialog":
        s["dialog"] = current_text(p, r["printer"])
    return s


def _snapshot(p):
    """Small state that changes on anything meaningful. Whole-screen diffs don't work:
    weather and animated tiles change the screen every frame."""
    r = raw(p)  # not get_state(): party/bag/battle reads made every press take ~1 s
    x, y, group, num = struct.unpack("<hhbb", p.range(p.read32(SB1_PTR), 6))
    player = p.range(OBJECT_EVENTS, 0x24)  # the player is object event 0 (gPlayerAvatar.objectEventId)
    pr = r["printer"]
    snap = {"map": (group, num), "pos": (x, y), "facing": FACING.get(player[0x18] & 0xF),
            "mode": r["mode"], "cb2": r["cb2"], "locked": r["locked"], "printer": (pr[0x1B], pr[0x1C], pr[0:4].hex())}
    if r["cb2"] == hex(PARTY_SCREEN_CB2):
        # On the party screen presses only move the cursor: without this every press read "changed: []" and the
        # agent pressed blind for ~20 actions on a choose-3 screen (OK is slot 6, Cancel 7).
        snap["party_cursor"] = p.read8(PARTY_MENU + 9)
    return snap


def press(p, key, frames=4, settle=16):
    """Press KEY, wait SETTLE frames, and report what changed."""
    before = _snapshot(p)
    p.press(key, frames)
    p.step(settle)
    sb1 = p.read32(SB1_PTR)
    for _ in range(40):  # still moving (an ice slide, a long walk): wait until the position holds
        pos = p.range(sb1, 4)
        p.step(6)
        if p.range(sb1, 4) == pos:
            break
    after = _snapshot(p)
    return {"key": key, "before": before, "after": after,
            "moved": (before["map"], before["pos"]) != (after["map"], after["pos"]),
            "changed": [k for k in before.keys() | after.keys() if before.get(k) != after.get(k)]}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = Probe()
    if sys.argv[1:2] == ["press"]:
        print(press(p, sys.argv[2], *map(int, sys.argv[3:])))
    else:
        print(json.dumps(get_state(p), ensure_ascii=False, indent=1))
