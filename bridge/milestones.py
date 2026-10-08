"""Milestone tracker (#18): records progress events to a JSONL file as the agent plays.

Events: a badge earned, a map visited for the first time, a new species in the party, a new highest
level. Unbound's story flags are undocumented and RetroAchievements sits behind a bot challenge, so
these are what the game itself shows; add flags here as RAM diffing discovers them.

    python milestones.py LOG     # summarise a milestones file
"""
import json
import os
import sys
import time


class Tracker:
    def __init__(self, path):
        self.path = path
        self.seen_maps, self.species, self.badges, self.top_level = set(), set(), 0, 0
        if os.path.exists(path):  # resume: rebuild what's already been recorded
            for line in open(path, encoding="utf-8"):
                e = json.loads(line)
                if e["kind"] == "map":
                    self.seen_maps.add(tuple(e["map"]))
                elif e["kind"] == "species":
                    self.species.add(e["species"])
                elif e["kind"] == "badge":
                    self.badges = max(self.badges, e["badges"])
                elif e["kind"] == "level":
                    self.top_level = max(self.top_level, e["level"])

    def update(self, s, step):
        """S is a get_state() dict. Returns the new events (also appended to the file)."""
        new = []
        here = (s["map"]["group"], s["map"]["num"])
        if here not in self.seen_maps:
            self.seen_maps.add(here)
            new.append({"kind": "map", "map": list(here), "name": s["map"]["name"]})
        if s["badges"] > self.badges:
            self.badges = s["badges"]
            new.append({"kind": "badge", "badges": s["badges"]})
        for m in s["party"]:
            if m.get("partner"):  # an NPC partner's Pokemon, only in the party for a battle
                continue
            if m["species"] not in self.species:
                self.species.add(m["species"])
                new.append({"kind": "species", "species": m["species"]})
            if m["level"] > self.top_level:
                self.top_level = m["level"]
                new.append({"kind": "level", "level": m["level"], "who": m["name"]})
        if new:
            with open(self.path, "a", encoding="utf-8") as f:
                for e in new:
                    f.write(json.dumps({"t": round(time.time()), "step": step, **e}, ensure_ascii=False) + "\n")
        return new


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    events = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    for kind in ("badge", "map", "species", "level"):
        es = [e for e in events if e["kind"] == kind]
        print(f"{kind}: {len(es)}", ", ".join(str(e.get("name") or e.get("species") or e.get("level") or e.get("badges")) for e in es[-8:]))
