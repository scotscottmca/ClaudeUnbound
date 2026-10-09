"""clear_obstacle (#166): Cut a tree or smash a rock in one call.

Unbound rule (verified live on Route 2, 2026-10-09): with the HM in the TM Case and a party Pokemon that could learn
the move (it needn't know it), pressing A while facing the obstacle uses the move at once: no party menu, no
question. Breakable rock (object graphics 96, Route 2 (40,25)): gone, and a wild Pokemon may jump out (a Binacle did).
Cut tree (graphics 95, Route 2 (32,29)): gone. A Strength boulder is activated the same way; then push it by walking.
"""
import party_menu as pm
import world as W
from state import get_state, raw

OBSTACLES = {95: "Cut tree", 96: "breakable rock", 97: "Strength boulder"}  # 97: unverified


def clear_obstacle(p, x=None, y=None):
    """Walk next to the obstacle at (X, Y) (default: the nearest one on screen), face it and press A."""
    import mcp_server
    w = W.read_world(p)
    obs = [n for n in w["npcs"] if n.get("graphics") in OBSTACLES]
    if x is not None and y is not None:
        obs = [n for n in obs if (n["x"], n["y"]) == (x, y)]
        if not obs:  # objects load only near the camera: walk toward it, then look again
            for stand in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= stand[0] < w["width"] and 0 <= stand[1] < w["height"] and not w["tile"](*stand)[1]:
                    mcp_server.t_walk_to({"x": stand[0], "y": stand[1]})
                    break
            w = W.read_world(p)
            obs = [n for n in w["npcs"] if n.get("graphics") in OBSTACLES and (n["x"], n["y"]) == (x, y)]
    if not obs:
        raise SystemExit("no Cut tree, breakable rock or boulder " + (f"at ({x},{y})" if x is not None else "on screen"))
    here = tuple(w["player"])
    o = min(obs, key=lambda n: abs(n["x"] - here[0]) + abs(n["y"] - here[1]))
    what, ox, oy = OBSTACLES[o["graphics"]], o["x"], o["y"]
    for (dx, dy), key in (((1, 0), "LEFT"), ((-1, 0), "RIGHT"), ((0, 1), "UP"), ((0, -1), "DOWN")):
        stand = (ox + dx, oy + dy)
        if not (0 <= stand[0] < w["width"] and 0 <= stand[1] < w["height"]) or w["tile"](*stand)[1]:
            continue
        if tuple(get_state(p)["pos"]) != stand:
            mcp_server.t_walk_to({"x": stand[0], "y": stand[1]})
        if tuple(get_state(p)["pos"]) == stand:
            break
    else:
        raise SystemExit(f"couldn't get next to the {what} at ({ox},{oy})")
    p.press(key, 4)  # a short tap only turns
    p.step(20)
    p.press("A", 4)
    said = []
    for _ in range(40):
        p.step(15)
        r = raw(p)
        if r["mode"] == "battle":
            return (f"the {what} at ({ox},{oy}) is cleared and a wild Pokemon jumped out: you're in a battle now "
                    "(battle it as usual)")
        if r["mode"] == "dialog" and pm._waiting(p):
            # "<mon> used Rock Smash!" etc.: advance with A (B here once left a half-done script, then a save prompt).
            # A question is the agent's call.
            text = pm._text(p)
            said.append(text)
            if "?" in text:
                return f"the game asks {text!r} at the {what}: answer it yourself (advance_dialog / press_buttons)"
            p.press("A", 4)
            continue
        if r["mode"] == "overworld":
            if not any(n["id"] == o["id"] for n in W.read_world(p)["npcs"]):
                return f"cleared the {what} at ({ox},{oy})"
            if said:
                raise SystemExit(f"the {what} wasn't cleared. The game said: {' / '.join(said)} (you need the HM in "
                                 "the TM Case and a party Pokemon that could learn the move)")
    if o["graphics"] == 97:
        return f"used Strength on the boulder at ({ox},{oy}): push it by walking into it"
    raise SystemExit(f"the {what} at ({ox},{oy}) is still there: look at the screen")


if __name__ == "__main__":
    assert OBSTACLES[95] == "Cut tree"
    print("field self-check ok (live checks: see #166)")
