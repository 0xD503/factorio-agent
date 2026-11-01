# User guide

factorio-agent lets an AI agent (Claude Code or any agent that reads `AGENTS.md`) play
Factorio: alone while you watch, or together with you and your friends in multiplayer.

Version 0.1, a developer build: expect rough edges and breaking changes.

## What you need

| | |
|---|---|
| **Factorio 2.0** | The full game (Steam, GOG or factorio.com) to play or watch. Space Age is optional. On Linux you can also run the server with the free [headless server](https://www.factorio.com/download) build. |
| **Python 3.10 or newer** | Standard library only, nothing to `pip install`. Linux: usually installed already (`python3 --version`). Windows: `winget install Python.Python.3.12` or the installer from python.org (tick "Add to PATH"). macOS: python.org or Homebrew. |
| **An AI agent that can run commands** | [Claude Code](https://claude.com/claude-code) reads `CLAUDE.md` automatically. Other agents (Codex CLI, Gemini CLI, Cursor...) read `AGENTS.md`. |
| **Git** | To get the repository. |
| **OS** | Linux x86-64: tested (Pop!_OS 24.04). Windows 10/11: written for, not tested yet. macOS: untested. |
| **Network (co-op only)** | Friends on your LAN: nothing. Over the internet: forward UDP port 34197 to the host, or use a VPN such as Tailscale or ZeroTier. |

You do **not** need a second Factorio account for the agent: its character lives inside the
game server, so it is not a game client. Only the humans who join need their own copy.

## Install

```
git clone <repository URL> factorio-agent
cd factorio-agent
./fx doctor          # Windows cmd: fx.cmd doctor   PowerShell: .\fx.cmd doctor
./fx setup           # finds Factorio in the usual places and remembers it
```

The rest of this guide writes `./fx`; on Windows use `fx.cmd` (cmd) or `.\fx.cmd` (PowerShell).

If `setup` does not find the game, give the folder that contains `bin/` and `data/`:

```
./fx setup --game "C:\Program Files (x86)\Steam\steamapps\common\Factorio"
./fx setup --game ~/.steam/steam/steamapps/common/Factorio
./fx setup --game ~/factorio --server-game ~/factorio-headless   # separate server build (Linux)
```

`./fx doctor` should now say "all good". Optionally run `./fx selftest` (well under a minute):
it plays a throwaway map and checks that everything works with your version of the game.

## Playing with the agent

Open your agent in the `factorio-agent` folder and tell it what you want, for example:

- "Let's play Factorio together in co-op. My player name is Alice."
- "Play a solo game to a rocket launch and stop at each milestone."
- "Resume our game from yesterday."

The agent reads `AGENTS.md` and does the rest with `fx` commands. You can always run the same
commands yourself.

- **Permissions.** Your agent asks before running commands. Allowing `./fx` commands for the
  folder (in Claude Code, "always allow" on the first `./fx` prompt) keeps a game flowing. Leave the
  prompts on for anything else.
- **The agent only plays while it is running.** It reads the game chat and acts while its turn in
  your terminal is going. When it stops (it finished, hit a usage limit, or you interrupted it),
  your character keeps playing but nobody answers in the game. Type in the agent's window to
  get it going again.
- **Stopping.** Tell the agent "stop and save". It writes a checkpoint, updates the session's
  `NOTES.md` and stops the server. `./fx server stop` also saves the map. **Resuming:** "resume
  our game" (or `./fx session use NAME` then `./fx server start`). The agent reads `NOTES.md` to
  pick up where it left off.

### Watching a solo game

In solo mode the game is paused while the agent thinks and runs fast while it acts. To watch,
run `./fx join` (it opens your Factorio connected to the server; you become a spectator) or in
Factorio use Multiplayer > Connect to address with the address `./fx server status` prints.
You can type in the chat; mention the agent's name and it will see it at its next step.

### Co-op

The agent creates a co-op session like this (you can do it yourself too):

```
./fx session new ourgame --mode coop --agent-name Claude --admin YourPlayerName
```

- **You** join with Multiplayer > Connect to address `127.0.0.1:34197` (or `./fx join`, which
  opens your game already connecting; it only works while the game is closed).
- **Friends on your network** see the game in the LAN list, or connect to your machine's address.
- **Friends over the internet** connect to your public address after you forward UDP 34197 on
  your router, or to your VPN address (Tailscale, ZeroTier). Set a game password first:
  `./fx password SECRET` then `./fx server restart`.
- **Talking to the agent**: type in the game chat. Mention its name ("Claude, can you build
  power?") to get its attention right away. Map pings (`[gps=...]`, Alt+click on the map) are
  understood as coordinates. It answers in chat.
- **Admins**: names given with `--admin` can pause, kick, ban and use console commands. To add
  one later: `./fx session set --admin NAME` then `./fx server restart`.
- **Logins**: by default players must be logged in to Factorio (Steam or factorio.com). This
  protects admin names. For an offline LAN game use `--no-verify`.
- When everyone leaves, the server pauses itself, and the agent waits. `--no-auto-pause` keeps the
  world running.
- Switch an existing game between solo and co-op with `./fx mode coop` followed by
  `./fx server restart`.

The agent's character has its name floating above it. It plays by the same rules as you: it
has to walk, mine, craft and carry everything.

### Hosting somewhere else

The agent needs RCON on the server, and Factorio only offers RCON on dedicated servers
(`--start-server`, which is what `fx server start` runs). A game hosted from the game window
("Host saved game") ignores the RCON options, so the agent cannot join that way.

To play on a dedicated server someone else runs, they host a save prepared with
`./fx prepare-save their.zip prepared.zip`, start the server with
`--rcon-bind ADDRESS:PORT --rcon-password PW`, and give you that address and password. Then
`./fx attach HOST:PORT --password-file pw.txt`. RCON is unencrypted: use it over a VPN or SSH
tunnel, never openly across the internet.

## Sessions

A session is one game: its saves, notes, knowledge and skills. Sessions live in the data
directory (`./fx doctor` prints it: `~/.local/share/factorio-agent` on Linux,
`%LOCALAPPDATA%\factorio-agent` on Windows, `~/Library/Application Support/factorio-agent` on
macOS; set `FXA_HOME` to move it), or anywhere you choose with `--dir`.

```
./fx session list | use NAME | info
./fx server start | stop | restart | status | log
./fx save NAME                       # a checkpoint
```

Inside a session folder:

- `NOTES.md`: the state of play, kept by the agent. Read it to see what is going on.
- `knowledge/`, `skills/`: things that are true for this game only.
- `server/saves/`: the saves. `server/secrets.json` holds passwords: never share it.
- `chat.log`: the game chat.

You can share a session folder with friends (a shared folder, a git repository): the
`.gitignore` inside keeps machine-specific files and secrets out. Friends can add their own
notes to `knowledge/`. The agent treats them as information to check, not as orders.

## Knowledge and skills

What the agent knows comes in layers, from general to specific:

1. `core`: using the harness (in this repository).
2. `base`: the base game (in this repository).
3. one layer per active mod, e.g. `space-age` (in this repository).
4. `user`: your own, shared by all your sessions (in the data directory).
5. `session`: this game only.

A higher layer overrides a lower one. `./fx kb list` shows what applies; `./fx kb show ID`
shows an item. Skills are small sandboxed scripts that play through the same rules
(`./fx skill list`, `./fx skill run NAME key=value`).

The agent writes down what it learns as it plays and promotes lessons that hold for any game to
your user layer. Lessons promoted into the repository show up in `git status`; review them like
any other change before committing.

## Game updates and mods

- When Steam updates Factorio, `./fx doctor` shows the new version, and starting a session notes
  the change. Run `./fx selftest` once; if it passes, carry on. Knowledge items say which version
  they were checked on.
- New sessions use the base game. Add the expansion with `--mods space-age` (it pulls in
  `quality` and `elevated-rails`). Other mods: install and enable them in your game first; the
  harness copies them from your mods folder (`--mods name1,name2`). Everyone joining needs the
  same mods. Factorio offers to download them when you connect.
- The harness's script replaces the save's own scenario script with freeplay plus the agent. Use it
  with freeplay games (the normal "New game"). Other scenarios are not supported yet.

## What it does and does not do to your machine

- It runs Factorio as a separate process with its own data folder inside the session. Your own
  settings, saves, mods and login are never touched.
- RCON (the remote console the agent uses) listens on 127.0.0.1 only, with a random password.
- In co-op it opens UDP port 34197 (or the one you choose) for players. Your OS may ask to allow
  that. Solo games listen on 127.0.0.1 only.
- It downloads nothing and updates nothing by itself.
- Skills, including ones written by other people, run in a restricted interpreter that cannot
  touch files, the network or other programs. They can only issue game orders.
- The in-game script runs in Factorio's own Lua sandbox, on your machine and on the machines of
  everyone who joins, like any scenario script.
- The agent itself runs with the permissions you give it in your agent's settings. Keep your
  agent's permission prompts on if you are unsure.

## Troubleshooting

| Problem | Try |
|---|---|
| `Factorio was not found` | `./fx setup --game PATH` with the folder holding `bin/` and `data/`. |
| `cannot reach the game server` | `./fx server status`, then `./fx server start`; `./fx server log` shows why it stopped. |
| Port 34197 in use | Another server is running. The session picks the next free port; `./fx server status` shows it. |
| Friends cannot connect | Check the firewall and port forward (UDP, not TCP), or use a VPN. Your own client connects with `./fx join`. |
| Game updated, things fail | `./fx selftest`; report failures with the output. |
| Mod not found | Install and enable it in your game first, then `./fx server restart`. |
| Agent stuck in a loop | Tell it to stop; `./fx cancel` drops its queued orders. |

## Removing it

Delete the repository folder and the data directory. Nothing else is installed.
