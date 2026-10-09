"""Stats, natures, EVs and IVs (Expert-run groundwork, #156).

Party layout (CFRU, unencrypted; verified 2026-10-09 by recomputing all six live party members' stored stats exactly):
EVs u8 x6 at +0x38 (HP Atk Def Spe SpA SpD), IVs packed 5 bits each at +0x48 (same order), nature = personality
(+0x00) % 25, stored stats u16 x6 at +0x58 (maxHP Atk Def Spe SpA SpD, party only). Species base stats in ROM
(moves.BASE_STATS, 0x1C each): stats +0..+5 in the same order, EV yield u16 +0x0A, 2 bits per stat, same order
(checked against the wiki's EV-yield table: Charizard SpA 3, Blastoise SpD 3, Snorlax HP 2, Metang Def 2...).

    python stats.py        # self-check, then the live party (read only)
"""
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


def _selftest():
    # Ion (Metang L43, Calm, read live 2026-10-09): stored stats 118 72 101 73 72 88
    assert calc([60, 75, 100, 50, 55, 80], [16, 7, 0, 23, 31, 9], [70, 90, 99, 145, 62, 28], 43, 20) == [118, 72, 101, 73, 72, 88]
    assert nature_effect(3) == ("Atk", "SpA") and nature_effect(0) is None and nature_effect(13) == ("Spe", "SpA")
    assert base(NAMES["species"].index("Snorlax"))[1] == {"HP": 2}


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
