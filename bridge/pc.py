"""PC tools (#161): pc_deposit, pc_withdraw, pc_swap at a Pokemon Center PC.

Flow (verified live on Unbound, Fallshore Center 14/6, 2026-10-09):
- The PC is the tile with behavior 0x83 (every Center has it at (11,3), behind the counter's right end): face it
  and press A -> "Claude booted up the PC." -> "Which PC should be accessed?" (Ayla's PC / Claude's PC / Prof. Log's
  PC / Log Off) -> Ayla's PC -> "Accessed Ayla's PC." -> "Pokemon Storage System opened." -> options menu (sMenu
  cursor 0x0203ADE6): 0 Move Pokemon, 1 Move Items, 2 Withdraw Pokemon, 3 Deposit Pokemon, 4 See Ya!
  (Unbound's order, not vanilla's). Withdraw with a full party refuses: "Can't take any more Pokemon."
- The storage screen runs on cb2 0x0808CDC5. Cursor: area u8 0x02039820 (0 box grid, 1 party list, 2 box title),
  position u8 0x02039821 (grid: row * 6 + column, 30 slots; party list: slot). The shown box is the storage's
  current box (gPokemonStoragePtr +0); on the title row LEFT/RIGHT change it.
- A on a Pokemon opens Store/Withdraw, Summary, Mark, RELEASE, Cancel (sMenu cursor, row 0 first). A is pressed
  only with that cursor on row 0, so Release can't be chosen.
- Store asks "Deposit in which Box?" starting at the current box; LEFT/RIGHT change it (the counter shows n/30).
- B leaves the screen with "Continue Box operations?" (Yes/No, cursor on No): A answers No. The party count
  (0x02024029) is compacted only when the screen closes.
Results are verified by re-reading the party and the storage (bridge/stats.py, #157).
"""
import struct

import stats
import world as W
from items import CB2
from party_menu import _messages, _text, _wait, _waiting, party
from state import PLAYER_PARTY_COUNT, get_state, raw

CB2_FIELD, CB2_STORAGE = 0x080565B5, 0x0808CDC5
MENU_CURSOR, AREA, POS = 0x0203ADE6, 0x02039820, 0x02039821
PC_TILE = 0x83
WITHDRAW, DEPOSIT = 2, 3
GRID, PARTY_LIST, TITLE = 0, 1, 2
BOXES_SEEN = 19  # boxes 1-19 are readable in RAM (#157)


def _current_box(p):
    return p.read8(p.read32(stats.STORAGE_PTR))


def _prompt_box(p):
    """The box index the "Deposit in which Box?" prompt shows (verified: tracks LEFT/RIGHT, #161)."""
    return p.read8(p.read32(0x0203982C) + 0x2094)


def _menu_to(p, row, tries=10):
    for _ in range(tries):
        cur = p.read8(MENU_CURSOR)
        if cur == row:
            return True
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(12)
    return p.read8(MENU_CURSOR) == row


def _walk_to_pc(p):
    """Stand below the PC tile, facing it. Uses the agent's own walk_to."""
    import mcp_server  # the walker lives there; imported late to avoid a cycle
    w = W.read_world(p)
    pcs = [(x, y) for y in range(w["height"]) for x in range(w["width"]) if w["tile"](x, y)[0] == PC_TILE]
    if not pcs:
        raise SystemExit("no PC on this map: go into a Pokemon Center (its PC is behind the counter's right end)")
    x, y = pcs[0]
    here = tuple(get_state(p)["pos"])
    if here != (x, y + 1):
        r = mcp_server.t_walk_to({"x": x, "y": y + 1})
        if tuple(get_state(p)["pos"]) != (x, y + 1):
            raise SystemExit(f"couldn't reach the PC at ({x},{y}): {r.get('result')}")
    p.press("UP", 4)  # a short tap turns without stepping (the PC is solid anyway)
    p.step(20)


def _open_storage(p, option):
    """From the overworld in a Center: PC -> Ayla's PC -> OPTION (WITHDRAW/DEPOSIT) -> the storage screen."""
    if raw(p)["mode"] != "overworld":
        raise SystemExit("this works in the overworld only: close the text or menu first")
    _walk_to_pc(p)
    p.press("A", 4)
    # "Claude booted up the PC." (a message) -> the "Which PC should be accessed?" list (a menu: mode "other"; the
    # question isn't in gStringVar4, which then holds "Claude's PC").
    for _ in range(8):
        _wait(p, lambda: _waiting(p) or raw(p)["mode"] == "other", 30)
        if raw(p)["mode"] == "other":
            break
        p.press("A", 4)
        p.step(20)
    if raw(p)["mode"] != "other" or "PC" not in _text(p):
        raise SystemExit(f"the PC didn't ask which PC to access (it says {_text(p)!r}): look at the screen")
    p.step(20)
    if not _menu_to(p, 0):
        raise SystemExit("couldn't select Ayla's PC: look at the screen")
    p.press("A", 4)
    for _ in range(4):  # "Accessed Ayla's PC." -> "Pokemon Storage System opened." -> the options menu
        _wait(p, lambda: _waiting(p), 30)
        p.press("A", 4)
        p.step(30)
        if raw(p)["mode"] == "other":
            break
    if not _menu_to(p, option):
        raise SystemExit("couldn't reach the storage option: look at the screen")
    p.press("A", 4)
    if not _wait(p, lambda: p.read32(CB2) == CB2_STORAGE, 40, 8):
        raise SystemExit(f"the storage screen didn't open (the game says {_text(p)!r})")
    p.step(60)  # the screen slides in


def _leave_storage(p):
    """B out of the storage screen, answer No to "Continue Box operations?", then back out to the overworld."""
    for _ in range(20):
        if p.read32(CB2) != CB2_STORAGE:
            break
        p.press("B", 4)
        p.step(40)
        if "Continue Box" in _text(p) and p.read8(MENU_CURSOR) == 1:  # the Yes/No box, cursor on No
            p.press("A", 4)
            p.step(80)
    for _ in range(12):  # the options menu, "Which PC", messages
        if raw(p)["mode"] == "overworld":
            p.step(20)
            if raw(p)["mode"] == "overworld":
                return
        p.press("B", 4)
        p.step(30)
    raise SystemExit("the PC menus didn't close back to the overworld: look at the screen")


def _cursor_to(p, area, pos, tries=20):
    for _ in range(tries):
        a, q = p.read8(AREA), p.read8(POS)
        if (a, q) == (area, pos):
            return True
        if area == PARTY_LIST:
            key = "DOWN" if q < pos else "UP"
        elif a != GRID:
            key = "DOWN"
        else:
            r, c, tr, tc = q // 6, q % 6, pos // 6, pos % 6
            key = "DOWN" if r < tr else "UP" if r > tr else "RIGHT" if c < tc else "LEFT"
        p.press(key, 4)
        p.step(20)
    return (p.read8(AREA), p.read8(POS)) == (area, pos)


def _act_row0(p):
    """A on the selected Pokemon, then A on row 0 of its menu (Store/Withdraw), never anything else."""
    p.press("A", 4)
    p.step(40)
    if p.read8(MENU_CURSOR) != 0:
        raise SystemExit("the Pokemon's menu didn't open on its first row: stopping (Release is on that menu)")
    p.press("A", 4)
    p.step(40)


def _box_counts(p):
    bx = stats.boxes(p)
    return {b: len(bx.get(b, [])) for b in range(1, BOXES_SEEN + 1)}


def pc_deposit(p, pokemon, box=None):
    """Put party member POKEMON into BOX (1-19; default: the first box with room)."""
    names = [m[1] for m in party(p)]
    hits = [i for i, n in enumerate(names) if n.lower() == pokemon.lower()]
    if not hits:
        raise SystemExit(f"no {pokemon!r} in the party: {names}")
    if len(hits) > 1:
        raise SystemExit(f"two party members are called {pokemon!r}: rename one first")
    if len(names) == 1:
        raise SystemExit("you can't deposit your last Pokemon")
    counts = _box_counts(p)
    if box is None:
        box = next((b for b in range(1, BOXES_SEEN + 1) if counts[b] < 30), None)
        if box is None:
            raise SystemExit("boxes 1-19 are full")
    if not 1 <= box <= BOXES_SEEN or counts[box] >= 30:
        raise SystemExit(f"box {box} is full or out of range (1-{BOXES_SEEN}): counts {counts}")
    slot = hits[0]
    _open_storage(p, DEPOSIT)
    if not _cursor_to(p, PARTY_LIST, slot):
        raise SystemExit("couldn't put the cursor on that party member: look at the screen")
    _act_row0(p)  # Store: "Deposit in which Box?" (drawn by the storage screen itself, not in gStringVar4)
    # The prompt keeps its own box index (not the current box): storage data (pointer 0x0203982C) +0x2094.
    for _ in range(BOXES_SEEN + 2):
        shown = _prompt_box(p) + 1
        if shown == box:
            break
        p.press("RIGHT" if box > shown else "LEFT", 4)
        p.step(30)
    if _prompt_box(p) + 1 != box:
        raise SystemExit(f"couldn't choose box {box} in the deposit prompt: look at the screen")
    p.press("A", 4)
    p.step(120)
    _leave_storage(p)
    now = [m[1] for m in party(p)]
    inbox = [m["name"] for _, m in stats.boxes(p).get(box, [])]
    if pokemon in now or pokemon not in inbox:
        raise SystemExit(f"deposit not confirmed: party {now}, box {box} {inbox}: look at the screen")
    return f"{pokemon} is in box {box}. Party: {', '.join(now)}"


def pc_withdraw(p, box, slot):
    """Take the Pokemon in BOX (1-19), SLOT (1-30, as pc_boxes lists them) into the party."""
    names = [m[1] for m in party(p)]
    if len(names) >= 6:
        raise SystemExit("the party is full (6): deposit one first, or use pc_swap")
    bx = dict(stats.boxes(p).get(box, []))
    if slot not in bx:
        raise SystemExit(f"box {box} slot {slot} is empty: {sorted((s, m['name']) for s, m in bx.items())}")
    who = bx[slot]["name"]
    _open_storage(p, WITHDRAW)
    p.press("UP", 4)  # onto the box title, where LEFT/RIGHT change the box
    p.step(25)
    if p.read8(AREA) != TITLE:
        _cursor_to(p, GRID, 0)
        p.press("UP", 4)
        p.step(25)
    for _ in range(BOXES_SEEN + 2):
        cur = _current_box(p) + 1
        if cur == box:
            break
        p.press("RIGHT" if box > cur else "LEFT", 4)
        p.step(60)
    if _current_box(p) + 1 != box:
        raise SystemExit(f"couldn't show box {box}: look at the screen")
    p.press("DOWN", 4)
    p.step(25)
    if not _cursor_to(p, GRID, slot - 1):
        raise SystemExit("couldn't put the cursor on that slot: look at the screen")
    _act_row0(p)  # Withdraw
    p.step(60)
    _leave_storage(p)
    now = [m[1] for m in party(p)]
    if who not in now:
        raise SystemExit(f"withdraw not confirmed: party {now}: look at the screen")
    return f"{who} joined the party (last place; reorder_party moves it). Party: {', '.join(now)}"


def pc_swap(p, pokemon, box, slot):
    """Put party member POKEMON into the PC and take BOX/SLOT into the party (deposit, then withdraw)."""
    bx = dict(stats.boxes(p).get(box, []))
    if slot not in bx:
        raise SystemExit(f"box {box} slot {slot} is empty")
    who = bx[slot]["name"]
    a = pc_deposit(p, pokemon)
    # The deposit may have filled an earlier empty slot of the same box; find the incoming Pokemon again by name.
    bx = stats.boxes(p)
    where = next(((b, s) for b, v in bx.items() for s, m in v if m["name"] == who), (box, slot))
    b = pc_withdraw(p, *where)
    return f"{a}. {b}"


if __name__ == "__main__":
    assert (WITHDRAW, DEPOSIT, GRID, PARTY_LIST, TITLE) == (2, 3, 0, 1, 2)
    print("pc self-check ok (live checks: see #161)")
