-- Orders: things the character does over time. Each one goes through the
-- character entity, so it needs the items, has to be within reach (the
-- character walks there first) and takes as many ticks as it does for a player.

local common = require("agent.common")

local dist = common.dist
local round = common.round

local orders = {}
local handlers = {}

---------------------------------------------------------------------------
-- Walking

local function stop_walking(ch)
    ch.walking_state =
        { walking = false, direction = ch.walking_state.direction }
end

local function dir8(dx, dy)
    local octant = math.floor(math.atan2(dy, dx) / (math.pi / 4) + 0.5) % 8
    return (4 + 2 * octant) % 16
end

-- `tight` plans with the character's real size; the default leaves a margin so
-- that paths do not scrape along walls.
local function request_path(ch, goal, radius, tight)
    local half = tight and 0.21 or 0.3
    local id = ch.surface.request_path({
        bounding_box = { { -half, -half }, { half, half } },
        collision_mask = ch.prototype.collision_mask,
        start = ch.position,
        goal = goal,
        force = ch.force,
        radius = radius,
        can_open_gates = true,
        entity_to_ignore = ch,
        pathfind_flags = { cache = false, prefer_straight_paths = true },
    })
    common.state().pending_paths[id] = true
    return id
end

local function give_up(order, ch, message)
    stop_walking(ch)
    order.nav = nil
    return "fail", message
end

-- Walk toward `goal` until within `radius` of it. Returns "arrived", "busy" or
-- "fail" plus a message. Progress is kept in order.nav.
local function navigate(order, ch, goal, radius)
    local pos = ch.position
    if dist(pos, goal) <= radius then
        if order.nav then
            stop_walking(ch)
            order.nav = nil
        end
        return "arrived"
    end

    local st = common.state()
    local nav = order.nav
    if not nav then
        nav = { tries = 0 }
        order.nav = nav
    end
    local where = string.format("(%.1f, %.1f)", goal.x, goal.y)

    -- Wedged against a cliff or a building the pathfinder finds nothing, even
    -- for
    -- a goal next door. Shuffle a few steps in one direction, then ask again.
    if nav.shuffle then
        nav.shuffle = nav.shuffle - 1
        ch.walking_state = { walking = true, direction = nav.shuffle_direction }
        if nav.shuffle <= 0 then
            nav.shuffle = nil
        end
        return "busy"
    end

    if not nav.path then
        if not nav.request then
            nav.tries = nav.tries + 1
            if nav.tries > 8 then
                return give_up(
                    order,
                    ch,
                    string.format(
                        "cannot reach %s, stuck at (%.1f, %.1f)",
                        where,
                        pos.x,
                        pos.y
                    )
                )
            end
            stop_walking(ch)
            nav.request =
                request_path(ch, goal, math.max(radius - 0.5, 0), nav.tight)
            nav.requested = game.tick
            return "busy"
        end
        local answer = st.paths[nav.request]
        if not answer then
            if game.tick - nav.requested > 900 then
                return give_up(
                    order,
                    ch,
                    "pathfinder gave no answer for " .. where
                )
            end
            return "busy"
        end
        st.paths[nav.request] = nil
        nav.request = nil
        if not answer.path then
            if answer.try_again_later then
                return "busy"
            end
            nav.failures = (nav.failures or 0) + 1
            if nav.failures == 1 then
                nav.tight = true
                return "busy"
            end
            if nav.failures > 6 then
                return give_up(order, ch, "no walkable path to " .. where)
            end
            -- toward the goal first, then the other three compass directions
            local toward = dir8(goal.x - pos.x, goal.y - pos.y)
            nav.shuffle_direction = (toward + (nav.failures - 2) * 4) % 16
            nav.shuffle = 40
            return "busy"
        end
        nav.path = answer.path
        nav.i = 1
        nav.still = 0
        nav.last = nil
    end

    local waypoint = nav.path[nav.i]
    while waypoint and dist(pos, waypoint) < 0.4 do
        nav.i = nav.i + 1
        waypoint = nav.path[nav.i]
    end
    local target = waypoint or goal
    ch.walking_state =
        { walking = true, direction = dir8(target.x - pos.x, target.y - pos.y) }

    if nav.last and dist(pos, nav.last) < 0.02 then
        nav.still = nav.still + 1
        if nav.still > 30 then
            -- Blocked by something the path did not account for: ask again.
            nav.path = nil
            nav.last = nil
        end
    else
        nav.still = 0
    end
    nav.last = { x = pos.x, y = pos.y }
    return "busy"
end

-- Walk until the game agrees the entity is within reach. Buildings can be
-- reached from several tiles away; trees and rocks only from next to them.
local function approach_entity(order, ch, entity)
    if ch.can_reach_entity(entity) then
        if order.nav then
            stop_walking(ch)
            order.nav = nil
        end
        return "arrived"
    end
    local radius = math.max(1.5, ch.reach_distance - 2)
    if order.close then
        local box = entity.bounding_box
        radius = 1.5
            + math.max(
                    box.right_bottom.x - box.left_top.x,
                    box.right_bottom.y - box.left_top.y
                )
                / 2
    end
    local status, message = navigate(order, ch, entity.position, radius)
    if status ~= "arrived" then
        return status, message
    end
    if order.close then
        return "fail", "cannot get within reach of " .. entity.name
    end
    order.close = true
    return "busy"
end

local function target(order, ch)
    local e = order.entity
    if e and e.valid then
        return e
    end
    e = common.entity_at(ch.surface, order.x, order.y, order.name)
    if not e then
        error(string.format("no entity at (%s, %s)", order.x, order.y), 0)
    end
    order.entity = e
    return e
end

handlers.walk = function(order, ch)
    local status, message =
        navigate(order, ch, { x = order.x, y = order.y }, order.radius or 0.5)
    if status ~= "arrived" then
        return status, message
    end
    return "done", { x = round(ch.position.x), y = round(ch.position.y) }
end

---------------------------------------------------------------------------
-- Mining

local function pick_mining_target(order, ch)
    -- A bare position means exactly the thing on that tile, not a neighbour.
    if order.x and not (order.name or order.kind or order.radius) then
        local e = common.entity_at(ch.surface, order.x, order.y)
        if e and e.minable then
            return e
        end
        return nil
    end
    local center =
        { x = order.x or ch.position.x, y = order.y or ch.position.y }
    local filter = { position = center, radius = order.radius or 1.5 }
    if order.name then
        filter.name = order.name
    end
    if order.kind == "tree" then
        filter.type = "tree"
    elseif order.kind == "rock" then
        filter.type = "simple-entity"
    elseif order.kind then
        filter.type = order.kind
    end
    local best, best_rank, best_dist
    for _, e in pairs(ch.surface.find_entities_filtered(filter)) do
        if e.minable and e.type ~= "character" and e.type ~= "item-entity" then
            -- Without a name, a building on top of ore is what was meant, not
            -- the ore.
            local rank = e.type == "resource" and 2 or 1
            local d = dist(e.position, ch.position)
            if
                not best
                or rank < best_rank
                or (rank == best_rank and d < best_dist)
            then
                best, best_rank, best_dist = e, rank, d
            end
        end
    end
    return best
end

-- count = units of ore for a resource, number of entities for anything else.
handlers.mine = function(order, ch)
    local goal = order.count or 1
    local e = order.entity
    if not (e and e.valid) then
        if order.entity then
            order.mined = (order.mined or 0)
                + (order.is_resource and order.last_amount or 1)
            order.entity = nil
            ch.mining_state = { mining = false }
        end
        if (order.mined or 0) >= goal then
            return "done", { mined = order.mined }
        end
        e = pick_mining_target(order, ch)
        if not e then
            if (order.mined or 0) > 0 then
                return "done",
                    { mined = order.mined, note = "nothing left to mine there" }
            end
            return "fail",
                string.format(
                    "nothing to mine at (%s, %s)",
                    tostring(order.x),
                    tostring(order.y)
                )
        end
        order.entity = e
        order.close = nil
        order.is_resource = e.type == "resource"
        order.last_amount = order.is_resource and e.amount or nil
        order.stalled = 0
        order.progress = nil
    end

    if order.is_resource then
        if
            order.nav
            or dist(ch.position, e.position)
                > ch.resource_reach_distance - 0.2
        then
            local status, message = navigate(order, ch, e.position, 2)
            if status ~= "arrived" then
                return status, message
            end
        end
    else
        local status, message = approach_entity(order, ch, e)
        if status ~= "arrived" then
            return status, message
        end
    end

    ch.selected = e
    if ch.selected ~= e then
        return "fail", "cannot select " .. e.name .. " for mining"
    end
    ch.mining_state = { mining = true, position = e.position }

    if order.is_resource then
        local amount = e.amount
        if amount < order.last_amount then
            order.mined = (order.mined or 0) + (order.last_amount - amount)
            order.last_amount = amount
        end
        if (order.mined or 0) >= goal then
            ch.mining_state = { mining = false }
            return "done", { mined = order.mined }
        end
    end

    local progress = ch.character_mining_progress
    if progress == order.progress then
        order.stalled = order.stalled + 1
        if order.stalled > 90 then
            ch.mining_state = { mining = false }
            return "fail",
                "mining " .. e.name .. " makes no progress (inventory full?)"
        end
    else
        order.stalled = 0
    end
    order.progress = progress
    return "busy"
end

---------------------------------------------------------------------------
-- Crafting and waiting

handlers.craft = function(order, ch)
    local count = order.count or 1
    if not order.queued then
        local possible = ch.get_craftable_count(order.recipe)
        if possible < count then
            return "fail",
                string.format(
                    "can hand-craft only %d of %d %s",
                    possible,
                    count,
                    order.recipe
                )
        end
        ch.begin_crafting({ recipe = order.recipe, count = count })
        order.queued = true
        if not order.wait then
            return "done", { queued = count }
        end
    end
    if ch.crafting_queue_size > 0 then
        return "busy"
    end
    return "done", { crafted = count }
end

-- Cancel queued hand-crafts of a recipe (all of them, or `count`), as the
-- crafting queue's
-- right-click does; the ingredients come back.
handlers.uncraft = function(order, ch)
    local left = order.count
    local cancelled = 0
    local queue = ch.crafting_queue or {}
    for i = #queue, 1, -1 do
        local item = queue[i]
        if item.recipe == order.recipe and not item.prerequisite then
            local n = left and math.min(left, item.count) or item.count
            ch.cancel_crafting({ index = item.index, count = n })
            cancelled = cancelled + n
            if left then
                left = left - n
                if left <= 0 then
                    break
                end
            end
        end
    end
    return "done", { cancelled = cancelled }
end

handlers.wait = function(order, ch)
    order.waited = (order.waited or 0) + 1
    if order.ticks then
        if order.waited >= order.ticks then
            return "done", { waited = order.waited }
        end
        return "busy"
    end
    local met
    if order.craft then
        met = ch.crafting_queue_size == 0
    elseif order.have then
        met = ch.get_item_count(order.have) >= (order.count or 1)
    elseif order.item then
        met = target(order, ch).get_item_count(order.item) >= (order.count or 1)
    else
        return "fail", "wait needs one of: ticks, craft, have, item"
    end
    if met then
        return "done", { waited = order.waited }
    end
    if order.waited >= (order.max or 18000) then
        return "fail", "still waiting after " .. order.waited .. " ticks"
    end
    return "busy"
end

---------------------------------------------------------------------------
-- Building

local function half_size(proto, direction)
    local box = proto.collision_box
    local hw = (box.right_bottom.x - box.left_top.x) / 2
    local hh = (box.right_bottom.y - box.left_top.y) / 2
    if
        direction == defines.direction.east
        or direction == defines.direction.west
    then
        hw, hh = hh, hw
    end
    return hw, hh
end

local function obstruction(surface, proto, pos, direction)
    local hw, hh = half_size(proto, direction)
    local names, seen = {}, {}
    for _, e in
        pairs(surface.find_entities_filtered({
            area = {
                { pos.x - hw, pos.y - hh },
                { pos.x + hw, pos.y + hh },
            },
            limit = 30,
        }))
    do
        if e.type ~= "resource" and not seen[e.name] then
            seen[e.name] = true
            names[#names + 1] = e.name
        end
    end
    local tile = surface.get_tile(pos.x, pos.y).name
    return (
        #names > 0 and ("in the way: " .. table.concat(names, ", ") .. "; ")
        or ""
    )
        .. "tile: "
        .. tile
end

handlers.place = function(order, ch)
    local item = prototypes.item[order.item]
    if not item then
        return "fail", "unknown item " .. tostring(order.item)
    end
    local proto = item.place_result
    if not proto then
        return "fail", order.item .. " cannot be placed as an entity"
    end
    if ch.get_item_count(order.item) < 1 then
        return "fail", "no " .. order.item .. " in inventory"
    end

    local surface = ch.surface
    local pos = { x = order.x, y = order.y }
    local direction = common.dir(order.dir) or defines.direction.north

    if order.aside then
        local status, message = navigate(order, ch, order.aside, 0.4)
        if status ~= "arrived" then
            return status, message
        end
        order.aside = nil
    end
    local status, message = navigate(order, ch, pos, ch.build_distance - 1)
    if status ~= "arrived" then
        return status, message
    end

    -- Wreckage of destroyed buildings does not stop a player building on top of
    -- it.
    do
        local hw, hh = half_size(proto, direction)
        for _, wreck in
            pairs(surface.find_entities_filtered({
                area = {
                    { pos.x - hw, pos.y - hh },
                    { pos.x + hw, pos.y + hh },
                },
                type = "corpse",
            }))
        do
            wreck.destroy()
        end
    end
    local check = {
        name = proto.name,
        position = pos,
        direction = direction,
        force = ch.force,
        build_check_type = defines.build_check_type.manual,
    }
    if not surface.can_place_entity(check) then
        local hw, hh = half_size(proto, direction)
        local standing_there = math.abs(ch.position.x - pos.x) < hw + 0.5
            and math.abs(ch.position.y - pos.y) < hh + 0.5
        if standing_there and not order.stepped_aside then
            order.stepped_aside = true
            order.aside = surface.find_non_colliding_position(
                "character",
                { pos.x + hw + 1.5, pos.y },
                8,
                0.5
            )
            if order.aside then
                return "busy"
            end
        end
        return "fail",
            string.format(
                "cannot place %s at (%s, %s): %s",
                proto.name,
                pos.x,
                pos.y,
                obstruction(surface, proto, pos, direction)
            )
    end

    local entity = surface.create_entity({
        name = proto.name,
        position = pos,
        direction = direction,
        force = ch.force,
        fast_replace = true,
        character = ch,
        spill = false,
        raise_built = true,
        create_build_effect_smoke = false,
        type = order.ug_type,
    })
    if not entity then
        return "fail", "the game refused to create " .. proto.name
    end
    ch.remove_item({ name = order.item, count = 1 })
    if entity.type == "radar" then
        common.mark_seen(
            math.floor(entity.position.x / 32),
            math.floor(entity.position.y / 32),
            common.RADAR_CHUNKS
        )
    end

    if order.recipe then
        for _, stack in pairs(entity.set_recipe(order.recipe) or {}) do
            ch.insert(stack)
        end
    end
    local info = {
        name = entity.name,
        x = round(entity.position.x),
        y = round(entity.position.y),
    }
    if entity.supports_direction then
        info.dir = common.dir_name(entity.direction)
    end
    return "done", info
end

---------------------------------------------------------------------------
-- Working with entities

handlers.put = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    local have = ch.get_item_count(order.item)
    local want = order.count and math.min(order.count, have) or have
    if want < 1 then
        return "fail", "no " .. order.item .. " in inventory"
    end
    local moved = e.insert({ name = order.item, count = want })
    if moved < 1 then
        return "fail", e.name .. " does not accept " .. order.item
    end
    ch.remove_item({ name = order.item, count = moved })
    return "done", { moved = moved, into = e.name }
end

handlers.take = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    local main = ch.get_main_inventory()
    local taken = {}
    local function take(name, available)
        local n = math.min(
            order.count or available,
            available,
            main.get_insertable_count(name)
        )
        if n < 1 then
            return
        end
        local removed = e.remove_item({ name = name, count = n })
        if removed > 0 then
            ch.insert({ name = name, count = removed })
            taken[name] = (taken[name] or 0) + removed
        end
    end
    if order.item then
        take(order.item, e.get_item_count(order.item))
    else
        -- Everything from the output; for things without one (a corpse),
        -- everything.
        local inventory = e.get_output_inventory()
        if inventory then
            for _, stack in pairs(inventory.get_contents()) do
                take(stack.name, stack.count)
            end
        else
            for index = 1, e.get_max_inventory_index() do
                local other = e.get_inventory(index)
                if other then
                    for _, stack in pairs(other.get_contents()) do
                        take(stack.name, stack.count)
                    end
                end
            end
        end
    end
    if not next(taken) then
        return "fail", "nothing to take from " .. e.name
    end
    return "done", { taken = taken, from = e.name }
end

handlers.recipe = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    local recipe = ch.force.recipes[order.recipe]
    if not (recipe and recipe.enabled) then
        return "fail", "recipe " .. tostring(order.recipe) .. " is not unlocked"
    end
    for _, stack in pairs(e.set_recipe(order.recipe) or {}) do
        ch.insert(stack)
    end
    local current = e.get_recipe()
    if not current or current.name ~= order.recipe then
        return "fail", e.name .. " cannot make " .. order.recipe
    end
    return "done", { recipe = order.recipe, on = e.name }
end

handlers.rotate = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    if order.dir then
        e.direction = common.dir(order.dir)
    else
        e.rotate()
    end
    return "done", { name = e.name, dir = common.dir_name(e.direction) }
end

-- Restrict an inserter to the listed items; an empty list removes the filter.
handlers.filter = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    local items = order.items or {}
    if e.filter_slot_count < #items then
        return "fail",
            string.format("%s has %d filter slots", e.name, e.filter_slot_count)
    end
    for slot = 1, e.filter_slot_count do
        e.set_filter(slot, items[slot])
    end
    if e.type == "inserter" then
        e.use_filters = #items > 0
        if #items > 0 then
            e.inserter_filter_mode = "whitelist"
        end
    end
    return "done", { name = e.name, filter = table.concat(items, ",") }
end

-- Flip a machine so its fluid inlets swap sides, as the flip keys do for a
-- player.
handlers.mirror = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    e.mirroring = not e.mirroring
    return "done", { name = e.name, mirrored = e.mirroring }
end

handlers.launch = function(order, ch)
    local e = target(order, ch)
    local status, message = approach_entity(order, ch, e)
    if status ~= "arrived" then
        return status, message
    end
    if e.type ~= "rocket-silo" then
        return "fail", e.name .. " is not a rocket silo"
    end
    if not e.launch_rocket() then
        return "fail", "the silo is not ready to launch"
    end
    return "done", {}
end

-- Moves a gun, armour or ammunition from the main inventory into its slot, as a
-- player does by
-- clicking it; whatever held that slot goes back to the main inventory.
local EQUIP_SLOT = {
    gun = defines.inventory.character_guns,
    armor = defines.inventory.character_armor,
    ammo = defines.inventory.character_ammo,
}
handlers.equip = function(order, ch)
    local proto = prototypes.item[order.item or ""]
    if not proto then
        return "fail", "unknown item " .. tostring(order.item)
    end
    local which = EQUIP_SLOT[proto.type]
    if not which then
        return "fail", order.item .. " is not a gun, armour or ammunition"
    end
    local main = ch.get_main_inventory()
    if main.get_item_count(order.item) < 1 then
        return "fail", "no " .. order.item .. " in inventory"
    end
    local slots = ch.get_inventory(which)
    local index = order.slot or 1
    local stack = slots[index]
    if stack.valid_for_read then
        if stack.name == order.item then
            return "done", { already = true }
        end
        local inserted = main.insert(stack)
        if inserted < stack.count then
            return "fail", "no room in the inventory for " .. stack.name
        end
        stack.clear()
    end
    local count = proto.type == "ammo"
            and math.min(main.get_item_count(order.item), proto.stack_size)
        or 1
    local removed = main.remove({ name = order.item, count = count })
    stack.set_stack({ name = order.item, count = removed })
    if proto.type == "gun" then
        ch.selected_gun_index = index
    end
    return "done", { equipped = order.item, slot = index }
end

-- Picks up loose items around the character, as holding the pickup key does.
handlers.pickup = function(order, ch)
    if order.x then
        local status, message =
            navigate(order, ch, { x = order.x, y = order.y }, 0.5)
        if status ~= "arrived" then
            return status, message
        end
    end
    order.waited = (order.waited or 0) + 1
    ch.picking_state = true
    if order.waited < (order.ticks or 30) then
        return "busy"
    end
    ch.picking_state = false
    return "done", {}
end

---------------------------------------------------------------------------
-- Queue

function orders.known(kind)
    return handlers[kind] ~= nil
end

function orders.cancel(st, ch)
    st.queue = {}
    st.current = nil
    if ch and ch.valid then
        stop_walking(ch)
        ch.mining_state = { mining = false }
        ch.picking_state = false
    end
end

local BELTS = { "transport-belt", "underground-belt", "splitter" }

-- When the work is done and the character is standing on a belt, queue a short
-- walk to the nearest free tile so it is not carried away while waiting.
local function step_off_belt(st, ch)
    local surface = ch.surface
    if
        surface.count_entities_filtered({
            position = ch.position,
            type = BELTS,
        }) == 0
    then
        return
    end
    local tx, ty = math.floor(ch.position.x), math.floor(ch.position.y)
    for radius = 1, 4 do
        for dx = -radius, radius do
            for dy = -radius, radius do
                if math.max(math.abs(dx), math.abs(dy)) == radius then
                    local spot = { x = tx + dx + 0.5, y = ty + dy + 0.5 }
                    if
                        surface.count_entities_filtered({
                                position = spot,
                                type = BELTS,
                            })
                            == 0
                        and surface.can_place_entity({
                            name = "character",
                            position = spot,
                        })
                    then
                        st.queue[#st.queue + 1] = {
                            type = "walk",
                            x = spot.x,
                            y = spot.y,
                            radius = 0.3,
                            internal = true,
                        }
                        return
                    end
                end
            end
        end
    end
end

-- Advances the current order by one tick. Returns true when nothing is left.
function orders.step(st, ch)
    local order = st.current
    if not order then
        order = table.remove(st.queue, 1)
        if not order then
            return true
        end
        order.began = game.tick
        st.current = order
    end

    local ok, status, info = pcall(handlers[order.type], order, ch)
    if not ok then
        status, info = "fail", tostring(status)
    end
    if status == "busy" then
        return false
    end

    st.current = nil
    if order.internal then
        return #st.queue == 0
    end
    local result = {
        n = order.n,
        type = order.type,
        ok = status == "done",
        ticks = game.tick - order.began,
    }
    if result.ok then
        result.info = info
    else
        result.error = info
    end
    st.results[#st.results + 1] = result
    if not result.ok then
        -- Later orders usually depend on this one, so drop them.
        st.dropped = #st.queue
        orders.cancel(st, ch)
        st.failed = true
    end
    if #st.queue == 0 then
        step_off_belt(st, ch)
    end
    return #st.queue == 0
end

return orders
