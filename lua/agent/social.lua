-- Multiplayer: the chat log, messages from the agent, the other players, the name tag.
--
-- The agent's character is not a player, so it cannot use /whisper or be whispered to.
-- Players talk to it in plain chat (mentioning its name makes the message stand out and,
-- by default, interrupts the run in progress); it answers with a chat line to everyone
-- or to one player.

local util = require("util")
local common = require("agent.common")

local social = {}

local CHAT_KEEP = 300

local function add_line(st, entry)
  st.chat_seq = st.chat_seq + 1
  entry.id = st.chat_seq
  entry.tick = game.tick
  st.chat[#st.chat + 1] = entry
  if #st.chat > CHAT_KEEP then table.remove(st.chat, 1) end
  return entry
end

function social.mentions(st, text)
  local name = string.lower(st.name or "")
  if name == "" then return false end
  return string.find(string.lower(text), name, 1, true) ~= nil
end

function social.on_chat(event)
  local st = storage.agent
  if not (st and st.started) then return end
  local player = event.player_index and game.get_player(event.player_index)
  local entry = add_line(st, {from = player and player.name or "<server>", text = event.message})
  if social.mentions(st, event.message) then entry.mention = true end
  -- Pending until a run sees it (main.lua) or the agent reads the chat: a line that arrives
  -- while a solo game is paused stops the next run at once.
  if st.chat_interrupt == "any" or (st.chat_interrupt == "mention" and entry.mention) then
    st.chat_pending = true
  end
end

-- A line printed by script on someone's behalf (the client link's `say`), so it is logged too.
function social.record(from, text)
  local st = storage.agent
  if not st or not st.chat then return end
  add_line(st, {from = from, text = text})
end

-- Joins, departures and deaths go into the same log, from "*".
function social.notice(text)
  local st = storage.agent
  if not (st and st.started) then return end
  add_line(st, {from = "*", text = text})
end

local function rgb(color)
  local c = color or {}
  return string.format("%d,%d,%d", math.floor((c.r or 1) * 255), math.floor((c.g or 1) * 255), math.floor((c.b or 1) * 255))
end

function social.say(st, text, to)
  if type(text) ~= "string" or text == "" then error("say needs some text", 0) end
  if #text > 1000 then error("message too long (1000 characters at most)", 0) end
  local line = string.format("[color=%s]%s[/color]: %s", rgb(st.color), st.name or "Agent", text)
  local settings = {skip = defines.print_skip.never}
  if to then
    local player = game.get_player(to)
    if not (player and player.connected) then error("no connected player named " .. tostring(to), 0) end
    player.print("(to you) " .. line, settings)
  else
    game.print(line, settings)
  end
  return add_line(st, {from = st.name or "Agent", text = text, to = to, self = true})
end

function social.lines(st, since, limit)
  local out = {}
  for _, entry in pairs(st.chat) do
    if entry.id > (since or 0) then out[#out + 1] = entry end
  end
  if limit and #out > limit then
    local cut = {}
    for index = #out - limit + 1, #out do cut[#cut + 1] = out[index] end
    out = cut
  end
  return out
end

-- What any player on the map can see of the others: names, positions, health.
-- Inventories are not visible to other players in the game, so they are not listed.
function social.players()
  local me = common.character()
  local out = {}
  for _, p in pairs(game.players) do
    local d = {name = p.name, connected = p.connected, admin = p.admin}
    if p.connected then
      d.x, d.y = common.round(p.position.x), common.round(p.position.y)
      if me then d.dist = common.round(common.dist(p.position, me.position)) end
      d.afk_ticks = p.afk_time
      if p.controller_type == defines.controllers.spectator then d.spectator = true end
      if p.character and p.character.valid then d.health = math.floor(p.character.health) end
      if p.vehicle then d.vehicle = p.vehicle.name end
    end
    out[#out + 1] = d
  end
  return out
end

-- The name over the character's head, for everyone else on the map.
function social.tag(st)
  if st.tag and st.tag.valid then st.tag.destroy() end
  st.tag = nil
  local ch = common.character()
  if not ch or not st.name or st.name == "" then return end
  st.tag = rendering.draw_text{
    text = st.name, surface = ch.surface, target = {entity = ch, offset = {0, -2.7}},
    color = st.color, scale = 1.3, alignment = "center", scale_with_zoom = false,
  }
end

-- Players who joined while the map was in solo mode became spectators. In co-op they
-- get a character, and the starting items freeplay would have given them, once.
function social.give_character(st, player)
  if not player.connected or (player.character and player.character.valid) then return end
  if player.controller_type == defines.controllers.cutscene then return end
  if player.controller_type ~= defines.controllers.god then
    player.set_controller{type = defines.controllers.god}
  end
  local surface = common.surface()
  local spawn = common.force().get_spawn_position(surface)
  player.teleport(surface.find_non_colliding_position("character", spawn, 32, 0.5) or spawn, surface)
  if not player.create_character() then return end
  if not st.given_start[player.index] then
    st.given_start[player.index] = true
    util.insert_safe(player, storage.created_items or {})
  else
    util.insert_safe(player, storage.respawn_items or {})
  end
end

return social
