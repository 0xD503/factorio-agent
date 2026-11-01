"""Where factorio-agent keeps its files on each OS, and small file helpers.

FXA_HOME overrides the data directory. It holds:
    config.json        machine settings (where the game is, defaults)
    sessions/<name>/   one directory per game session (see session.py)
    user/knowledge/    the user's own layer of knowledge and skills, shared by
                       all sessions
    user/skills/
"""

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LUA = REPO / "lua"
LAYERS = REPO / "layers"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def home():
    env = os.environ.get("FXA_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform == "win32":
        return (
            Path(
                os.environ.get("LOCALAPPDATA")
                or Path.home() / "AppData" / "Local"
            )
            / "factorio-agent"
        )
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support" / "factorio-agent"
        )
    return (
        Path(
            os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        )
        / "factorio-agent"
    )


def check_name(name, what="name"):
    """Names that become file names: no separators, no '..', nothing hidden."""
    if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
        raise ValueError(
            f"bad {what} {name!r}: use letters, digits, '.', '_' and '-' (not "
            "starting with '.' or '-')"
        )
    return name


def inside(base, path):
    """`path` resolved, provided it lies within `base`; ValueError otherwise."""
    base, path = Path(base).resolve(), Path(path).resolve()
    if path != base and base not in path.parents:
        raise ValueError(f"{path} is outside {base}")
    return path


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if private:
        private_file(temp)
    os.replace(temp, path)


def private_file(path):
    """Readable by the owner only, where the OS supports it (Windows profiles
    are per-user anyway)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def config():
    return read_json(home() / "config.json", {})


def save_config(data):
    write_json(home() / "config.json", data)
