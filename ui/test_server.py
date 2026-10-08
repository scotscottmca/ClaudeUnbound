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
print("ok")
