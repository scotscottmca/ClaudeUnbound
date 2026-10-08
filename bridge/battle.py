"""Battle menu tools (#70): pick a move or run in one call, instead of walking the menus by hand.

Signals (verified, docs/learnings.md): the player battler's controller function is ACTION_MENU at the
Fight/Cube/Pokemon/Run menu and MOVE_MENU at the move list; both cursors are 2x2 grids, one byte per
battler. Text and prompts (level-ups, "forget a move?") are left to the agent: these tools never
press through them.
"""
import struct

from naming import NAMING_CB2
from state import BATTLE_MONS, DISPLAYED_STRING_BATTLE, NAMES, PLAYER_PARTY, STRING_VAR4, decode, get_state, raw

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
    if p.read32(0x030030F4) == CB2_BATTLE_PARTY:
        return "a Pokemon fainted: choose its replacement with switch_to"
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
        # Unbound's battle party screen is always the two-column grid (0 1 / 2 3 / 4 5, Cancel 7), even when the
        # layout byte says single: walked on a single trainer battle with five Pokemon (slots 2-4 unreachable before).
        slot, double = b[9], True
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


def _party_slot(p, name):
    party = get_state(p)["party"]
    # Who's in battle, by personality (gBattleMons +0x48 vs party +0): independent of party order and names.
    out = {p.read32(BATTLE_MONS + 0x58 * b + 0x48) for b in ((0, 2) if p.read32(BATTLE_TYPE_FLAGS) & DOUBLE else (0,))}
    ok = [not m["hp"].startswith("0/") and p.read32(PLAYER_PARTY + 100 * i) not in out for i, m in enumerate(party)]
    # Names can repeat (two uncaught-nickname Makuhita): take one that can be sent in.
    matches = [i for i, m in enumerate(party) if m["name"].lower() == name.lower()]
    if not matches:
        raise SystemExit(f"no {name!r} in the party: {[m['name'] for m in party]}")
    slot = next((i for i in matches if ok[i]), None)
    if slot is None:
        raise SystemExit(f"{name} has fainted or is already in battle; you can send in: "
                         f"{[m['name'] for i, m in enumerate(party) if ok[i]] or 'nobody'}")
    return slot


def switch_to(p, name):
    """Send NAME in: from the forced "Choose a Pokemon" screen, or from your battle menu (Pokemon).
    While the battle party screen is open, gPlayerParty is rearranged into battle order (the menu's rows,
    active Pokemon first); otherwise it's in field order. So the row is looked up once the screen is open."""
    _party_slot(p, name)  # fail early, before opening anything
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
    slot = _party_slot(p, name)  # menu row: the party is in battle order now
    if not party_cursor_to(p, slot):
        raise SystemExit(f"couldn't put the cursor on {name}")
    p.press("A", 4)  # opens Send Out / Shift
    p.step(30)
    p.press("A", 4)  # confirm
    p.step(60)
    if p.read32(0x030030F4) == CB2_BATTLE_PARTY:
        raise SystemExit(f"still on the party screen: the game refused {name} (already in battle, or your "
                         "Pokemon is trapped, e.g. by Mean Look): look at the screen")
    return f"sent in {name}; {_settle(p)}"


CB2_BATTLE_BAG = 0x08107EE1  # the bag opened from the battle menu (0x08107F11 for a frame while it opens)
BAG_POCKET = 0x0203AD02  # u16 open pocket: 0 Items, 1 Key Items, 2 Poke Balls (the last; RIGHT stops there)
BAG_CURSOR = 0x0203AD04  # u16 cursor row per pocket
BALL_POCKET, BALL_SLOTS = 0x0203C354, 50  # u16 item, u16 count; the bag lists the non-empty slots in order
TRAINER = 0x8


def _plain(s):
    return s.replace("é", "e").lower()


def throw_ball(p, ball="Poké Ball"):
    """Wild battle: Bag -> Poke Balls -> BALL -> Use, then follow the throw to its result."""
    if p.read32(BATTLE_TYPE_FLAGS) & TRAINER and raw(p)["mode"] == "battle":
        raise SystemExit("this is a trainer battle: you can't catch a trainer's Pokemon")
    pocket = struct.unpack(f"<{2 * BALL_SLOTS}H", p.range(BALL_POCKET, 4 * BALL_SLOTS))
    balls = [NAMES["items"][pocket[i]] for i in range(0, len(pocket), 2) if pocket[i] and pocket[i + 1]]
    row = next((i for i, n in enumerate(balls) if _plain(n) == _plain(ball)), None)
    if row is None:
        raise SystemExit(f"no {ball!r} in the bag; balls: {balls or 'none'}")
    b, menu = wait_for_menu(p)
    if b is None:
        raise SystemExit("no battle menu: text or a prompt is waiting, or the battle is over")
    if menu == MOVE_MENU:
        p.press("B", 4)
        p.step(10)
    if not to_cursor(p, ACTION_CURSOR + b, 1):
        raise SystemExit("couldn't put the cursor on the bag")
    p.press("A", 4)
    for _ in range(30):
        p.step(6)
        if p.read32(0x030030F4) == CB2_BATTLE_BAG:
            break
    else:
        raise SystemExit("the bag didn't open")
    p.step(30)  # the bag ignores input while it slides in
    for _ in range(3):
        if p.read16(BAG_POCKET) == 2:
            break
        p.press("RIGHT", 4)
        p.step(30)
    for _ in range(len(balls) + 2):
        cur = p.read16(BAG_CURSOR + 4)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(10)
    # ponytail: the list's scroll offset isn't read; past a screenful of ball types the check below catches it.
    p.press("A", 4)  # opens Use / Cancel, cursor on Use
    p.step(30)
    if _plain(decode(p.range(STRING_VAR4, 0x40))) != _plain(f"{balls[row]} is\nselected."):
        raise SystemExit(f"the bag didn't select {balls[row]} (pocket {p.read16(BAG_POCKET)}, "
                         f"row {p.read16(BAG_CURSOR + 4)}): look at the screen")
    p.press("A", 4)
    return f"threw a {balls[row]}; {_after_throw(p)}"


def _after_throw(p):
    """Follow the throw: A through plain text and the post-capture exp/level-up/Pokedex screens; stop at the
    nickname question, any other question, the next turn, or the end of the battle."""
    caught, idle = None, 0
    for _ in range(30):  # the bag closes first (two callbacks, a few frames)
        p.step(6)
        if raw(p)["mode"] == "battle":
            break
    for _ in range(300):
        p.step(10)
        r = raw(p)
        if p.read32(0x030030F4) == NAMING_CB2:
            return f"caught {caught}; on the naming screen: use type_name"
        if r["mode"] != "battle":
            return (f"caught {caught}; the battle is over" if caught else
                    f"the battle is over (now {r['mode']}): look at the screen")
        if acting(p)[0] is not None:
            return "it broke free; your next turn" if not caught else f"caught {caught}; your next turn?"
        text = decode(p.range(DISPLAYED_STRING_BATTLE, 0x100)).strip()
        if "was caught" in text:
            caught = NAMES["species"][p.read16(BATTLE_MONS + 0x58)]  # the wild foe, battler 1
        active, state = r["printer"][0x1B], r["printer"][0x1C]
        if "nickname" in text.lower() and not active:
            return (f"caught {caught}; the game asks {text!r}: answer Yes (A) and call type_name, "
                    "or No (DOWN, A)")
        if text.endswith("?") and (not active or state == 2) and not text.startswith("What will"):  # the menu's own
            return f"{'caught ' + caught if caught else 'it broke free'}; a question is waiting: {text!r}"
        if active and state == 2:
            p.press("A", 4)
            idle = 0
            continue
        idle = 0 if active else idle + 1
        # After a capture, the level-up stat box and the Pokedex page wait for A with no text printing.
        if caught and idle >= 6 and ("grew to" in text or "Pokédex" in text):
            p.press("A", 4)
            idle = 0
        elif idle >= 60:
            raise SystemExit(f"nothing has happened for 10 s after the throw (text {text!r}): look at the screen")
    raise SystemExit("the throw didn't resolve: look at the screen")


if __name__ == "__main__":
    # Self-check on a wild battle savestate with a Poke Ball: python battle.py STATE [PORT]
    import sys
    from probe import Probe
    p = Probe(port=int(sys.argv[2]) if len(sys.argv) > 2 else 8888)
    p.load(sys.argv[1])
    p.step(2)
    try:
        throw_ball(p, "Master Ball")
        raise AssertionError("threw a ball the bag doesn't hold")
    except SystemExit as e:
        assert "no 'Master Ball'" in str(e), e
    out = throw_ball(p, "Poke Ball")
    print(out)
    assert out.startswith("threw a Poké Ball; ") and ("caught" in out or "broke free" in out), out
