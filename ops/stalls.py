"""Read-only: sample gMain.vblankCounter2 every 0.1 s for N seconds; print each stall (frame clock not advancing
for > 0.4 s, or a read that took > 0.4 s) with wall time, then a summary. Reads only."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))
from probe import Probe  # noqa: E402
import state  # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 180
p = Probe()
clock = state.G_MAIN + 0x24
end = time.time() + secs
last_f, last_t, stall_from = p.read32(clock), time.time(), None
stalls, slow = [], []
while time.time() < end:
    t0 = time.time()
    f = p.read32(clock)
    t1 = time.time()
    if t1 - t0 > 0.4:
        slow.append((round(t0, 1), round(t1 - t0, 2)))
        print(f"slow read at {time.strftime('%H:%M:%S', time.localtime(t0))}: {t1 - t0:.2f} s", flush=True)
    if f == last_f:
        stall_from = stall_from or last_t
    else:
        if stall_from and t1 - stall_from > 0.4:
            stalls.append((round(stall_from, 1), round(t1 - stall_from, 2), f - last_f))
            print(f"stall at {time.strftime('%H:%M:%S', time.localtime(stall_from))}: {t1 - stall_from:.2f} s, "
                  f"then +{f - last_f} frames", flush=True)
        stall_from = None
        last_f, last_t = f, t1
    time.sleep(0.1)
print(f"done: {len(stalls)} stalls, {len(slow)} slow reads in {secs:.0f} s", flush=True)
print("STALLS", stalls, "SLOW", slow, flush=True)
