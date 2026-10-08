"""Type a name on the naming screen (nicknames, rival), closed-loop on RAM (docs/addresses.md).

    python naming.py Copilot      # on a naming screen: type it and confirm
"""
import sys

from state import G_MAIN, decode

NAMING_CB2 = 0x0809FB71  # gMain.callback2 while the naming screen is up
# sNamingScreen is heap-allocated, so its fields move: a nickname after a capture wasn't where the rival's
# and Beldum's screens put it. Follow the pointer.
NAMING_PTR = 0x0203998C  # sNamingScreen
BUF, PAGE, CURSOR_SPRITE = 0x1800, 0x1E22, 0x1E23  # textBuffer (0xFF-terminated); page 2 lower, 0 others, 1 upper
#   (SELECT cycles 2 -> 0 -> 1, ~20 frames a switch); cursorSpriteId
SPRITES, SPRITE_SIZE = 0x0202063C, 0x44  # gSprites; the cursor's data[0]/[1] at +0x2E/+0x30 are x/y (x 8: buttons)
ROWS = {2: ["abcdef .", "ghijkl ,", "mnopqrs ", "tuvwxyz "],
        1: ["ABCDEF .", "GHIJKL ,", "MNOPQRS ", "TUVWXYZ "]}
KEYS = {ch: (page, x, y) for page, rows in ROWS.items() for y, row in enumerate(rows) for x, ch in enumerate(row)}


def _base(p):
    return p.read32(NAMING_PTR)


def text(p):
    return decode(p.range(_base(p) + BUF, 16))


def _cursor(p):
    sprite = SPRITES + SPRITE_SIZE * p.read8(_base(p) + CURSOR_SPRITE)
    return p.read8(sprite + 0x2E), p.read8(sprite + 0x30)


def _cursor_to(p, x, y):
    for _ in range(30):
        cx, cy = _cursor(p)
        if (cx, cy) == (x, y):
            return
        p.press("RIGHT" if cx < x else "LEFT" if cx > x else "DOWN" if cy < y else "UP", 4)
        p.step(8)
    raise RuntimeError(f"naming cursor stuck at {cx},{cy} wanting {x},{y}")


def _page_to(p, page):
    for _ in range(4):
        if p.read8(_base(p) + PAGE) == page:
            return
        p.press("SELECT", 4)
        p.step(40)
    raise RuntimeError(f"naming page stuck at {p.read8(_base(p) + PAGE)} wanting {page}")


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
