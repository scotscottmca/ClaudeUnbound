"""Read-only recorder for the user's demo run: one JSON line per sample (frame-stamped).
Player map/pos/facing/elevation, every loaded object (id, pos, facing, movement, trainer, sight), the GBA key
register (pressed buttons), mode and the dialog/battle text. Only read8/16/32/range are sent."""
import json
import struct
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))
from probe import Probe  # noqa: E402
import state  # noqa: E402

KEYINPUT = 0x04000130  # 0 bit = pressed: A B Select Start Right Left Up Down R L
KEYS = ["A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L"]
CLOCK = state.G_MAIN + 0x24  # gMain.vblankCounter2
out = open(sys.argv[1], "a", encoding="utf-8")
p = Probe()
last_text, last_cb2, last_n = None, None, -1
while True:
    try:
        gm = p.range(state.G_MAIN, 0x28)  # one read: callback2 (+4) and the frame clock (+0x24)
        cb2, f = struct.unpack_from("<I", gm, 4)[0], struct.unpack_from("<I", gm, 0x24)[0]
        keys = p.read16(KEYINPUT)
        x, y, g, n = struct.unpack("<hhbb", p.range(p.read32(state.SB1_PTR), 6))
        evs = p.range(state.OBJECT_EVENTS, 16 * 0x24)
        objs, me = [], None
        for i in range(16):
            ev = evs[i * 0x24:(i + 1) * 0x24]
            if not ev[0] & 1:
                continue
            ox, oy = (c - 7 for c in struct.unpack("<hh", ev[0x10:0x14]))
            o = {"id": ev[8], "x": ox, "y": oy, "f": ev[0x18] & 0xF, "mv": ev[6], "tr": ev[7], "sight": ev[0x1D]}
            if ev[8] == 0xFF:
                me = {"f": o["f"], "elev": ev[0x0B] & 0xF}
            else:
                objs.append(o)
        rec = {"t": round(time.time(), 3), "frame": f, "map": [g, n], "pos": [x, y], "me": me, "cb2": hex(cb2),
               "keys": [k for i, k in enumerate(KEYS) if not keys >> i & 1], "objs": objs}
        if cb2 != last_cb2 or len(objs) != last_n or any(k in rec["keys"] for k in ("A", "B")):
            r = state.raw(p)  # the full mode/text check only when something may have changed (it costs reads)
            rec["mode"] = r["mode"]
            text = state.current_text(p, r["printer"]) if r["mode"] == "dialog" else None
            if text != last_text:
                rec["text"] = text
                last_text = text
        last_cb2, last_n = cb2, len(objs)
        out.write(json.dumps(rec) + "\n")
        out.flush()
    except Exception as e:  # emulator busy or mid-transition: note it and keep going
        out.write(json.dumps({"t": round(time.time(), 3), "error": repr(e)}) + "\n")
        time.sleep(0.2)
        try:
            p = Probe()
        except Exception:
            time.sleep(1)
