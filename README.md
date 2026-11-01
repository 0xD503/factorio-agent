# factorio-agent

Let an AI agent play Factorio: on its own while you watch, or with you and your friends in
multiplayer. The agent controls a real character through a text interface and plays by the
game's rules, with no cheats. It talks to players in the game chat, and it writes down what it
learns so that the next game goes better.

The first agent to use it (Claude) went from an empty default map to a rocket launch in
33 hours of game time.

- **For players**: [docs/USER_GUIDE.md](docs/USER_GUIDE.md) covers requirements, install, solo and co-op.
- **For AI agents**: [AGENTS.md](AGENTS.md) is the manual. Claude Code also reads `CLAUDE.md`.
- **For developers**: [docs/DESIGN.md](docs/DESIGN.md) covers architecture, safety model and design decisions.

```
git clone <repository URL> factorio-agent && cd factorio-agent
./fx doctor && ./fx setup          # Windows: fx.cmd doctor, fx.cmd setup
```

Then open your agent in this folder and say "let's play Factorio".

Needs Factorio 2.0 and Python 3.10+ (standard library only). Linux is tested. Windows and
macOS are supported in the code but untested. Status: v0.1 developer build.
