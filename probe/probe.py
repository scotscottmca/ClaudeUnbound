"""Client for probe.lua. Use as a library (Probe) or CLI:

    python probe.py read32 0x030030F0
    python probe.py range 0x02024284 100
    python probe.py step 60
    python probe.py press A [FRAMES]
    python probe.py dump 0x02000000 0x40000 before.bin    # snapshot
    python probe.py diff before.bin after.bin [BASE]      # changed bytes, offline
"""
import socket
import sys

CHUNK = 0x1000  # keeps each reply line small


class Probe:
    def __init__(self, host="127.0.0.1", port=8888):
        self.f = socket.create_connection((host, port)).makefile("rw", newline="\n")

    def cmd(self, line):
        self.f.write(line + "\n")
        self.f.flush()
        out = self.f.readline().strip()
        if not out or out.startswith("err"):
            raise RuntimeError(out or "connection closed")
        return out

    def read8(self, addr): return int(self.cmd(f"read8 {addr:#x}"), 16)
    def read16(self, addr): return int(self.cmd(f"read16 {addr:#x}"), 16)
    def read32(self, addr): return int(self.cmd(f"read32 {addr:#x}"), 16)

    def range(self, addr, length):
        return b"".join(
            bytes.fromhex(self.cmd(f"range {a:#x} {min(CHUNK, addr + length - a)}"))
            for a in range(addr, addr + length, CHUNK)
        )

    def step(self, frames): self.cmd(f"step {frames}")
    def press(self, key, frames=4): self.cmd(f"press {key} {frames}")


def diff(a, b, base=0):
    """[(addr, old, new)] for every byte that differs."""
    return [(base + i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]


def main(argv):
    cmd, args = argv[0], argv[1:]
    num = lambda s: int(s, 0)
    if cmd == "diff":
        a, b = (open(p, "rb").read() for p in args[:2])
        for addr, x, y in diff(a, b, num(args[2]) if len(args) > 2 else 0):
            print(f"{addr:08x}: {x:02x} -> {y:02x}")
        return
    p = Probe()
    if cmd in ("read8", "read16", "read32"):
        print(f"{getattr(p, cmd)(num(args[0])):#x}")
    elif cmd == "range":
        print(p.range(num(args[0]), num(args[1])).hex(" "))
    elif cmd == "dump":
        open(args[2], "wb").write(p.range(num(args[0]), num(args[1])))
    elif cmd == "step":
        p.step(num(args[0]))
    elif cmd == "press":
        p.press(args[0], *map(num, args[1:]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:]) if sys.argv[1:] else sys.exit(__doc__)
