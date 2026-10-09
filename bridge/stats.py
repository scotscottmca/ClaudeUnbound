"""Stats, natures, EVs and IVs (Expert-run groundwork, #156).

Party layout (CFRU, unencrypted; verified 2026-10-09 by recomputing all six live party members' stored stats exactly):
EVs u8 x6 at +0x38 (HP Atk Def Spe SpA SpD), IVs packed 5 bits each at +0x48 (same order), nature = personality
(+0x00) % 25, stored stats u16 x6 at +0x58 (maxHP Atk Def Spe SpA SpD, party only). Species base stats in ROM
(moves.BASE_STATS, 0x1C each): stats +0..+5 in the same order, EV yield u16 +0x0A, 2 bits per stat, same order
(checked against the wiki's EV-yield table: Charizard SpA 3, Blastoise SpD 3, Snorlax HP 2, Metang Def 2...).

    python stats.py        # self-check, then the live party (read only)
"""
import os
import struct
import sys

import moves
from state import NAMES, NATURES, decode

STATS = ["HP", "Atk", "Def", "Spe", "SpA", "SpD"]
EV_TOTAL, EV_STAT = 510, 252
# Level caps with Capped Exp. Share by badge count (Unbound wiki, Level Caps; "Difficult and above" table).
# Index = badges; 4.5 (after Tarmigan Mansion) is between 4 and 5. Vanilla's differ (15 .. 66).
CAPS = {"vanilla": [15, 22, 29, 33, 37, 51, 55, 60, 66], "expert": [20, 26, 32, 36, 40, 52, 57, 61, 75]}


def nature_effect(nature):
    """(raised, lowered) stat names, or None for a neutral nature. Order: Atk Def Spe SpA SpD by nature // 5, % 5."""
    up, down = STATS[1 + nature // 5], STATS[1 + nature % 5]
    return None if up == down else (up, down)


def base(species):
    """(base stats [HP Atk Def Spe SpA SpD], EV yield {stat: n}) for a species id."""
    o = moves.BASE_STATS - 0x08000000 + 0x1C * species
    d = moves._data()
    ev = struct.unpack("<H", d[o + 0xA:o + 0xC])[0]
    return list(d[o:o + 6]), {STATS[i]: ev >> (2 * i) & 3 for i in range(6) if ev >> (2 * i) & 3}


def calc(bs, iv, ev, level, nature):
    """Stats from base stats, IVs, EVs, level and nature (the game's integer formula)."""
    out = [(2 * bs[0] + iv[0] + ev[0] // 4) * level // 100 + level + 10]
    eff = nature_effect(nature)
    for i in range(1, 6):
        v = (2 * bs[i] + iv[i] + ev[i] // 4) * level // 100 + 5
        if eff:
            v = v * 11 // 10 if STATS[i] == eff[0] else v * 9 // 10 if STATS[i] == eff[1] else v
        out.append(v)
    return out


def detail(m):
    """Training detail of one 100-byte party Pokemon."""
    pid = struct.unpack("<I", m[0:4])[0]
    species = struct.unpack("<H", m[0x20:0x22])[0]
    evs = list(m[0x38:0x3E])
    ivw = struct.unpack("<I", m[0x48:0x4C])[0]
    ivs = [(ivw >> (5 * i)) & 31 for i in range(6)]
    bs, _ = base(species)
    eff = nature_effect(pid % 25)
    fmt = lambda v: " ".join(f"{s} {x}" for s, x in zip(STATS, v))  # noqa: E731
    return {"name": decode(m[8:18]), "species": NAMES["species"][species], "level": m[0x54],
            "nature": NATURES[pid % 25] + (f" (+{eff[0]} -{eff[1]})" if eff else " (neutral)"),
            "stats": fmt(struct.unpack("<6H", m[0x58:0x64])), "base": fmt(bs),
            "evs": fmt(evs) + f" (total {sum(evs)}/{EV_TOTAL}; {EV_TOTAL - sum(evs)} left)",
            "ivs": fmt(ivs)}


def exp_for(rate, n):
    """EXP needed for level N at growth rate RATE (ROM species +0x13; vanilla order: 0 medium fast, 1 erratic,
    2 fluctuating, 3 medium slow, 4 fast, 5 slow)."""
    if n <= 1:
        return 0
    c = n ** 3
    if rate == 1:
        return c * (100 - n) // 50 if n <= 50 else c * (150 - n) // 100 if n <= 68 else             c * ((1911 - 10 * n) // 3) // 500 if n <= 98 else c * (160 - n) // 100
    if rate == 2:
        return c * ((n + 1) // 3 + 24) // 50 if n <= 15 else c * (n + 14) // 50 if n <= 36 else c * (n // 2 + 32) // 50
    if rate == 3:
        return 6 * c // 5 - 15 * n * n + 100 * n - 140
    return {0: c, 4: 4 * c // 5, 5: 5 * c // 4}[rate]


def level_from_exp(species, exp):
    rate = moves._data()[moves.BASE_STATS - 0x08000000 + 0x1C * species + 0x13]
    return max(n for n in range(1, 101) if exp_for(rate, n) <= exp)


# PC storage (CFRU, verified #157): gPokemonStoragePtr (0x03005010) -> current box (u8) at +0, then 58-byte compressed
# Pokemon from +4 in vanilla's 0x8340-byte box area (579 slots: boxes 1-19 and box 20 slots 1-9), box names (9
# bytes each) at +0x8344. Where boxes 20+ live is pending.
STORAGE_PTR, BOX_SIZE, BOX_SLOTS, IN_RAM = 0x03005010, 0x3A, 30, 579


def box_mon(b):
    """One 58-byte compressed box Pokemon: +0 personality, +8 nickname, +0x1C species, +0x1E item, +0x20 EXP,
    +0x27 four moves packed 10 bits each, +0x2C EVs x6, +0x36 IVs (5 bits x6)."""
    species, item = struct.unpack("<HH", b[0x1C:0x20])
    if not species or species >= len(NAMES["species"]):
        return None
    mv = int.from_bytes(b[0x27:0x2C], "little")
    ivw = struct.unpack("<I", b[0x36:0x3A])[0]
    pid = struct.unpack("<I", b[0:4])[0]
    eff = nature_effect(pid % 25)
    return {"name": decode(b[8:18]), "species": NAMES["species"][species],
            "level": level_from_exp(species, struct.unpack("<I", b[0x20:0x24])[0]),
            "types": moves.species_types(NAMES["species"][species]),
            "item": NAMES["items"][item] if item else None,
            "moves": [NAMES["moves"][m] for m in ((mv >> (10 * i)) & 0x3FF for i in range(4)) if m],
            "nature": NATURES[pid % 25] + (f" (+{eff[0]} -{eff[1]})" if eff else ""),
            "evs": sum(b[0x2C:0x32]), "ivs": " ".join(str((ivw >> 5 * i) & 31) for i in range(6))}


def boxes(p):
    """{box number: [(slot, Pokemon), ...]} for the occupied slots of boxes 1-19."""
    ptr = p.read32(STORAGE_PTR)
    raw = b"".join(p.range(ptr + 4 + o, 0x1000) for o in range(0, BOX_SIZE * IN_RAM, 0x1000))
    out = {}
    for i in range(BOX_SLOTS * 19):
        m = box_mon(raw[i * BOX_SIZE:(i + 1) * BOX_SIZE])
        if m:
            out.setdefault(i // BOX_SLOTS + 1, []).append((i % BOX_SLOTS + 1, m))
    return out


DIFFICULTY = os.environ.get("UNBOUND_DIFFICULTY", "vanilla")  # the run's difficulty (set by the runner for Expert)


def foe_evs(badges):
    """Do trainers' Pokemon likely carry 252 EVs in their two best stats? Expert: after 4 badges (and Ace Trainers,
    Experts, Victory Road, which the harness can't tell apart); Insane: after 2. Vanilla/Difficult: no."""
    return {"expert": badges >= 4, "insane": badges >= 2}.get(DIFFICULTY, False)


def stage(v, n):
    """A stat at stage N (-6..+6)."""
    return v * (2 + n) // 2 if n >= 0 else v * 2 // (2 - n)


def likely(species_name, level, evs_top2=False):
    """A foe's likely stats {HP Atk Def Spe SpA SpD}: IVs 31, neutral nature, no EVs, or 252 in its two best base
    stats (Expert: Ace Trainers, Experts and trainers after 4 badges). What a player can know: base stats and level."""
    bs, _ = base(NAMES["species"].index(species_name))
    ev = [0] * 6
    if evs_top2:
        for i in sorted(range(6), key=lambda i: -bs[i])[:2]:
            ev[i] = 252
    return dict(zip(STATS, calc(bs, [31] * 6, ev, level, 0)))


def damage(level, power, atk, dfn, stab, eff):
    """(min, max) damage of one hit, no crit: the game's formula with the 85-100% roll. Items, abilities, weather,
    screens and multi-hit are ignored (ponytail: add them when a fight turns on one)."""
    base_ = ((2 * level // 5 + 2) * power * atk // dfn) // 50 + 2
    return tuple(int(int(base_ * r // 100 * (1.5 if stab else 1)) * eff) for r in (85, 100))


def _selftest():
    # Ion (Metang L43, Calm, read live 2026-10-09): stored stats 118 72 101 73 72 88
    assert calc([60, 75, 100, 50, 55, 80], [16, 7, 0, 23, 31, 9], [70, 90, 99, 145, 62, 28], 43, 20) == [118, 72, 101, 73, 72, 88]
    assert nature_effect(3) == ("Atk", "SpA") and nature_effect(0) is None and nature_effect(13) == ("Spe", "SpA")
    assert base(NAMES["species"].index("Snorlax"))[1] == {"HP": 2}
    assert stage(100, 1) == 150 and stage(100, -1) == 66 and stage(100, 2) == 200
    assert damage(50, 80, 100, 100, True, 2.0) == (92, 110)  # base 37; rolls 31..37; x1.5 = 46..55; x2 = 92..110
    assert likely("Snorlax", 50)["HP"] == 235  # (2*160+31)*50//100 + 50 + 10
    assert exp_for(0, 13) == 2197 and level_from_exp(NAMES["species"].index("Pumpkaboo"), 2197) == 13


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    _selftest()
    print("stats self-check ok")
    from probe import Probe
    from state import PLAYER_PARTY, PLAYER_PARTY_COUNT
    p = Probe()
    n = p.read8(PLAYER_PARTY_COUNT)
    raw = p.range(PLAYER_PARTY, 100 * n)
    for k in range(n):
        print(detail(raw[k * 100:(k + 1) * 100]))
