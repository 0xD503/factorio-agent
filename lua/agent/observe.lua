-- Read-only views of the game, limited to chunks that have been revealed.

local common = require("agent.common")

local round = common.round
local dist = common.dist
local contents = common.contents

local observe = { ops = {} }
local ops = observe.ops

local status_name = {}
for name, value in pairs(defines.entity_status) do
    status_name[value] = name
end

local function origin(req)
    local ch = common.character()
    local base = ch and ch.position or { x = 0, y = 0 }
    return { x = req.x or base.x, y = req.y or base.y }
end

local function sort_by_distance(list, center)
    table.sort(list, function(a, b)
        return dist(a.position, center) < dist(b.position, center)
    end)
end

---------------------------------------------------------------------------
-- Character and overall state

local function character_info(ch)
    local info = {
        x = round(ch.position.x),
        y = round(ch.position.y),
        health = math.floor(ch.health),
        max_health = math.floor(ch.max_health),
        inventory = contents(ch.get_main_inventory()),
        guns = contents(ch.get_inventory(defines.inventory.character_guns)),
        ammo = contents(ch.get_inventory(defines.inventory.character_ammo)),
        armor = contents(ch.get_inventory(defines.inventory.character_armor)),
        crafting = {},
    }
    if ch.crafting_queue_size > 0 then
        for _, entry in pairs(ch.crafting_queue) do
            info.crafting[#info.crafting + 1] =
                { recipe = entry.recipe, count = entry.count }
        end
    end
    return info
end

local function research_info()
    local force = common.force()
    local info = { queue = {} }
    local current = force.current_research
    if current then
        info.current = current.name
        info.progress = round(force.research_progress)
    end
    for _, tech in pairs(force.research_queue) do
        info.queue[#info.queue + 1] = tech.name
    end
    return info
end

function observe.brief()
    local st = common.state()
    local ch = common.character()
    local out = { tick = game.tick }
    if ch then
        out.x, out.y = round(ch.position.x), round(ch.position.y)
        out.health = math.floor(ch.health)
        out.inventory = contents(ch.get_main_inventory())
        out.crafting = ch.crafting_queue_size
    else
        out.dead = true
        out.respawn_in = st.respawn_at and (st.respawn_at - game.tick) or nil
    end
    return out
end

ops.state = function()
    local st = common.state()
    local ch = common.character()
    local out = {
        started = st.started or false,
        mode = st.mode,
        name = st.name,
        chat_seq = st.chat_seq,
        players_online = #game.connected_players,
        seed = common.surface().map_gen_settings.seed,
        deaths = st.deaths,
        speed = st.run_speed,
        research = research_info(),
        orders = {
            current = st.current and st.current.type or nil,
            queued = #st.queue,
        },
        evolution = round(
            game.forces.enemy.get_evolution_factor(common.surface())
        ),
    }
    if ch then
        out.character = character_info(ch)
        out.pollution = round(ch.surface.get_pollution(ch.position))
    end
    return out
end

---------------------------------------------------------------------------
-- Entity detail

local function xy(position)
    return { round(position.x), round(position.y) }
end

local function describe_unsafe(e)
    local d =
        { name = e.name, x = round(e.position.x), y = round(e.position.y) }
    local kind = e.type
    if kind == "resource" then
        d.amount = e.amount
        return d
    end
    if kind == "entity-ghost" then
        d.ghost = e.ghost_name
        local ok, recipe = pcall(function()
            return e.get_recipe()
        end)
        if ok and recipe then
            d.recipe = recipe.name
        end
    end
    if e.supports_direction then
        d.dir = common.dir_name(e.direction)
    end
    local status = e.status
    if status then
        d.status = status_name[status]
    end

    if
        kind == "assembling-machine"
        or kind == "furnace"
        or kind == "rocket-silo"
    then
        local recipe = e.get_recipe()
        if recipe then
            d.recipe = recipe.name
        end
        if e.is_crafting() then
            d.progress = round(e.crafting_progress)
        end
        if kind == "rocket-silo" then
            d.rocket_parts = e.rocket_parts
        end
    elseif kind == "inserter" then
        d.pickup = xy(e.pickup_position)
        d.drop = xy(e.drop_position)
        if e.held_stack.valid_for_read then
            d.held = e.held_stack.name
        end
        if e.use_filters then
            local names = {}
            for slot = 1, e.filter_slot_count do
                local filter = e.get_filter(slot)
                if filter then
                    names[#names + 1] = type(filter.name) == "string"
                            and filter.name
                        or filter.name.name
                end
            end
            d.filter = table.concat(names, ",")
        end
    elseif kind == "mining-drill" then
        d.drop = xy(e.drop_position)
        local mining = e.mining_target
        if mining then
            d.mining = mining.name
        end
    elseif kind == "underground-belt" then
        d.ug = e.belt_to_ground_type
    end

    if e.health and e.health < e.max_health then
        d.hp = round(e.health / e.max_health)
    end

    local items
    for index = 1, e.get_max_inventory_index() do
        local inventory = e.get_inventory(index)
        if inventory and not inventory.is_empty() then
            items = items or {}
            items[e.get_inventory_name(index)] = contents(inventory)
        end
    end
    d.items = items

    if
        kind == "transport-belt"
        or kind == "underground-belt"
        or kind == "splitter"
    then
        local on_belt = {}
        for index = 1, e.get_max_transport_line_index() do
            for _, stack in pairs(e.get_transport_line(index).get_contents()) do
                on_belt[stack.name] = (on_belt[stack.name] or 0) + stack.count
            end
        end
        if next(on_belt) then
            d.belt = on_belt
        end
    end

    local fluids = e.get_fluid_contents()
    if next(fluids) then
        d.fluids = {}
        for name, amount in pairs(fluids) do
            d.fluids[name] = math.floor(amount)
        end
    end

    -- Where pipes have to go to connect, and whether something is connected
    -- there.
    -- For a pipe-to-ground the underground end is marked [ug].
    if kind ~= "pipe" then
        local fluidbox = common.get(e, "fluidbox") or {}
        local pipes = {}
        for index = 1, #fluidbox do
            for _, connection in pairs(fluidbox.get_pipe_connections(index)) do
                local at = connection.target_position
                pipes[#pipes + 1] = string.format(
                    "%s,%s%s%s",
                    round(at.x),
                    round(at.y),
                    (connection.connection_type == "underground") and "[ug]"
                        or "",
                    connection.target and "" or "(open)"
                )
            end
        end
        if #pipes > 0 then
            d.pipes = table.concat(pipes, " ")
        end
    end

    local burner = common.get(e, "burner")
    if burner then
        d.fuel = burner.inventory.get_item_count()
        if burner.currently_burning then
            d.burning = burner.currently_burning.name.name
        end
    end
    return d
end

local function describe(e)
    local ok, d = pcall(describe_unsafe, e)
    if ok then
        return d
    end
    return {
        name = e.name,
        x = round(e.position.x),
        y = round(e.position.y),
        note = tostring(d),
    }
end

local function search_filter(req)
    if req.x1 then
        return { area = { { req.x1, req.y1 }, { req.x2, req.y2 } } }, {
            x = (req.x1 + req.x2) / 2,
            y = (req.y1 + req.y2) / 2,
        }
    end
    local center = origin(req)
    return { position = center, radius = req.r or 20 }, center
end

-- Detailed list. Without a name or type it shows the player's own buildings.
ops.entities = function(req)
    local filter, center = search_filter(req)
    filter.name = req.name
    filter.type = req.type
    if not (req.name or req.type or req.all) then
        filter.force = common.force()
    end
    local found = common.surface().find_entities_filtered(filter)
    sort_by_distance(found, center)
    local out, total = {}, 0
    local limit = req.limit or 60
    for _, e in pairs(found) do
        if e.type ~= "character" and common.charted(e.position) then
            total = total + 1
            if #out < limit then
                out[#out + 1] = describe(e)
            end
        end
    end
    return { entities = out, total = total }
end

-- Own buildings grouped by name and status, with a few positions for each
-- status that is not plain "working" or "normal".
ops.buildings = function(req)
    local filter, center = search_filter(req)
    filter.force = common.force()
    local groups = {}
    for _, e in pairs(common.surface().find_entities_filtered(filter)) do
        local status = e.status
        if status and e.type ~= "character" then
            local key = e.name .. " " .. status_name[status]
            local group = groups[key]
            if not group then
                group = {
                    name = e.name,
                    status = status_name[status],
                    count = 0,
                    at = {},
                }
                groups[key] = group
            end
            group.count = group.count + 1
            if
                group.status ~= "working"
                and group.status ~= "normal"
                and #group.at < 6
            then
                group.at[#group.at + 1] = xy(e.position)
            end
        end
    end
    local out = {}
    for _, group in pairs(groups) do
        out[#out + 1] = group
    end
    return { groups = out }
end

-- Nearest entities of a name or type.
ops.find = function(req)
    if not (req.name or req.type) then
        error("find needs a name or a type", 0)
    end
    local center = origin(req)
    local found = common.surface().find_entities_filtered({
        position = center,
        radius = req.r or 150,
        name = req.name,
        type = req.type,
    })
    sort_by_distance(found, center)
    local out = {}
    local limit = req.limit or 8
    for _, e in pairs(found) do
        if common.charted(e.position) then
            local d = {
                name = e.name,
                x = round(e.position.x),
                y = round(e.position.y),
                dist = round(dist(e.position, center)),
            }
            if e.type == "resource" then
                d.amount = e.amount
            end
            out[#out + 1] = d
            if #out >= limit then
                break
            end
        end
    end
    return { found = out }
end

---------------------------------------------------------------------------
-- Area summary

local CELL = 8

local function resource_patches(entities, center)
    local cells = {}
    for _, e in pairs(entities) do
        local p = e.position
        local gx, gy = math.floor(p.x / CELL), math.floor(p.y / CELL)
        local by_name = cells[e.name]
        if not by_name then
            by_name = {}
            cells[e.name] = by_name
        end
        local key = gx .. "," .. gy
        local cell = by_name[key]
        if not cell then
            cell = {
                gx = gx,
                gy = gy,
                tiles = 0,
                amount = 0,
                x1 = p.x,
                y1 = p.y,
                x2 = p.x,
                y2 = p.y,
            }
            by_name[key] = cell
        end
        cell.tiles = cell.tiles + 1
        cell.amount = cell.amount + e.amount
        cell.x1, cell.y1 = math.min(cell.x1, p.x), math.min(cell.y1, p.y)
        cell.x2, cell.y2 = math.max(cell.x2, p.x), math.max(cell.y2, p.y)
    end

    local out = {}
    for name, by_name in pairs(cells) do
        for _, first in pairs(by_name) do
            if not first.seen then
                first.seen = true
                local patch = {
                    name = name,
                    tiles = 0,
                    amount = 0,
                    x1 = first.x1,
                    y1 = first.y1,
                    x2 = first.x2,
                    y2 = first.y2,
                }
                local stack = { first }
                while #stack > 0 do
                    local cell = table.remove(stack)
                    patch.tiles = patch.tiles + cell.tiles
                    patch.amount = patch.amount + cell.amount
                    patch.x1, patch.y1 =
                        math.min(patch.x1, cell.x1), math.min(patch.y1, cell.y1)
                    patch.x2, patch.y2 =
                        math.max(patch.x2, cell.x2), math.max(patch.y2, cell.y2)
                    for dx = -1, 1 do
                        for dy = -1, 1 do
                            local neighbour =
                                by_name[(cell.gx + dx) .. "," .. (cell.gy + dy)]
                            if neighbour and not neighbour.seen then
                                neighbour.seen = true
                                stack[#stack + 1] = neighbour
                            end
                        end
                    end
                end
                patch.x1, patch.y1 = math.floor(patch.x1), math.floor(patch.y1)
                patch.x2, patch.y2 = math.floor(patch.x2), math.floor(patch.y2)
                patch.position = {
                    x = (patch.x1 + patch.x2) / 2,
                    y = (patch.y1 + patch.y2) / 2,
                }
                patch.dist = math.floor(dist(patch.position, center))
                out[#out + 1] = patch
            end
        end
    end
    sort_by_distance(out, center)
    for _, patch in pairs(out) do
        patch.position = nil
    end
    return out
end

local water_names

local function water_tiles()
    if not water_names then
        water_names = {}
        for name, tile in pairs(prototypes.tile) do
            if tile.collision_mask.layers["water_tile"] then
                water_names[#water_names + 1] = name
            end
        end
    end
    return water_names
end

local function charted_only(list)
    local out = {}
    for _, e in pairs(list) do
        if common.charted(e.position) then
            out[#out + 1] = e
        end
    end
    return out
end

ops.scan = function(req)
    local surface, force = common.surface(), common.force()
    local center = origin(req)
    local r = math.min(req.r or 64, 300)
    local area =
        { { center.x - r, center.y - r }, { center.x + r, center.y + r } }
    local out = { x = round(center.x), y = round(center.y), r = r }

    out.resources = resource_patches(
        charted_only(
            surface.find_entities_filtered({ area = area, type = "resource" })
        ),
        center
    )

    local trees = charted_only(
        surface.find_entities_filtered({ area = area, type = "tree" })
    )
    out.trees = { count = #trees }
    if #trees > 0 then
        local nearest = surface.get_closest(center, trees)
        out.trees.nearest = xy(nearest.position)
    end

    out.rocks = {}
    local rocks = charted_only(
        surface.find_entities_filtered({ area = area, type = "simple-entity" })
    )
    sort_by_distance(rocks, center)
    for _, rock in pairs(rocks) do
        if rock.minable and #out.rocks < 8 then
            out.rocks[#out.rocks + 1] = {
                name = rock.name,
                x = round(rock.position.x),
                y = round(rock.position.y),
            }
        end
    end

    local water = charted_only(
        surface.find_tiles_filtered({ area = area, name = water_tiles() })
    )
    out.water = { tiles = #water }
    if #water > 0 then
        local best, best_dist
        for _, tile in pairs(water) do
            local d = dist(tile.position, center)
            if not best or d < best_dist then
                best, best_dist = tile, d
            end
        end
        out.water.nearest = { best.position.x, best.position.y }
    end

    -- Nests stay known once seen; moving units only where the character can see
    -- now.
    local nests = charted_only(surface.find_entities_filtered({
        area = area,
        force = "enemy",
        type = { "unit-spawner", "turret" },
    }))
    out.enemy = { nests = #nests, units = 0 }
    if #nests > 0 then
        local nearest = surface.get_closest(center, nests)
        out.enemy.nearest_nest = xy(nearest.position)
        out.enemy.nearest_nest_dist = math.floor(dist(nearest.position, center))
    end
    for _, unit in
        pairs(surface.find_entities_filtered({
            area = area,
            force = "enemy",
            type = "unit",
        }))
    do
        if common.in_view(unit.position) then
            out.enemy.units = out.enemy.units + 1
        end
    end

    out.own = {}
    for _, e in
        pairs(surface.find_entities_filtered({ area = area, force = force }))
    do
        if e.type ~= "character" then
            out.own[e.name] = (out.own[e.name] or 0) + 1
        end
    end

    -- Wreckage and other neutral containers that hold something.
    out.containers = {}
    for _, e in
        pairs(charted_only(surface.find_entities_filtered({
            area = area,
            type = "container",
        })))
    do
        local inventory = e.get_inventory(defines.inventory.chest)
        local wreck = e.force ~= force
            or string.sub(e.name, 1, 10) == "crash-site"
        if wreck and inventory and not inventory.is_empty() then
            out.containers[#out.containers + 1] = {
                name = e.name,
                x = round(e.position.x),
                y = round(e.position.y),
                items = contents(inventory),
            }
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Tile map, one character per tile

local BELT = { [0] = "^", [4] = ">", [8] = "v", [12] = "<" }
local RESOURCE = {
    ["iron-ore"] = "i",
    ["copper-ore"] = "c",
    ["coal"] = "k",
    ["stone"] = "s",
    ["uranium-ore"] = "u",
    ["crude-oil"] = "o",
}
local BY_NAME = { ["oil-refinery"] = "Y", ["chemical-plant"] = "H" }
local BY_TYPE = {
    ["splitter"] = "S",
    ["pipe"] = "=",
    ["pipe-to-ground"] = "p",
    ["pump"] = "q",
    ["electric-pole"] = "+",
    ["assembling-machine"] = "A",
    ["furnace"] = "F",
    ["mining-drill"] = "M",
    ["lab"] = "L",
    ["container"] = "C",
    ["logistic-container"] = "C",
    ["boiler"] = "B",
    ["generator"] = "G",
    ["offshore-pump"] = "O",
    ["ammo-turret"] = "X",
    ["electric-turret"] = "X",
    ["fluid-turret"] = "X",
    ["artillery-turret"] = "X",
    ["wall"] = "W",
    ["gate"] = "w",
    ["radar"] = "D",
    ["storage-tank"] = "K",
    ["roboport"] = "P",
    ["beacon"] = "N",
    ["rocket-silo"] = "Z",
    ["solar-panel"] = "*",
    ["accumulator"] = "a",
    ["straight-rail"] = "/",
    ["curved-rail-a"] = "/",
    ["curved-rail-b"] = "/",
    ["half-diagonal-rail"] = "/",
    ["train-stop"] = "t",
    ["locomotive"] = "l",
    ["cargo-wagon"] = "l",
    ["fluid-wagon"] = "l",
    ["car"] = "&",
    ["spider-vehicle"] = "&",
    ["reactor"] = "E",
    ["heat-pipe"] = "h",
}

local function symbol(e)
    local kind = e.type
    if kind == "character" then
        return "@", 9
    end
    if kind == "resource" then
        return RESOURCE[e.name] or "r", 2
    end
    if kind == "tree" then
        return "T", 3
    end
    if kind == "cliff" then
        return "#", 3
    end
    if kind == "simple-entity" then
        return "R", 3
    end
    if
        kind == "unit-spawner" or (kind == "turret" and e.force.name == "enemy")
    then
        return "!", 6
    end
    if kind == "unit" then
        return "e", 7
    end
    if kind == "item-entity" then
        return "$", 4
    end
    if kind == "entity-ghost" then
        return "g", 5
    end
    if not e.unit_number then
        return nil
    end
    if kind == "transport-belt" then
        return BELT[e.direction] or "%", 6
    end
    if kind == "underground-belt" then
        return e.belt_to_ground_type == "input" and "(" or ")", 6
    end
    if kind == "inserter" then
        local dx = e.drop_position.x - e.pickup_position.x
        local dy = e.drop_position.y - e.pickup_position.y
        if math.abs(dx) > math.abs(dy) then
            return dx > 0 and "→" or "←", 6
        end
        return dy > 0 and "↓" or "↑", 6
    end
    return BY_NAME[e.name] or BY_TYPE[kind] or "%", 6
end

-- Coarse map: one character per scale x scale tiles. B = own buildings,
-- ! = enemy nest, ore letters, ~ = mostly water, T = wooded.
local function overview(req)
    local surface, force = common.surface(), common.force()
    local scale = math.floor(req.scale)
    local center = origin(req)
    local w = math.min(req.w or 64, 200)
    local h = math.min(req.h or 32, 120)
    local x0 = math.floor((req.x1 or (center.x - w * scale / 2)) / scale)
        * scale
    local y0 = math.floor((req.y1 or (center.y - h * scale / 2)) / scale)
        * scale
    local area = { { x0, y0 }, { x0 + w * scale, y0 + h * scale } }

    local cells = {}
    for r = 1, h do
        cells[r] = {}
        for c = 1, w do
            cells[r][c] = { water = 0, trees = 0, own = 0, ore = 0 }
        end
    end
    local function cell(position)
        local c = math.floor((position.x - x0) / scale) + 1
        local r = math.floor((position.y - y0) / scale) + 1
        return cells[r] and cells[r][c]
    end

    for _, tile in
        pairs(
            surface.find_tiles_filtered({ area = area, name = water_tiles() })
        )
    do
        local at = cell(tile.position)
        if at then
            at.water = at.water + 1
        end
    end
    for _, e in
        pairs(surface.find_entities_filtered({
            area = area,
            type = { "resource", "tree", "unit-spawner", "turret" },
        }))
    do
        local at = cell(e.position)
        if at then
            if e.type == "tree" then
                at.trees = at.trees + 1
            elseif e.type == "resource" then
                at.ore = at.ore + 1
                at.ores = at.ores or {}
                at.ores[e.name] = (at.ores[e.name] or 0) + 1
            elseif e.force.name == "enemy" then
                at.nest = true
            end
        end
    end
    for _, e in
        pairs(surface.find_entities_filtered({ area = area, force = force }))
    do
        local at = cell(e.position)
        if at then
            if e.type == "character" then
                at.me = true
            else
                at.own = at.own + 1
            end
        end
    end

    local lines = {}
    for r = 1, h do
        local row = {}
        for c = 1, w do
            local at = cells[r][c]
            local middle =
                { x = x0 + (c - 0.5) * scale, y = y0 + (r - 0.5) * scale }
            local char = "."
            if not common.charted(middle) then
                char = "?"
            elseif at.me then
                char = "@"
            elseif at.nest then
                char = "!"
            elseif at.own > 0 then
                char = "B"
            elseif at.ore > 0 then
                local best, best_count
                for name, count in pairs(at.ores) do
                    if not best or count > best_count then
                        best, best_count = name, count
                    end
                end
                char = RESOURCE[best] or "r"
            elseif at.water * 2 >= scale * scale then
                char = "~"
            elseif at.trees * 16 >= scale * scale then
                char = "T"
            end
            row[c] = char
        end
        lines[r] = table.concat(row)
    end
    return { x = x0, y = y0, w = w, h = h, scale = scale, rows = lines }
end

ops.map = function(req)
    if req.scale and req.scale > 1 then
        return overview(req)
    end
    local surface, force = common.surface(), common.force()
    local center = origin(req)
    local w = math.min(req.w or 64, 200)
    local h = math.min(req.h or 32, 120)
    local x0 = math.floor(req.x1 or (center.x - w / 2))
    local y0 = math.floor(req.y1 or (center.y - h / 2))

    local rows, priority = {}, {}
    for r = 1, h do
        local row, prow = {}, {}
        for c = 1, w do
            row[c], prow[c] = ".", 0
        end
        rows[r], priority[r] = row, prow
    end
    local function put(x, y, char, p)
        local c, r = x - x0 + 1, y - y0 + 1
        if c >= 1 and c <= w and r >= 1 and r <= h and p >= priority[r][c] then
            rows[r][c], priority[r][c] = char, p
        end
    end

    local area = { { x0, y0 }, { x0 + w, y0 + h } }
    for _, tile in
        pairs(
            surface.find_tiles_filtered({ area = area, name = water_tiles() })
        )
    do
        put(tile.position.x, tile.position.y, "~", 1)
    end
    for _, e in pairs(surface.find_entities_filtered({ area = area })) do
        local char, p = symbol(e)
        if char then
            -- Boxes can poke slightly past the tiles an entity occupies.
            local box = e.bounding_box
            local x1 = math.floor(box.left_top.x + 0.2)
            local x2 = math.ceil(box.right_bottom.x - 0.2) - 1
            for x = x1, x2 do
                local y1 = math.floor(box.left_top.y + 0.2)
                local y2 = math.ceil(box.right_bottom.y - 0.2) - 1
                for y = y1, y2 do
                    put(x, y, char, p)
                end
            end
        end
    end
    for cx = math.floor(x0 / 32), math.floor((x0 + w - 1) / 32) do
        for cy = math.floor(y0 / 32), math.floor((y0 + h - 1) / 32) do
            if not common.chunk_seen(cx, cy) then
                for x = cx * 32, cx * 32 + 31 do
                    for y = cy * 32, cy * 32 + 31 do
                        put(x, y, "?", 99)
                    end
                end
            end
        end
    end

    local lines = {}
    for r = 1, h do
        lines[r] = table.concat(rows[r])
    end
    return { x = x0, y = y0, w = w, h = h, rows = lines }
end

---------------------------------------------------------------------------
-- Recipes, technologies, statistics

-- The recipe's crafting categories. Newer 2.0 releases list several
-- (`categories`); earlier
-- ones had one (`category`). Reading a key a LuaObject does not have raises,
-- hence pcall.
local function recipe_categories(proto)
    local ok, list = pcall(function()
        return proto.categories
    end)
    if ok and type(list) == "table" then
        return list
    end
    local ok_one, one = pcall(function()
        return proto.category
    end)
    if ok_one and one then
        return { one }
    end
    return {}
end

local function recipe_info(recipe, force, ch)
    local proto = recipe.prototype
    local categories = recipe_categories(proto)
    local info = {
        name = recipe.name,
        category = table.concat(categories, ","),
        seconds = proto.energy,
        enabled = recipe.enabled,
        ingredients = {},
        products = {},
    }
    for _, ingredient in pairs(proto.ingredients) do
        info.ingredients[ingredient.name] = ingredient.amount
    end
    for _, product in pairs(proto.products) do
        info.products[product.name] = product.amount
            or ((product.amount_min + product.amount_max) / 2)
    end
    info.by_hand = false
    info.made_in = {}
    local seen = {}
    for _, category in pairs(categories) do
        if ch ~= nil and ch.prototype.crafting_categories[category] then
            info.by_hand = true
        end
        for name in
            pairs(prototypes.get_entity_filtered({
                {
                    filter = "crafting-category",
                    crafting_category = category,
                },
            }))
        do
            if name ~= "character" and not seen[name] then
                seen[name] = true
                info.made_in[#info.made_in + 1] = name
            end
        end
    end
    return info
end

-- By recipe name, or every recipe that makes the named item or fluid.
ops.recipe = function(req)
    local force, ch = common.force(), common.character()
    local out = {}
    local exact = force.recipes[req.name]
    if exact then
        out[1] = recipe_info(exact, force, ch)
    end
    for _, recipe in pairs(force.recipes) do
        if recipe.name ~= req.name then
            for _, product in pairs(recipe.prototype.products) do
                if product.name == req.name then
                    out[#out + 1] = recipe_info(recipe, force, ch)
                    break
                end
            end
        end
    end
    if #out == 0 then
        error("no recipe named or producing " .. tostring(req.name), 0)
    end
    return { recipes = out }
end

local function tech_cost(tech)
    local cost = {
        count = tech.research_unit_count,
        seconds = tech.research_unit_energy / 60,
        packs = {},
    }
    for _, ingredient in pairs(tech.research_unit_ingredients) do
        cost.packs[ingredient.name] = ingredient.amount
    end
    return cost
end

local function tech_trigger(tech)
    local trigger = tech.prototype.research_trigger
    if not trigger then
        return nil
    end
    local out = { type = trigger.type }
    for _, key in pairs({ "item", "entity", "fluid", "count", "amount" }) do
        local value = trigger[key]
        if type(value) == "table" then
            value = value.name or value
        end
        if type(value) == "userdata" then
            value = value.name
        end
        out[key] = value
    end
    return out
end

ops.tech = function(req)
    local tech = common.force().technologies[req.name]
    if not tech then
        error("no technology named " .. tostring(req.name), 0)
    end
    local out = {
        name = tech.name,
        researched = tech.researched,
        enabled = tech.enabled,
        prerequisites = {},
        unlocks = {},
        effects = {},
    }
    for name, prerequisite in pairs(tech.prerequisites) do
        out.prerequisites[name] = prerequisite.researched
    end
    out.trigger = tech_trigger(tech)
    if not out.trigger then
        out.cost = tech_cost(tech)
    end
    for _, effect in pairs(tech.prototype.effects) do
        if effect.type == "unlock-recipe" then
            out.unlocks[#out.unlocks + 1] = effect.recipe
        else
            out.effects[#out.effects + 1] = effect.type
        end
    end
    return out
end

-- Technologies that can be researched right now.
ops.techs = function()
    local out = {}
    for name, tech in pairs(common.force().technologies) do
        if tech.enabled and not tech.researched then
            local ready = true
            for _, prerequisite in pairs(tech.prerequisites) do
                if not prerequisite.researched then
                    ready = false
                    break
                end
            end
            if ready then
                local entry = { name = name, trigger = tech_trigger(tech) }
                if not entry.trigger then
                    entry.cost = tech_cost(tech)
                end
                out[#out + 1] = entry
            end
        end
    end
    return { available = out, research = research_info() }
end

ops.production = function(req)
    local force, surface = common.force(), common.surface()
    local out = {}
    for kind, stats in pairs({
        items = force.get_item_production_statistics(surface),
        fluids = force.get_fluid_production_statistics(surface),
    }) do
        local made, used = stats.input_counts, stats.output_counts
        local names = {}
        for name in pairs(made) do
            names[name] = true
        end
        for name in pairs(used) do
            names[name] = true
        end
        local section = {}
        for name in pairs(names) do
            if not req.names or req.names[name] then
                local function rate(category, precision)
                    return round(stats.get_flow_count({
                        name = name,
                        category = category,
                        precision_index = precision,
                    }))
                end
                section[name] = {
                    made = made[name] or 0,
                    used = used[name] or 0,
                    made_1m = rate(
                        "input",
                        defines.flow_precision_index.one_minute
                    ),
                    used_1m = rate(
                        "output",
                        defines.flow_precision_index.one_minute
                    ),
                    made_10m = rate(
                        "input",
                        defines.flow_precision_index.ten_minutes
                    ),
                    used_10m = rate(
                        "output",
                        defines.flow_precision_index.ten_minutes
                    ),
                }
            end
        end
        out[kind] = section
    end
    return out
end

-- Electric network of the pole nearest to the given point: what generators
-- can deliver, what is being drawn, and the biggest consumers.
ops.power = function(req)
    local surface, force = common.surface(), common.force()
    local center = origin(req)
    local poles = surface.find_entities_filtered({
        position = center,
        radius = req.r or 40,
        type = "electric-pole",
        force = force,
    })
    if #poles == 0 then
        error("no electric pole near there", 0)
    end
    local pole = surface.get_closest(center, poles)
    local stats = pole.electric_network_statistics
    local function watts(name, category)
        -- Flow is reported in joules per tick.
        return stats.get_flow_count({
            name = name,
            category = category,
            precision_index = defines.flow_precision_index.five_seconds,
        }) * 60
    end
    local out = { produced = 0, consumed = 0, consumers = {}, producers = {} }
    for name in pairs(stats.input_counts) do
        local w = watts(name, "input")
        out.consumed = out.consumed + w
        out.consumers[name] = math.floor(w / 1000)
    end
    for name in pairs(stats.output_counts) do
        local w = watts(name, "output")
        out.produced = out.produced + w
        out.producers[name] = math.floor(w / 1000)
    end
    out.produced, out.consumed =
        math.floor(out.produced / 1000), math.floor(out.consumed / 1000)
    out.capacity = 0
    for _, e in
        pairs(surface.find_entities_filtered({
            type = "generator",
            force = force,
        }))
    do
        if e.electric_network_id == pole.electric_network_id then
            out.capacity = out.capacity
                + math.floor(
                    e.prototype.get_max_energy_production() * 60 / 1000
                )
        end
    end
    return out
end

ops.enemies = function(req)
    local surface, force = common.surface(), common.force()
    local center = origin(req)
    local out = {
        evolution = round(game.forces.enemy.get_evolution_factor(surface)),
        pollution = round(surface.get_pollution(center)),
        nests = {},
    }
    local nests = charted_only(surface.find_entities_filtered({
        position = center,
        radius = req.r or 300,
        force = "enemy",
        type = { "unit-spawner", "turret" },
    }))
    sort_by_distance(nests, center)
    for _, nest in pairs(nests) do
        if #out.nests >= (req.limit or 10) then
            break
        end
        out.nests[#out.nests + 1] = {
            name = nest.name,
            x = round(nest.position.x),
            y = round(nest.position.y),
            dist = math.floor(dist(nest.position, center)),
        }
    end
    out.total_nests = #nests
    return out
end

ops.can_place = function(req)
    local ch = common.need_character()
    local item = prototypes.item[req.item]
    local proto = item and item.place_result
    if not proto then
        error(tostring(req.item) .. " is not a placeable item", 0)
    end
    local ok = ch.surface.can_place_entity({
        name = proto.name,
        position = { req.x, req.y },
        direction = common.dir(req.dir) or defines.direction.north,
        force = ch.force,
        build_check_type = defines.build_check_type.manual,
    })
    return { can_place = ok, entity = proto.name }
end

return observe
