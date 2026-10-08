"""python ui/test_server.py: offline checks for the spectator server (no bridge needed)."""
import json
import server as s

# the bridge client refuses anything that isn't a read, before touching the socket
p = s.ReadOnlyProbe.__new__(s.ReadOnlyProbe)
for c in ("press A 4", "step 1", "load x.ss1", "save x.ss1", "autosave d 1"):
    try:
        p.cmd(c)
        raise AssertionError(c)
    except PermissionError:
        pass

ents = s.entities('Prof. Log in Dresco Town wants Ion and a Zubat. #014 Neighbourly Assistance. [[Moltres plan]]', {"Ion"})
assert {("npc", "Prof. Log"), ("map", "Dresco Town"), ("nick", "Ion"), ("species", "Zubat"),
        ("mission", "#014 Neighbourly Assistance"), ("link", "Moltres plan")} <= ents, ents

txt = lambda t: {"content": [{"type": "text", "text": t}]}
assert s.result_label(txt('{"result": "done"}')) == "done"
assert s.result_label(txt(json.dumps([{"key": "UP", "moved": True}, {"key": "UP", "moved": False}]))) == "moved 1/2"
assert s.result_label({"content": "x"}, "Edit") == "saved"
assert s.tool_label("mcp__unbound__walk_to", {"x": 20, "y": 21}) == "walk_to (20, 21)"
assert s.mem_file(r"D:\run\memory\learnings.md") == "learnings.md" and s.mem_file("D:/run/log.jsonl") is None
# exp curves: medium slow Lv10 = 560 (docs/addresses.md, Larvitar); medium fast n^3; the six curves meet at 100
assert s.exp_for(3, 10) == 560 and s.exp_for(0, 25) == 15625 and s.exp_for(5, 1) == 0
assert [s.exp_for(r, 100) for r in range(6)] == [1000000, 600000, 1640000, 1059860, 800000, 1250000]

st = s.Stats(None)
st.log({"t": 1, "step": 1, "tool": "throw_ball", "args": {}, "result": "\"threw a Poke Ball; caught Swinub; a question\""})
st.usage({"t": 2, "cost_usd": 0.5, "models": {"claude-haiku-5-5": {"outputTokens": 10}}})
assert st.s["catches"] == ["Swinub"] and st.s["actions"] == 1 and st.s["tokens"] == {"claude-haiku-5-5": 10}
st.usage({"t": 3, "kind": "watcher", "cost_usd": 0.001})  # a harness call: costs, but isn't a chunk
assert st.s["chunks"] == 1 and abs(st.s["cost"] - 0.501) < 1e-9

# a harness-run call in log.jsonl becomes a router handoff and its return
evs = []
tr = s.Transcript(type("Hub", (), {"emit": lambda self, e, keep=True: evs.append(e)})(), None, None)
tr.harness_call({"t": 5, "step": 40, "harness_call": "watcher", "secs": 6.6, "cost_usd": 0.001, "note": "heal Ion"}, 5)
assert [(e["k"], e["agent"]) for e in evs] == [("spawn", "watcher"), ("return", "watcher")] and evs[1]["text"] == "heal Ion", evs
print("ok")
