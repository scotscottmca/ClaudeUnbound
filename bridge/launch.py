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
# User: never faster than 2x. mGBA's own limiter (audio sync at a 120 fps target) holds exactly 120 fps at ~2.4% CPU;
# CPU caps don't set speed (1% of the machine gave 2.6 fps, 3% gave 150-190).
SPEED = ["-C", "audioSync=1", "-C", "videoSync=0", "-C", "fpsTarget=120"]
MGBA = os.environ.get("MGBA", r"D:\Tools\mGBA-dev\mGBA-build-2026-10-06-win64-9154-3a5e34be33dc7f8f707e5bc9db69e8a430046f21\mGBA.exe")


def running():
    """True once the emulator runs frames: it can listen without running (see launch)."""
    try:
        with socket.create_connection(("127.0.0.1", 8888), timeout=5) as s:
            s.sendall(b"step 1\n")
            return s.recv(64).startswith((b"ok", b"err busy"))  # busy: another client is driving it
    except OSError:
        return False


def serving():
    try:
        socket.create_connection(("127.0.0.1", 8888), timeout=1).close()
        return True
    except OSError:
        return False


def launch(state=None):
    if serving() and running():
        return
    args = [MGBA, *SPEED, "--script", os.path.join(HERE, "probe.lua")]
    if state:
        args += ["-t", os.path.abspath(state)]
    # Through "start" so mGBA has no parent: stopping a runner's process tree mustn't take the emulator with it.
    # Started inside a disconnected remote desktop session, audio sync never runs a frame (no audio device). Rather
    # than run unthrottled, wait and retry: it works again once the session is reconnected.
    while True:
        subprocess.Popen(["cmd", "/c", "start", "", "/belownormal", *args, os.path.join(RUN, "Unbound.gba")])
        for _ in range(30):
            time.sleep(1)
            if serving():
                break
        if serving() and running():
            return
        print("mGBA isn't running frames (disconnected remote desktop session?); retrying in 5 minutes", flush=True)
        subprocess.run(["taskkill", "/IM", "mGBA.exe", "/F"], capture_output=True)
        time.sleep(300)


if __name__ == "__main__":
    launch(*sys.argv[1:2])
    print("bridge up")
