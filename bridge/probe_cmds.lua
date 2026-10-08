-- Command handlers for probe.lua, reloadable in flight with the "reload" command (no mGBA restart).
--   read8|read16|read32 ADDR   -> hex value
--   range ADDR LEN             -> hex bytes
--   step N                     -> "ok" after N frames
--   shot PATH                  -> save a PNG screenshot, "ok"
--   press KEY [FRAMES]         -> hold KEY (A B START SELECT UP DOWN LEFT RIGHT L R) for FRAMES (default 4), release, "ok"
--   save PATH / load PATH      -> savestate to/from file (everything, incl. RTC and save data), "ok"
--   autosave DIR FRAMES [KEEP] -> every FRAMES frames save DIR/auto-N.ss1, cycling N over KEEP files (default 10); FRAMES 0 stops
-- Frame commands set S.pending; the core counts the frames down and replies "ok".

local function hex(data)
	return (data:gsub(".", function(c) return string.format("%02x", c:byte()) end))
end

local M = {}
M.readonly = { read8 = true, read16 = true, read32 = true, range = true, shot = true }

function M.handle(S, sock, line, cmd)
	local reply = S.reply
	local a, b = line:match("^%S+%s*(%S*)%s*(%S*)")
	if cmd == "press" then
		local key = C.GBA_KEY[a:upper()]
		if not key then return reply(sock, "err unknown key " .. a) end
		emu:addKey(key)
		S.pending = { sock = sock, frames = tonumber(b) or 4, key = key }
		return
	end
	a, b = tonumber(a), tonumber(b)
	if cmd == "read8" and a then reply(sock, string.format("%x", emu:read8(a)))
	elseif cmd == "read16" and a then reply(sock, string.format("%x", emu:read16(a)))
	elseif cmd == "read32" and a then reply(sock, string.format("%x", emu:read32(a)))
	elseif cmd == "range" and a and b then reply(sock, hex(emu:readRange(a, b)))
	elseif cmd == "shot" then
		emu:screenshot(line:match("^shot%s+(.+)$"))
		reply(sock, "ok")
	elseif cmd == "save" or cmd == "load" then
		local path = line:match("^%S+%s+(.+)$")
		if not path then return reply(sock, "err missing path") end
		local ok
		if cmd == "save" then ok = emu:saveStateFile(path) else
			S.pending = nil
			emu:setKeys(0)
			ok = emu:loadStateFile(path)
		end
		reply(sock, ok and "ok" or "err " .. cmd .. " failed: " .. path)
	elseif cmd == "autosave" then
		local dir, every, keep = line:match("^autosave%s+(.-)%s+(%d+)%s*(%d*)$")
		every = tonumber(every)
		if not every then return reply(sock, "err usage: autosave DIR FRAMES [KEEP]") end
		S.autosave = every > 0 and { dir = dir, every = every, keep = tonumber(keep) or 10, frames = 0, n = 0 } or nil
		reply(sock, "ok")
	elseif cmd == "step" and a then
		if a <= 0 then return reply(sock, "ok") end
		S.pending = { sock = sock, frames = a }
	else reply(sock, "err bad command: " .. line) end
end

return M
