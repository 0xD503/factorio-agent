-- Agent interface for a script-driven character on a freeplay server.
-- Requests arrive over RCON as `/agent <json>`; replies go back as JSON.
--
-- Two modes (st.mode):
-- solo  the agent runs the clock: the game stays paused except while a `run`
-- request
--         is being served, at up to 64x. Anyone who joins is a spectator.
-- coop  real time with human players: the clock is never touched, orders
-- execute as
-- soon as they are queued, and `run` only waits for them (or for an
-- interruption,
-- such as a chat line that mentions the agent). Joining players get characters.

local util = require("util")
local crash_site = require("crash-site")
local common = require("agent.common")
local orders = require("agent.orders")
local observe = require("agent.observe")
local social = require("agent.social")
local link = require("agent.link")

local RESPAWN_TICKS = 600
local ENEMY_ALERT_RANGE = 25
local ALERT_COOLDOWN = 600
local AUTOSAVE_TICKS = 36000
local AUTOSAVE_SLOTS = 5

local ops = {}
for name, op in pairs(observe.ops) do
    ops[name] = op
end

---------------------------------------------------------------------------
-- Character lifecycle

local function spawn_character(st, items)
    local surface, force = common.surface(), common.force()
    local spawn = force.get_spawn_position(surface)
    local position = surface.find_non_colliding_position(
        "character",
        spawn,
        16,
        0.5
    ) or spawn
    local ch = surface.create_entity({
        name = "character",
        position = position,
        force = force,
    })
    util.insert_safe(ch, items)
    st.character = ch
    st.health = ch.health
    st.chunk_x, st.chunk_y = nil, nil
    social.tag(st)
    return ch
end

-- Does for our character what freeplay does for the first player who joins.
ops.start = function()
    local st = common.state()
    if st.started then
        return { already_started = true }
    end
    local surface, force = common.surface(), common.force()
    local first = not storage.init_ran
    storage.init_ran = true

    -- Freeplay reveals a square around the spawn point for the first player.
    local r = storage.chart_distance or 200
    local spawn = force.get_spawn_position(surface)
    for cx = math.floor((spawn.x - r) / 32), math.floor((spawn.x + r) / 32) do
        local cy1, cy2 =
            math.floor((spawn.y - r) / 32), math.floor((spawn.y + r) / 32)
        for cy = cy1, cy2 do
            common.mark_seen(cx, cy, 0)
        end
    end

    local ch = spawn_character(st, storage.created_items)
    if first and not storage.disable_crashsite then
        surface.daytime = 0.7
        crash_site.create_crash_site(
            surface,
            { -5, -6 },
            util.copy(storage.crashed_ship_items),
            util.copy(storage.crashed_debris_items),
            util.copy(storage.crashed_ship_parts)
        )
        util.remove_safe(ch, storage.crashed_ship_items)
        util.remove_safe(ch, storage.crashed_debris_items)
        ch.get_main_inventory().sort_and_merge()
    end

    st.started = true
    if st.mode == "solo" then
        game.tick_paused = true
        game.ticks_to_run = 0
    end
    return { started = true, x = ch.position.x, y = ch.position.y }
end

local function handle_death(st)
    if not st.respawn_at then
        st.deaths = st.deaths + 1
        st.respawn_at = game.tick + RESPAWN_TICKS
        st.character = nil
        orders.cancel(st)
        common.event("died", { deaths = st.deaths })
        st.interrupt = "character died"
    elseif game.tick >= st.respawn_at then
        st.respawn_at = nil
        local ch = spawn_character(st, storage.respawn_items)
        common.event("respawned", { x = ch.position.x, y = ch.position.y })
        st.interrupt = "character respawned"
    end
end

---------------------------------------------------------------------------
-- Per-tick upkeep: what the game does for a connected player's character

-- Spectators see the map through the force's chart, which only updates while
-- someone is connected.
local function chart_for_spectators(cx1, cy1, cx2, cy2)
    if #game.connected_players == 0 then
        return
    end
    common.force().chart(
        common.surface(),
        { { cx1 * 32, cy1 * 32 }, { cx2 * 32 + 31, cy2 * 32 + 31 } }
    )
end

-- Hand-crafting by a character that no player controls is not counted as
-- production and does not fire "craft-item" research triggers (crafting the
-- first lab unlocks science packs). The game does both for a player, so we do
-- both here.
local craft_triggers

local function count_crafted(st, force, item, count)
    if not craft_triggers then
        craft_triggers = {}
        for name, tech in pairs(prototypes.technology) do
            local trigger = tech.research_trigger
            if trigger and trigger.type == "craft-item" then
                craft_triggers[name] = {
                    item = trigger.item.name or trigger.item,
                    count = trigger.count or 1,
                }
            end
        end
    end
    for name, trigger in pairs(craft_triggers) do
        local tech = force.technologies[name]
        if trigger.item == item and tech.enabled and not tech.researched then
            local ready = true
            for _, prerequisite in pairs(tech.prerequisites) do
                ready = ready and prerequisite.researched
            end
            if ready then
                st.trigger_counts[name] = (st.trigger_counts[name] or 0) + count
                if st.trigger_counts[name] >= trigger.count then
                    tech.researched = true
                end
            end
        end
    end
end

local function watch_crafting(st, ch)
    local size = ch.crafting_queue_size
    local head = size > 0 and ch.crafting_queue[1] or nil
    local before = st.craft_head
    if before then
        local finished = 0
        if size < before.size or not head or head.recipe ~= before.recipe then
            finished = 1
        elseif head.count < before.count then
            finished = before.count - head.count
        end
        if finished > 0 then
            local stats = ch.force.get_item_production_statistics(ch.surface)
            local recipe = prototypes.recipe[before.recipe]
            for _, product in pairs(recipe.products) do
                if product.type == "item" then
                    local made = (product.amount or product.amount_min)
                        * finished
                    stats.on_flow(product.name, made)
                    count_crafted(st, ch.force, product.name, made)
                end
            end
        end
    end
    st.craft_head = head
            and { recipe = head.recipe, count = head.count, size = size }
        or nil
end

-- A player switches to the best gun they carry and keeps it loaded; do the
-- same.
local function ready_weapon(ch)
    local guns = ch.get_inventory(defines.inventory.character_guns)
    local ammo = ch.get_inventory(defines.inventory.character_ammo)
    -- The strongest gun held; a fresh character's pistol must not win over a
    -- submachine gun.
    local RANK = { pistol = 1, ["submachine-gun"] = 2 }
    local best, best_rank
    for index = 1, #guns do
        if guns[index].valid_for_read then
            local rank = RANK[guns[index].name] or 3
            if not best or rank > best_rank then
                best, best_rank = index, rank
            end
        end
    end
    if not best then
        return
    end
    if not ammo[best].valid_for_read then
        for index = 1, #ammo do
            if
                index ~= best
                and ammo[index].valid_for_read
                and ammo[best].swap_stack(ammo[index])
            then
                break
            end
        end
    end
    if ch.selected_gun_index ~= best then
        ch.selected_gun_index = best
    end
end

local function upkeep(st, ch)
    local tick = game.tick
    local pos = ch.position
    local cx, cy = math.floor(pos.x / 32), math.floor(pos.y / 32)
    if cx ~= st.chunk_x or cy ~= st.chunk_y then
        st.chunk_x, st.chunk_y = cx, cy
        ch.surface.request_to_generate_chunks(pos, 3)
        common.mark_seen(cx, cy, common.VIEW_CHUNKS)
        chart_for_spectators(
            cx - common.VIEW_CHUNKS,
            cy - common.VIEW_CHUNKS,
            cx + common.VIEW_CHUNKS,
            cy + common.VIEW_CHUNKS
        )
    end

    watch_crafting(st, ch)
    if tick % 60 == 0 then
        ready_weapon(ch)
    end

    local health = ch.health
    if st.health and health < st.health - 0.01 then
        if not st.damage_alert or tick - st.damage_alert > ALERT_COOLDOWN then
            st.damage_alert = tick
            common.event("damaged", { health = math.floor(health) })
            st.interrupt = "character damaged"
        end
    end
    st.health = health

    -- Shoot back at anything hostile nearby, as holding the fire key would.
    if tick % 15 == 0 then
        local enemy = ch.surface.find_nearest_enemy({
            position = pos,
            max_distance = ENEMY_ALERT_RANGE,
            force = ch.force,
        })
        st.enemy = enemy
        if
            enemy
            and (not st.enemy_alert or tick - st.enemy_alert > ALERT_COOLDOWN)
        then
            st.enemy_alert = tick
            common.event("enemy_near", {
                name = enemy.name,
                x = common.round(enemy.position.x),
                y = common.round(enemy.position.y),
            })
            st.interrupt = "enemy nearby"
        end
    end
    local enemy = st.enemy
    if enemy and enemy.valid then
        ch.shooting_state = {
            state = defines.shooting.shooting_enemies,
            position = enemy.position,
        }
        st.shooting = true
    elseif st.shooting then
        ch.shooting_state =
            { state = defines.shooting.not_shooting, position = pos }
        st.shooting = false
    end
end

---------------------------------------------------------------------------
-- Running the clock

-- While paused the server idles at normal speed; solo runs go at st.run_speed.
local function halt(st, reason)
    st.stop = reason
    st.run = nil
    if st.mode == "solo" then
        -- 1, not 0: zero would abandon the tick that is being processed right
        -- now.
        game.ticks_to_run = 1
        game.speed = 1
    end
end

local function running(st)
    if st.mode == "solo" then
        return game.ticks_to_run > 0
    end
    return st.run ~= nil
end

local function tick_unsafe(st)
    local ch = st.character
    if not (ch and ch.valid) then
        handle_death(st)
        ch = st.character
    end
    local idle = true
    if ch and ch.valid then
        upkeep(st, ch)
        idle = orders.step(st, ch)
    end

    local run = st.run
    if not run then
        return
    end
    run.left = run.left - 1
    if st.chat_pending then
        st.chat_pending = nil
        st.interrupt = st.interrupt or "chat"
    end
    if st.interrupt then
        halt(st, st.interrupt)
    elseif st.failed then
        halt(st, "order failed")
    elseif idle and run.until_idle then
        halt(st, "done")
    elseif run.left <= 0 then
        halt(st, "ticks elapsed")
    end
    st.interrupt = nil
    st.failed = nil
end

local function on_tick()
    -- The client link works on any server whose save has this script, started
    -- or not.
    local ok_link, link_error = pcall(link.tick)
    if not ok_link then
        log("agent link: " .. tostring(link_error))
    end
    local st = storage.agent
    if not (st and st.started) then
        return
    end
    local ok, message = pcall(tick_unsafe, st)
    if not ok then
        common.event("script_error", { message = tostring(message) })
        halt(st, "script error")
    end
end

-- Appends orders to the queue.
ops.enqueue = function(req)
    local st = common.state()
    if not st.started then
        error("not started", 0)
    end
    local list = req.orders or {}
    for index, order in pairs(list) do
        if not orders.known(order.type) then
            error(
                "order " .. index .. ": unknown type " .. tostring(order.type),
                0
            )
        end
    end
    local base = req.base or 0
    for index, order in pairs(list) do
        order.n = base + index
        st.queue[#st.queue + 1] = order
    end
    return { queued = #st.queue + (st.current and 1 or 0) }
end

-- Whether a run is in progress. Unlike report, this consumes nothing.
ops.status = function()
    local st = common.state()
    return {
        running = running(st),
        queued = #st.queue + (st.current and 1 or 0),
    }
end

-- Ends the run in progress now; queued orders stay queued.
ops.halt = function(req)
    local st = common.state()
    if running(st) then
        halt(st, req.reason or "halted")
    end
    return {}
end

ops.cancel = function()
    local st = common.state()
    local dropped = #st.queue + (st.current and 1 or 0)
    orders.cancel(st, common.character())
    return { dropped = dropped }
end

-- Lets the game run for up to `ticks`. It stops earlier when something needs
-- attention, or when the queue empties if `until_idle` is set.
ops.run = function(req)
    local st = common.state()
    if not st.started then
        error("not started", 0)
    end
    local ticks = math.floor(req.ticks or 600)
    if ticks < 1 then
        error("ticks must be at least 1", 0)
    end
    if running(st) then
        error("a run is already in progress", 0)
    end
    st.stop, st.interrupt, st.failed = nil, nil, nil
    if req.until_idle and not st.current and #st.queue == 0 then
        st.stop = "done"
        return { running = false }
    end
    st.run = { until_idle = req.until_idle and true or false, left = ticks }
    if st.mode == "coop" then
        return { running = true }
    end
    game.tick_paused = true
    game.speed = st.run_speed
    -- The run ends itself in on_tick; the extra ticks are only a backstop.
    game.ticks_to_run = ticks + 10
    return { running = true }
end

-- What happened during the last run. Clears the result and event buffers.
ops.report = function()
    local st = common.state()
    if running(st) then
        return { running = true }
    end
    if st.run and st.mode == "solo" then
        -- Ended by the tick backstop rather than by on_tick.
        st.run = nil
        game.speed = 1
    end
    local out = {
        running = false,
        reason = st.stop or "ticks elapsed",
        results = st.results,
        events = st.events,
        dropped = st.dropped,
        queued = #st.queue + (st.current and 1 or 0),
        state = observe.brief(),
    }
    -- Inventory changes since the previous report; `state` has the full list.
    local now = out.state.inventory or {}
    local before = st.reported_inventory or {}
    local changed = {}
    for name, count in pairs(now) do
        if count ~= (before[name] or 0) then
            changed[name] = count - (before[name] or 0)
        end
    end
    for name, count in pairs(before) do
        if not now[name] then
            changed[name] = -count
        end
    end
    st.reported_inventory = now
    out.state.inventory = nil
    out.changed = changed
    -- Chat the agent has not seen yet (not fetched with `chat`, not its own
    -- lines).
    local unseen = {}
    for _, line in pairs(social.lines(st, st.chat_reported, 50)) do
        if not line.self then
            unseen[#unseen + 1] = line
        end
    end
    out.chat = unseen
    st.chat_reported = st.chat_seq
    st.run, st.stop, st.dropped = nil, nil, nil
    st.results, st.events = {}, {}

    -- Rolling saves by played time. The server's own autosave counts idle time
    -- too and would fire every few seconds at high speed, so it is turned off.
    if game.tick - st.saved_tick >= AUTOSAVE_TICKS then
        st.saved_tick = game.tick
        st.save_slot = st.save_slot % AUTOSAVE_SLOTS + 1
        game.server_save("auto-" .. st.save_slot)
        out.saved = "auto-" .. st.save_slot
    end
    return out
end

ops.research = function(req)
    local force = common.force()
    if req.clear then
        force.research_queue = {}
    end
    local added = {}
    for _, name in pairs(req.techs or {}) do
        if not force.technologies[name] then
            error("no technology named " .. tostring(name), 0)
        end
        added[name] = force.add_research(name)
    end
    local queue = {}
    for _, tech in pairs(force.research_queue) do
        queue[#queue + 1] = tech.name
    end
    return { added = added, queue = queue }
end

-- Speed used while a run is in progress.
ops.speed = function(req)
    local st = common.state()
    if req.speed then
        if st.mode ~= "solo" then
            error(
                "game speed is shared with the other players in co-op;"
                    .. " it stays at 1",
                0
            )
        end
        if req.speed <= 0 or req.speed > 64 then
            error("speed must be between 0 and 64", 0)
        end
        st.run_speed = req.speed
    end
    return { speed = st.run_speed }
end

local function valid_save_name(name)
    return type(name) == "string"
        and #name <= 100
        and string.match(name, "^[%w][%w%._%-]*$") ~= nil
        and not string.find(name, "..", 1, true)
end

ops.save = function(req)
    if not valid_save_name(req.name) then
        error("save names are letters, digits, '.', '_' and '-'", 0)
    end
    game.server_save(req.name)
    return { saving = req.name }
end

ops.import_blueprint = function(req)
    return orders.import_blueprint(req)
end

-- Mode, name, colour and chat handling; see the header and social.lua.
ops.configure = function(req)
    local st = common.state()
    if req.mode ~= nil then
        if req.mode ~= "solo" and req.mode ~= "coop" then
            error("mode is solo or coop", 0)
        end
        if req.mode ~= st.mode then
            if running(st) then
                error("a run is in progress", 0)
            end
            st.mode = req.mode
            if st.mode == "coop" then
                game.speed = 1
                game.tick_paused = false
                for _, player in pairs(game.connected_players) do
                    social.give_character(st, player)
                end
            elseif st.started then
                game.tick_paused = true
                game.ticks_to_run = 0
            end
        end
    end
    if req.name ~= nil then
        if type(req.name) ~= "string" or #req.name > 40 then
            error("name: a string of up to 40 characters", 0)
        end
        st.name = req.name
    end
    if req.color ~= nil then
        st.color = req.color
    end
    if req.chat_interrupt ~= nil then
        if
            req.chat_interrupt ~= "any"
            and req.chat_interrupt ~= "mention"
            and req.chat_interrupt ~= "none"
        then
            error("chat_interrupt is any, mention or none", 0)
        end
        st.chat_interrupt = req.chat_interrupt
    end
    if st.started then
        social.tag(st)
    end
    return {
        mode = st.mode,
        name = st.name,
        color = st.color,
        chat_interrupt = st.chat_interrupt,
    }
end

ops.chat = function(req)
    local st = common.state()
    st.chat_pending = nil
    local lines = social.lines(st, req.since, req.limit or 50)
    local last = lines[#lines]
    if last and last.id > st.chat_reported then
        st.chat_reported = last.id
    end
    return { lines = lines, seq = st.chat_seq }
end

ops.say = function(req)
    local st = common.state()
    return { line = social.say(st, req.text, req.to) }
end

ops.players = function()
    return { players = social.players() }
end

-- Which of these names exist as an item, entity, recipe, technology or fluid in
-- this game
-- (mods add and remove prototypes; skills check what they need before they
-- start).
ops.exists = function(req)
    local out = {}
    for _, name in pairs(req.names or {}) do
        out[name] = (
            prototypes.item[name]
            or prototypes.entity[name]
            or prototypes.recipe[name]
            or prototypes.technology[name]
            or prototypes.fluid[name]
        )
                and true
            or false
    end
    return { exists = out }
end

-- Active mods and their versions ("base" is the game's own version).
ops.mods = function()
    local out = {}
    for name, version in pairs(script.active_mods) do
        out[name] = version
    end
    return { mods = out }
end

-- Several requests in one command. Each RCON command costs one server update
-- (1/60 s)
-- however little it does, so batching observations saves real time.
ops.batch = function(req)
    local replies = {}
    for index, sub in pairs(req.requests or {}) do
        local op = type(sub) == "table" and ops[sub.op]
        if not op or sub.op == "batch" then
            replies[index] = {
                ok = false,
                error = "unknown op "
                    .. tostring(type(sub) == "table" and sub.op),
            }
        else
            local ok, result = pcall(op, sub)
            if ok then
                result = result or {}
                result.ok = true
            else
                result = { ok = false, error = tostring(result) }
            end
            replies[index] = result
        end
    end
    return { replies = replies }
end

---------------------------------------------------------------------------
-- Events

local events = {}

events[defines.events.on_tick] = on_tick

events[defines.events.on_script_path_request_finished] = function(event)
    local st = storage.agent
    if not (st and st.pending_paths[event.id]) then
        return
    end
    st.pending_paths[event.id] = nil
    local path
    if event.path then
        path = {}
        for index, waypoint in pairs(event.path) do
            path[index] = { x = waypoint.position.x, y = waypoint.position.y }
        end
    end
    -- Answers nobody collected (their order ended first) would pile up
    -- otherwise.
    for id, answer in pairs(st.paths) do
        if event.tick - answer.tick > 1800 then
            st.paths[id] = nil
        end
    end
    st.paths[event.id] = {
        path = path,
        try_again_later = event.try_again_later,
        tick = event.tick,
    }
end

events[defines.events.on_entity_died] = function(event)
    local st = storage.agent
    if not (st and st.started) then
        return
    end
    local entity = event.entity
    if entity.force ~= common.force() or entity.type == "character" then
        return
    end
    common.event("lost", {
        name = entity.name,
        x = common.round(entity.position.x),
        y = common.round(entity.position.y),
        cause = event.cause and event.cause.valid and event.cause.name or nil,
    })
    -- Every loss is logged, but a raid should stop the run once, not once per
    -- belt tile.
    if not st.loss_alert or event.tick - st.loss_alert > ALERT_COOLDOWN then
        st.loss_alert = event.tick
        st.interrupt = "building destroyed"
    end
end

events[defines.events.on_research_finished] = function(event)
    local st = storage.agent
    if not (st and st.started) then
        return
    end
    common.event("research_finished", { name = event.research.name })
    if #common.force().research_queue == 0 then
        st.interrupt = "research queue empty"
    end
end

events[defines.events.on_rocket_launched] = function()
    local st = storage.agent
    if not (st and st.started) then
        return
    end
    st.rockets = (st.rockets or 0) + 1
    common.event("rocket_launched", { count = st.rockets })
    st.interrupt = "rocket launched"
end

events[defines.events.on_sector_scanned] = function(event)
    local st = storage.agent
    if not (st and st.started) or event.radar.force ~= common.force() then
        return
    end
    common.mark_seen(event.chunk_position.x, event.chunk_position.y, 0)
end

events[defines.events.on_console_chat] = social.on_chat

events[defines.events.on_udp_packet_received] = link.on_packet

events[defines.events.on_player_left_game] = function(event)
    social.notice(game.get_player(event.player_index).name .. " left")
end

events[defines.events.on_player_died] = function(event)
    social.notice(game.get_player(event.player_index).name .. " died")
end

events[defines.events.on_player_joined_game] = function(event)
    local st = storage.agent
    if not (st and st.started) then
        return
    end
    local player = game.get_player(event.player_index)
    social.notice(player.name .. " joined")
    if st.mode == "coop" then
        social.give_character(st, player)
    end
    local spawn = common.force().get_spawn_position(common.surface())
    local r = storage.chart_distance or 200
    common.force().chart(
        common.surface(),
        { { spawn.x - r, spawn.y - r }, { spawn.x + r, spawn.y + r } }
    )
    if st.chunk_x then
        chart_for_spectators(
            st.chunk_x - common.VIEW_CHUNKS,
            st.chunk_y - common.VIEW_CHUNKS,
            st.chunk_x + common.VIEW_CHUNKS,
            st.chunk_y + common.VIEW_CHUNKS
        )
    end
end

-- Solo: anyone who connects is an observer, with no character and no starting
-- items.
-- Co-op: freeplay's own handler gives them a character and its starting items.
events[defines.events.on_player_created] = function(event)
    local st = storage.agent
    if st and st.mode == "coop" then
        return
    end
    local player = game.get_player(event.player_index)
    if player.controller_type == defines.controllers.cutscene then
        return
    end
    local character = player.character
    player.set_controller({ type = defines.controllers.spectator })
    if character and character.valid then
        character.destroy()
    end
end

---------------------------------------------------------------------------
-- Command

local function on_command(command)
    if command.player_index then
        game.get_player(command.player_index)
            .print("/agent is only available over RCON")
        return
    end
    local ok, result = pcall(function()
        local request = helpers.json_to_table(command.parameter or "")
        if type(request) ~= "table" or not request.op then
            error("expected a JSON object with an op", 0)
        end
        local op = ops[request.op]
        if not op then
            error("unknown op " .. tostring(request.op), 0)
        end
        return op(request) or {}
    end)
    local reply = ok and result or { error = tostring(result) }
    reply.ok = ok
    reply.tick = game.tick
    rcon.print(helpers.table_to_json(reply))
end

-- An error escaping an event handler would stop the server.
local function guarded(handler)
    return function(event)
        local ok, message = pcall(handler, event)
        if not ok then
            log("agent: " .. tostring(message))
            pcall(common.event, "script_error", { message = tostring(message) })
        end
    end
end

for id, handler in pairs(events) do
    if handler ~= on_tick then
        events[id] = guarded(handler)
    end
end

return {
    events = events,
    add_commands = function()
        commands.add_command(
            "agent",
            "Agent interface (RCON only).",
            on_command
        )
    end,
}
