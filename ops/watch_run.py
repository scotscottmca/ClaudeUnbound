"""Quiet run monitor for the operator session (docs/operator-runbook.md). One process, so there are no tail.exe
children to leak when a Claude Code Monitor expires (32 leaked once, #147).

    python ops/watch_run.py [WORKSPACE]    # default D:/ClaudeUnboundRuns/full1; console log = WORKSPACE + ".console.log"

Prints one line per event worth the operator's attention:
- runner lines from the console log: stops, budget/usage alarms, tracebacks, retries (never the agent's or tools' lines);
- from WORKSPACE/log.jsonl: errors, WATCHDOG notes, failed hot reloads, badges;
- every 60 s: whether an agent/run.py process exists (reports a stop or a start).
"""
import json
import os
import re
import subprocess
import sys
import time

WS = os.path.normpath(sys.argv[1] if len(sys.argv) > 1 else "D:/ClaudeUnboundRuns/full1")
CONSOLE = re.compile(r"goal reached|budget alarm|usage window|relaunched|Traceback|Error|max chunks|retrying|stalled")
QUIET = re.compile(r"^ +(agent|tool|model):")


def follow(path):
    f = open(path, encoding="utf-8", errors="replace")
    f.seek(0, os.SEEK_END)
    return f


def runner_alive():
    cmd = ("(Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | "
           "Where-Object { $_.CommandLine -match 'agent[\\\\/]run\\.py' }).Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()
    return out not in ("", "0")


con, log = follow(WS + ".console.log"), follow(os.path.join(WS, "log.jsonl"))
alive, checked = runner_alive(), 0.0
print(f"watching {WS} (runner {'running' if alive else 'NOT running'})", flush=True)
while True:
    for line in con.readlines():
        if CONSOLE.search(line) and not QUIET.match(line):
            print("RUNNER: " + line.rstrip()[:220], flush=True)
    for line in log.readlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        now = e.get("now") if isinstance(e.get("now"), dict) else {}
        where = f"{now.get('map')} {now.get('map_id')} {now.get('pos')} {now.get('mode')}"
        if "FAILED" in str(e.get("harness_reload", "")):
            print(f"RELOAD FAILED: {e['harness_reload'][:200]}", flush=True)
        if e.get("error"):
            print(f"ERROR step {e.get('step')} {e.get('tool')}: {str(e['error'])[:200]} | {where}", flush=True)
        for n in e.get("harness") or []:
            if n.startswith(("WATCHDOG", "HARNESS UPDATE FAILED")) or '"kind": "badge"' in n:
                print(f"step {e.get('step')} | {where} | {n[:180]}", flush=True)
    if time.time() - checked > 60:
        checked = time.time()
        a = runner_alive()
        if a != alive:
            print("RUNNER " + ("started" if a else "STOPPED: no agent/run.py process"), flush=True)
            alive = a
    time.sleep(2)
