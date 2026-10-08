"""Battle menu tools (#70): pick a move or run in one call, instead of walking the menus by hand.

Signals (verified, docs/learnings.md): the player battler's controller function is ACTION_MENU at the
Fight/Cube/Pokemon/Run menu and MOVE_MENU at the move list; both cursors are 2x2 grids, one byte per
battler. Text and prompts (level-ups, "forget a move?") are left to the agent: these tools never
press through them.
"""
import struct

from state import BATTLE_MONS, DISPLAYED_STRING_BATTLE, NAMES, decode, get_state, raw

CONTROLLERS = 0x03004FE0  # gBattlerControllerFuncs, u32 per battler
ACTION_MENU, MOVE_MENU = 0x0802E439, 0x0802EA11
ACTION_CURSOR = 0x02023FF8  # gActionSelectionCursor[battler]: 0 Fight, 1 Cube, 2 Pokemon, 3 Run
MOVE_CURSOR = 0x02023FFC  # gMoveSelectionCursor[battler]: move slot 0-3
BATTLE_TYPE_FLAGS = 0x02022B4C
DOUBLE = 0x1


def acting(p):
    """(battler, menu) for the player battler whose menu is up, or (None, None)."""
    for b in (0, 2):
        f = struct.unpack("<I", p.range(CONTROLLERS + 4 * b, 4))[0]
        if f in (ACTION_MENU, MOVE_MENU):
            return b, f
    return None, None


def wait_for_menu(p, frames=1500, seen=None):
    """Wait until a player menu is up, pressing A through plain battle text ("A wild Rattata appeared!"
    waits for a press in Unbound). Stops at a question ("forget a move?"): that's the agent's call.
    Returns (battler, menu) or (None, None) if the battle ended or a question is waiting."""
    for _ in range(frames // 12):
        r = raw(p)
        if r["mode"] != "battle":
            return None, None
        b, f = acting(p)
        if b is not None:
            return b, f
        if r["printer"][0x1B] and r["printer"][0x1C] == 2:  # text finished, waiting for a press
            text = decode(p.range(DISPLAYED_STRING_BATTLE, 0x100)).strip()
            if seen is not None and (not seen or seen[-1] != text):
                seen.append(text)
            if text.endswith("?"):
                return None, None
            p.press("A", 4)
        p.step(12)
    return None, None


def to_cursor(p, addr, target):
    """Move a 2x2 menu cursor (0 1 / 2 3) to TARGET."""
    for _ in range(4):
        cur = p.read8(addr)
        if cur == target:
            return True
        if cur % 2 != target % 2:
            p.press("RIGHT" if target % 2 else "LEFT", 4)
        else:
            p.press("DOWN" if target >= 2 else "UP", 4)
        p.step(6)
    return p.read8(addr) == target


def _settle(p):
    """After choosing: wait for the next menu, the end of the battle, or a prompt (agent's call)."""
    b, _ = wait_for_menu(p)
    r = raw(p)
    if r["mode"] != "battle":
        return "the battle is over" if r["mode"] in ("overworld", "other") else f"now in {r['mode']}"
    return "your next turn" if b is not None else "text or a prompt is waiting (advance_dialog / press_buttons)"


def fight(p, move):
    b, menu = wait_for_menu(p)
    if b is None:
        raise SystemExit("no move menu: text or a prompt is waiting, or the battle is over")
    if menu == MOVE_MENU:
        p.press("B", 4)
        p.step(10)
    moves = struct.unpack("<4H", p.range(BATTLE_MONS + 0x58 * b + 0x0C, 8))
    names = [NAMES["moves"][m] for m in moves if m]
    slot = next((i for i, m in enumerate(moves) if m and NAMES["moves"][m].lower() == move.lower()), None)
    if slot is None:
        raise SystemExit(f"{move!r} isn't one of this Pokemon's moves: {names}")
    if not to_cursor(p, ACTION_CURSOR + b, 0):
        raise SystemExit("couldn't put the cursor on Fight")
    p.press("A", 4)
    for _ in range(20):
        p.step(6)
        if acting(p)[1] == MOVE_MENU:
            break
    else:
        raise SystemExit("the move menu didn't open")
    if not to_cursor(p, MOVE_CURSOR + b, slot):
        raise SystemExit(f"couldn't put the cursor on {move}")
    p.press("A", 4)
    p.step(20)
    if p.read32(BATTLE_TYPE_FLAGS) & DOUBLE and acting(p)[0] is None and raw(p)["mode"] == "battle":
        p.press("A", 4)  # double battle: accept the default target
        p.step(20)
    return f"used {NAMES['moves'][moves[slot]]}; {_settle(p)}"


def run(p):
    b, menu = wait_for_menu(p)
    if b is None:
        raise SystemExit("no battle menu: text or a prompt is waiting, or the battle is over")
    if menu == MOVE_MENU:
        p.press("B", 4)
        p.step(10)
    if not to_cursor(p, ACTION_CURSOR + b, 3):
        raise SystemExit("couldn't put the cursor on Run")
    p.press("A", 4)
    p.step(60)
    return f"chose Run; {_settle(p)}"


PARTY_MENU = 0x0203B0A0  # gPartyMenu: +8 menuType/layout bits, +9 cursor slot (verified on the switch screen)
CB2_BATTLE_PARTY = 0x0811EBA1  # the party screen inside battle (forced or chosen switch)


def party_cursor_to(p, target):
    """Move the party-screen cursor to slot TARGET. Double layout: two columns (0 2 4 | 1 3 5), Cancel 7
    under the right; single layout: slot 0 on the left, 1-5 down the right."""
    for _ in range(12):
        b = p.range(PARTY_MENU, 10)
        slot, double = b[9], (b[8] >> 4) & 3 == 1
        if slot == target:
            return True
        if double:
            key = ("RIGHT" if target % 2 else "LEFT") if slot % 2 != target % 2 or slot > 5 else \
                  ("DOWN" if target > slot else "UP")
        else:
            key = "LEFT" if target == 0 else "RIGHT" if slot == 0 else ("DOWN" if target > slot else "UP")
        p.press(key, 4)
        p.step(8)
    return p.read8(PARTY_MENU + 9) == target


def switch_to(p, name):
    """Send NAME in: from the forced "Choose a Pokemon" screen, or from your battle menu (Pokemon)."""
    party = get_state(p)["party"]
    slot = next((i for i, m in enumerate(party) if m["name"].lower() == name.lower()), None)
    if slot is None:
        raise SystemExit(f"no {name!r} in the party: {[m['name'] for m in party]}")
    if party[slot]["hp"].startswith("0/"):
        raise SystemExit(f"{name} has fainted; healthy: {[m['name'] for m in party if not m['hp'].startswith('0/')]}")
    if p.read32(0x030030F4) != CB2_BATTLE_PARTY:
        b, menu = wait_for_menu(p)
        if b is None:
            raise SystemExit("no battle menu: text or a prompt is waiting, or the battle is over")
        if menu == MOVE_MENU:
            p.press("B", 4)
            p.step(10)
        if not to_cursor(p, ACTION_CURSOR + b, 2):
            raise SystemExit("couldn't put the cursor on Pokemon")
        p.press("A", 4)
        for _ in range(30):
            p.step(6)
            if p.read32(0x030030F4) == CB2_BATTLE_PARTY:
                break
        else:
            raise SystemExit("the party screen didn't open")
        p.step(20)
    if not party_cursor_to(p, slot):
        raise SystemExit(f"couldn't put the cursor on {name}")
    p.press("A", 4)  # opens Send Out / Shift
    p.step(30)
    p.press("A", 4)  # confirm
    p.step(60)
    if p.read32(0x030030F4) == CB2_BATTLE_PARTY:
        raise SystemExit(f"still on the party screen: {name} may already be in battle")
    return f"sent in {name}; {_settle(p)}"
