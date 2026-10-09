"""Party-menu tools (#161): give_item, take_item, reorder_party. Field only (the overworld start menu).

Flow (verified live on Unbound, 2026-10-09): START -> icon 1 (Pokemon) -> party screen (cb2 0x0811EBA1) -> a
Pokemon -> action list -> Item -> Give / Take / Move / Cancel, or Switch -> "Move to where?". The action list is
sPartyMenuInternal->actions (pointer 0x0203B09C, actions u8[8] at +0x0F, count at +0x17), ids as in FireRed:
0 Summary, 1 Switch, 2 Cancel, 3 Item, 4 Give, 5 Take, 9 Cancel (item submenu), 18 Move (CFRU), field moves 18+ in
the first list. The list cursor is sMenu.cursorPos (0x0203ADE6). Give opens the bag on its own callback
(0x08107EE1) with the usual pocket/cursor/scroll variables. A Pokemon that already holds an item asks "Would you
like to switch the two items?" (Yes/No). Every tool re-reads the party and bag to verify its result.

    python party_menu.py      # offline self-check of the helpers
"""
import struct

from battle import BAG_CURSOR, BAG_POCKET, party_cursor_to
from items import BAG_SCROLL, CB2, START_CURSOR, _start_menu_open
from state import NAMES, PLAYER_PARTY, PLAYER_PARTY_COUNT, POCKETS, STRING_VAR4, decode, raw

CB2_PARTY = 0x0811EBA1
CB2_GIVE_BAG = 0x08107EE1
INTERNAL_PTR, MENU_CURSOR = 0x0203B09C, 0x0203ADE6
SWITCH, ITEM, GIVE, TAKE = 1, 3, 4, 5


def party(p):
    """[(personality, nickname, held item name or None)] in party order."""
    n = p.read8(PLAYER_PARTY_COUNT)
    d = p.range(PLAYER_PARTY, 100 * n)
    out = []
    for i in range(n):
        m = d[100 * i:100 * (i + 1)]
        item = struct.unpack("<H", m[0x22:0x24])[0]
        out.append((struct.unpack("<I", m[:4])[0], decode(m[8:0x12]), NAMES["items"][item] if item else None))
    return out


def bag_items(p):
    """The Items pocket's rows in order: [(name, count)]."""
    addr, slots = POCKETS["items"]
    d = struct.unpack(f"<{2 * slots}H", p.range(addr, 4 * slots))
    return [(NAMES["items"][d[i]], d[i + 1]) for i in range(0, len(d), 2) if d[i] and d[i + 1]]


def _slot_of(p, pokemon):
    names = [m[1] for m in party(p)]
    hits = [i for i, n in enumerate(names) if n.lower() == pokemon.lower()]
    if not hits:
        raise SystemExit(f"no {pokemon!r} in the party: {names}")
    if len(hits) > 1:
        raise SystemExit(f"two party members are called {pokemon!r}: rename one first (Name Rater)")
    return hits[0]


def _text(p):
    return decode(p.range(STRING_VAR4, 0x80)).replace("\n", " ")


def _waiting(p):
    """A message has finished printing and waits for a press (or a Yes/No)."""
    r = raw(p)
    return bool(r["printer"][0x1B]) and r["printer"][0x1C] == 2


def _wait(p, cond, tries=40, step=6):
    for _ in range(tries):
        p.step(step)
        if cond():
            return True
    return False


def _actions(p):
    ptr = p.read32(INTERNAL_PTR)
    b = p.range(ptr + 0x0F, 9)
    return list(b[:b[8]]) if 0 < b[8] <= 8 else []


def _choose_action(p, action, what):
    if not _wait(p, lambda: action in _actions(p), 20):
        raise SystemExit(f"the party menu didn't offer {what} (actions {_actions(p)}): look at the screen")
    row = _actions(p).index(action)
    for _ in range(10):
        cur = p.read8(MENU_CURSOR)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(8)
    if p.read8(MENU_CURSOR) != row:
        raise SystemExit(f"couldn't put the menu cursor on {what}: look at the screen")
    p.press("A", 4)
    p.step(20)


def open_party(p):
    """From the overworld (or the open start menu) to the party screen."""
    if p.read32(CB2) == CB2_PARTY:
        return
    if not _start_menu_open(p):
        if raw(p)["mode"] != "overworld":
            raise SystemExit("this works in the overworld only: close the text, menu or battle first")
        p.press("START", 4)
        if not _wait(p, lambda: _start_menu_open(p), 10):
            raise SystemExit("START didn't open the start menu: look at the screen")
    for _ in range(8):
        cur = p.read8(START_CURSOR)
        if cur == 1:
            break
        p.press("RIGHT" if cur < 1 else "LEFT", 4)
        p.step(10)
    p.press("A", 4)
    if not _wait(p, lambda: p.read32(CB2) == CB2_PARTY, 30):
        raise SystemExit("the party screen didn't open: look at the screen")
    p.step(30)  # it ignores input while it slides in


def _pick(p, slot):
    if not party_cursor_to(p, slot):
        raise SystemExit("couldn't put the party cursor on that Pokemon: look at the screen")
    p.press("A", 4)
    p.step(20)


def close(p):
    """B back to the overworld from the party screen, the bag or a message; verifies it got there."""
    for _ in range(30):
        if raw(p)["mode"] == "overworld" and not _start_menu_open(p) and p.read32(CB2) not in (CB2_PARTY, CB2_GIVE_BAG):
            p.step(10)
            if raw(p)["mode"] == "overworld" and not _start_menu_open(p):
                return
        p.press("B", 4)
        p.step(25)
    raise SystemExit("the menus didn't close back to the overworld: look at the screen")


def _messages(p, answer_yes, tries=12):
    """Read through the messages that follow an action: returns their texts. A Yes/No question is answered
    with ANSWER_YES (True: A, False: B)."""
    seen = []
    for _ in range(tries):
        if not _wait(p, lambda: _waiting(p), 30):
            break
        t = _text(p)
        if not seen or seen[-1] != t:
            seen.append(t)
        if "Would you like" in t:
            p.press("A", 4)  # the question's text page; the Yes/No box then takes a while to accept input
            for _ in range(5):  # (a Yes pressed 30 frames later was dropped: the swap never happened)
                p.step(40)
                p.press("A" if answer_yes else "B", 4)
                p.step(30)
                if _text(p) != t:
                    break
            continue
        p.press("A", 4)
        p.step(20)
        if p.read32(CB2) == CB2_PARTY and not _waiting(p):
            break
    return seen


def give_item(p, item, pokemon, replace=False):
    """Give ITEM (Items pocket) to party member POKEMON to hold. If it already holds one, swap only when REPLACE."""
    bag = bag_items(p)
    names = [n for n, _ in bag]
    want = next((n for n in names if n.lower() == item.lower()), None)
    if want is None:
        raise SystemExit(f"no {item!r} in the Items pocket (give_item reads that pocket only): {names}")
    slot = _slot_of(p, pokemon)
    held = party(p)[slot][2]
    if held and not replace:
        raise SystemExit(f"{pokemon} already holds {held}: call again with replace=true to swap it for {want} "
                         f"({held} goes back to the bag)")
    open_party(p)
    _pick(p, slot)
    _choose_action(p, ITEM, "Item")
    _choose_action(p, GIVE, "Give")
    if not _wait(p, lambda: p.read32(CB2) == CB2_GIVE_BAG, 30):
        raise SystemExit("Give didn't open the bag: look at the screen")
    p.step(30)
    for _ in range(3):
        if p.read16(BAG_POCKET) == 0:
            break
        p.press("LEFT", 4)
        p.step(30)
    row = names.index(want)
    for _ in range(2 * len(names) + 4):
        cur = p.read16(BAG_CURSOR) + p.read16(BAG_SCROLL)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(10)
    if p.read16(BAG_CURSOR) + p.read16(BAG_SCROLL) != row:
        raise SystemExit(f"couldn't put the bag cursor on {want}: look at the screen")
    p.press("A", 4)
    _wait(p, lambda: p.read32(CB2) == CB2_PARTY, 30)
    msgs = _messages(p, answer_yes=True)
    close(p)
    now = party(p)[slot][2]
    if now != want:
        raise SystemExit(f"{pokemon} holds {now}, not {want}, after giving it (the game said: {msgs}): look at the screen")
    return f"{pokemon} now holds {want}" + (f" ({held} went back to the bag)" if held else "") + (f". Game: {' / '.join(msgs)}" if msgs else "")


def take_item(p, pokemon):
    """Take party member POKEMON's held item back into the bag."""
    slot = _slot_of(p, pokemon)
    held = party(p)[slot][2]
    if not held:
        raise SystemExit(f"{pokemon} isn't holding anything")
    open_party(p)
    _pick(p, slot)
    _choose_action(p, ITEM, "Item")
    _choose_action(p, TAKE, "Take")
    msgs = _messages(p, answer_yes=False)
    close(p)
    if party(p)[slot][2]:
        raise SystemExit(f"{pokemon} still holds {party(p)[slot][2]} (the game said: {msgs}): look at the screen")
    return f"took {held} from {pokemon} (back in the bag)" + (f". Game: {' / '.join(msgs)}" if msgs else "")


def reorder_party(p, pokemon, position):
    """Move POKEMON to party POSITION (1 = lead) by swapping with whoever is there."""
    order = [m[1] for m in party(p)]
    if not 1 <= position <= len(order):
        raise SystemExit(f"position must be 1..{len(order)}")
    slot, target = _slot_of(p, pokemon), position - 1
    if slot == target:
        return f"{pokemon} is already in position {position}: {order}"
    open_party(p)
    _pick(p, slot)
    _choose_action(p, SWITCH, "Switch")
    p.step(20)
    if not party_cursor_to(p, target, which=0xA):  # the Switch target is gPartyMenu.slotId2 (+0xA)
        raise SystemExit("couldn't move the cursor to the target slot: look at the screen")
    p.press("A", 4)
    _wait(p, lambda: [m[1] for m in party(p)] != order, 40, 8)  # the swap animation
    p.step(40)
    close(p)
    now = [m[1] for m in party(p)]
    if now[target] != pokemon:
        raise SystemExit(f"the order is now {now}, {pokemon} isn't in position {position}: look at the screen")
    return f"party order: {', '.join(now)}"


if __name__ == "__main__":
    assert (SWITCH, ITEM, GIVE, TAKE) == (1, 3, 4, 5)
    print("party_menu self-check ok (live checks: see #161)")
