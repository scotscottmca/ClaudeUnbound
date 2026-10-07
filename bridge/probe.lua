-- Bridge server for mGBA 0.10+ (Tools > Scripting > File > Load script).
-- Line protocol on 127.0.0.1:8888, one reply line per command:
--   read8|read16|read32 ADDR   -> hex value
--   range ADDR LEN             -> hex bytes
--   step N                     -> "ok" after N frames
--   shot PATH                  -> save a PNG screenshot, "ok"
--   press KEY [FRAMES]         -> hold KEY (A B START SELECT UP DOWN LEFT RIGHT L R) for FRAMES (default 4), release, "ok"
--   save PATH / load PATH      -> savestate to/from file (everything, incl. RTC and save data), "ok"
--   autosave DIR FRAMES [KEEP] -> every FRAMES frames save DIR/auto-N.ss1, cycling N over KEEP files (default 10); FRAMES 0 stops
-- Errors reply "err <message>".

local PORT = 8888
local pending -- frame-based command waiting to finish: {sock, frames, key}
local closed = {}
local autosave -- {dir, every, keep, frames, n}

local function send(sock, s)
	local i = 1
	while i <= #s do
		local last, err = sock:send(s, i)
		if last then
			i = last + 1
		elseif err ~= socket.ERRORS.AGAIN then
			console:error("probe: send failed: " .. tostring(err))
			return
		end
	end
end

local function reply(sock, s) send(sock, s .. "\n") end

local function hex(data)
	return (data:gsub(".", function(c) return string.format("%02x", c:byte()) end))
end

local function handle(sock, line)
	if pending then return reply(sock, "err busy: another client's command is running") end
	local cmd, a, b = line:match("^(%S+)%s*(%S*)%s*(%S*)")
	if cmd == "press" then
		local key = C.GBA_KEY[a:upper()]
		if not key then return reply(sock, "err unknown key " .. a) end
		emu:addKey(key)
		pending = { sock = sock, frames = tonumber(b) or 4, key = key }
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
			pending = nil
			emu:setKeys(0)
			ok = emu:loadStateFile(path)
		end
		reply(sock, ok and "ok" or "err " .. cmd .. " failed: " .. path)
	elseif cmd == "autosave" then
		local dir, every, keep = line:match("^autosave%s+(.-)%s+(%d+)%s*(%d*)$")
		every = tonumber(every)
		if not every then return reply(sock, "err usage: autosave DIR FRAMES [KEEP]") end
		autosave = every > 0 and { dir = dir, every = every, keep = tonumber(keep) or 10, frames = 0, n = 0 } or nil
		reply(sock, "ok")
	elseif cmd == "step" and a then
		if a <= 0 then return reply(sock, "ok") end
		pending = { sock = sock, frames = a }
	else reply(sock, "err bad command: " .. line) end
end

callbacks:add("frame", function()
	if autosave then
		autosave.frames = autosave.frames + 1
		if autosave.frames >= autosave.every then
			autosave.frames = 0
			local path = string.format("%s/auto-%d.ss1", autosave.dir, autosave.n)
			if not emu:saveStateFile(path) then console:error("probe: autosave failed: " .. path) end
			autosave.n = (autosave.n + 1) % autosave.keep
		end
	end
	if not pending then return end
	pending.frames = pending.frames - 1
	if pending.frames > 0 then return end
	local p = pending
	pending = nil
	if p.key then emu:clearKey(p.key) end
	reply(p.sock, "ok")
end)

local server = assert(socket.bind("127.0.0.1", PORT))
assert(server:listen())
server:add("received", function()
	local sock = server:accept()
	if not sock then return end
	local buf = ""
	sock:add("received", function()
		while true do
			local data, err = sock:receive(4096)
			if not data then
				if err ~= socket.ERRORS.AGAIN then
					console:log("probe: client closed (" .. tostring(err) .. ")")
					sock:close()
					-- mGBA 0.10 doesn't invalidate a closed socket, so GC would close the
					-- handle again and kill whichever new client Windows reused it for.
					-- ponytail: leaks one small table per connection; fine for a dev probe.
					table.insert(closed, sock)
				end
				return
			end
			buf = buf .. data
			for line in buf:gmatch("([^\n]*)\n") do handle(sock, (line:gsub("\r$", ""))) end
			buf = buf:match("[^\n]*$")
		end
	end)
	console:log("probe: client connected")
end)
console:log("probe: listening on 127.0.0.1:" .. PORT)
