-- Helpers shared by the agent interface.

local common = {}

-- Chunks around the character that count as seen (5x5), and around a radar (7x7).
common.VIEW_CHUNKS = 2
common.RADAR_CHUNKS = 3

-- Bump when a field is added, so saves made by older scripts pick it up.
local STATE_VERSION = 4

local function state_defaults()
  return {
    mode = "solo",      -- solo: the agent runs the clock, joiners spectate; coop: real time, joiners play
    name = "Agent",     -- shown over the character and in chat
    color = {r = 0.45, g = 0.75, b = 1},
    chat = {},          -- recent chat lines, see social.lua
    chat_seq = 0,
    chat_reported = 0,  -- last chat line included in a report
    chat_interrupt = "mention", -- which chat lines stop a run: any | mention | none
    given_start = {},   -- players who got freeplay's starting items from social.give_character
    queue = {},         -- orders waiting to run
    results = {},       -- outcomes of orders finished since the last report
    events = {},        -- things that happened since the last report
    paths = {},         -- pathfinder answers, by request id
    pending_paths = {}, -- request ids we are waiting on
    seen = {},          -- chunks revealed so far
    trigger_counts = {}, -- progress of craft-item research triggers
    deaths = 0,
    run_speed = 64,
    saved_tick = 0,
    save_slot = 0,
  }
end

function common.state()
  local st = storage.agent
  if not st and storage.claude then
    -- Saves from the first run (scripts in claude/, state in storage.claude).
    st = storage.claude
    storage.agent, storage.claude = st, nil
  end
  if not st then
    st = {}
    storage.agent = st
  end
  if st.version ~= STATE_VERSION then
    for key, value in pairs(state_defaults()) do
      if st[key] == nil then st[key] = value end
    end
    st.version = STATE_VERSION
  end
  return st
end

function common.surface()
  return game.surfaces.nauvis
end

function common.force()
  return game.forces.player
end

function common.character()
  local ch = common.state().character
  if ch and ch.valid then return ch end
end

function common.need_character()
  return common.character() or error("no character (not started, or dead and waiting to respawn)", 0)
end

function common.event(kind, data)
  local st = common.state()
  local entry = data or {}
  entry.type = kind
  entry.tick = game.tick
  st.events[#st.events + 1] = entry
  if #st.events > 200 then table.remove(st.events, 1) end
end

function common.round(v)
  return math.floor(v * 100 + 0.5) / 100
end

function common.dist(a, b)
  local dx, dy = a.x - b.x, a.y - b.y
  return math.sqrt(dx * dx + dy * dy)
end

local DIR = {n = 0, ne = 2, e = 4, se = 6, s = 8, sw = 10, w = 12, nw = 14, north = 0, east = 4, south = 8, west = 12}
local DIR_NAME = {[0] = "n", [2] = "ne", [4] = "e", [6] = "se", [8] = "s", [10] = "sw", [12] = "w", [14] = "nw"}

function common.dir(value)
  if value == nil then return nil end
  if type(value) == "number" then return value end
  return DIR[string.lower(value)] or error("unknown direction " .. tostring(value), 0)
end

function common.dir_name(direction)
  return DIR_NAME[direction] or tostring(direction)
end

function common.contents(inventory)
  local out = {}
  for _, stack in pairs(inventory.get_contents()) do
    out[stack.name] = (out[stack.name] or 0) + stack.count
  end
  return out
end

-- Observation is limited to chunks the character or a radar has revealed.
-- The game's own chart cannot be used for this: a headless server does not
-- update it while no player is connected.
local function chunk_key(cx, cy)
  return (cx + 32768) * 65536 + (cy + 32768)
end

function common.mark_seen(cx, cy, radius)
  local seen = common.state().seen
  for x = cx - radius, cx + radius do
    for y = cy - radius, cy + radius do
      seen[chunk_key(x, y)] = true
    end
  end
end

-- In co-op the force's map is shared with players who chart it as they move, so what
-- they have revealed counts too.
function common.chunk_seen(cx, cy)
  local st = common.state()
  if st.seen[chunk_key(cx, cy)] then return true end
  return st.mode == "coop" and common.force().is_chunk_charted(common.surface(), {cx, cy})
end

function common.charted(position)
  return common.chunk_seen(math.floor(position.x / 32), math.floor(position.y / 32))
end

-- Moving things are only known where the character can currently see.
function common.in_view(position)
  local st = common.state()
  if not st.chunk_x then return false end
  return math.abs(math.floor(position.x / 32) - st.chunk_x) <= common.VIEW_CHUNKS
     and math.abs(math.floor(position.y / 32) - st.chunk_y) <= common.VIEW_CHUNKS
end

local SCENERY = {["tree"] = true, ["simple-entity"] = true, ["cliff"] = true, ["character-corpse"] = true}

-- The entity occupying the tile-sized box around (x, y). Buildings win over
-- scenery, scenery over ore, ore over loose items.
function common.entity_at(surface, x, y, name)
  local found = surface.find_entities_filtered{area = {{x - 0.49, y - 0.49}, {x + 0.49, y + 0.49}}, name = name}
  local best, best_rank, best_dist
  for _, e in pairs(found) do
    local rank
    if e.type == "character" then rank = nil
    elseif e.unit_number then rank = 1
    elseif SCENERY[e.type] then rank = 2
    elseif e.type == "resource" then rank = 3
    elseif e.type == "item-entity" then rank = 4
    end
    if rank then
      local d = common.dist(e.position, {x = x, y = y})
      if not best or rank < best_rank or (rank == best_rank and d < best_dist) then
        best, best_rank, best_dist = e, rank, d
      end
    end
  end
  return best
end

return common
