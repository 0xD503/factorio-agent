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

## Game versions

- Python never hard-codes game data. Recipes, technologies and prototypes come from the running
  game (`fx recipe`, `fx call exists`).
- The Lua uses the 2.0 API and refuses to load on older versions. `fxa/__init__.py` records the
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

## Known limits and next steps

- Windows and macOS: written for (no signals, UTF-8 everywhere, `.cmd` launcher, Steam/registry
  discovery, process checks via the Win32 API), but not run yet.
- One agent per server. Several agents would need per-agent state in `storage` and a name per
  request.
- Only freeplay saves: the harness replaces the save's control script with freeplay + agent.
- Skills from the first run that depend on map data or a second server (raid repair by diffing
  against a reference save, chores, assault) are not ported yet. The approach is in
  `layers/base/knowledge/combat.md` and the first run's notes.
- No orders yet for tiles (concrete, landfill), circuit wires, trains, vehicles, blueprints or
  repair packs.
- Space Age: multiple surfaces are not handled (the script assumes nauvis).
