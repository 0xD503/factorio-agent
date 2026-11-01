# factorio-agent

Let an AI agent play Factorio: on its own while you watch, or with you and your
friends in multiplayer. The agent controls a real character through a text
interface and plays by the game's rules, with no cheats. It talks to players in
the game chat, and it writes down what it learns so that the next game goes
better.

The first agent to use it (Claude) went from an empty default map to a rocket
launch in 33 hours of game time.

- **For players**: [docs/USER_GUIDE.md](docs/USER_GUIDE.md) covers requirements,
  install, solo and co-op.
- **For AI agents**: [AGENTS.md](AGENTS.md) is the manual. Claude Code also
  reads `CLAUDE.md`.
- **For developers**: [docs/DESIGN.md](docs/DESIGN.md) covers architecture,
  safety model and design decisions.

Install: download a release archive, extract it, then from inside the folder run
`./fx doctor`, `./fx setup` and `./fx selftest` (Windows: `fx.cmd ...`). Details
are in the user guide. Then open your agent in that folder and say "let's play
Factorio".

Needs Factorio 2.0 or newer and Python 3.10+ (standard library only). Linux is
tested. Windows and macOS are supported in the code but untested. Status: v0.1
developer build.

Developing the harness itself: clone the repository and open it in the dev
container (`.devcontainer/`; the host needs only a container engine, a POSIX
shell and git), then read the "Changing the harness" part of
[AGENTS.md](AGENTS.md). Releases are made with `tools/release.py`.

## License

Apache License 2.0, see [LICENSE](LICENSE). Factorio is a game by Wube Software;
this project is not affiliated with Wube and ships no part of the game.
