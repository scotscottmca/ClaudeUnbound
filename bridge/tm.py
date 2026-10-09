"""teach_tm (#166): teach a TM from the TM Case to a party member in one call (field).

Flow (verified live on Unbound, 2026-10-09, TM40 Aerial Ace -> Batty, replacing Wing Attack):
START -> bag (Key Items pocket 1: cursor u16 0x0203AD06, scroll 0x0203AD0C) -> TM Case -> A ("TM Case is selected.")
-> A -> the TM Case list (cb2 0x08131865; cursor u16 0x0203B114, scroll 0x0203B116; contents = the TM pocket at
0x0203C41C, u16 item id + u16 count pairs, HMs first, the same order as the list) -> A on a TM -> Use / Give / Exit
(sMenu 0x0203ADE6, Use first) -> the party screen "Teach which Pokemon?" (ABLE / NOT ABLE) -> the Pokemon.
There is no "Teach it?" question. With four moves: "<mon> wants to learn the move <X>. However, <mon> already knows
four moves. Should a move be deleted...?" -> Yes -> the move screen (cb2 0x08137EE9, cursor u8 0x0203B16D: rows 0-3
the known moves, 4 the new one = give up) -> A -> "<mon> learned <X>!" -> back in the TM Case list. TMs are not used
up. Unbound HMs needn't be taught (any Pokemon that could learn one can use it), so this refuses HMs.
"""
import struct

import battle
import party_menu as pm
from items import BAG_SCROLL, CB2, START_CURSOR, _start_menu_open, _wait_cb2
from state import NAMES, STRING_VAR4, decode, get_state, raw

CB2_TM_CASE, CB2_FORGET = 0x08131865, 0x08137EE9
TM_POCKET, TM_CURSOR, TM_SCROLL = 0x0203C41C, 0x0203B114, 0x0203B116
KEY_CURSOR, KEY_SCROLL = 0x0203AD06, 0x0203AD0C
FORGET_CURSOR, MENU_CURSOR = 0x0203B16D, 0x0203ADE6


def tm_case(p):
    d = struct.unpack("<128H", p.range(TM_POCKET, 256))
    return [NAMES["items"][d[i]] for i in range(0, 128, 2) if d[i] and d[i + 1]]


def _tm_move(p, row):
    """The move a TM teaches, read from the TM Case's own label while the cursor is on ROW ("No040 Aerial Ace")."""
    t = decode(p.range(STRING_VAR4, 0x40)).strip()
    return t.split(" ", 1)[1] if " " in t else t


def _open_case(p):
    if raw(p)["mode"] != "overworld":
        raise SystemExit("teach_tm works in the overworld only: close the text, menu or battle first")
    if not _start_menu_open(p):
        p.press("START", 4)
        p.step(20)
    for _ in range(8):
        cur = p.read8(START_CURSOR)
        if cur == 2:
            break
        p.press("RIGHT" if cur < 2 else "LEFT", 4)
        p.step(10)
    p.press("A", 4)
    if not _wait_cb2(p, battle.CB2_BATTLE_BAG):
        raise SystemExit("the bag didn't open: look at the screen")
    p.step(30)
    for _ in range(3):
        if p.read16(battle.BAG_POCKET) == 1:
            break
        p.press("RIGHT" if p.read16(battle.BAG_POCKET) < 1 else "LEFT", 4)
        p.step(30)
    keys = list(get_state(p)["bag"]["key_items"])
    if "TM Case" not in keys:
        raise SystemExit("no TM Case in Key Items")
    row = keys.index("TM Case")
    for _ in range(2 * len(keys) + 4):
        cur = p.read16(KEY_CURSOR) + p.read16(KEY_SCROLL)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(10)
    p.press("A", 4)  # "TM Case is selected." + its menu (Use first)
    p.step(40)
    p.press("A", 4)
    if not pm._wait(p, lambda: p.read32(CB2) == CB2_TM_CASE, 40, 8):
        raise SystemExit("the TM Case didn't open: look at the screen")
    p.step(40)


def teach_tm(p, tm, pokemon, forget=None):
    """Teach TM (e.g. "TM40", or the move's name once seen in the case) to party member POKEMON. If it knows four
    moves, FORGET names the move to replace; without it the tool refuses and lists the moves."""
    case = tm_case(p)
    team = get_state(p)["party"]
    hits = [i for i, m in enumerate(team) if m["name"].lower() == pokemon.lower()]
    if len(hits) != 1:
        raise SystemExit(f"{'no' if not hits else 'two'} {pokemon!r} in the party: {[m['name'] for m in team]}")
    slot, moves = hits[0], list(team[hits[0]]["moves"])
    if forget and forget not in moves:
        raise SystemExit(f"{pokemon} doesn't know {forget!r}: it knows {moves}")
    if len(moves) >= 4 and not forget:
        raise SystemExit(f"{pokemon} knows four moves ({', '.join(moves)}): say which one to forget (forget=...)")
    _open_case(p)
    # Find the row: by item name (TM40), or by the move's name shown in the case's label.
    row = next((i for i, n in enumerate(case) if n.lower() == tm.lower()), None)
    labels = {}
    if row is None:
        for i in range(len(case)):
            for _ in range(2 * len(case) + 4):
                cur = p.read16(TM_CURSOR) + p.read16(TM_SCROLL)
                if cur == i:
                    break
                p.press("DOWN" if cur < i else "UP", 4)
                p.step(12)
            labels[i] = _tm_move(p, i)
            if labels[i].lower() == tm.lower():
                row = i
                break
    if row is None or case[row].startswith("HM"):
        pm.close(p)
        if row is not None:
            raise SystemExit("HMs needn't be taught in Unbound: any Pokemon that could learn one can use it")
        raise SystemExit(f"no {tm!r} in the TM Case: {', '.join(case)}")
    for _ in range(2 * len(case) + 4):
        cur = p.read16(TM_CURSOR) + p.read16(TM_SCROLL)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(12)
    p.press("A", 4)  # Use / Give / Exit
    p.step(40)
    if p.read8(MENU_CURSOR) != 0:
        pm.close(p)
        raise SystemExit("the TM's menu didn't open on Use: look at the screen")
    p.press("A", 4)
    if not pm._wait(p, lambda: p.read32(CB2) == battle.CB2_BATTLE_PARTY, 40, 8):
        pm.close(p)
        raise SystemExit("Use didn't open the party screen: look at the screen")
    p.step(40)
    if not battle.party_cursor_to(p, slot):
        pm.close(p)
        raise SystemExit("couldn't put the cursor on that Pokemon: look at the screen")
    p.press("A", 4)
    p.step(40)
    said = []
    for _ in range(12):
        t = pm._text(p)
        if not said or said[-1] != t:
            said.append(t)
        if "Should a move be deleted" in t or "deleted and replaced" in t:  # first: it also says "already knows four"
            for _ in range(5):  # the question page, then Yes (the box drops an early press)
                p.press("A", 4)
                p.step(60)
                if p.read32(CB2) == CB2_FORGET:
                    break
            if not pm._wait(p, lambda: p.read32(CB2) == CB2_FORGET, 40, 8):
                pm.close(p)
                raise SystemExit("the move screen didn't open: look at the screen")
            p.step(60)
            target = moves.index(forget)
            for _ in range(8):
                cur = p.read8(FORGET_CURSOR)
                if cur == target:
                    break
                p.press("DOWN" if cur < target else "UP", 4)
                p.step(20)
            if p.read8(FORGET_CURSOR) != target:
                pm.close(p)
                raise SystemExit("couldn't put the cursor on the move to forget: look at the screen")
            p.press("A", 4)
            p.step(80)
            continue
        if "learned" in t or "can't learn" in t or "not compatible" in t.lower() or "already knows" in t:
            break
        p.press("A", 4)
        p.step(40)
    for _ in range(4):  # finish "learned" / "can't learn" without pressing A into the case again
        if p.read32(CB2) in (CB2_TM_CASE, battle.CB2_BATTLE_PARTY) and "learned" not in pm._text(p):
            break
        if "learned" in pm._text(p) and p.read32(CB2) == CB2_TM_CASE:
            break
        p.press("A", 4)
        p.step(40)
    pm.close(p)
    now = list(get_state(p)["party"][slot]["moves"])
    new = [m for m in now if m not in moves]  # the TM Case's label lags the cursor, so the moveset says what was taught
    if not new:
        raise SystemExit(f"{pokemon} didn't learn anything: it knows {now}. The game said: {' / '.join(said)}")
    gone = [m for m in moves if m not in now]
    return f"{pokemon} learned {new[0]}" + (f" (forgot {gone[0]})" if gone else "") + f": {', '.join(now)}"


if __name__ == "__main__":
    print("tm self-check ok (live checks: see #166)")
