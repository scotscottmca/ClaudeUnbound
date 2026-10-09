"""fly (Expert-run tools): fly to a town in one call.

Unbound rule (user, and verified live 2026-10-09): an HM's field move can be used by any party Pokemon that could
learn it, without teaching it. The party menu offers it only where it can be used: Batty (Crobat) got Fly (action
21) in Fallshore City's streets, not inside the Mart. Flow: party menu -> the Pokemon -> Fly -> the fly map
(cb2 0x080C08B5): cursor x u16 0x020081D0, y u16 0x020081D2, map section under it u8 0x020081E4. The region map's
section grid is in ROM at 0x083F2490, 22 wide (verified: 29/29 cursor positions matched the live section). Fly
spots (visited towns) flash with a wing icon; A on one flies there, A elsewhere does nothing.
"""
import glob
import os

import party_menu as pm
from items import CB2
from state import NAMES, get_state, raw

CB2_FLY_MAP = 0x080C08B5
CUR_X, CUR_Y, CUR_SEC = 0x020081D0, 0x020081D2, 0x020081E4
GRID, GRID_W, GRID_H = 0x083F2490, 22, 15
FLY_ACTION = 21  # party-menu action id for Fly (FireRed's field moves start at 18; 19 Flash, 24 Rock Smash)
_grid = None


def grid():
    global _grid
    if _grid is None:
        rom = open(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rom", "*.gba"))[0], "rb").read()
        o = GRID - 0x08000000
        _grid = [list(rom[o + y * GRID_W:o + (y + 1) * GRID_W]) for y in range(GRID_H)]
    return _grid


def section_id(name):
    for k, v in NAMES["mapsecs"].items():
        if v.lower() == name.lower():
            return int(k)
    return None


def _flyer(p):
    """Open the party menu on a Pokemon that offers Fly; returns its name (the action menu is left open)."""
    team = pm.party(p)
    pm.open_party(p)
    for slot in range(len(team)):
        pm._pick(p, slot)
        pm._wait(p, lambda: len(pm._actions(p)) > 0, 20)
        if FLY_ACTION in pm._actions(p):
            return team[slot][1]
        p.press("B", 4)
        p.step(30)
    pm.close(p)
    raise SystemExit("no party Pokemon can use Fly here: you need a Pokemon that could learn Fly (it needn't know "
                     "it) and HM02 in the TM Case, and you must be outdoors")


def fly(p, destination):
    """Fly to DESTINATION (a town or city name, e.g. "Dresco Town") from outdoors."""
    target = section_id(destination)
    if target is None:
        towns = sorted({v for v in NAMES["mapsecs"].values() if v.endswith(("Town", "City"))})
        raise SystemExit(f"unknown place {destination!r}; towns and cities: {', '.join(towns)}")
    cells = [(x, y) for y, row in enumerate(grid()) for x, v in enumerate(row) if v == target]
    if not cells:
        raise SystemExit(f"{destination} isn't on the fly map")
    s = get_state(p)
    if s["map"]["name"].lower() == destination.lower() and s["map"].get("kind") in ("town", "city"):
        return f"you're already in {destination}"
    if raw(p)["mode"] != "overworld":
        raise SystemExit("fly works in the overworld only: close the text, menu or battle first")
    if s["map"].get("kind") not in ("town", "city", "route"):
        raise SystemExit(f"you can't fly from here ({s['map'].get('kind')}): go outside first")
    who = _flyer(p)
    pm._choose_action(p, FLY_ACTION, "Fly")
    if not pm._wait(p, lambda: p.read32(CB2) == CB2_FLY_MAP, 40, 8):
        raise SystemExit("Fly didn't open the fly map: look at the screen")
    p.step(40)
    x, y = p.read16(CUR_X), p.read16(CUR_Y)
    tx, ty = min(cells, key=lambda c: abs(c[0] - x) + abs(c[1] - y))
    for _ in range(GRID_W + GRID_H + 6):
        x, y = p.read16(CUR_X), p.read16(CUR_Y)
        if (x, y) == (tx, ty):
            break
        p.press("RIGHT" if x < tx else "LEFT" if x > tx else "DOWN" if y < ty else "UP", 4)
        p.step(12)
    if p.read8(CUR_SEC) != target:
        raise SystemExit(f"couldn't put the fly-map cursor on {destination}: look at the screen")
    before = (s["map"]["group"], s["map"]["num"])
    p.press("A", 4)
    p.step(60)
    if p.read32(CB2) == CB2_FLY_MAP:  # A did nothing: not a fly spot yet
        for _ in range(6):
            if raw(p)["mode"] == "overworld":
                break
            p.press("B", 4)
            p.step(40)
        pm.close(p)
        raise SystemExit(f"{destination} isn't a fly spot yet: you fly only to towns you have visited "
                         "(they flash with a wing icon on the fly map)")
    for _ in range(60):  # the flight and the landing
        p.step(10)
        if raw(p)["mode"] == "overworld":
            now = get_state(p)
            if (now["map"]["group"], now["map"]["num"]) != before:
                p.step(30)
                break
    now = get_state(p)
    if now["map"]["name"].lower() != destination.lower():
        raise SystemExit(f"after flying you're in {now['map']['name']} {now['pos']}, not {destination}: look at the screen")
    return f"{who} flew you to {destination}: now at {now['map']['name']} {now['pos']} (map {now['map']['group']}/{now['map']['num']})"


if __name__ == "__main__":
    g = grid()
    assert g[13][6] == section_id("Fallshore City") and g[13][5] == section_id("Route 10"), (g[13][5], g[13][6])
    print("fly self-check ok")
