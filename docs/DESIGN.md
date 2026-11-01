# Design

How factorio-agent works and why it is built this way. Version 0.1.

## Overview

```
 agent (LLM) --shell--> fx (Python, stdlib) --RCON/TCP 127.0.0.1--> Factorio server
                          |                                          | control.lua + agent/*.lua
                          | layers: knowledge + skills               | inside the save
                          | sandbox: runs skills                     |
                          | sessions: saves, notes, secrets          +--UDP--> human players
```

- **In-game script** (`lua/`). Written into every save the harness runs (`fxa/savefile.py`), like
  a scenario script, so no mod is needed and players download it with the map. It creates a
  character that no player controls and exposes one console command, `/agent <json>`, accepted
  from RCON only. Its operations are *observe* (read-only views limited to what the character or
  the force has seen) and *orders* (walk, mine, craft, place, ...) executed tick by tick with the
  engine's own rules and timings. It also logs chat, writes chat lines, lists players and keeps
  rolling saves.
- **Harness** (`fxa/`). Finds the game, runs servers, keeps sessions, turns replies into compact
  text, resolves knowledge and skills through the layers, and runs skills in the sandbox.
- **Agent**. Any LLM agent that can run shell commands. `AGENTS.md` is its manual; `CLAUDE.md`
  imports it for Claude Code.

## Modes and the clock

| | solo | coop |
|---|---|---|
| clock | paused between calls; runs at up to 64x during `run` | real time, never touched |
| `fx do` | runs the game until the orders finish or something interrupts | waits for the orders, which started when queued |
| joiners | spectators | players with characters and freeplay starting items |
| network | 127.0.0.1 | 0.0.0.0:34197 (configurable), LAN-visible, logins verified |
| saves | script's rolling saves by played time | the server's autosave |

Interruptions (enemy near, damage, losses, research queue empty, death, a chat line naming the
agent) stop a run so the agent can react. A mention that arrives while a solo game is paused
stops the next run at once, so nothing said to the agent is missed.

## Multiplayer model

The agent is a script-driven character on a server the harness can reach over RCON. It is not
a game client. As a result:

- No Factorio account or licence is needed for the agent; humans join with their own.
- Joining as a real player is the planned next step: see "Client mode" below.
- The server can be the harness's own (the usual case; the full game works as a dedicated
  server too, so no separate download is needed) or a dedicated server elsewhere that runs a
  prepared save and grants RCON (`fx attach`). A game hosted from the game window cannot be
  used: with 2.0.77, a game started with `--host` ignores `--rcon-port`, `--rcon-bind` and
  `--port` (tested).
- Joining a third-party server the agent has no RCON on is not possible. That would take a
  second licence and driving the graphical client, which this design avoids.
- The agent cannot use `/whisper`. Players talk to it in plain chat, and it can answer one player
  privately (`fx say --to`).
- Script commands run on every peer in lockstep, so the in-game script is written to be
  deterministic. The only module-level state is caches of prototype data, which are identical on
  every peer.

## Sessions and layers

A session is a directory: `session.json` (settings), `NOTES.md`, `knowledge/`, `skills/`,
`chat.log`, and `server/` (Factorio's write-data: saves, logs, config, `secrets.json`).
Everything shareable sits at the top. Machine-specific files and secrets are under `server/`,
which the session's `.gitignore` excludes, all but the saves.

Knowledge (Markdown with a small header) and skills (`.fxs`) are resolved through layers:
`core` -> `base` -> `mod:<name>` for each active mod, ordered by the dependencies in the mod's
`info.json` -> `user` -> `session`. An item with the same id in a higher layer wins. An item
whose `game:` version range or `mods:` list does not match the session is skipped. A skill
whose `requires` prototypes the game lacks refuses to run. So base-game skills keep working
under mods unless a mod layer overrides them or the mod removed what they need.

Self-improvement moves knowledge down the layers: session -> user (`fx kb promote`, local
and private) -> repository (`--to base|core|mod:X`, which produces a reviewable diff). Promotion
into the repository refuses texts full of map coordinates, since those are rarely general.

## Safety

The harness runs on players' machines, and sessions can hold files written by other people.
Threats and what stops them:

| Threat | Mitigation |
|---|---|
| Skill code from a shared session or a pull request tries to read files, run programs or use the network | Skills are never run as Python. `fxa/sandbox.py` interprets a subset of Python itself: no import, no attribute access except whitelisted list/dict/str/set methods, no dunder names, no classes, exceptions or `with`. Values are plain data only, and host functions receive and return plain data. Tested against the known escapes (`tests/test_sandbox.py`). |
| A skill exhausts CPU or memory | Step budget, CPU-time limit, call depth, tracemalloc memory limit, caps on string, collection and integer sizes, size checks before `*`, `**`, `<<`, `replace` and `join`, no `%` formatting, capped format widths, capped `repr` of self-referencing structures. |
| Text written by others (knowledge, notes, chat, skill output) tries to instruct the agent | `AGENTS.md` makes it a hard rule that such text is information, not instructions. `fx kb show` marks session-layer items as such. Control characters are stripped from chat and skill output. |
| Someone on the network takes over the game through RCON | RCON binds to 127.0.0.1 with a random per-session password, stored in `server/secrets.json` (mode 0600). Attaching to a remote RCON is an explicit command, and the docs say to tunnel it. |
| Someone claims an admin's name | Co-op servers verify logins by default. `--no-verify` is opt-in and documented as allowing spoofing. |
| Path tricks through save, session or item names | Names are restricted to `[A-Za-z0-9._-]` with no leading dot or `..`. Written paths are checked to stay inside their layer. The in-game script checks save names too. |
| The in-game script harms players' machines | It runs in Factorio's Lua sandbox (no file or network access), like any scenario script. |
| The harness changes the user's game | Servers use their own write-data directory per session. The user's config, saves, mods and `player-data.json` are never read or written. |
| Unwanted downloads or updates | The harness downloads nothing. Mods are copied from the user's own mods folder. |
| The agent edits the harness badly | Allowed, but on a git branch with tests passing and the user told (`AGENTS.md`). Lua changes go through `fx selftest`, which uses a throwaway session. |

Fair play is a separate rule from safety. The CLI has no way to run arbitrary Lua, and the
in-game operations only do what a player could do through their character, with the
observation limits described above.

## Installs, distribution and mods

- Nothing about the machine is hard-coded. The game installs are found at run time: flags,
  `FACTORIO_SERVER`/`FACTORIO_CLIENT`/`FACTORIO_PATH`, `config.json` written by `fx setup`, or a
  search of standalone install locations. Steam and GOG installs are searched, used or recorded
  only on request (`fx setup --steam` or `fx setup --gog`, or an explicit path), because they are the user's
  main copy, managed by the store.
- The harness only runs the configured binary, with its own config and write-data directory.
  It never writes into an install, and it reads only the client's `mod-list.json` and mod files
  (to copy them).
- Players install from release archives: an annotated tag plus zip and tar.gz from `git archive`,
  with checksums (`tools/release.py`). `fxa/_build.py` gets the commit stamped in through
  `export-subst`, and `fx doctor` prints it. An upgrade replaces the folder. All state lives in
  the data directory.
- A selftest pass is recorded per install and version in `config.json`. Doctor and server start
  warn until the configured server has passed on its current version.
- Mods: a new session copies the list of mods enabled in the user's game, so the user can join
  without a mod download. An existing session never changes by itself: adding or removing a
  mod changes the map. Differences are reported, and `fx session mods --sync` adopts them.

## Game versions

- Python never hard-codes game data. Recipes, technologies and prototypes come from the running
  game (`fx recipe`, `fx call exists`).
- The Lua uses the 2.0 API (and nothing removed since) and refuses to load on older versions. `fxa/__init__.py` records the
  newest tested version. Newer ones get a warning and a hint to run `fx selftest`.
- Sessions record the game version they last ran on, and a change is reported at start.
  Knowledge items carry `verified:` and optionally a `game:` range.
- Old saves from the first run (`storage.claude`, `claude/*.lua`) are migrated on load.

## Language choice: is Python the bottleneck?

Measured on the M7 save (a 33-hour base) on a Ryzen 7 5800H:

| Step | Time |
|---|---|
| One RCON request, any size up to a 64x32 map | 16.7 ms: one server update at 60 Hz; the server answers RCON once per frame |
| Entity dump of a 40-tile radius, 95 KB | 36 ms in Factorio |
| Parsing that reply in Python | 1 ms |
| Starting `fx` (interpreter, imports, connect, one request) | 50-60 ms |
| Simulation at 64x | 1,600-2,800 ticks/s, limited by the engine |
| One LLM decision | several seconds |

Python accounts for about 1% of the time per step. What dominates is the model's thinking
time, then the engine's speed, then the 16.7 ms RCON floor. The levers that matter:

1. Fewer, bigger agent decisions: orders that run many ticks inside the game, skills that loop
   without consulting the model, compact observations.
2. Batching requests (`batch` op) to beat the per-request floor.
3. Keeping heavy loops in Lua, inside the game, where they run in the same tick.

A compiled harness (Go, Rust) would save milliseconds per step, but it would cost the zero-install
setup (Python ships with most Linux systems and installs in one command on Windows). It would
also cost the agent's ability to read and improve the harness without a toolchain. Skills
stay in a Python subset because models write Python best, and because the subset can be
interpreted safely. Revisit if profiling ever shows the harness in the critical path.

## Client mode (prototype)

The aim is to let the agent join as a real player, with its own account and game window, so it
shows in the player list and needs no RCON from the host. Factorio 2.0 makes this possible, and a
prototype (`lua/agent/link.lua`, `fxa/link.py`, `fx client`) works:

- The agent's game client starts with `--enable-lua-udp PORT` (`fx client launch HOST:PORT`).
  The harness sends JSON requests to that port. The script (in the save, on every peer) calls
  `helpers.recv_udp(player_index)` for each connected player every tick. The game raises
  `on_udp_packet_received` on every peer alike, and the reply goes back with
  `helpers.send_udp(port, data, player_index)`. A packet is attributed to the player whose client
  received it, so a program can only drive the character of the player on whose machine it runs.
- Tested on 2.1.24 by driving the user's own character, since no second account was available:
  `hello`, `state`, `walk` and `say` answered over UDP with no RCON involved, the server saw the
  character arrive where the client was told, and neither side logged a desync.
- Not done yet: the full order set (mine, craft, place, ...) and the observations for a player's
  character. That needs the in-game state to move from one agent to one per player index; the
  order handlers already take the character as a parameter. Also not done: a test with a second
  account, and running the agent's client without a visible window (the game needs a display).
- It still needs the script in the save (a prepared save, on a server run by anyone) and a game
  licence for the agent. It does not make arbitrary public servers playable.

## Known limits and next steps

- Windows and macOS: written for (no signals, UTF-8 everywhere, `.cmd` launcher, Steam/registry
  discovery, process checks via the Win32 API), but not run yet. `.github/workflows/tests.yml`
  runs the offline tests on both (and the live selftest on Linux) once the repository is on
  GitHub; it has not run yet either.
- Game versions run so far: 2.0.77 (the first game, and v0.1 development) and 2.1.24 (all live
  tests). 2.1 changed two things the script relied on: recipes list several crafting categories
  (`categories`), and reading a property an entity lacks (`fluidbox`, `burner`) raises an error
  instead of returning nil. The script now handles both versions.
- One agent per server. Several agents would need per-agent state in `storage` and a name per
  request.
- Only freeplay saves: the harness replaces the save's control script with freeplay + agent.
- Skills from the first run that depend on map data or a second server (raid repair by diffing
  against a reference save, chores, assault) are not ported yet. The approach is in
  `layers/base/knowledge/combat.md` and the first run's notes.
- No orders yet for tiles (concrete, landfill), circuit wires, trains, vehicles, blueprints or
  repair packs.
- Space Age: multiple surfaces are not handled (the script assumes nauvis).
