-- Bridge server for mGBA 0.10+ (Tools > Scripting > File > Load script).
-- Line protocol on 127.0.0.1:8888, one reply line per command. This file is the stable core: the socket
-- server, the pending/busy bookkeeping and autosave. The commands live in probe_cmds.lua (listed there), and
--   reload                     -> load probe_cmds.lua again, "ok" (on an error the old commands stay: "err ...")
-- swaps them in without restarting mGBA, even while a frame command is pending (it keeps counting).
-- Errors reply "err <message>". While one client's step/press is pending, other clients may only read and shoot.

local PORT = 8888
local DIR = debug.getinfo(1, "S").source:match("^@(.*[/\\])") or ""
-- Core state, shared with the handlers and kept across a reload.
-- S.pending: frame-based command waiting to finish {sock, frames, key}; S.autosave: {dir, every, keep, frames, n}
local S = { closed = {} }
local H -- the handlers: {readonly = {cmd = true}, handle = function(S, sock, line, cmd)}

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

function S.reply(sock, s) send(sock, s .. "\n") end

local function load_handlers()
	local chunk, err = loadfile(DIR .. "probe_cmds.lua")
	if not chunk then return err end
	local ok, h = pcall(chunk)
	if not ok then return h end
	if type(h) ~= "table" or type(h.handle) ~= "function" then return "probe_cmds.lua must return {readonly, handle}" end
	H = h
end

local function handle(sock, line)
	local cmd = line:match("^(%S+)")
	if cmd == "reload" then -- doesn't advance frames: allowed beside a pending command
		local err = load_handlers()
		console:log("probe: reload " .. (err and ("failed: " .. tostring(err)) or "ok"))
		return S.reply(sock, err and ("err reload: " .. tostring(err):gsub("\n", " ")) or "ok")
	end
	-- Reads and screenshots don't advance frames, so they're safe beside another client's pending command (#58).
	if S.pending and not H.readonly[cmd] then return S.reply(sock, "err busy: another client's command is running") end
	local ok, err = pcall(H.handle, S, sock, line, cmd)
	if not ok then S.reply(sock, "err handler: " .. tostring(err):gsub("\n", " ")) end
end

callbacks:add("frame", function()
	local a = S.autosave
	if a then
		a.frames = a.frames + 1
		if a.frames >= a.every then
			a.frames = 0
			local path = string.format("%s/auto-%d.ss1", a.dir, a.n)
			if not emu:saveStateFile(path) then console:error("probe: autosave failed: " .. path) end
			a.n = (a.n + 1) % a.keep
		end
	end
	local p = S.pending
	if not p then return end
	p.frames = p.frames - 1
	if p.frames > 0 then return end
	S.pending = nil
	if p.key then emu:clearKey(p.key) end
	S.reply(p.sock, "ok")
end)

assert(not load_handlers(), "probe: can't load probe_cmds.lua")
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
					table.insert(S.closed, sock)
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
