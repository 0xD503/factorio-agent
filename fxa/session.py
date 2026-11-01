"""Game sessions: one directory per game, holding everything specific to it.

    <session>/
        session.json     settings: mode, mods, seed, agent name, server options
        NOTES.md         the state of play, kept up to date by the agent (start here when resuming)
        knowledge/       knowledge for this game only (map facts, lessons); top layer, see layers.py
        skills/          skills for this game only (sandboxed .fxs scripts)
        chat.log         chat transcript
        server/          the game server's own directory: saves/, logs, config (machine-specific)
            saves/       checkpoints
            secrets.json RCON password and other credentials (never share)

A session lives in <FXA_HOME>/sessions/<name> unless created with --dir, in which case its
path is recorded in <FXA_HOME>/sessions.json. Other players may add files to knowledge/ and
skills/ of a shared session; those are treated as untrusted (see docs/DESIGN.md, "Safety").
"""

import datetime
import os
import secrets as _secrets
from pathlib import Path

from fxa import paths


class SessionError(Exception):
    pass


GITIGNORE = """# Machine-specific server files and credentials. Saves are kept apart so they can be shared.
server/*
!server/saves/
"""

NOTES_TEMPLATE = """# {name}

State of play for this session. Keep it current: it is the first thing read when the game is resumed.

- Mode: {mode}. Mods: {mods}.
- Goal: (what the players want from this game)

## Now

(nothing yet)
"""

DEFAULT_SERVER = {
    "bind": None,             # solo: 127.0.0.1, coop: 0.0.0.0
    "port": None,             # solo: any free port, coop: 34197
    "max_players": 0,
    "lan": True,              # coop: show the game on the local network
    "public": False,          # coop: list on the public server browser (needs a factorio.com login, see the guide)
    "verify_users": True,     # coop: players must be logged in to factorio.com (protects admin names)
    "auto_pause": True,       # coop: pause while nobody is connected
    "admins": [],             # player names that get admin rights
    "description": "",
}


class Session:
    def __init__(self, directory):
        self.dir = Path(directory).resolve()
        meta = paths.read_json(self.dir / "session.json")
        if meta is None:
            raise SessionError(f"{self.dir} is not a session (no session.json)")
        self.meta = meta

    # -- settings
    @property
    def name(self):
        return self.meta.get("name", self.dir.name)

    @property
    def mode(self):
        return self.meta.get("mode", "solo")

    @property
    def mods(self):
        return list(self.meta.get("mods") or ["base"])

    @property
    def agent_name(self):
        return self.meta.get("agent_name", "Agent")

    @property
    def server_settings(self):
        return {**DEFAULT_SERVER, **(self.meta.get("server") or {})}

    def update(self, **fields):
        self.meta.update(fields)
        self.save()

    def save(self):
        paths.write_json(self.dir / "session.json", self.meta)

    # -- places
    @property
    def server_dir(self):
        return self.dir / "server"

    @property
    def saves_dir(self):
        return self.server_dir / "saves"

    @property
    def knowledge_dir(self):
        return self.dir / "knowledge"

    @property
    def skills_dir(self):
        return self.dir / "skills"

    def save_path(self, save):
        return self.saves_dir / f"{paths.check_name(save, 'save name')}.zip"

    # -- secrets, kept out of session.json so the session can be shared
    def secret(self, key, create=False):
        path = self.server_dir / "secrets.json"
        data = paths.read_json(path, {})
        if key not in data and create:
            data[key] = _secrets.token_urlsafe(18)
            paths.write_json(path, data, private=True)
        return data.get(key)

    def set_secret(self, key, value):
        path = self.server_dir / "secrets.json"
        data = paths.read_json(path, {})
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        paths.write_json(path, data, private=True)

    def log_chat(self, lines):
        """Append chat lines to chat.log, each once (several commands report the same lines).

        Lines are recognised by (id, tick, text); ids alone repeat after an older save is loaded."""
        if not lines:
            return
        seen_file = self.server_dir / "chat-seen.json"
        seen = paths.read_json(seen_file, [])
        known = {tuple(x) for x in seen}
        fresh = []
        for line in sorted(lines, key=lambda l: (l.get("tick", 0), l.get("id", 0))):
            key = (line.get("id", 0), line.get("tick", 0), str(line.get("text", ""))[:200])
            if key not in known:
                known.add(key)
                seen.append(list(key))
                fresh.append(line)
        if not fresh:
            return
        paths.write_json(seen_file, seen[-500:])
        with open(self.dir / "chat.log", "a", encoding="utf-8") as out:
            for line in fresh:
                to = f" (to {line['to']})" if line.get("to") else ""
                out.write(f"{line.get('tick', '?')}\t#{line.get('id', '?')}\t{line.get('from', '?')}{to}: {line.get('text', '')}\n")

    def __repr__(self):
        return f"Session({self.name!r}, {self.dir})"


def _registry():
    return paths.read_json(paths.home() / "sessions.json", {})


def _sessions_root():
    return paths.home() / "sessions"


def create(name, directory=None, mode="solo", mods=None, agent_name="Agent", seed=None, server=None):
    paths.check_name(name, "session name")
    if mode not in ("solo", "coop"):
        raise SessionError("mode is solo or coop")
    if name in _registry() or (_sessions_root() / name).exists():
        raise SessionError(f"a session named {name!r} already exists")
    target = Path(directory).expanduser().resolve() if directory else _sessions_root() / name
    if (target / "session.json").exists():
        raise SessionError(f"{target} already holds a session")
    if target.exists() and any(target.iterdir()):
        raise SessionError(f"{target} exists and is not empty")
    for sub in ("knowledge", "skills", "server/saves"):
        (target / sub).mkdir(parents=True, exist_ok=True)
    mods = list(dict.fromkeys(["base"] + list(mods or [])))
    meta = {
        "name": name, "mode": mode, "mods": mods, "agent_name": agent_name, "seed": seed, "save": "game",
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "server": {key: value for key, value in (server or {}).items() if value is not None},
    }
    paths.write_json(target / "session.json", meta)
    (target / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (target / "NOTES.md").write_text(NOTES_TEMPLATE.format(name=name, mode=mode, mods=", ".join(mods)), encoding="utf-8")
    if directory:
        registry = _registry()
        registry[name] = str(target)
        paths.write_json(paths.home() / "sessions.json", registry)
    return Session(target)


def find(spec):
    """A session by name or path."""
    if not spec:
        raise SessionError("no session given")
    as_path = Path(spec).expanduser()
    if (as_path / "session.json").exists():
        return Session(as_path)
    registry = _registry()
    if spec in registry:
        return Session(registry[spec])
    try:
        paths.check_name(spec, "session name")
    except ValueError as err:
        raise SessionError(str(err)) from None
    local = _sessions_root() / spec
    if (local / "session.json").exists():
        return Session(local)
    raise SessionError(f"no session named {spec!r} (see `fx session list`)")


def current(spec=None):
    """The session named by --session, FXA_SESSION, or the one last chosen with `fx session use`."""
    spec = spec or os.environ.get("FXA_SESSION")
    if not spec:
        try:
            spec = (paths.home() / "current").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            spec = None
    if not spec:
        raise SessionError("no session selected: create one with `fx session new NAME` or pick one with `fx session use NAME`")
    return find(spec)


def use(session):
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "current").write_text(session.name if find_quiet(session.name) else str(session.dir), encoding="utf-8")


def find_quiet(spec):
    try:
        return find(spec)
    except SessionError:
        return None


def all_sessions():
    out = {}
    root = _sessions_root()
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if (child / "session.json").exists():
                out[child.name] = child
    for name, path in _registry().items():
        out[name] = Path(path)
    return out
