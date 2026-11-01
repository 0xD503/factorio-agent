"""Running a session's game server, the same way on Linux, Windows and macOS.

Everything the server writes goes into <session>/server/ (passed as its write-data directory),
so the user's own game settings, saves and mods are never touched. RCON listens on 127.0.0.1
only, with a random password kept in <session>/server/secrets.json.

The server is stopped with the RCON command /quit, which saves the map over the file it was
started from and exits; no signals are needed, so this works on every OS.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from fxa import install as _install
from fxa import paths, savefile
from fxa.rcon import RconClient, RconError


class ServerError(Exception):
    pass


SOLO_SETTINGS = {
    "visibility": {"public": False, "lan": False},
    "require_user_verification": False,
    # The agent runs the clock itself, with or without spectators.
    "auto_pause": False,
    "auto_pause_when_players_connect": False,
    # The script keeps rolling saves by played time; the server's own autosave would count
    # paused time too and fire every few seconds at 64x.
    "autosave_interval": 100000,
    "autosave_slots": 1,
}

COMMON_SETTINGS = {
    "tags": ["factorio-agent"],
    "username": "", "password": "", "token": "",
    "allow_commands": "admins-only",
    "afk_autokick_interval": 0,
    "only_admins_can_pause_the_game": True,
    "autosave_only_on_server": True,
    "non_blocking_saving": False,
    "max_upload_in_kilobytes_per_second": 0,
    "minimum_latency_in_ticks": 0,
    "ignore_player_limit_for_returning_players": False,
}


def free_port(kind, host, start=None, tries=50):
    """A port nobody listens on; from `start` upwards, or any if start is None."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock_type = socket.SOCK_DGRAM if kind == "udp" else socket.SOCK_STREAM
    ports = range(start, start + tries) if start else [0]
    for port in ports:
        with socket.socket(family, sock_type) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise ServerError(f"no free {kind} port from {start} on {host}")


def pid_alive(pid):
    """Whether `pid` is a running Factorio process (guards against recycled pids)."""
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                return False
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return "factorio" in buf.value.lower()
            return True
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)        # signal 0: existence check only (never call this on Windows)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.exists():
        try:
            return b"factorio" in cmdline.read_bytes().lower()
        except OSError:
            return False
    return True


def kill(pid):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    import signal
    try:
        os.kill(int(pid), signal.SIGTERM)
        for _ in range(100):
            if not pid_alive(pid):
                return
            time.sleep(0.1)
        os.kill(int(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def _detached():
    if sys.platform == "win32":
        return {"creationflags": 0x00000200 | 0x00000008}   # CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    return {"start_new_session": True}


class Target:
    """Where to send RCON commands."""

    def __init__(self, host, port, password, label=""):
        self.host, self.port, self.password, self.label = host, int(port), password, label

    def connect(self, timeout=30.0):
        client = RconClient(host=self.host, port=self.port, password=self.password, timeout=timeout)
        client.connect()
        return client


class Server:
    def __init__(self, session):
        self.session = session
        self.dir = session.server_dir
        self.run_file = self.dir / "run.json"

    # -- state
    def info(self):
        return paths.read_json(self.run_file, {}) or {}

    def pid(self):
        pid = self.info().get("pid")
        return pid if pid_alive(pid) else None

    def running(self):
        return self.pid() is not None

    def target(self):
        attach = self.session.meta.get("attach")
        if attach:
            password = self.session.secret("attach_password")
            if not password:
                raise ServerError("attached server has no password stored; run `fx attach` again")
            return Target(attach["host"], attach["port"], password, label=f"attached {attach['host']}:{attach['port']}")
        info = self.info()
        if not info.get("rcon_port"):
            raise ServerError(f"the server of session {self.session.name} is not running (`fx server start`)")
        return Target("127.0.0.1", info["rcon_port"], self.session.secret("rcon_password"), label=self.session.name)

    def log_tail(self, lines=25):
        for name in ("server.log", "factorio-current.log"):
            try:
                text = (self.dir / name).read_text(encoding="utf-8", errors="replace")
                return "\n".join(text.splitlines()[-lines:])
            except OSError:
                continue
        return "(no log)"

    # -- files
    def prepare(self, game):
        """Write config, mod list and server settings for this session."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session.saves_dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "config.ini").write_text(
            "[path]\n"
            f"read-data={game.data.as_posix()}\n"
            f"write-data={self.dir.as_posix()}\n"
            "[other]\ncheck-updates=false\nenable-crash-log-uploading=false\n",
            encoding="utf-8")
        self._prepare_mods(game)
        settings = self._settings()
        paths.write_json(self.dir / "server-settings.json", settings, private=True)
        paths.write_json(self.dir / "server-adminlist.json", list(self.session.server_settings["admins"]))
        self.session.secret("rcon_password", create=True)

    def _prepare_mods(self, game):
        mods_dir = self.dir / "mods"
        mods_dir.mkdir(exist_ok=True)
        wanted = self.session.mods
        builtin = game.builtin_mods()
        entries = [{"name": name, "enabled": name in wanted} for name in builtin]
        external = [name for name in wanted if name not in builtin]
        if external:
            source = _install.user_mods_dir(game)
            for name in external:
                matches = sorted(source.glob(f"{name}_*.zip")) + sorted(p for p in source.glob(f"{name}_*") if p.is_dir())
                if not matches and (source / name).is_dir():
                    matches = [source / name]
                if not matches:
                    raise ServerError(f"mod {name} is not in {source}; install it in your game first")
                pick = matches[-1]
                dest = mods_dir / pick.name
                if not dest.exists():
                    (shutil.copytree if pick.is_dir() else shutil.copyfile)(pick, dest)
                entries.append({"name": name, "enabled": True})
            if (source / "mod-settings.dat").exists() and not (mods_dir / "mod-settings.dat").exists():
                shutil.copyfile(source / "mod-settings.dat", mods_dir / "mod-settings.dat")
        paths.write_json(mods_dir / "mod-list.json", {"mods": entries})

    def _settings(self):
        s = self.session.server_settings
        out = dict(COMMON_SETTINGS)
        out["name"] = self.session.name
        out["description"] = s.get("description") or f"factorio-agent session {self.session.name}"
        out["max_players"] = int(s.get("max_players") or 0)
        out["game_password"] = self.session.secret("game_password") or ""
        if self.session.mode == "solo":
            out.update(SOLO_SETTINGS)
        else:
            out.update({
                "visibility": {"public": bool(s.get("public")), "lan": bool(s.get("lan"))},
                "require_user_verification": bool(s.get("verify_users", True)),
                "auto_pause": bool(s.get("auto_pause", True)),
                "auto_pause_when_players_connect": False,
                "autosave_interval": 10,
                "autosave_slots": 5,
            })
            if s.get("public"):
                login = self.session.secret("factorio_login") or {}
                if not (isinstance(login, dict) and login.get("username") and login.get("token")):
                    raise ServerError("a public game needs a factorio.com username and token: `fx server login`")
                out["username"], out["token"] = login["username"], login["token"]
        return out

    def _args(self, game):
        return [str(game.binary), "--config", str(self.dir / "config.ini"), "--mod-directory", str(self.dir / "mods")]

    # -- lifecycle
    def create_map(self, game, save="game", seed=None, map_gen_settings=None, map_settings=None):
        """Generate a new map with default (or given) settings and put the agent's script in it."""
        if self.running():
            raise ServerError("the server is running; stop it first")
        self.prepare(game)
        path = self.session.save_path(save)
        if path.exists():
            raise ServerError(f"{path} already exists")
        args = self._args(game) + ["--create", str(path)]
        if seed is not None:
            args += ["--map-gen-seed", str(int(seed))]
        if map_gen_settings:
            args += ["--map-gen-settings", str(map_gen_settings)]
        if map_settings:
            args += ["--map-settings", str(map_settings)]
        done = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.dir,
                              **_install._no_window())
        if done.returncode != 0 or not path.exists():
            raise ServerError("map creation failed:\n" + (done.stdout or "")[-2000:])
        savefile.inject(path)
        return path

    def start(self, game, save=None, wait=120.0):
        if self.session.meta.get("attach"):
            raise ServerError("this session uses a server run elsewhere (`fx attach`); it cannot be started from here")
        if self.running():
            raise ServerError("the server is already running")
        save = save or self.session.meta.get("save") or "game"
        path = self.session.save_path(save)
        if not path.exists():
            raise ServerError(f"no save at {path}")
        self.prepare(game)
        savefile.inject(path)     # always run the current script
        s = self.session.server_settings
        solo = self.session.mode == "solo"
        bind = s.get("bind") or ("127.0.0.1" if solo else "0.0.0.0")
        if s.get("port"):
            port = int(s["port"])
            free_port("udp", bind, port, tries=1)
        else:
            port = free_port("udp", bind, None if solo else 34197, tries=20)
        rcon_port = free_port("tcp", "127.0.0.1")
        args = self._args(game) + [
            "--start-server", str(path),
            "--server-settings", str(self.dir / "server-settings.json"),
            "--server-adminlist", str(self.dir / "server-adminlist.json"),
            "--bind", bind, "--port", str(port),
            "--rcon-bind", f"127.0.0.1:{rcon_port}",
            "--rcon-password", self.session.secret("rcon_password"),
        ]
        with open(self.dir / "server.log", "wb") as log:
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    cwd=self.dir, **_detached())
        info = {"pid": proc.pid, "save": save, "bind": bind, "game_port": port, "rcon_port": rcon_port,
                "version": game.version_str, "binary": str(game.binary), "started": time.time()}
        paths.write_json(self.run_file, info)
        target = self.target()
        deadline = time.time() + wait
        while time.time() < deadline:
            if proc.poll() is not None:
                raise ServerError("the server exited during startup:\n" + self.log_tail())
            try:
                target.connect(timeout=2.0).close()
                self.session.update(game_version=game.version_str, save=save)
                return info
            except RconError:
                time.sleep(0.25)
        raise ServerError("the server did not open RCON in time:\n" + self.log_tail())

    def stop(self, wait=120.0):
        """Save over the save it was started from, and exit."""
        pid = self.pid()
        if pid is None:
            return False
        try:
            client = self.target().connect(timeout=5.0)
            try:
                client.command("/quit")
            finally:
                client.close()
        except (RconError, OSError):
            kill(pid)
        deadline = time.time() + wait
        while time.time() < deadline:
            if not pid_alive(pid):
                return True
            time.sleep(0.1)
        kill(pid)
        raise ServerError(f"server {pid} did not exit within {wait:.0f}s and was killed (the map was not saved)")

    def wait_for_save(self, name, before_mtime, timeout=180.0):
        path = self.session.save_path(name)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists() and path.stat().st_mtime_ns != before_mtime and zipfile.is_zipfile(path):
                return path
            time.sleep(0.1)
        raise ServerError(f"save {name} did not appear within {timeout:.0f}s")
