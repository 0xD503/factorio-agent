"""Finding the Factorio installation and reading its version.

Two installs are configured, and they may be the same one:
    server  runs the game server (the Linux headless build, or the full game with --start-server)
    client  the game a person plays with (only used to launch it: `fx join`, `fx host`)

They come from, in order: command-line flags, FACTORIO_SERVER / FACTORIO_CLIENT / FACTORIO_PATH,
config.json (`fx setup`), and finally a search of the usual places (Steam libraries, standalone
installs). A path may name the binary, the install directory, or a macOS .app bundle.
"""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from fxa import GAME_MIN, GAME_TESTED, paths

EXE = "factorio.exe" if sys.platform == "win32" else "factorio"


class InstallError(Exception):
    pass


@dataclass
class Install:
    binary: Path
    data: Path
    version: tuple = ()
    flavour: str = ""      # "headless", "full", "expansion"... as the game reports it
    platform: str = ""

    @property
    def root(self):
        return self.data.parent

    @property
    def version_str(self):
        return ".".join(map(str, self.version)) or "?"

    @property
    def headless(self):
        return self.flavour == "headless"

    def builtin_mods(self):
        """Mods shipped in the data directory (base, and the expansion's mods where present)."""
        return sorted(p.parent.name for p in self.data.glob("*/info.json") if p.parent.name != "core")

    def api_doc(self):
        """The Lua API reference shipped with full builds (not with headless ones)."""
        path = self.root / "doc-html" / "runtime-api.json"
        return path if path.exists() else None

    def describe(self):
        return f"Factorio {self.version_str} ({self.flavour or '?'}, {self.platform or '?'}) at {self.binary}"


def _layout(path):
    """(binary, data) for a path naming the binary, an install root, bin/x64, or a .app bundle."""
    path = Path(path).expanduser()
    if path.suffix == ".app" or (path / "Contents" / "MacOS").is_dir():
        return path / "Contents" / "MacOS" / "factorio", path / "Contents" / "data"
    if path.is_file():
        binary = path
        # bin/x64/factorio -> root/data ; factorio.app/Contents/MacOS/factorio -> Contents/data
        if binary.parent.name == "MacOS":
            return binary, binary.parent.parent / "data"
        return binary, binary.parent.parent.parent / "data"
    for candidate in (path / "bin" / "x64" / EXE, path / EXE, path / "x64" / EXE, path / "factorio" / "bin" / "x64" / EXE):
        if candidate.is_file():
            return _layout(candidate)
    raise InstallError(f"no Factorio binary found at {path}")


def probe(path):
    binary, data = _layout(path)
    if not binary.is_file():
        raise InstallError(f"{binary} does not exist")
    if not (data / "base" / "info.json").is_file():
        raise InstallError(f"{binary} found, but no game data at {data}")
    install = Install(binary=binary, data=data)
    try:
        out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=60,
                             stdin=subprocess.DEVNULL, **_no_window()).stdout
    except (OSError, subprocess.TimeoutExpired) as err:
        raise InstallError(f"could not run {binary} --version: {err}") from err
    match = re.search(r"Version:\s*(\d+)\.(\d+)\.(\d+)\s*\(build\s*\d+,\s*([^,]+),\s*([^)]+)\)", out)
    if not match:
        raise InstallError(f"unexpected output from {binary} --version: {out[:300]!r}")
    install.version = tuple(int(match.group(i)) for i in (1, 2, 3))
    install.platform, install.flavour = match.group(4).strip(), match.group(5).strip()
    return install


def _no_window():
    """Keep Windows from opening a console window for the game process."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}   # CREATE_NO_WINDOW
    return {}


def _steam_roots():
    home = Path.home()
    if sys.platform == "win32":
        roots = []
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
        return roots
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Steam"]
    return [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            home / "snap" / "steam" / "common" / ".local" / "share" / "Steam"]


def _steam_libraries():
    libraries = []
    for root in _steam_roots():
        if not root.is_dir():
            continue
        libraries.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(match.group(1).replace("\\\\", "\\")))
    return libraries


def candidates():
    """Places a Factorio install is commonly found, most likely first."""
    home = Path.home()
    found = []
    for library in _steam_libraries():
        game = library / "steamapps" / "common" / "Factorio"
        found.append(game / "factorio.app" if sys.platform == "darwin" else game)
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(env):
                found.append(Path(os.environ[env]) / "Factorio")
        found += [Path("C:/GOG Games/Factorio"), home / "Factorio"]
    elif sys.platform == "darwin":
        found += [Path("/Applications/factorio.app"), home / "Applications" / "factorio.app"]
    else:
        found += [home / "factorio", home / "Games" / "factorio", home / "games" / "factorio",
                  Path("/opt/factorio"), Path("/usr/share/factorio"), Path("/usr/share/games/factorio")]
    out, seen = [], set()
    for path in found:
        key = str(path).lower() if sys.platform == "win32" else str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def search():
    """Every install found in the usual places, as Install objects."""
    out = []
    for path in candidates():
        try:
            out.append(probe(path))
        except InstallError:
            continue
    return out


def configured(role, override=None):
    """The install for `role` ('server' or 'client')."""
    env = {"server": "FACTORIO_SERVER", "client": "FACTORIO_CLIENT"}[role]
    cfg = paths.config().get("game", {})
    for source, value in (("--game", override), (env, os.environ.get(env)), ("FACTORIO_PATH", os.environ.get("FACTORIO_PATH")),
                          ("config.json", cfg.get(role)), ("config.json", cfg.get("path"))):
        if value:
            try:
                return probe(value)
            except InstallError as err:
                raise InstallError(f"{source} names {value}: {err}") from None
    found = search()
    if role == "client":
        found = [i for i in found if not i.headless] or found
    if not found:
        raise InstallError("Factorio was not found. Run `fx setup --game PATH` with the folder Factorio is installed in "
                           "(the one containing bin/ and data/), or set FACTORIO_PATH.")
    return found[0]


def version_notes(install):
    """Warnings about the game version, for `fx doctor` and server start."""
    notes = []
    if install.version < GAME_MIN:
        notes.append(f"Factorio {install.version_str} is too old: the in-game script needs {'.'.join(map(str, GAME_MIN))} or newer")
    elif install.version > GAME_TESTED:
        notes.append(f"Factorio {install.version_str} is newer than the last tested version "
                     f"{'.'.join(map(str, GAME_TESTED))}; run `fx selftest` once to check the interface still works")
    return notes


def user_mods_dir(install=None):
    """The mods folder the user's own game uses, to copy mods from."""
    if install is not None:
        portable = install.root / "mods"
        if (portable / "mod-list.json").exists():
            return portable
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Factorio" / "mods"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "factorio" / "mods"
    return Path.home() / ".factorio" / "mods"
