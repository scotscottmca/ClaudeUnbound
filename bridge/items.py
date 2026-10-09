"""use_item (#101): use a healing item from the bag on a party member in one call, in the field or in battle.

    python items.py OVERWORLD_STATE BATTLE_STATE [PORT]    # self-check (see __main__)

Field: START -> Cube (start-menu icon 2) -> Items pocket -> item -> Use -> party screen -> target; the screen
then stays on "Use on which Pokemon?", so B backs out through the bag and start menu. Battle: action menu Cube
-> the same bag and party screen; the item uses up the turn. Addresses: docs/addresses.md (Bag, start menu).
"""
import struct

from battle import (ACTION_CURSOR, BAG_CURSOR, BAG_POCKET, CB2_BATTLE_BAG, CB2_BATTLE_PARTY, MOVE_MENU, _plain,
                    _settle, party_cursor_to, to_cursor, wait_for_menu)
from state import CB2_BATTLE, G_MAIN, NAMES, PLAYER_PARTY, PLAYER_PARTY_COUNT, POCKETS, STRING_VAR4, decode, raw

CB2 = G_MAIN + 4
BAG_SCROLL = 0x0203AD0A  # u16 list scroll per pocket; the selected row is cursor + scroll
START_CURSOR = 0x020370F4  # u8 start-menu icon: 0 Pokedex, 1 Pokemon List, 2 Cube (the bag)
TASKS = 0x03005090  # gTasks: 16 x 0x28, func +0, isActive +4
START_MENU_TASK = 0x0806F1F1  # active exactly while the start menu is open

HP, STATUS, BOTH, REVIVE = "hp", "status", "both", "revive"
HEALING = {n: HP for n in ("Potion", "Super Potion", "Hyper Potion", "Max Potion", "Fresh Water", "Soda Pop",
                           "Lemonade", "Moomoo Milk", "EnergyPowder", "Energy Root", "Berry Juice")}
HEALING |= {n: STATUS for n in ("Antidote", "Burn Heal", "Ice Heal", "Awakening", "Parlyz Heal", "Full Heal",
                                "Heal Powder", "Lava Cookie")}
HEALING |= {"Full Restore": BOTH, "Revive": REVIVE, "Max Revive": REVIVE, "Revival Herb": REVIVE}
# ponytail: Items pocket only; berries (Oran, Sitrus) live in a pocket not mapped yet.


def _items(p):
    addr, slots = POCKETS["items"]
    d = struct.unpack(f"<{2 * slots}H", p.range(addr, 4 * slots))
    return [NAMES["items"][d[i]] for i in range(0, len(d), 2) if d[i] and d[i + 1]]  # the bag's rows, in order


def _party(p):
    """[(personality, name, hp, max_hp, status)] in gPlayerParty's current order."""
    n = p.read8(PLAYER_PARTY_COUNT)
    d = p.range(PLAYER_PARTY, 100 * n)
    out = []
    for i in range(n):
        m = d[100 * i:100 * (i + 1)]
        hp, mx = struct.unpack("<HH", m[0x56:0x5A])
        out.append((struct.unpack("<I", m[:4])[0], decode(m[8:0x12]), hp, mx, struct.unpack("<I", m[0x50:0x54])[0]))
    return out


def _why_not(kind, hp, mx, status):
    """Why KIND of item would do nothing for this Pokemon, or None if it helps."""
    if kind == REVIVE:
        return None if hp == 0 else "isn't fainted"
    if hp == 0:
        return "has fainted (use a Revive)"
    if kind == HP and hp == mx:
        return "is already at full HP"
    if kind == STATUS and not status:
        return "has no status condition"
    if kind == BOTH and hp == mx and not status:
        return "is already at full HP with no status condition"
    return None


def _start_menu_open(p):
    t = p.range(TASKS, 16 * 0x28)
    return any(t[i * 0x28 + 4] and struct.unpack("<I", t[i * 0x28:i * 0x28 + 4])[0] == START_MENU_TASK
               for i in range(16))


def _wait_cb2(p, cb2, tries=30):
    for _ in range(tries):
        p.step(6)
        if p.read32(CB2) == cb2:
            return True
    return False


def _choose(p, row, item, pid):
    """In the open bag: Items pocket -> ROW -> Use -> party screen -> the Pokemon with personality PID.
    Returns the game's message after the item takes effect."""
    p.step(30)  # the bag ignores input while it slides in
    for _ in range(3):
        if p.read16(BAG_POCKET) == 0:
            break
        p.press("LEFT", 4)
        p.step(30)
    for _ in range(2 * row + 4):  # the list wraps; walk straight there
        cur = p.read16(BAG_CURSOR) + p.read16(BAG_SCROLL)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(10)
    p.press("A", 4)  # Use / (Give / Toss) / Cancel, cursor on Use
    p.step(30)
    if _plain(decode(p.range(STRING_VAR4, 0x40))) != _plain(f"{item} is\nselected."):
        raise SystemExit(f"the bag didn't select {item} (pocket {p.read16(BAG_POCKET)}, row "
                         f"{p.read16(BAG_CURSOR) + p.read16(BAG_SCROLL)}): look at the screen")
    p.press("A", 4)
    if not _wait_cb2(p, CB2_BATTLE_PARTY):
        raise SystemExit(f"Use didn't open the party screen (the game says {decode(p.range(STRING_VAR4, 0x60))!r}): "
                         "look at the screen")
    p.step(20)
    # While this screen is open in battle the party is in battle order: find the row by personality.
    slot = next(i for i, m in enumerate(_party(p)) if m[0] == pid)
    if not party_cursor_to(p, slot):
        raise SystemExit("couldn't put the party cursor on the target: look at the screen")
    p.press("A", 4)
    for _ in range(40):  # HP bar animation, then the message
        p.step(6)
        r = raw(p)
        if r["printer"][0x1B] and r["printer"][0x1C]:
            break
    else:
        raise SystemExit("no message after choosing the target: look at the screen")
    p.step(30)
    return decode(p.range(STRING_VAR4, 0x80)).replace("\n", " ")


def use_item(p, item, pokemon):
    """Use healing ITEM on party member POKEMON (by nickname), in the overworld or in your battle turn."""
    kind = next((k for n, k in HEALING.items() if _plain(n) == _plain(item)), None)
    bag = _items(p)
    held = sorted({n for n in bag if n in HEALING})
    if kind is None:
        raise SystemExit(f"use_item handles healing items only (potions, status cures, revives; not berries "
                         f"yet); you hold: {held or 'none'}")
    name = next(n for n in HEALING if _plain(n) == _plain(item))
    if name not in bag:
        raise SystemExit(f"no {name} in the bag; healing items: {held or 'none'}")
    party = _party(p)
    matches = [m for m in party if m[1].lower() == pokemon.lower()]
    if not matches:
        raise SystemExit(f"no {pokemon!r} in the party: {[m[1] for m in party]}")
    target = next((m for m in matches if not _why_not(kind, *m[2:])), None)  # duplicate names: one it helps
    if target is None:
        raise SystemExit(f"{name} would do nothing: {pokemon} {_why_not(kind, *matches[0][2:])}")
    pid, before = target[0], f"{target[2]}/{target[3]}"

    if p.read32(CB2) == CB2_BATTLE:
        b, menu = wait_for_menu(p)
        if b is None:
            raise SystemExit("no battle menu: text or a prompt is waiting, or the battle is over")
        if menu == MOVE_MENU:
            p.press("B", 4)
            p.step(10)
        if not to_cursor(p, ACTION_CURSOR + b, 1):
            raise SystemExit("couldn't put the cursor on the bag")
        p.press("A", 4)
        if not _wait_cb2(p, CB2_BATTLE_BAG):
            raise SystemExit("the bag didn't open (items may not be allowed in this battle): look at the screen")
        msg = _choose(p, bag.index(name), name, pid)
        p.press("A", 4)  # closes the message; the party screen closes (0x080777E9) and the turn runs
        _wait_cb2(p, CB2_BATTLE)
        after = next(f"{m[2]}/{m[3]}" for m in _party(p) if m[0] == pid)
        return f"{name} on {target[1]}: {before} -> {after} ({msg}); {_settle(p)}"

    if not _start_menu_open(p):
        if p.read32(CB2) == CB2_BATTLE_PARTY:
            raise SystemExit("the party screen is open: on a forced switch, choose with switch_to first")
        if raw(p)["mode"] != "overworld":
            raise SystemExit("use_item works in the overworld or at your battle menu; close the text or menu first")
        p.press("START", 4)
        p.step(20)
        if not _start_menu_open(p):
            raise SystemExit("START didn't open the start menu: look at the screen")
    for _ in range(8):
        cur = p.read8(START_CURSOR)
        if cur == 2:
            break
        p.press("RIGHT" if cur < 2 else "LEFT", 4)
        p.step(10)
    p.press("A", 4)
    if not _wait_cb2(p, CB2_BATTLE_BAG):  # the field bag runs on the same callback as the battle one
        raise SystemExit("the bag didn't open: look at the screen")
    msg = _choose(p, bag.index(name), name, pid)
    after = next(f"{m[2]}/{m[3]}" for m in _party(p) if m[0] == pid)
    p.press("A", 4)  # closes the message; the party screen asks "Use on which Pokemon?" again
    p.step(20)
    for _ in range(40):  # B: party screen -> bag -> start menu -> overworld
        if raw(p)["mode"] == "overworld":
            p.step(20)  # the bag hands back to the field (0x08056809, then CB2_Overworld) ~6 frames before
            if raw(p)["mode"] == "overworld" and not _start_menu_open(p):  # the start menu task restarts
                return f"{name} on {target[1]}: {before} -> {after} ({msg})"
            continue
        screen = (p.read32(CB2), _start_menu_open(p))
        if screen[0] not in (CB2_BATTLE_PARTY, CB2_BATTLE_BAG) and not screen[1]:
            p.step(6)  # between screens (the bag closing back to the start menu): press nothing
            continue
        p.press("B", 4)
        for _ in range(20):  # a B pressed while a screen slides in or out is dropped: wait for the change
            p.step(6)
            if (p.read32(CB2), _start_menu_open(p)) != screen:
                break
        p.step(20)
    raise SystemExit(f"{name} on {target[1]}: {before} -> {after} ({msg}), but the menus didn't close "
                     "back to the overworld: look at the screen")


# Non-healing items used on a party member from the field bag (#166): vitamins (EVs), evolution stones, Rare Candy.
# The bag -> Use -> party flow is use_item's; the check differs: EVs rose, the species changed, the level rose.
VITAMINS = {"HP Up": 0, "Protein": 1, "Iron": 2, "Carbos": 3, "Calcium": 4, "Zinc": 5}  # -> HP Atk Def Spe SpA SpD
STONES = {"Fire Stone", "Water Stone", "Thunder Stone", "Thunderstone", "Leaf Stone", "Moon Stone", "Sun Stone",
          "Shiny Stone", "Dusk Stone", "Dawn Stone", "Ice Stone"}
OTHER = {"Rare Candy"}


def _snapshot(p, pid):
    n = p.read8(PLAYER_PARTY_COUNT)
    d = p.range(PLAYER_PARTY, 100 * n)
    for i in range(n):
        m = d[100 * i:100 * (i + 1)]
        if struct.unpack("<I", m[:4])[0] == pid:
            return {"species": NAMES["species"][struct.unpack("<H", m[0x20:0x22])[0]], "level": m[0x54],
                    "evs": list(m[0x38:0x3E])}
    return None


def use_on(p, item, pokemon):
    """Field: use a vitamin, an evolution stone or a Rare Candy from the Items pocket on party member POKEMON.
    An evolution or a move-learning question is the agent's call: the tool stops there and says so."""
    name = next((n for n in list(VITAMINS) + sorted(STONES) + sorted(OTHER) if _plain(n) == _plain(item)), None)
    if name is None:
        raise SystemExit(f"use_on takes vitamins ({', '.join(VITAMINS)}), evolution stones or Rare Candy; for "
                         "healing items use use_item")
    bag = _items(p)
    if name not in bag:
        raise SystemExit(f"no {name} in the Items pocket")
    party = _party(p)
    hits = [m for m in party if m[1].lower() == pokemon.lower()]
    if len(hits) != 1:
        raise SystemExit(f"{'no' if not hits else 'two'} {pokemon!r} in the party: {[m[1] for m in party]}")
    pid = hits[0][0]
    before = _snapshot(p, pid)
    if name in VITAMINS:
        i = VITAMINS[name]
        if sum(before["evs"]) >= 510 or before["evs"][i] >= 252:
            raise SystemExit(f"{pokemon}'s EVs are full ({sum(before['evs'])}/510 total, {before['evs'][i]}/252 in "
                             f"that stat): {name} would do nothing")
    if raw(p)["mode"] != "overworld" or p.read32(CB2) == CB2_BATTLE:
        raise SystemExit("use_on works in the overworld only: close the text, menu or battle first")
    if not _start_menu_open(p):
        p.press("START", 4)
        p.step(20)
        if not _start_menu_open(p):
            raise SystemExit("START didn't open the start menu: look at the screen")
    for _ in range(8):
        cur = p.read8(START_CURSOR)
        if cur == 2:
            break
        p.press("RIGHT" if cur < 2 else "LEFT", 4)
        p.step(10)
    p.press("A", 4)
    if not _wait_cb2(p, CB2_BATTLE_BAG):
        raise SystemExit("the bag didn't open: look at the screen")
    try:
        msg = _choose(p, bag.index(name), name, pid)
    except SystemExit:
        msg = ""  # an evolution takes over the screen instead of printing a message
    for _ in range(120):  # an evolution scene runs on its own; wait for it to end or to ask something
        r = raw(p)
        if p.read32(CB2) in (CB2_BATTLE_PARTY, CB2_BATTLE_BAG) or r["mode"] == "overworld":
            break
        if r["mode"] == "dialog" and r["printer"][0x1C] == 2:
            text = decode(p.range(STRING_VAR4, 0x100)).replace("\n", " ")
            if "?" in text:
                return f"{name} on {pokemon}: the game asks {text!r}. Answer it yourself (advance_dialog / press_buttons)."
            p.press("A", 4)
        p.step(10)
    import party_menu
    party_menu.close(p)
    after = _snapshot(p, pid)
    said = f" (the game said: {msg})" if msg else ""
    if name in VITAMINS:
        i = VITAMINS[name]
        if after["evs"][i] <= before["evs"][i]:
            raise SystemExit(f"{name} did nothing to {pokemon}{said}")
        return (f"{name} on {pokemon}: {('HP', 'Atk', 'Def', 'Spe', 'SpA', 'SpD')[i]} EVs {before['evs'][i]} -> "
                f"{after['evs'][i]} (total {sum(after['evs'])}/510){said}")
    if name in STONES:
        if after["species"] == before["species"]:
            raise SystemExit(f"{name} had no effect on {pokemon} ({before['species']}){said}")
        return f"{pokemon} evolved: {before['species']} -> {after['species']}{said}"
    if after["level"] <= before["level"]:
        raise SystemExit(f"{name} did nothing to {pokemon} (level {before['level']}){said}")
    return f"{name} on {pokemon}: level {before['level']} -> {after['level']}" + (
        f", evolved into {after['species']}" if after["species"] != before["species"] else "") + said


if __name__ == "__main__":
    # Self-check: python items.py STATE... [PORT]. Each state needs a Potion and a damaged party member: the
    # fixtures overworld_items.ss1 (start menu open), wild_battle_prethrow.ss1, trainer_battle_riolu.ss1.
    import sys
    from probe import Probe
    assert _why_not(HP, 0, 40, 0) and _why_not(HP, 40, 40, 0) and not _why_not(HP, 5, 40, 0)
    assert _why_not(REVIVE, 5, 40, 0) and not _why_not(REVIVE, 0, 40, 0) and _why_not(STATUS, 5, 40, 0)
    assert not _why_not(BOTH, 40, 40, 8) and _why_not(BOTH, 40, 40, 0)

    def refused(item, who, why):
        try:
            use_item(p, item, who)
        except SystemExit as e:
            assert why in str(e), e
            return
        raise AssertionError(f"used {item} on {who}")

    p = Probe(port=int(sys.argv[-1]) if sys.argv[-1].isdigit() else 8888)
    for state in [a for a in sys.argv[1:] if not a.isdigit()]:
        p.load(state)
        p.step(2)
        party = _party(p)
        names = [m[1] for m in party]
        hurt = next(m[1] for m in party if 0 < m[2] < m[3])
        refused("Master Ball", hurt, "healing items only")
        if "Max Revive" not in _items(p):
            refused("Max Revive", hurt, "no Max Revive in the bag")
        for m in party:
            if names.count(m[1]) == 1 and m[2] in (0, m[3]):
                refused("Potion", m[1], "full HP" if m[2] else "fainted")
        out = use_item(p, "Potion", hurt)
        print(out)
        b, a = out.split(": ")[1].split(" (")[0].split(" -> ")
        assert int(a.split("/")[0]) > int(b.split("/")[0]), out
