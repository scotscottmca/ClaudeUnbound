"""Type a name on the naming screen (nicknames, rival), closed-loop on RAM (docs/addresses.md).

    python naming.py Copilot      # on a naming screen: type it and confirm
"""
import sys

from state import G_MAIN, decode

NAMING_CB2 = 0x0809FB71  # gMain.callback2 while the naming screen is up
BUF = 0x02004560  # sNamingScreen->textBuffer (0xFF-terminated)
PAGE = 0x02004B82  # 2 lower, 0 others, 1 upper; SELECT cycles 2 -> 0 -> 1, ~20 frames per switch
CURSOR_X, CURSOR_Y = 0x0202066A, 0x0202066C  # cursor sprite data[0]/[1]; x 8 is the button column
ROWS = {2: ["abcdef .", "ghijkl ,", "mnopqrs ", "tuvwxyz "],
        1: ["ABCDEF .", "GHIJKL ,", "MNOPQRS ", "TUVWXYZ "]}
KEYS = {ch: (page, x, y) for page, rows in ROWS.items() for y, row in enumerate(rows) for x, ch in enumerate(row)}


def text(p):
    return decode(p.range(BUF, 16))


def _cursor_to(p, x, y):
    for _ in range(30):
        cx, cy = p.read8(CURSOR_X), p.read8(CURSOR_Y)
        if (cx, cy) == (x, y):
            return
        p.press("RIGHT" if cx < x else "LEFT" if cx > x else "DOWN" if cy < y else "UP", 4)
        p.step(8)
    raise RuntimeError(f"naming cursor stuck at {cx},{cy} wanting {x},{y}")


def _page_to(p, page):
    for _ in range(4):
        if p.read8(PAGE) == page:
            return
        p.press("SELECT", 4)
        p.step(40)
    raise RuntimeError(f"naming page stuck at {p.read8(PAGE)} wanting {page}")


def type_name(p, name, confirm=True):
    """Clear the box, type NAME (letters and spaces), check the buffer, then confirm with START + A."""
    if p.read32(G_MAIN + 4) != NAMING_CB2:
        raise RuntimeError("not on the naming screen")
    bad = [c for c in name if c not in KEYS]
    if bad:
        raise ValueError(f"can't type {bad}: letters and spaces only")
    for _ in range(20):
        if not text(p):
            break
        p.press("B", 4)
        p.step(10)
    for ch in name:
        page, x, y = KEYS[ch]
        before = text(p)
        _page_to(p, page)  # also undoes the game's switch to lower case after the first capital
        _cursor_to(p, x, y)
        p.press("A", 4)
        p.step(12)
        if text(p) != before + ch:
            raise RuntimeError(f"typed {ch!r} but the box reads {text(p)!r} (name too long?)")
    typed = text(p)
    if confirm:
        p.press("START", 4)  # cursor to OK
        p.step(10)
        p.press("A", 4)
        p.step(60)
    return typed


if __name__ == "__main__":
    from probe import Probe
    print(type_name(Probe(), " ".join(sys.argv[1:])))
