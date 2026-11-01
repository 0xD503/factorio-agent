-- Client link (experimental): lets a program on a player's own machine drive that player's
-- character, through the player's game client instead of the server's RCON.
--
-- The player's game is started with `--enable-lua-udp PORT`. A local program sends JSON
-- requests to 127.0.0.1:PORT; every tick this script asks the game to deliver what each
-- connected player's client received (helpers.recv_udp), the game raises
-- on_udp_packet_received on every peer alike, and the reply goes back from that player's client
-- with helpers.send_udp. Packets are attributed to the player whose client received them,
-- so a program can only ever drive the character of the player on whose machine it runs.
--
-- Requests: {"id": 1, "op": "hello"|"state"|"walk"|"stop"|"say", "reply_port": N, ...}

local common = require("agent.common")
local social = require("agent.social")

local link = {}

local function links()
    storage.agent_links = storage.agent_links or {}
    return storage.agent_links
end

local function reply(event, req, out)
    out.id = req.id
    out.tick = game.tick
    if type(req.reply_port) == "number" then
        pcall(helpers.send_udp, req.reply_port, helpers.table_to_json(out), event.player_index)
    end
end

-- 16-way defines.direction for a step (dx, dy); y grows southwards.
local function direction_to(dx, dy)
    local angle = math.atan2(dx, -dy)                     -- 0 = north, clockwise
    local step = math.floor(angle / (2 * math.pi) * 8 + 0.5) % 8
    return step * 2
end

local function stop(ch)
    if ch and ch.valid then ch.walking_state = {walking = false, direction = defines.direction.north} end
end

function link.on_packet(event)
    local player = game.get_player(event.player_index)
    if not player then return end
    local ok, req = pcall(helpers.json_to_table, event.payload)
    if not ok or type(req) ~= "table" then return end
    local state = links()[player.index] or {}
    links()[player.index] = state
    local ch = player.character
    local op = req.op
    if op == "hello" then
        reply(event, req, {ok = true, player = player.name, character = ch ~= nil and ch.valid})
    elseif op == "state" then
        local out = {ok = true, player = player.name}
        if ch and ch.valid then
            out.x, out.y = common.round(ch.position.x), common.round(ch.position.y)
            out.health = math.floor(ch.health)
            out.inventory = common.contents(ch.get_main_inventory())
            out.walking_to = state.target
        else
            out.dead = true
        end
        reply(event, req, out)
    elseif op == "walk" then
        if type(req.x) ~= "number" or type(req.y) ~= "number" then
            reply(event, req, {ok = false, error = "walk needs x and y"})
            return
        end
        state.target = {x = req.x, y = req.y}
        reply(event, req, {ok = true})
    elseif op == "stop" then
        state.target = nil
        stop(ch)
        reply(event, req, {ok = true})
    elseif op == "say" then
        if type(req.text) ~= "string" or req.text == "" or #req.text > 500 then
            reply(event, req, {ok = false, error = "say needs text (500 characters at most)"})
            return
        end
        game.print({"", player.name, " (agent): ", req.text}, {color = player.chat_color, skip = defines.print_skip.never})
        social.record(player.name .. " (agent)", req.text)
        reply(event, req, {ok = true})
    else
        reply(event, req, {ok = false, error = "unknown op " .. tostring(op)})
    end
end

function link.tick()
    for _, player in pairs(game.connected_players) do
        pcall(helpers.recv_udp, player.index)
    end
    local all = storage.agent_links
    if not all then return end
    for index, state in pairs(all) do
        local player = game.get_player(index)
        local ch = player and player.connected and player.character
        if state.target and ch and ch.valid then
            local dx, dy = state.target.x - ch.position.x, state.target.y - ch.position.y
            if dx * dx + dy * dy < 0.09 then
                state.target = nil
                stop(ch)
            else
                ch.walking_state = {walking = true, direction = direction_to(dx, dy)}
            end
        elseif state.target then
            state.target = nil
        end
    end
end

return link
