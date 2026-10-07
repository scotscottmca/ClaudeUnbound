-- RAM probe server for mGBA 0.10+ (Tools > Scripting > File > Load script).
-- Line protocol on 127.0.0.1:8888, one reply line per command:
--   read8|read16|read32 ADDR   -> hex value
--   range ADDR LEN             -> hex bytes
--   step N                     -> "ok" after N frames
--   press KEY [FRAMES]         -> hold KEY (A B START SELECT UP DOWN LEFT RIGHT L R) for FRAMES (default 4), release, "ok"
-- Errors reply "err <message>".

local PORT = 8888
local pending -- frame-based command waiting to finish: {sock, frames, key}

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
	elseif cmd == "step" and a then
		if a <= 0 then return reply(sock, "ok") end
		pending = { sock = sock, frames = a }
	else reply(sock, "err bad command: " .. line) end
end

callbacks:add("frame", function()
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
