"""Start mGBA with the bridge script unless it's already serving.

    python launch.py [STATE]    # STATE: savestate to load at start (default: none, resume the in-game save)

Needs an mGBA build with --script (0.11 / dev builds). Set MGBA to its mGBA.exe.
"""
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "..", "run")
MGBA = os.environ.get("MGBA", r"D:\Tools\mGBA-dev\mGBA-build-2026-10-06-win64-9154-3a5e34be33dc7f8f707e5bc9db69e8a430046f21\mGBA.exe")


def serving():
    try:
        socket.create_connection(("127.0.0.1", 8888), timeout=1).close()
        return True
    except OSError:
        return False


def launch(state=None):
    if serving():
        return
    args = [MGBA, "--script", os.path.join(HERE, "probe.lua")]
    if state:
        args += ["-t", os.path.abspath(state)]
    # Through "start" so mGBA has no parent: stopping a runner's process tree mustn't take the emulator with it.
    subprocess.Popen(["cmd", "/c", "start", "", *args, os.path.join(RUN, "Unbound.gba")])
    for _ in range(30):
        time.sleep(1)
        if serving():
            return
    sys.exit("mGBA started but the bridge never came up")


if __name__ == "__main__":
    launch(*sys.argv[1:2])
    print("bridge up")
