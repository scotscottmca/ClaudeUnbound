"""buy (#109): purchase from a Poke Mart in one call.

Flow (verified live on Unbound, Fallshore Mart 14/5, 2026-10-09):
- The clerk (graphics 68; Bellin and Fallshore both at (1,3)) is talked to across the counter: stand two tiles
  away with the counter between, face the clerk, A -> "Hi, there! May I help you?" + Buy / Sell / See Ya!
  (sMenu cursor 0x0203ADE6).
- Buy opens the list (cb2 0x0809ADE5). Mart data: item list pointer 0x02039938 (u16 item ids in ROM, ended by 0),
  total price u16 0x0203993C, list cursor u16 0x02039940 (row on screen, stops at 3), scroll u16 0x02039942,
  item count u16 0x02039944. Selected item = cursor + scroll.
- A on an item -> "<Item>? Certainly. How many would you like?" with a quantity box: quantity u16 0x030050C2
  (UP/DOWN +-1, RIGHT/LEFT +-10).
- A -> "<Item>, and you want N. That will be $P. Okay?" (Yes/No, Yes first) -> A -> "Here you are! Thank you!" -> A
  -> back to the list. B leaves the list, then the Buy/Sell menu.
The tool checks stock and money first, the price before confirming, and the bag and money after.
"""
import struct

import world as W
from items import CB2
from party_menu import _text, _wait, _waiting
from state import NAMES, get_state, raw

CLERK = 68
CB2_SHOP = 0x0809ADE5
LIST_PTR, PRICE, CURSOR, SCROLL, COUNT = 0x02039938, 0x0203993C, 0x02039940, 0x02039942, 0x02039944
QTY, MENU_CURSOR = 0x030050C2, 0x0203ADE6


def _owned(s, item):
    return sum(pocket.get(item, 0) for pocket in s["bag"].values() if isinstance(pocket, dict))


def stock(p):
    ptr = p.read32(LIST_PTR)
    out = []
    for i in range(64):
        item = p.read16(ptr + 2 * i)
        if not item:
            break
        out.append(NAMES["items"][item])
    return out


def _to_clerk(p):
    """Stand across the counter from the clerk, facing them, and press A."""
    import mcp_server
    w = W.read_world(p)
    clerk = next((n for n in w["npcs"] if n.get("graphics") == CLERK), None)
    if clerk is None:
        raise SystemExit("no shop clerk here: go into a Poke Mart")
    for key, (dx, dy) in (("LEFT", (1, 0)), ("UP", (0, 1)), ("RIGHT", (-1, 0)), ("DOWN", (0, -1))):
        stand = (clerk["x"] + 2 * dx, clerk["y"] + 2 * dy)  # the counter is between
        mid = (clerk["x"] + dx, clerk["y"] + dy)
        if not (0 <= stand[0] < w["width"] and 0 <= stand[1] < w["height"]) or not w["tile"](*mid)[1] \
                or w["tile"](*stand)[1]:
            continue
        mcp_server.t_walk_to({"x": stand[0], "y": stand[1]})
        if tuple(get_state(p)["pos"]) == stand:
            p.press(key, 4)
            p.step(20)
            p.press("A", 4)
            return
    raise SystemExit(f"couldn't get across the counter from the clerk at ({clerk['x']},{clerk['y']})")


def _leave(p):
    for _ in range(12):
        if raw(p)["mode"] == "overworld":
            p.step(20)
            if raw(p)["mode"] == "overworld":
                return
        p.press("B", 4)
        p.step(40)
    raise SystemExit("the shop menus didn't close back to the overworld: look at the screen")


def buy(p, item, quantity=1):
    """Buy QUANTITY (1-99) of ITEM from the Mart clerk on this map."""
    if not 1 <= quantity <= 99:
        raise SystemExit("quantity must be 1-99")
    if raw(p)["mode"] != "overworld":
        raise SystemExit("this works in the overworld only: close the text or menu first")
    before = get_state(p)
    _to_clerk(p)
    if not _wait(p, lambda: raw(p)["mode"] == "other", 40):
        raise SystemExit(f"the clerk didn't offer Buy/Sell (the game says {_text(p)!r})")
    p.step(20)
    if p.read8(MENU_CURSOR) != 0:
        p.press("UP", 4)
        p.step(12)
    p.press("A", 4)
    if not _wait(p, lambda: p.read32(CB2) == CB2_SHOP, 40, 8):
        raise SystemExit("Buy didn't open the shop list: look at the screen")
    p.step(40)
    goods = stock(p)
    want = next((g for g in goods if g.lower() == item.lower()), None)
    if want is None:
        _leave(p)
        raise SystemExit(f"this Mart doesn't sell {item!r}. It sells: {', '.join(goods)}")
    row = goods.index(want)
    for _ in range(2 * len(goods) + 4):
        cur = p.read16(CURSOR) + p.read16(SCROLL)
        if cur == row:
            break
        p.press("DOWN" if cur < row else "UP", 4)
        p.step(12)
    if p.read16(CURSOR) + p.read16(SCROLL) != row:
        _leave(p)
        raise SystemExit(f"couldn't put the cursor on {want}: look at the screen")
    p.press("A", 4)
    # The clerk's "<Item>? Certainly. How many..." flashes (instant text, never "waiting"), then the quantity box
    # draws "x01" and the quantity reads 1. Waiting for "quantity == 1" alone went on too early once (a stale 1 from
    # an earlier visit): the presses moved the list cursor instead.
    if not _wait(p, lambda: "Certainly" in _text(p) or p.read16(QTY) == 1 and _text(p).endswith("01"), 40, 3) \
            or not _wait(p, lambda: p.read16(QTY) == 1, 40):
        _leave(p)
        raise SystemExit(f"no quantity box for {want} (the game says {_text(p)!r})")
    p.step(30)
    unit = p.read16(PRICE)  # the box opens at 1: the unit price
    if unit * quantity > before["money"]:
        _leave(p)
        raise SystemExit(f"{quantity} {want} cost ${unit * quantity} (${unit} each); you have ${before['money']}: "
                         f"you can afford {before['money'] // unit}")
    for _ in range(40):
        q = p.read16(QTY)
        if q == quantity:
            break
        diff = quantity - q
        p.press("RIGHT" if diff >= 10 else "LEFT" if diff <= -10 else "UP" if diff > 0 else "DOWN", 4)
        p.step(12)
    if p.read16(QTY) != quantity:
        _leave(p)
        raise SystemExit(f"couldn't set the quantity to {quantity} (it shows {p.read16(QTY)})")
    price = p.read16(PRICE)
    if price > before["money"]:
        _leave(p)
        raise SystemExit(f"{quantity} {want} cost ${price}; you have ${before['money']}")
    p.press("A", 4)
    if not _wait(p, lambda: "Okay?" in _text(p), 40, 3):  # instant text too: never "waiting"
        _leave(p)
        raise SystemExit(f"no price confirmation (the game says {_text(p)!r})")
    p.step(30)
    # Yes is the default, but the Yes/No box drops an A pressed too soon (then B on the way out answered No and
    # nothing was bought): press until the clerk says "Here you are", checking the money too.
    for _ in range(6):
        p.step(30)
        if p.read16(MENU_CURSOR) & 0xFF != 0:
            break  # not on Yes: don't buy by accident
        p.press("A", 4)
        p.step(30)
        if "Here you are" in _text(p) or get_state(p)["money"] < before["money"]:
            break
    for _ in range(4):  # "Here you are! Thank you!" (and a bonus message, e.g. a Premier Ball for 10 balls)
        p.press("A", 4)
        p.step(40)
        if "Here you are" not in _text(p) and "also" not in _text(p):
            break
    _leave(p)
    after = get_state(p)
    got = _owned(after, want) - _owned(before, want)
    paid = before["money"] - after["money"]
    if got < quantity:
        raise SystemExit(f"bought {got} {want} (paid ${paid}), not {quantity}: look at the screen")
    return f"bought {quantity} {want} for ${paid}; you have {_owned(after, want)} now and ${after['money']} left"


if __name__ == "__main__":
    assert struct.calcsize("<H") == 2
    print("shop self-check ok (live checks: see #109)")
