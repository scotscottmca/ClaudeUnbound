"""Move data and type matchups (#62), read from the run's ROM.

    python moves.py        # self-check against moves seen in this game
"""
import os

from state import NAMES, TYPES

MOVES = 0x08900000  # CFRU gBattleMoves: 12 bytes each (effect, power, type, accuracy, pp, chance,
#                     target, priority, flags, z-power, split, z-effect); found by searching for Pound
SPLIT = {0: "physical", 1: "special", 2: "status"}

# Gen 6+ chart (CFRU), attacker -> {defender: multiplier}; anything missing is 1x.
_N, _FI, _FL, _PO, _GR, _RO, _BU, _GH, _ST, _FR, _WA, _GA, _EL, _PS, _IC, _DR, _DA, _FA = (
    0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 23)
CHART = {
    _N: {_RO: .5, _GH: 0, _ST: .5},
    _FI: {_N: 2, _FL: .5, _PO: .5, _RO: 2, _BU: .5, _GH: 0, _ST: 2, _PS: .5, _IC: 2, _DA: 2, _FA: .5},
    _FL: {_FI: 2, _RO: .5, _BU: 2, _ST: .5, _GA: 2, _EL: .5},
    _PO: {_PO: .5, _GR: .5, _RO: .5, _GH: .5, _ST: 0, _GA: 2, _FA: 2},
    _GR: {_FL: 0, _PO: 2, _RO: 2, _BU: .5, _ST: 2, _FR: 2, _GA: .5, _EL: 2},
    _RO: {_FI: .5, _FL: 2, _GR: .5, _BU: 2, _ST: .5, _FR: 2, _IC: 2},
    _BU: {_FI: .5, _FL: .5, _PO: .5, _GH: .5, _ST: .5, _FR: .5, _GA: 2, _PS: 2, _DA: 2, _FA: .5},
    _GH: {_N: 0, _GH: 2, _PS: 2, _DA: .5},
    _ST: {_RO: 2, _ST: .5, _FR: .5, _WA: .5, _EL: .5, _IC: 2, _FA: 2},
    _FR: {_RO: .5, _BU: 2, _ST: 2, _FR: .5, _WA: .5, _GA: 2, _IC: 2, _DR: .5},
    _WA: {_GR: 2, _RO: 2, _FR: 2, _WA: .5, _GA: .5, _DR: .5},
    _GA: {_FL: .5, _PO: .5, _GR: 2, _RO: 2, _BU: .5, _ST: .5, _FR: .5, _WA: 2, _GA: .5, _DR: .5},
    _EL: {_FL: 2, _GR: 0, _WA: 2, _GA: .5, _EL: .5, _DR: .5},
    _PS: {_FI: 2, _PO: 2, _ST: .5, _PS: .5, _DA: 0},
    _IC: {_FL: 2, _GR: 2, _ST: .5, _FR: .5, _WA: .5, _GA: 2, _IC: .5, _DR: 2},
    _DR: {_ST: .5, _DR: 2, _FA: 0},
    _DA: {_FI: .5, _GH: 2, _PS: 2, _DA: .5, _FA: .5},
    _FA: {_FI: 2, _PO: .5, _ST: .5, _FR: .5, _DR: 2, _DA: 2},
}
TYPE_ID = {v: k for k, v in TYPES.items()}
_rom = None


def _data():
    global _rom
    if _rom is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "run", "Unbound.gba"), "rb") as f:
            _rom = f.read()
    return _rom


def move(move_id):
    o = MOVES - 0x08000000 + 12 * move_id
    b = _data()[o:o + 12]
    return {"name": NAMES["moves"][move_id], "type": TYPES.get(b[2], f"type {b[2]}"), "power": b[1],
            "accuracy": b[3], "split": SPLIT.get(b[10], b[10])}


def effectiveness(attack_type, defender_types):
    """Multiplier of an attack type against a list of defender type names."""
    a = TYPE_ID[attack_type]
    m = 1.0
    for t in defender_types:
        m *= CHART.get(a, {}).get(TYPE_ID[t], 1)
    return m


def move_id(name):
    return NAMES["moves"].index(name)


BASE_STATS = 0x099E0C9C  # 0x1C per species; types at +6/+7 (docs/addresses.md)


def species_types(species_name):
    o = BASE_STATS - 0x08000000 + 0x1C * NAMES["species"].index(species_name)
    t1, t2 = _data()[o + 6], _data()[o + 7]
    return [TYPES[t1]] + ([TYPES[t2]] if t2 != t1 else [])


def _best(move_names, foe_types):
    hits = [effectiveness(move(move_id(m))["type"], foe_types) for m in move_names if move(move_id(m))["power"]]
    return max(hits, default=0)


def matchups(state):
    """Battle hints: my active Pokemon's moves vs the foe, and how each benched Pokemon would fare."""
    b = state.get("battle")
    if not b:
        return None
    foes = [x for x in b["battlers"] if x["side"] == "opponent" and not x["hp"].startswith("0/")]
    if not foes:
        return None
    foe = foes[0]
    out = {"vs": f"{foe['species']} ({'/'.join(foe['types'])})", "my_moves": [], "switch_options": []}
    import stats  # here: stats imports moves
    trainer = int(b.get("flags", "0"), 16) & 0x8  # BATTLE_TYPE_TRAINER
    foe_stats = stats.likely(foe["species"], foe["level"], bool(trainer) and stats.foe_evs(state.get("badges") or 0))         if "level" in foe else None
    foe_hp, foe_max = map(int, foe["hp"].split("/"))
    for mine in (x for x in b["battlers"] if x["side"] == "player"):
        st, sg = (mine.get("stats") or {}) if foe_stats else {}, mine.get("stages") or {}
        mine_types = species_types(mine["species"]) if st else []
        for name in mine.get("moves", {}):
            m = move(move_id(name))
            eff = effectiveness(m["type"], foe["types"]) if m["power"] else None
            row = {"user": mine["name"], "move": name, "type": m["type"], "power": m["power"], "split": m["split"],
                   "effectiveness": eff}
            if m["power"] > 1 and st and m["split"] in ("physical", "special"):
                a_, d_ = ("Atk", "Def") if m["split"] == "physical" else ("SpA", "SpD")
                lo, hi = stats.damage(mine["level"], m["power"], stats.stage(st[a_], sg.get(a_, 0)), foe_stats[d_],
                                      m["type"] in mine_types, eff)
                pct = lambda v: round(100 * v / foe_max)  # noqa: E731
                row["damage"] = (f"~{pct(lo)}-{pct(hi)}% of its max HP" + (" (likely KO)" if lo >= foe_hp else
                                 " (KO on a high roll)" if hi >= foe_hp else ""))
            out["my_moves"].append(row)
        if st:
            mine_spe, foe_spe = stats.stage(st["Spe"], sg.get("Spe", 0)), foe_stats["Spe"]
            out.setdefault("speed", []).append(
                f"{mine['name']} speed {mine_spe} vs {foe['species']} likely {foe_spe}: "
                + ("you move first" if mine_spe > foe_spe else "it likely moves first" if mine_spe < foe_spe else "a tie"))
    out["note"] = ("Damage is an estimate from the foe's base stats and level (perfect IVs, neutral nature"
                   + (", 252 EVs in its two best stats" if trainer and stats.foe_evs(state.get("badges") or 0) else "")
                   + "); abilities, items, weather and crits aren't counted.")
    active = {x["name"] for x in b["battlers"] if x["side"] == "player"}
    for p in state["party"]:
        if p["name"] in active or p["hp"].startswith("0/"):
            continue
        types = species_types(p["species"])
        out["switch_options"].append({
            "name": p["name"], "types": types, "hp": p["hp"],
            "best_attack": _best(p["moves"], foe["types"]),
            # how hard the foe's same-type attacks would hit this Pokemon
            "takes_from_foe_types": max(effectiveness(t, types) for t in foe["types"])})
    return out


if __name__ == "__main__":
    seen = {"Pound": ("Normal", 40, "physical"), "Rock Throw": ("Rock", 50, "physical"),
            "Astonish": ("Ghost", 30, "physical"), "Bite": ("Dark", 60, "physical"),
            "Leer": ("Normal", 0, "status"), "Sandstorm": ("Rock", 0, "status")}
    for name, (t, pw, sp) in seen.items():
        m = move(move_id(name))
        assert (m["type"], m["power"], m["split"]) == (t, pw, sp), (name, m)
    assert effectiveness("Rock", ["Ice"]) == 2 and effectiveness("Ground", ["Flying"]) == 0
    assert effectiveness("Electric", ["Water", "Flying"]) == 4 and effectiveness("Dragon", ["Fairy"]) == 0
    assert species_types("Larvitar") == ["Rock", "Ground"] and species_types("Snorunt") == ["Ice"]
    fake = {"party": [{"name": "Chomp", "species": "Gible", "hp": "30/37", "moves": {"Tackle": 35}},
                      {"name": "Rocky", "species": "Larvitar", "hp": "20/32", "moves": {"Rock Throw": 15, "Leer": 30}}],
            "battle": {"battlers": [
                {"side": "player", "name": "Chomp", "species": "Gible", "hp": "30/37", "moves": {"Tackle": 35}},
                {"side": "opponent", "name": "Snorunt", "species": "Snorunt", "hp": "20/27", "types": ["Ice"]}]}}
    mu = matchups(fake)
    assert mu["switch_options"][0]["best_attack"] == 2 and mu["switch_options"][0]["takes_from_foe_types"] == 2, mu
    print("moves ok")
