"""Start mGBA with the bridge script unless one is already running (then attach; never a second instance).

    python launch.py [STATE]    # STATE: savestate to load at start (default: none, resume the in-game save)
    python launch.py --detach NAME [--min] COMMAND LINE...   # run anything (the runner, the spectator) the same way

Needs an mGBA build with --script (0.11 / dev builds). Set MGBA to its mGBA.exe.
"""
import os
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "..", "run")
# User: never faster than 2x. mGBA's own limiter (audio sync at a 120 fps target) holds exactly 120 fps at ~2.4% CPU;
# CPU caps don't set speed (1% of the machine gave 2.6 fps, 3% gave 150-190).
SPEED = ["-C", "audioSync=1", "-C", "videoSync=0", "-C", "fpsTarget=120"]
PORT = int(os.environ.get("UNBOUND_PORT", 8888))
MGBA = os.environ.get("MGBA", r"D:\Tools\mGBA-dev\mGBA-build-2026-10-06-win64-9154-3a5e34be33dc7f8f707e5bc9db69e8a430046f21\mGBA.exe")


def running():
    """True once the emulator runs frames: it can listen without running (see launch)."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=5) as s:
            s.sendall(b"step 1\n")
            return s.recv(64).startswith((b"ok", b"err busy"))  # busy: another client is driving it
    except OSError:
        return False


def serving():
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        return True
    except OSError:
        return False


def mgba_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mGBA.exe", "/NH"], capture_output=True, text=True).stdout
    return "mgba.exe" in out.lower()


def detached(name, line, cwd=HERE, minimized=False):
    """Start the command LINE through WMI (Win32_Process.Create), so it belongs to no one: its parent is the WMI
    service, not whatever called this, and it outlives it. Started from a Claude Code shell, mGBA was ended along
    with the app when the app updated itself (2026-10-09 06:20:30, #151). It runs in the caller's desktop session.
    Returns the new process id. (Task Scheduler was tried first: its tasks failed with result 1 on this machine.)"""
    first, _, rest = line.partition(" ")
    if not first.startswith('"') and shutil.which(first):  # WMI doesn't search PATH ("python": error 9, not found)
        line = subprocess.list2cmdline([shutil.which(first)]) + (" " + rest if rest else "")
    q = lambda v: "'" + str(v).replace("'", "''") + "'"  # noqa: E731 PowerShell single-quoted string
    ps = ("$s = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]"
          f"{7 if minimized else 1}}}; $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
          f"@{{CommandLine={q(line)}; CurrentDirectory={q(os.path.abspath(cwd))}; ProcessStartupInformation=$s}}; "
          "\"$($r.ReturnValue) $($r.ProcessId)\"")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()
    if not out or out[0] != "0":
        raise SystemExit(f"could not start {name}: WMI Win32_Process.Create returned {out}")
    return int(out[1])


def launch(state=None):
    """Start mGBA only if none is running. A running one is attached to, never restarted: even a paused
    emulator (which serves but runs no frames) is the live run. Only one mGBA may ever run (user rule)."""
    if mgba_running():
        if serving():
            return
        sys.exit(f"an mGBA is running but nothing serves 127.0.0.1:{PORT}: refusing to start a second one. "
                 "Load bridge/probe.lua into it (Tools > Scripting) or close it yourself.")
    args = [MGBA, *SPEED, "--script", os.path.join(HERE, "probe.lua")]
    if state:
        args += ["-t", os.path.abspath(state)]
    # Through WMI (detached), so mGBA has no parent: stopping a runner's process tree, or the Claude app
    # updating itself, mustn't take the emulator with it. Normal priority: below-normal starved its display (#144).
    # Started inside a disconnected remote desktop session, audio sync never runs a frame (no audio device). Rather
    # than run unthrottled, wait and retry: it works again once the session is reconnected.
    while True:
        detached("mgba", subprocess.list2cmdline([*args, os.path.abspath(os.path.join(RUN, "Unbound.gba"))]))
        for _ in range(30):
            time.sleep(1)
            if serving():
                break
        if serving() and running():
            return
        print("mGBA isn't running frames (disconnected remote desktop session?); retrying in 5 minutes", flush=True)
        subprocess.run(["taskkill", "/IM", "mGBA.exe", "/F"], capture_output=True)  # the one just started: none ran before
        time.sleep(300)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--detach"]:
        rest = sys.argv[3:]
        minimized = rest[:1] == ["--min"]
        pid = detached(sys.argv[2], " ".join(rest[minimized:]), os.getcwd(), minimized)
        print(f"started {sys.argv[2]} (pid {pid}), detached")
    else:
        launch(*sys.argv[1:2])
        print("bridge up")
