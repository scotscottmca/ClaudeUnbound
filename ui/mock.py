"""Scripted mock run for the spectator UI: python ui/server.py --mock [SECONDS]

Feeds synthetic stream-json, log and usage lines through the same Transcript/Stats/Graph code as live mode,
plus party snapshots shaped like state.get_state(). No bridge, no emulator, nothing under a real workspace:
memory files live in a temp dir.
"""
import copy
import itertools
import os
import random
import tempfile
import time

MAIN, SONNET, OPUS, FABLE = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"
SEED = {
    "objectives.md": "# Objectives\n\n- Goal: earn 8 badges. Badges: 1 (Leaf Badge, Leader Mirskle).\n"
                     "- Next gym: Crater Town (Dark). Route: Route 4 -> Cinder Volcano -> Route 5 -> Crater Town.\n"
                     "- Mission: \"Make a beeline for Cinder Volcano and save Moltres!\"\n",
    "team.md": "# Team\n\n- Ion: Metang Lv25 (Steel/Psychic), lead.\n- Makuhita: Makuhita Lv23, Fighting.\n"
               "- Batty: Zubat Lv21.\n- Frost: Swinub Lv18.\n- Pip: Patrat Lv17.\n",
    "opponents.md": "# Opponents\n\n- Leader Mirskle (Dresco Town): Flabebe, Gloom. Beaten.\n"
                    "- Kindler Daniel (Dresco Town): Litleo.\n- Wild Salandit in Cinder Volcano burns.\n",
    "map_notes.md": "# Map notes\n\n## Cinder Volcano\n- 1F east entrance from Route 4.\n"
                    "## Grim Woods\n- West exit via the ledge and 0x7F hops south of the pond.\n",
    "npcs.md": "# NPCs\n\n- Prof. Log (Frozen Heights): gave the Pokedex.\n- Route 2 healer (53,13).\n",
    "learnings.md": "# Learnings\n\n- Check the bag before leaving a shop town: 0 balls means lost catches.\n",
}
PARTY = [
    {"name": "Ion", "species": "Metang", "level": 25, "hp": [70, 70], "status": None, "item": None, "exp": [300, 1393]},
    {"name": "Makuhita", "species": "Makuhita", "level": 23, "hp": [73, 73], "status": None, "item": "Black Belt", "exp": [500, 1388]},
    {"name": "Batty", "species": "Zubat", "level": 21, "hp": [55, 55], "status": None, "item": None, "exp": [700, 1662]},
    {"name": "Frost", "species": "Swinub", "level": 18, "hp": [48, 48], "status": None, "item": "Never-Melt Ice", "exp": [900, 1333]},
    {"name": "Pip", "species": "Patrat", "level": 17, "hp": [44, 44], "status": None, "item": None, "exp": [400, 1018]},
]


class Mock:
    def __init__(self, hub, graph, tr, stats, seconds):
        self.hub, self.graph, self.tr, self.stats = hub, graph, tr, stats
        self.seconds, self.ids = seconds, itertools.count(1)
        self.party, self.foe = copy.deepcopy(PARTY), None
        self.st = {"mode": "overworld", "map": "Cinder Volcano", "pos": [30, 6], "badges": 1, "money": 14096,
                   "playtime": [4, 46], "dex_owned": 12}
        self.mem = graph.memdir
        self.t0 = time.time()

    # -- raw lines, as the real run writes them
    def say(self, text, model=MAIN, parent=None):
        self.tr.line({"type": "assistant", "parent_tool_use_id": parent,
                      "message": {"model": model, "content": [{"type": "text", "text": text}]}}, time.time())

    def call(self, name, inp, result, model=MAIN, parent=None, log=True):
        tid = f"mock_{next(self.ids)}"
        self.tr.line({"type": "assistant", "parent_tool_use_id": parent,
                      "message": {"model": model, "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}},
                     time.time())
        if not parent:
            self.tr.line({"type": "user", "parent_tool_use_id": None, "message": {"content": [
                {"type": "tool_result", "tool_use_id": tid, "content": result}]}}, time.time())
        if log and name.startswith("mcp__unbound__"):
            self.stats.log({"t": time.time(), "tool": name.replace("mcp__unbound__", ""), "result": result})
            self.stats.publish()
        return tid

    def game(self, name, inp, result, note=None):
        """An MCP game tool; NOTE is a harness note appended to the result, as the server does."""
        return self.call("mcp__unbound__" + name, inp, result + (f'\n{{"harness": ["{note}"]}}' if note else ""))

    def spawn(self, agent, desc, model, work, summary):
        tid = self.call("Agent", {"subagent_type": agent, "description": desc, "prompt": desc},
                        "Async agent launched successfully.", log=False)
        for step in work:
            step(tid, model)
        self.tr.line({"type": "system", "subtype": "task_notification", "tool_use_id": tid, "summary": summary},
                     time.time())

    def mem_read(self, f, parent=None, model=MAIN):
        self.call("Read", {"file_path": f"{self.mem}/{f}"}, f"1\t# {f}", model=model, parent=parent, log=False)

    def mem_edit(self, f, line, parent=None, model=MAIN):
        path = os.path.join(self.mem, f)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.call("Edit", {"file_path": path, "old_string": "", "new_string": line}, "ok", model=model,
                  parent=parent, log=False)
        self.graph.scan()

    # -- party snapshot, shaped like state.get_state() + the UI's extras
    def snap(self):
        party = [{**p, "hp": f"{p['hp'][0]}/{p['hp'][1]}"} for p in self.party]
        s = {**self.st, "map": {"name": self.st["map"]}, "party": party, "src": "mock", "t": time.time()}
        if self.foe:
            s["battle"] = {"battlers": [{"side": "opponent", **self.foe, "hp": f"{self.foe['hp'][0]}/{self.foe['hp'][1]}"}]}
        self.hub.set("party", s)

    def hit(self, who, dmg):
        p = self.party[who]
        p["hp"][0] = max(0, p["hp"][0] - dmg)

    def foe_hit(self, dmg):
        self.foe["hp"][0] = max(0, self.foe["hp"][0] - dmg)

    def gain(self, who, exp):
        p = self.party[who]
        p["exp"][0] += exp
        if p["exp"][0] >= p["exp"][1]:
            p["exp"][0] -= p["exp"][1]
            p["level"] += 1
            p["hp"][1] += 3
            p["hp"][0] += 3

    # -- the scripted minute
    def script(self):
        g = self.game
        yield lambda: (self.mem_read("objectives.md"), self.mem_read("team.md"))
        yield lambda: self.say("Back in Cinder Volcano. The mission says save Moltres; my objectives route me "
                               "through 2F to the summit. Ion leads, and Makuhita covers Fire types with Thick Fat.")
        yield lambda: g("get_state", {}, '{"mode": "overworld", "map": {"name": "Cinder Volcano"}, "pos": [30, 6]}')

        def wild():
            self.foe = {"name": "Numel", "species": "Numel", "level": 19, "hp": [52, 52], "types": ["Fire", "Ground"]}
            self.st.update(mode="battle", pos=[33, 9])
            self.snap()
            g("travel_to", {"map": "Cinder Volcano 2F"}, '{"result": "stopped: wild battle started. Battle it, and '
              'catch it if you have Poke Balls."}')
        yield wild
        yield lambda: self.say("A wild Numel (Fire/Ground). Fire beats Steel, so I'll switch to Makuhita, which takes "
                               "Fire hits well, and weaken it for a catch.")
        yield lambda: (g("switch_to", {"pokemon": "Makuhita"}, '{"result": "sent in Makuhita; your next turn"}'),
                       self.party.insert(0, self.party.pop(1)), self.snap())
        yield lambda: (g("fight", {"move": "Arm Thrust"}, '{"result": "used Arm Thrust; your next turn"}'),
                       self.foe_hit(30), self.hit(0, 11), self.snap())
        yield lambda: (g("throw_ball", {"ball": "Poke Ball"}, '{"result": "threw a Poke Ball; it broke free; your next turn"}'),
                       self.hit(0, 9), self.snap())
        yield lambda: (g("throw_ball", {"ball": "Poke Ball"}, '{"result": "threw a Poke Ball; caught Numel; the game asks '
                         '\'Give a nickname to the captured Numel?\'"}'),
                       self.foe_hit(0), self.gain(0, 420), self.st.update(dex_owned=13), self.snap())
        yield lambda: g("type_name", {"name": "Cinder"}, '{"typed": "Cinder"}')
        yield lambda: (setattr(self, "foe", None), self.st.update(mode="overworld"), self.snap(),
                       self.mem_edit("team.md", "- Cinder: Numel Lv19 (Fire/Ground), caught on Cinder Volcano 2F, in the PC."))

        def verify():
            self.game("walk_to", {"x": 41, "y": 12}, '{"result": "done"}', note="VERIFY (action 20): ask the verifier")
            self.spawn("verifier", "Verify the volcano route and team", SONNET, [
                lambda tid, m: self.say("Checking state against the plan: position, party HP, objectives.", m, tid),
                lambda tid, m: self.mem_read("objectives.md", tid, m),
                lambda tid, m: self.call("mcp__unbound__get_state", {}, "{}", m, tid, log=False),
            ], "APPROVE: on route to 2F, party healthy; Frost should stay benched in here (Ice/Ground vs Fire).")
        yield verify
        yield lambda: self.say("The verifier agrees. Frost stays on the bench in the volcano.")
        yield lambda: (self.st.update(map="Cinder Volcano", pos=[44, 18]), self.snap(),
                       g("walk_to", {"x": 44, "y": 18}, '{"result": "stopped: a script or dialog started"}'))

        def trainer():
            self.foe = {"name": "Magmar", "species": "Magmar", "level": 24, "hp": [71, 71], "types": ["Fire"]}
            self.st.update(mode="battle")
            self.snap()
            g("advance_dialog", {}, '{"boxes": ["Hiker Rocco: The volcano tests the strong!"], "now": "battle"}',
              note="ESCALATE to the strategist subagent: trainer battle against a close-level foe")
        yield trainer
        yield lambda: self.spawn("strategist", "Plan vs Hiker Rocco's Magmar", OPUS, [
            lambda tid, m: self.mem_read("opponents.md", tid, m),
            lambda tid, m: self.say("Magmar Lv24, Fire. Makuhita's Fighting moves are neutral; Thick Fat halves Fire. "
                                    "Lead Makuhita, Arm Thrust, switch to Ion only if a Fighting resist shows up.", m, tid),
        ], "PLAN: Makuhita leads with Arm Thrust; Ion as backup; no Frost.")
        yield lambda: (g("fight", {"move": "Arm Thrust"}, '{"result": "used Arm Thrust; your next turn"}'),
                       self.foe_hit(28), self.hit(0, 18), self.snap())
        yield lambda: (g("fight", {"move": "Arm Thrust"}, '{"result": "used Arm Thrust; your next turn"}'),
                       self.foe_hit(25), self.hit(0, 22), self.party[0].update(status="burned"), self.snap())
        yield lambda: (g("use_item", {"item": "Potion", "pokemon": "Makuhita"},
                         '{"result": "Potion on Makuhita: 19/73 -> 39/73"}'), self.party[0]["hp"].__setitem__(0, 39), self.snap())
        yield lambda: (g("fight", {"move": "Arm Thrust"}, '{"result": "used Arm Thrust; the battle is over"}'),
                       self.foe_hit(99), self.gain(0, 800), self.snap())
        yield lambda: (setattr(self, "foe", None), self.st.update(mode="overworld", money=self.st["money"] + 960),
                       self.snap(), self.mem_edit("opponents.md", "- Hiker Rocco (Cinder Volcano 2F): Magmar Lv24. Beaten "
                                                  "with Makuhita (Thick Fat); burn is the risk."))
        yield lambda: g("advance_dialog", {}, '{"boxes": ["You defeated Hiker Rocco!"], "now": "overworld"}',
                        note="LEARNING CHECK (action 40): review what happened")

        def learn():
            self.spawn("refiner", "Review the last stretch", OPUS, [
                lambda tid, m: self.mem_read("learnings.md", tid, m),
                lambda tid, m: self.mem_edit("learnings.md", "- Lead Makuhita vs Fire trainers: Thick Fat halves Fire "
                                             "damage; carry Burn Heals into Cinder Volcano.", tid, m),
                lambda tid, m: self.mem_edit("map_notes.md", "- Cinder Volcano 2F: Hiker Rocco at (44,18); summit "
                                             "stairs north-west.", tid, m),
            ], "Recorded 1 learning and the 2F layout; advice: buy Burn Heals before the summit.")
        yield learn
        yield lambda: (self.mem_edit("learnings.md", "- A burned lead loses Attack: heal the burn before trainer fights."),)
        yield lambda: (g("walk_to", {"x": 12, "y": 3}, '{"result": "no path"}'),)
        yield lambda: g("press_buttons", {"buttons": ["UP"]}, '[{"key": "UP", "moved": false, "changed": []}]',
                        note="WATCHDOG: nothing has changed for 15 actions. Stop and reflect")

        def stuck():
            self.spawn("expert", "Stuck below the summit stairs", FABLE, [
                lambda tid, m: self.mem_read("map_notes.md", tid, m),
                lambda tid, m: self.say("The stairs tile is elevation 0; approach from the east ledge instead.", m, tid),
            ], "Route found: east ledge (14,5) then UP onto the stairs.")
        yield stuck
        yield lambda: (self.st.update(map="Cinder Volcano", pos=[13, 2]), self.snap(),
                       g("walk_to", {"x": 13, "y": 2}, '{"result": "done"}'),
                       self.mem_edit("learnings.md", "- When walk_to says no path near stairs, check elevation-0 "
                                     "tiles and approach from another side."))
        yield lambda: self.say("Up the stairs. Moltres should be at the summit; I'll save it and then head down "
                               "the west side to Route 5 and Crater Town.")
        yield lambda: (self.st.update(map="Crater Town", pos=[20, 14]), self.party[0].update(status=None),
                       [p["hp"].__setitem__(0, p["hp"][1]) for p in self.party], self.snap(),
                       g("travel_to", {"map": "Crater Town"}, '{"result": "done"}'))
        yield lambda: self.mem_edit("objectives.md", "- Reached Crater Town; healed. Gym next (Dark): Makuhita leads.")
        yield lambda: (self.st.update(mode="battle"), setattr(self, "foe", {"name": "Umbreon", "species": "Umbreon",
                       "level": 23, "hp": [80, 80], "types": ["Dark"]}), self.snap(),
                       g("advance_dialog", {}, '{"boxes": ["Leader: Show me your vision!"], "now": "battle"}'))
        yield lambda: (g("fight", {"move": "Arm Thrust"}, '{"result": "used Arm Thrust; your next turn"}'),
                       self.foe_hit(45), self.hit(0, 25), self.snap())
        yield lambda: (g("fight", {"move": "Arm Thrust"}, '{"result": "used Arm Thrust; the battle is over"}'),
                       self.foe_hit(99), self.gain(0, 1500), self.gain(1, 600), self.snap())
        yield lambda: (setattr(self, "foe", None), self.st.update(mode="overworld", badges=2, money=self.st["money"] + 2300),
                       self.snap(), self.say("Vision Badge earned. Two down."),
                       self.mem_edit("objectives.md", "- Badges: 2 (Vision Badge, Crater Town)."))
        yield lambda: self.stats.usage({"t": time.time(), "cost_usd": 0.42, "models": {
            MAIN: {"outputTokens": 9100}, SONNET: {"outputTokens": 2100}, OPUS: {"outputTokens": 3300},
            FABLE: {"outputTokens": 900}}}) or self.stats.publish()

    def run(self):
        for f, content in SEED.items():
            with open(os.path.join(self.mem, f), "w", encoding="utf-8") as fh:
                fh.write(content)
        self.graph.scan()
        self.graph.publish()
        self.snap()
        self.stats.usage({"t": time.time(), "cost_usd": 2.31, "models": {MAIN: {"outputTokens": 122000},
                          SONNET: {"outputTokens": 22000}, OPUS: {"outputTokens": 21000}}})
        self.stats.publish()
        while not self.hub.clients:  # start the minute when someone is watching
            time.sleep(0.2)
        time.sleep(1.5)
        self.t0 = time.time()
        steps = list(self.script())
        gap = self.seconds / len(steps)
        for i, step in enumerate(steps):
            time.sleep(max(0, self.t0 + i * gap + random.uniform(0, gap * 0.3) - time.time()))
            step()
            h, m = divmod(self.st["playtime"][0] * 60 + self.st["playtime"][1] + 1, 60)  # a game minute per step
            self.st["playtime"] = [h, m]
        self.hub.emit({"k": "text", "t": time.time(), "text": f"[mock run finished after {self.seconds:g}s]"})


def workspace():
    ws = tempfile.mkdtemp(prefix="unbound-mock-")
    os.makedirs(os.path.join(ws, "memory"))
    return ws
