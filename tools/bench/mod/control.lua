-- Development bench: builds one blueprint in a throwaway game, feeds its ports,
-- and logs rates and machine states as BENCH-SAMPLE and BENCH-REPORT lines.
--
-- tools/bench/run.py generates payload.lua and runs this in a temporary data
-- directory. It has no console commands, and `fx` never loads it.
local payload = require("payload")

local SURFACE = "bench"
local ORIGIN = { x = 0, y = 0 }

local status_names = {}
for name, value in pairs(defines.entity_status) do
    status_names[value] = name
end

-- Units of finished technologies, plus the share of the current one, so the
-- count keeps rising across a change of technology.
script.on_event(defines.events.on_research_finished, function(event)
    storage.units_done = (storage.units_done or 0)
        + event.research.research_unit_count
end)

local function research_units()
    local force = game.forces.player
    local current = force.current_research
    local share = current
            and force.research_progress * current.research_unit_count
        or 0
    return (storage.units_done or 0) + share
end

local function tile_entity(surface, x, y, types)
    local found = surface.find_entities_filtered({
        area = { { x + 0.1, y + 0.1 }, { x + 0.9, y + 0.9 } },
        type = types,
    })
    return found[1]
end

local function setup()
    local force = game.forces.player
    force.research_all_technologies()
    -- Researching everything also grants its bonuses. A module has to work
    -- without them, because it is built before they exist.
    force.inserter_stack_size_bonus = 0
    force.bulk_inserter_capacity_bonus = 0
    force.mining_drill_productivity_bonus = 0
    force.laboratory_speed_modifier = 0
    force.laboratory_productivity_bonus = 0
    local surface = game.create_surface(SURFACE, {
        default_enable_all_autoplace_controls = false,
        autoplace_settings = {
            entity = { treat_missing_as_default = false },
            tile = { treat_missing_as_default = false },
            decorative = { treat_missing_as_default = false },
        },
    })
    surface.generate_with_lab_tiles = true
    surface.always_day = true
    local radius = 8
    surface.request_to_generate_chunks({ 0, 0 }, radius)
    surface.force_generate_chunk_requests()
    force.chart(surface, {
        { -radius * 32, -radius * 32 },
        { radius * 32, radius * 32 },
    })
    storage.surface = surface
    if payload.research then
        -- Several technologies, so the labs never run out within a run.
        for _, name in pairs(payload.research.names) do
            force.technologies[name].researched = false
        end
        force.laboratory_speed_modifier = payload.research.speed
        force.research_queue = payload.research.names
    end
    if payload.ore then
        local half_w = math.ceil(payload.width / 2) + 4
        local half_h = math.ceil(payload.height / 2) + 4
        for x = -half_w, half_w do
            for y = -half_h, half_h do
                surface.create_entity({
                    name = payload.ore,
                    position = { x + 0.5, y + 0.5 },
                    amount = 1000000,
                })
            end
        end
    end
end

local function build()
    local surface = storage.surface
    local force = game.forces.player
    local inventory = game.create_inventory(1)
    local stack = inventory[1]
    local report = storage.report
    local imported = stack.import_stack(payload.blueprint)
    if imported ~= 0 then
        report.errors[#report.errors + 1] = "import_stack: " .. imported
    end
    if stack.is_blueprint_book then
        -- A book is only checked for importing: count its pages.
        local pages = stack.get_inventory(defines.inventory.item_main)
        report.book_pages = #pages - pages.count_empty_stacks()
        report.ghosts = 0
        inventory.destroy()
        return
    end
    local ghosts = stack.build_blueprint({
        surface = surface,
        force = force,
        position = ORIGIN,
        build_mode = defines.build_mode.forced,
        skip_fog_of_war = false,
    })
    report.ghosts = #ghosts
    for _, ghost in pairs(ghosts) do
        if ghost.valid then
            local revived = ghost.revive()
            if not revived then
                report.errors[#report.errors + 1] = "not revived: "
                    .. ghost.ghost_name
            end
        end
    end
    inventory.destroy()
end

-- The blueprint is centred on the position it is built at, so a port's tile in
-- the module is found relative to the area the module actually covers.
local function bounds()
    local surface = storage.surface
    local x1, y1 = math.huge, math.huge
    for _, e in pairs(surface.find_entities_filtered({ force = "player" })) do
        local box = e.selection_box
        x1 = math.min(x1, math.floor(box.left_top.x + 0.01))
        y1 = math.min(y1, math.floor(box.left_top.y + 0.01))
    end
    return x1, y1
end

local function connect_power(x1, y1)
    local surface = storage.surface
    local force = game.forces.player
    local report = storage.report
    local px, py = x1 - 6, y1 - 6
    local source = surface.create_entity({
        name = "electric-energy-interface",
        position = { px, py },
        force = force,
    })
    source.electric_buffer_size = 1e10
    if payload.power_demand then
        source.power_production = 0
        source.power_usage = payload.power_demand / 60
    else
        source.power_production = 1e10
    end
    local pole = surface.create_entity({
        name = "substation",
        position = { px + 3, py },
        force = force,
    })
    storage.power_pole = pole
    local first
    local nearest = math.huge
    for _, e in
        pairs(surface.find_entities_filtered({ type = "electric-pole" }))
    do
        if e ~= pole then
            local dx = e.position.x - pole.position.x
            local dy = e.position.y - pole.position.y
            if dx * dx + dy * dy < nearest then
                nearest, first = dx * dx + dy * dy, e
            end
        end
    end
    if not first then
        if payload.needs_power then
            report.errors[#report.errors + 1] = "module has no pole"
        end
        return
    end
    local copper = defines.wire_connector_id.pole_copper
    local ours = pole.get_wire_connector(copper, true)
    local theirs = first.get_wire_connector(copper, true)
    -- A pole within reach was already joined when the bench pole was built.
    if not ours.is_connected_to(theirs) and not ours.connect_to(theirs, false)
    then
        report.errors[#report.errors + 1] = "could not wire the bench pole"
    end
end

local function bind_ports(x1, y1)
    local surface = storage.surface
    local report = storage.report
    storage.ports = {}
    for _, port in pairs(payload.ports) do
        local x, y = x1 + port.x, y1 + port.y
        local item = {
            name = port.name,
            kind = port.kind,
            items = port.items,
            rate = port.rate,
            blocked = port.blocked,
        }
        if port.kind == "belt-in" or port.kind == "belt-out" then
            item.entity = tile_entity(
                surface,
                x,
                y,
                { "transport-belt", "underground-belt", "splitter" }
            )
        else
            item.entity =
                tile_entity(surface, x, y, { "pipe", "pipe-to-ground" })
        end
        if not item.entity then
            report.errors[#report.errors + 1] = "port has no entity: "
                .. port.name
        else
            item.credit = 0
            storage.ports[#storage.ports + 1] = item
        end
    end
end

local function feed_belt(port)
    for lane = 1, 2 do
        local item = port.items[lane] or port.items[1]
        local line = port.entity.get_transport_line(lane)
        -- An empty name keeps that lane free.
        if item ~= "" and line.can_insert_at_back() then
            if port.rate then
                port.credit = port.credit + port.rate / 60 / 2
                if port.credit >= 1 then
                    port.credit = port.credit - 1
                    line.insert_at_back({ name = item, count = 1 })
                end
            else
                line.insert_at_back({ name = item, count = 1 })
            end
        end
    end
end

-- Takes what reached the port's last tile, counting it. Only that tile's items
-- go, so a belt limits the rate the way it would in a real base.
local function drain_belt(port)
    local drained = storage.report.drained
    for lane = 1, 2 do
        local line = port.entity.get_transport_line(lane)
        for _, stack in pairs(line.get_contents()) do
            drained[stack.name] = (drained[stack.name] or 0) + stack.count
        end
        line.clear()
    end
end

-- A logistic network the bench owns: a roboport with robots, and a storage
-- chest kept stocked with the module's `supply` items.
local function create_supply(x1, y1)
    if not payload.supply then
        return
    end
    local surface = storage.surface
    local force = game.forces.player
    local port = surface.create_entity({
        name = "roboport",
        position = { x1 - 12, y1 - 8 },
        force = force,
    })
    port.insert({ name = "logistic-robot", count = 50 })
    storage.supply_chest = surface.create_entity({
        name = "storage-chest",
        position = { x1 - 9.5, y1 - 9.5 },
        force = force,
    })
end

local function top_up()
    local chest = storage.supply_chest
    if not chest or not chest.valid then
        return
    end
    for name, want in pairs(payload.supply) do
        local have = chest.get_item_count(name)
        if have < want then
            chest.insert({ name = name, count = want - have })
        end
    end
end

-- The first launch wins a freeplay game, and a finished game stops the
-- benchmark. Keep it going.
script.on_event(defines.events.on_rocket_launched, function()
    storage.report.launches = (storage.report.launches or 0) + 1
    game.reset_game_state()
end)

local function drive_ports()
    for _, port in pairs(storage.ports) do
        if port.entity.valid then
            if port.kind == "belt-in" then
                feed_belt(port)
            elseif port.kind == "belt-out" then
                drain_belt(port)
            elseif port.kind == "fluid-in" then
                port.entity.set_fluid(
                    1,
                    { name = port.items[1], amount = 100, temperature = 15 }
                )
            elseif port.kind == "fluid-out" and not port.blocked then
                local fluid = port.entity.get_fluid(1)
                if fluid and fluid.amount > 0 then
                    local taken = port.entity.remove_fluid(1, fluid.amount)
                    local drained = storage.report.fluids
                    local amount = type(taken) == "table" and taken.amount
                        or fluid.amount
                    drained[fluid.name] = (drained[fluid.name] or 0) + amount
                end
            end
        end
    end
end

local function copy(source)
    local out = {}
    for name, count in pairs(source) do
        out[name] = count
    end
    return out
end

local function sample()
    local surface = storage.surface
    local stats = game.forces.player.get_item_production_statistics(surface)
    local machines = {}
    local stock = {}
    local tanks = {}
    local parts = 0
    local plants = {}
    local generated = 0
    for _, e in pairs(surface.find_entities_filtered({ force = "player" })) do
        local chest = e.type == "container" or e.type == "logistic-container"
        if chest and e ~= storage.supply_chest then
            local inventory = e.get_inventory(defines.inventory.chest)
            for _, item in pairs(inventory.get_contents()) do
                stock[item.name] = (stock[item.name] or 0) + item.count
            end
        elseif e.type == "storage-tank" then
            local fluid = e.get_fluid(1)
            tanks[#tanks + 1] = fluid and fluid.amount or 0
        elseif e.name == "chemical-plant" then
            local fluid = e.get_fluid(1)
            plants[#plants + 1] = {
                x = e.position.x,
                r = e.get_recipe() and e.get_recipe().name,
                a = fluid and fluid.amount or 0,
                n = fluid and fluid.name or "",
            }
        elseif e.type == "rocket-silo" then
            parts = math.max(parts, e.rocket_parts)
            if e.status == defines.entity_status.waiting_to_launch_rocket then
                parts = math.max(parts, 100)
            end
        elseif e.type == "generator" then
            generated = generated + e.energy_generated_last_tick * 60
        end
        local ok, status = pcall(function()
            return e.status
        end)
        if ok and status and e.type ~= "transport-belt" then
            local by = machines[e.name] or {}
            local name = status_names[status] or tostring(status)
            by[name] = (by[name] or 0) + 1
            machines[e.name] = by
        end
    end
    -- One log line per sample: a single line holding every sample grew too
    -- long for the log once samples carried debug data.
    local entry = {
        tick = game.tick,
        produced = copy(storage.report.drained),
        made = copy(stats.input_counts),
        stock = stock,
        fluids = copy(storage.report.fluids),
        tanks = tanks,
        -- Logistic, silo and inserter states, for FXA_BENCH_DEBUG runs.
        net = (function()
            if not (payload.supply and payload.debug) then
                return nil
            end
            local out = {}
            for _, e in
                pairs(storage.surface.find_entities_filtered({
                    type = {
                        "logistic-container",
                        "roboport",
                        "assembling-machine",
                        "rocket-silo",
                        "inserter",
                        "cargo-landing-pad",
                    },
                }))
            do
                local inv = e.get_inventory(defines.inventory.chest)
                    or (e.type == "rocket-silo" and e.get_inventory(
                        defines.inventory.rocket_silo_rocket
                    ))
                    or (e.type == "cargo-landing-pad" and e.get_inventory(
                        defines.inventory.cargo_landing_pad_main
                    ))
                    or e.get_inventory(defines.inventory.crafter_output)
                local held = e.type == "inserter"
                    and e.held_stack.valid_for_read
                    and e.held_stack.name
                local net = e.logistic_network
                out[#out + 1] = {
                    n = e.name,
                    x = e.position.x,
                    y = e.position.y,
                    items = inv and inv.get_contents() or {},
                    robots = net and net.all_logistic_robots or -1,
                    avail = net and net.available_logistic_robots or -1,
                    cells = net and #net.cells or -1,
                    held = held or nil,
                    status = e.status,
                    silo = e.type == "rocket-silo" and e.rocket_silo_status
                        or nil,
                    drop = e.type == "inserter" and e.drop_target
                        and e.drop_target.name or nil,
                }
            end
            return out
        end)(),
        parts = parts,
        plants = plants,
        research = research_units(),
        generated = generated,
        machines = machines,
    }
    log("BENCH-SAMPLE " .. helpers.table_to_json(entry))
end

script.on_init(function()
    storage.report = {
        errors = {},
        samples = {},
        drained = {},
        fluids = {},
        ports = #payload.ports,
    }
    setup()
end)

script.on_event(defines.events.on_tick, function(event)
    local start = 120
    if event.tick == 5 then
        game.forces.player.chart(storage.surface, {
            { -256, -256 },
            { 256, 256 },
        })
    elseif event.tick == start then
        build()
    elseif storage.report.book_pages then
        if event.tick == start + 1 then
            log("BENCH-REPORT " .. helpers.table_to_json(storage.report))
        end
    elseif event.tick == start + 1 then
        local x1, y1 = bounds()
        storage.report.origin = { x = x1, y = y1 }
        connect_power(x1, y1)
        bind_ports(x1, y1)
        create_supply(x1, y1)
    elseif event.tick > start + 1 then
        drive_ports()
        if game.finished or game.finished_but_continuing then
            game.reset_game_state()
        end
        if payload.supply and event.tick % 60 == 0 then
            top_up()
        end
        if payload.switch_at and event.tick == payload.switch_at * 3600 then
            for _, e in
                pairs(storage.surface.find_entities_filtered({
                    name = "oil-refinery",
                }))
            do
                e.set_recipe("advanced-oil-processing")
            end
        end
        if event.tick % payload.sample_every == 0 then
            sample()
            -- Benchmark mode writes no script-output, so the report goes in the
            -- log; the last BENCH-REPORT line is current.
            log("BENCH-REPORT " .. helpers.table_to_json(storage.report))
        end
    end
end)
