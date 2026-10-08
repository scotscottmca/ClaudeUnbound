"""Spectator UI for a run (#98): a local page beside mGBA, viewing only.

    python ui/server.py [--workspace DIR] [--port 8765] [--bridge-port 8888] [--replay [--speed N]]

Tails <workspace>/transcripts/*.jsonl, log.jsonl and memory/*.md and pushes events to the page
over Server-Sent Events. Polls the bridge for the party through ReadOnlyProbe, which can only send
read8/16/32/range. Never writes under the workspace.
"""
import argparse
import glob
import json
import os
import queue
import re
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bridge"))
from probe import Probe  # noqa: E402

NAMES = json.load(open(os.path.join(os.path.dirname(HERE), "bridge", "names.json"), encoding="utf-8"))
TRIGGERS = ("VERIFY before answering", "LEARNING CHECK", "ESCALATE", "WATCHDOG", "VERIFY")


class ReadOnlyProbe:
    """The only bridge client the UI has: reads, nothing that steps, presses, loads or saves."""
    ALLOWED = {"read8", "read16", "read32", "range"}
    read8, read16, read32, range = Probe.read8, Probe.read16, Probe.read32, Probe.range

    def __init__(self, port):
        self.f = socket.create_connection(("127.0.0.1", port), timeout=5).makefile("rw", newline="\n")

    def cmd(self, line):
        if line.split()[0] not in self.ALLOWED:
            raise PermissionError(f"read-only bridge client refused {line.split()[0]!r}")
        return Probe.cmd(self, line)


# ---------------------------------------------------------------- hub: state + SSE fan-out

class Hub:
    def __init__(self, mode):
        self.lock = threading.Lock()
        self.ring = deque(maxlen=400)  # recent feed events, replayed to a new page
        self.clients = []
        self.state = {"mode": mode, "graph": {"nodes": [], "edges": []}, "party": None, "counts": {}, "stats": None}

    def emit(self, ev, keep=True):
        data = json.dumps(ev)
        with self.lock:
            if keep:
                self.ring.append(data)
            for q in self.clients:
                q.put(data)

    def set(self, key, value):
        self.state[key] = value
        self.emit({"k": key, key: value}, keep=False)

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.clients.append(q)
            snap = json.dumps({"k": "snapshot", **self.state, "events": [json.loads(e) for e in self.ring]})
        return q, snap


# ---------------------------------------------------------------- memory graph

SPECIES = {s for s in NAMES["species"] if len(s) >= 4 and s.isalpha() and s[0].isupper()}
MAPS = {m for m in NAMES["mapsecs"].values() if not m.isupper()}
TRAINER = re.compile(r"\b(?:Prof\.|Leader|Rival|Youngster|Lass|Hiker|School Kid|Bug Catcher|Ace Trainer|Camper|"
                     r"Picnicker|Fisherman|Swimmer|Gentleman|Beauty|Sailor|Bird Keeper|Black Belt|Psychic|Ranger|"
                     r"Officer|Elite|Champion|Admin|Breeder|Hex Maniac|Ruin Maniac|Super Nerd|Scientist|Rocker|"
                     r"Biker|Pokefan|Twins|Grunt|Lady|Rich Boy|Tuber|Ninja Boy|Battle Girl|Dragon Tamer|"
                     r"Cooltrainer|Aroma Lady|Kindler|Expert|Collector|Poke Maniac) [A-Z][a-z]+")
KNOWN = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(SPECIES | MAPS, key=len, reverse=True)) + r")\b")
MISSION = re.compile(r"#\d{3} [A-Z][\w' ]+[\w]|\"([A-Z][^\"]{15,80}!)\"")
LINK = re.compile(r"\[\[([^\]|]+)")


def entities(text, nicks):
    out = set()
    for m in KNOWN.findall(text):
        out.add(("map" if m in MAPS else "species", m))
    for m in TRAINER.findall(text):
        out.add(("npc", m))
    for m in MISSION.finditer(text):
        out.add(("mission", m.group(1) or m.group(0)))
    for m in LINK.findall(text):
        out.add(("link", m.strip()))
    for n in nicks:
        if re.search(rf"\b{re.escape(n)}\b", text):
            out.add(("nick", n))
    return out


class Graph:
    def __init__(self, hub, memdir):
        self.hub, self.memdir = hub, memdir
        self.files = {}  # name -> set of (type, name)
        self.nicks = set()
        self.mtimes = {}

    def scan(self):
        """Re-read memory files whose mtime changed. Returns True if the graph changed."""
        changed = False
        for path in glob.glob(os.path.join(self.memdir, "*.md")):
            mt = os.stat(path).st_mtime
            name = os.path.basename(path)
            if self.mtimes.get(name) != mt:
                self.mtimes[name] = mt
                text = open(path, encoding="utf-8", errors="replace").read()
                if name == "team.md":  # "- Ion: Metang Lv24" names the nicknames
                    self.nicks |= {n for n in re.findall(r"^- ([A-Z][a-z]+)[: (]", text, re.M) if n not in SPECIES}
                ents = entities(text, self.nicks)
                if ents != self.files.get(name):
                    self.files[name] = ents
                    changed = True
        return changed

    def add(self, name, text):
        """Grow the graph from an edit seen in the transcript (replay has no file history)."""
        ents = entities(text, self.nicks)
        new = ents - self.files.get(name, set())
        if new or name not in self.files:
            self.files.setdefault(name, set()).update(ents)
            self.publish()
        return sorted(f"{t}:{n}" for t, n in ents)

    def publish(self):
        nodes, edges = {}, []
        for f, ents in self.files.items():
            nodes["file:" + f] = {"id": "file:" + f, "label": f, "type": "file"}
            for t, n in ents:
                nodes[f"{t}:{n}"] = {"id": f"{t}:{n}", "label": n, "type": t}
                edges.append(["file:" + f, f"{t}:{n}"])
        self.hub.set("graph", {"nodes": list(nodes.values()), "edges": edges})


# ---------------------------------------------------------------- transcript -> events

def clip(s, n=90):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1] + "…"


def mem_file(path):
    path = str(path or "").replace("\\", "/")
    return path.rsplit("/", 1)[-1] if "/memory/" in "/" + path or path.startswith("memory/") else None


def tool_label(name, inp):
    n = name.replace("mcp__unbound__", "")
    if n in ("Read", "Write", "Edit"):
        p = str(inp.get("file_path", "")).replace("\\", "/")
        return f"{n} {'/'.join(p.split('/')[-2:])}"
    if n in ("Grep", "Glob"):
        return f"{n} {inp.get('pattern', '')}"
    if n in ("Bash", "PowerShell"):
        return f"{n} {inp.get('command', '')}"
    vals = []
    for v in inp.values():
        vals.append(" ".join(map(str, v)) if isinstance(v, list) else str(v))
    if n == "walk_to" and len(vals) == 2:
        return f"walk_to ({vals[0]}, {vals[1]})"
    return clip(f"{n} {' '.join(vals)}", 70)


def result_label(block, name=""):
    if name in ("Write", "Edit") and not block.get("is_error"):
        return "saved"
    c = block.get("content")
    if isinstance(c, list):
        texts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
        if not texts:
            return "[image]"
        c = texts[0]
    c = str(c or "")
    try:
        d = json.loads(c)
    except ValueError:
        d = None
    if isinstance(d, list) and d and all(isinstance(x, dict) and "moved" in x for x in d):
        return f"moved {sum(bool(x['moved']) for x in d)}/{len(d)}"
    if isinstance(d, dict):
        if "result" in d:
            r = d["result"]
            if isinstance(r, list) and r and all(isinstance(x, dict) and "moved" in x for x in r):
                return f"moved {sum(bool(x['moved']) for x in r)}/{len(r)}"
            return clip(r if isinstance(r, str) else json.dumps(r))
        if "mode" in d:
            m = d.get("map")
            return clip(f"{d['mode']} · {m.get('name') if isinstance(m, dict) else m} {d.get('pos', '')}")
    if re.match(r"\s*1\t", c):
        return f"{c.count(chr(10)) + 1} lines"
    return "error: " + clip(c, 80) if block.get("is_error") else clip(c.splitlines()[0] if c else "ok")


def result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c or "")


class Transcript:
    """Turns stream-json lines into UI events. Shared by live tailing and replay."""

    def __init__(self, hub, graph, learned):
        self.hub, self.graph, self.learned = hub, graph, learned
        self.tools = {}  # tool_use_id -> name (main agent)
        self.spawns = {}  # Agent tool_use_id -> subagent_type
        self.trigger = None

    def line(self, d, t):
        typ = d.get("type")
        parent = d.get("parent_tool_use_id")
        if typ == "assistant":
            msg = d.get("message", {})
            model = msg.get("model")
            if model and model != "<synthetic>":
                counts = self.hub.state["counts"]
                counts[model] = counts.get(model, 0) + 1
                self.hub.set("counts", counts)
            who = self.spawns.get(parent, "subagent") if parent else "main"
            for b in msg.get("content", []):
                if b.get("type") == "text" and not parent and b.get("text", "").strip():
                    self.hub.emit({"k": "text", "t": t, "text": b["text"]})
                elif b.get("type") == "tool_use":
                    self.tool_use(b, parent, who, t)
        elif typ == "user" and not parent and isinstance(d.get("message", {}).get("content"), list):
            for b in d["message"]["content"]:
                if b.get("type") != "tool_result":
                    continue
                name = self.tools.get(b.get("tool_use_id"))
                txt = result_text(b)
                self.hub.emit({"k": "act", "t": t, "who": "main", "what": "thinking", "kind": "think"}, keep=False)
                for trig in TRIGGERS:
                    if trig in txt:
                        self.trigger = trig
                        break
                if name in ("Agent", "Task"):
                    if not txt.startswith("Async agent launched"):
                        self.ret(b["tool_use_id"], txt, t)
                elif name:
                    self.hub.emit({"k": "result", "t": t, "id": b["tool_use_id"], "text": result_label(b, name),
                                   "err": bool(b.get("is_error"))})
        elif typ == "user" and not parent and isinstance(d.get("message", {}).get("content"), str):
            for trig in TRIGGERS:
                if trig in d["message"]["content"]:
                    self.trigger = trig
                    break
        elif typ == "system" and d.get("subtype") == "task_notification":
            self.ret(d.get("tool_use_id"), d.get("summary", ""), t)

    def tool_use(self, b, parent, who, t):
        name, inp = b.get("name", ""), b.get("input", {}) or {}
        self.activity(name, inp, who, t)
        if not parent:
            self.tools[b["id"]] = name
        if name in ("Agent", "Task") and not parent:
            agent = inp.get("subagent_type", "general")
            self.spawns[b["id"]] = agent
            self.hub.emit({"k": "spawn", "t": t, "id": b["id"], "agent": agent,
                           "trigger": self.trigger or "self", "desc": clip(inp.get("description", ""), 60)})
            self.trigger = None
            return
        if not parent:
            self.hub.emit({"k": "tool", "t": t, "id": b["id"], "text": tool_label(name, inp)})
        f = mem_file(inp.get("file_path") or inp.get("path"))
        if f and name in ("Read", "Grep", "Glob"):
            self.hub.emit({"k": "mem", "t": t, "op": "read", "file": f, "who": who})
        elif f and name in ("Write", "Edit"):
            new = inp.get("content") or inp.get("new_string") or ""
            ents = self.graph.add(f, new)
            self.hub.emit({"k": "mem", "t": t, "op": "write", "file": f, "who": who, "ents": ents})
            old = set((inp.get("old_string") or "").splitlines())
            added = [ln for ln in new.splitlines() if ln.strip() and ln not in old and not ln.startswith("#")]
            if f == "learnings.md":
                for ln in added:
                    self.learned(ln, f, who, t, old)
            elif who == "refiner" and added:  # one card per refiner edit, not one per line
                more = f" (+{len(added) - 1} more lines)" if len(added) > 1 else ""
                self.learned(f"{f}: {added[0].strip()}{more}", f, who, t)

    def harness_call(self, d, t):
        """A harness-run model call (bridge/watcher.py), logged to log.jsonl when it ends: a handoff and its return."""
        kind, tid = d["harness_call"], f"h-{d.get('t')}-{d['harness_call']}"
        cost = f" · ${d['cost_usd']:.3f}" if isinstance(d.get("cost_usd"), (int, float)) else ""
        reason = f" · {d['reason']}" if d.get("reason") else ""
        self.spawns[tid] = kind
        self.hub.emit({"k": "spawn", "t": t, "id": tid, "agent": kind, "trigger": "harness",
                       "desc": f"step {d.get('step')}{reason} · {d.get('secs', '?')} s{cost}"})
        self.ret(tid, d.get("note") or (f"failed: {d['error']}" if d.get("error") else "nothing to add"), t)

    def activity(self, name, inp, who, t):
        """What the agent is doing right now, for the status pill (#132): memory reads/edits, subagents, play."""
        f = mem_file(inp.get("file_path") or inp.get("path"))
        n = name.replace("mcp__unbound__", "")
        if f and n in ("Read", "Grep", "Glob"):
            what, kind = f"reading memory: {f}", "read"
        elif f and n in ("Write", "Edit"):
            what, kind = f"writing memory: {f}", "write"
        elif n in ("Agent", "Task"):
            what, kind = f"consulting the {inp.get('subagent_type', 'subagent')}", "wait"
        elif name.startswith("mcp__unbound__"):
            what, kind = tool_label(name, inp), "play"
        else:
            what, kind = n, "other"
        self.hub.emit({"k": "act", "t": t, "who": who, "what": what, "kind": kind, "file": f}, keep=False)

    def ret(self, tid, summary, t):
        agent = self.spawns.get(tid)
        if agent:
            self.hub.emit({"k": "return", "t": t, "id": tid, "agent": agent, "text": clip(summary, 160)})


# ---------------------------------------------------------------- learnings feed

class Learnings:
    def __init__(self, hub):
        self.hub, self.seen = hub, set()

    def __call__(self, line, file, who, t, old=(), quiet=False):
        s = line.strip()
        if not s or s.startswith("#") or s in old or s in self.seen or len(s) < 12:
            return
        self.seen.add(s)
        self.hub.emit({"k": "learn", "t": t, "file": file, "who": who, "text": s.lstrip("-* ").strip(),
                       "quiet": quiet})


# ---------------------------------------------------------------- sources

def iso(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


class Stats:
    """Run totals from log.jsonl and usage.jsonl lines, fed incrementally."""

    def __init__(self, hub):
        self.hub = hub
        self.s = {"actions": 0, "catches": [], "first": None, "last": None, "cost": 0.0, "chunks": 0,
                  "costed": 0, "tokens": {}}

    def log(self, d):
        s = self.s
        s["first"] = s["first"] or d.get("t")
        s["last"] = d.get("t") or s["last"]
        if "result" in d:
            s["actions"] += 1
            m = d["tool"] == "throw_ball" and re.search(r"caught ([\w' .-]+?)[;\"]", str(d["result"]))
            if m:
                s["catches"].append(m.group(1))

    def usage(self, d):
        s = self.s
        s["chunks"] += 0 if d.get("kind") else 1  # "kind": a harness-run watcher/verifier/curator call, not a chunk
        if d.get("cost_usd") is not None:
            s["cost"] += d["cost_usd"]
            s["costed"] += 0 if d.get("kind") else 1  # chunks with a reported cost (harness calls are extra)
        for model, u in (d.get("models") or d.get("usage") or {}).items():
            if isinstance(u, dict) and model.startswith("claude"):
                out = u.get("outputTokens", u.get("output_tokens", 0))
                s["tokens"][model] = s["tokens"].get(model, 0) + out

    def publish(self):
        if self.s != self.hub.state.get("stats"):
            self.hub.set("stats", json.loads(json.dumps(self.s)))


def party_from_now(now, t):
    party = []
    for p in now.get("party", []):
        name, _, hp = p.rpartition(" ")
        party.append({"name": name, "hp": hp})
    return {"src": "log", "t": t, "mode": now.get("mode"), "map": now.get("map"), "pos": now.get("pos"),
            "badges": now.get("badges"), "party": party}


# Gen 3 experience curves by growth rate (base stats +0x13): 0 medium fast, 1 erratic, 2 fluctuating,
# 3 medium slow, 4 fast, 5 slow. Total exp needed to reach level n.
def exp_for(rate, n):
    if n <= 1:
        return 0
    if rate == 1:
        return (n ** 3 * (100 - n) // 50 if n <= 50 else n ** 3 * (150 - n) // 100 if n <= 68
                else n ** 3 * ((1911 - 10 * n) // 3) // 500 if n <= 98 else n ** 3 * (160 - n) // 100)
    if rate == 2:
        return (n ** 3 * ((n + 1) // 3 + 24) // 50 if n <= 15 else n ** 3 * (n + 14) // 50 if n <= 36
                else n ** 3 * (n // 2 + 32) // 50)
    if rate == 3:
        return 6 * n ** 3 // 5 - 15 * n ** 2 + 100 * n - 140
    return {4: 4 * n ** 3 // 5, 5: 5 * n ** 3 // 4}.get(rate, n ** 3)


BASE_STATS = 0x099E0C9C  # ROM, 0x1C per species; growth rate +0x13 (docs/addresses.md)
DEX_OWNED = 0x38D  # SaveBlock1 offset: 0x7D bytes, bit n-1 = national dex n (docs/addresses.md)


def extras(p, s, rates, state):
    """Exp progress per member, play time and Pokedex owned count: a few more reads."""
    n = len(s["party"])
    raw = p.range(state.PLAYER_PARTY, 100 * n) if n else b""
    for i, mon in enumerate(s["party"]):
        m = raw[i * 100:(i + 1) * 100]
        sp, exp = int.from_bytes(m[0x20:0x22], "little"), int.from_bytes(m[0x24:0x28], "little")
        if sp not in rates:
            rates[sp] = p.read8(BASE_STATS + 0x1C * sp + 0x13)
        lo, hi = exp_for(rates[sp], m[0x54]), exp_for(rates[sp], m[0x54] + 1)
        mon["exp"] = [exp - lo, hi - lo] if lo <= exp <= hi and m[0x54] < 100 else None  # None: curve unproven
    t = p.range(p.read32(state.SB2_PTR) + 0x0E, 3)
    s["playtime"] = [t[0] | t[1] << 8, t[2]]
    s["dex_owned"] = sum(bin(b).count("1") for b in p.range(p.read32(state.SB1_PTR) + DEX_OWNED, 0x7D))


def bridge_loop(hub, port, live_flag):
    import state
    p, last, rates = None, None, {}
    while True:
        try:
            p = p or ReadOnlyProbe(port)
            s = state.get_state(p)
            s.pop("bag", None)
            extras(p, s, rates, state)
            s["src"], s["t"] = "bridge", time.time()
            live_flag[0] = True
            if json.dumps({**s, "t": 0}) != last:
                last = json.dumps({**s, "t": 0})
                hub.set("party", s)
            time.sleep(1.5)
        except Exception as e:  # bridge down or busy: drop the socket, fall back to log.jsonl
            if live_flag[0]:
                print("bridge:", e, file=sys.stderr)
            live_flag[0], p, last = False, None, None
            time.sleep(5)


class Tail:
    """Incremental reader: only complete new lines, from a remembered offset."""

    def __init__(self, path, offset=0):
        self.path, self.off, self.buf = path, offset, b""

    def lines(self):
        try:
            if os.path.getsize(self.path) <= self.off:
                return []
            with open(self.path, "rb") as f:
                f.seek(self.off)
                data = f.read()
        except OSError:
            return []
        self.off += len(data)
        *done, self.buf = (self.buf + data).split(b"\n")
        out = []
        for ln in done:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out


def live_loop(hub, ws, graph, tr, learned, live_flag, stats):
    tdir = os.path.join(ws, "transcripts")
    files = sorted(glob.glob(os.path.join(tdir, "*.jsonl")))
    # model counts for the whole run, cheaply; the newest chunk is replayed in full below
    counts = hub.state["counts"]
    for f in files[:-1]:
        for m in re.findall(rb'"type": "assistant", "message": \{"model": "([^"]+)"', open(f, "rb").read()):
            counts[m.decode()] = counts.get(m.decode(), 0) + 1
    cur = Tail(files[-1]) if files else None
    logp = os.path.join(ws, "log.jsonl")
    log, usage = Tail(logp), Tail(os.path.join(ws, "usage.jsonl"))
    learnp = os.path.join(ws, "memory", "learnings.md")
    learn_mt = None
    if os.path.exists(learnp):  # existing learnings: the last few as quiet history, none pop
        lines = open(learnp, encoding="utf-8", errors="replace").read().splitlines()
        for ln in lines[-8:]:
            learned(ln, "learnings.md", "file", os.stat(learnp).st_mtime, quiet=True)
        learned.seen.update(x.strip() for x in lines)
        learn_mt = os.stat(learnp).st_mtime
    while True:
        if cur:
            for d in cur.lines():
                tr.line(d, iso(d.get("timestamp")) or time.time())
            newest = max(glob.glob(os.path.join(tdir, "*.jsonl")), default=cur.path)
            if newest != cur.path:  # rotation: the old chunk is drained above, follow the new one
                cur = Tail(newest)
        elif glob.glob(os.path.join(tdir, "*.jsonl")):
            cur = Tail(max(glob.glob(os.path.join(tdir, "*.jsonl"))))
        now = None
        for d in log.lines():
            now = d.get("now") and (d["now"], d["t"]) or now
            stats.log(d)
            if d.get("harness_call"):
                tr.harness_call(d, d.get("t") or time.time())
        for d in usage.lines():
            stats.usage(d)
        stats.publish()
        if now and not live_flag[0]:
            hub.set("party", party_from_now(*now))
        if graph.scan():
            graph.publish()
        try:
            mt = os.stat(learnp).st_mtime
            if mt != learn_mt:
                learn_mt = mt
                for ln in open(learnp, encoding="utf-8", errors="replace").read().splitlines():
                    learned(ln, "learnings.md", "file", time.time())
        except OSError:
            pass
        time.sleep(0.5)


def replay_loop(hub, ws, graph, tr, speed, live_flag, stats):
    timeline = []
    for f in sorted(glob.glob(os.path.join(ws, "transcripts", "*.jsonl"))):
        t = None
        for ln in open(f, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            t = iso(d.get("timestamp")) or t
            if t:
                timeline.append((t, 0, d))
    logp = os.path.join(ws, "log.jsonl")
    if os.path.exists(logp):
        for ln in open(logp, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            timeline.append((d["t"], 1, d))
    up = os.path.join(ws, "usage.jsonl")
    if os.path.exists(up):
        for ln in open(up, encoding="utf-8", errors="replace"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            timeline.append((d["t"], 2, d))
    timeline.sort(key=lambda x: (x[0], x[1]))
    print(f"replay: {len(timeline)} events", file=sys.stderr)
    prev = None
    for t, src, d in timeline:
        if prev is not None:
            time.sleep(min(t - prev, 30) / speed[0])
        prev = t
        if src == 0:
            tr.line(d, t)
        elif src == 2:
            stats.usage(d)
            stats.publish()
        else:
            stats.log(d)
            stats.publish()
            if d.get("harness_call"):
                tr.harness_call(d, t)
            if d.get("now") and not live_flag[0]:
                hub.set("party", party_from_now(d["now"], t))
    hub.emit({"k": "text", "t": time.time(), "text": "[replay finished]"})


# ---------------------------------------------------------------- HTTP

def serve(hub, port, speed):
    page = os.path.join(HERE, "index.html")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                body = open(page, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/speed":
                speed[0] = max(0.1, float(parse_qs(u.query).get("x", ["1"])[0]))
                self.send_response(204)
                self.end_headers()
            elif u.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q, snap = hub.subscribe()
                try:
                    self.wfile.write(f"data: {snap}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            data = q.get(timeout=15)
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        else:
                            self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                except OSError:
                    pass
                finally:
                    with hub.lock:
                        hub.clients.remove(q)
            else:
                self.send_error(404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.daemon_threads = True
    print(f"spectator UI: http://127.0.0.1:{port}/", file=sys.stderr)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=r"D:\ClaudeUnboundRuns\full1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bridge-port", type=int, default=8888)
    ap.add_argument("--replay", action="store_true", help="stream the run's history instead of following it")
    ap.add_argument("--speed", type=float, default=20, help="replay speed multiplier")
    ap.add_argument("--mock", type=float, nargs="?", const=60, metavar="SECONDS",
                    help="a scripted fake run (default 60 s): no bridge, temp memory dir, nothing real touched")
    a = ap.parse_args()
    if a.mock:
        import mock
        ws = mock.workspace()
        hub = Hub("mock")
        graph = Graph(hub, os.path.join(ws, "memory"))
        learned = Learnings(hub)
        stats = Stats(hub)
        m = mock.Mock(hub, graph, Transcript(hub, graph, learned), stats, a.mock)
        threading.Thread(target=m.run, daemon=True).start()
        serve(hub, a.port, [1])
        return
    ws = os.path.abspath(a.workspace)
    hub = Hub(f"replay x{a.speed:g}" if a.replay else "live")
    graph = Graph(hub, os.path.join(ws, "memory"))
    graph.scan()
    graph.publish()
    learned = Learnings(hub)
    tr = Transcript(hub, graph, learned)
    live_flag, speed, stats = [False], [a.speed], Stats(hub)
    threading.Thread(target=bridge_loop, args=(hub, a.bridge_port, live_flag), daemon=True).start()
    if a.replay:
        threading.Thread(target=replay_loop, args=(hub, ws, graph, tr, speed, live_flag, stats), daemon=True).start()
    else:
        threading.Thread(target=live_loop, args=(hub, ws, graph, tr, learned, live_flag, stats), daemon=True).start()
    serve(hub, a.port, speed)


if __name__ == "__main__":
    main()
