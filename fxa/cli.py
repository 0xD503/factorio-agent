"""Command-line entry point: `fx <command>`. See `fx --help` and AGENTS.md."""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from fxa import dsl, fmt, install, paths, savefile, server, session
from fxa.game import Game, GameError
from fxa.rcon import RconError

# Ticks to let a freshly created world settle before the first look around.
SETTLE_TICKS = 120


def _area(p, radius):
    p.add_argument("x", type=float, nargs="?")
    p.add_argument("y", type=float, nargs="?")
    p.add_argument("-r", type=float, default=radius)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="fx",
        description="Play Factorio through a text interface. Start with "
        "AGENTS.md.",
    )
    parser.add_argument(
        "-s",
        "--session",
        help="session name or path (default: $FXA_SESSION, or the one chosen "
        "with `fx session use`)",
    )
    parser.add_argument("--json", action="store_true", help="print raw replies")
    sub = parser.add_subparsers(
        dest="command", required=True, metavar="COMMAND"
    )

    # -- setup
    p = sub.add_parser(
        "setup", help="find the game (or use the paths given) and remember it"
    )
    p.add_argument(
        "--game", help="Factorio install used for both server and client"
    )
    p.add_argument(
        "--server-game",
        help="install that runs servers (e.g. the Linux headless build)",
    )
    p.add_argument("--client-game", help="install you play with")
    p.add_argument(
        "--steam",
        action="store_true",
        help="also look for a Steam install (left alone otherwise)",
    )
    p.add_argument(
        "--gog",
        action="store_true",
        help="also look for a GOG install (left alone otherwise)",
    )
    p.add_argument(
        "--agent-name", help="default name of the agent in new sessions"
    )
    sub.add_parser(
        "doctor", help="check Python, the game, ports and the current session"
    )
    p = sub.add_parser(
        "selftest",
        help="run the live tests against the configured game (a few minutes)",
    )
    p.add_argument("-k", help="only tests matching this pattern")

    # -- sessions
    p = sub.add_parser("session", help="create, list and choose game sessions")
    ss = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    q = ss.add_parser(
        "new", help="create a session and its map, and start its server"
    )
    q.add_argument("name")
    q.add_argument(
        "--dir", help="where to keep it (default: <FXA_HOME>/sessions/NAME)"
    )
    q.add_argument(
        "--mode",
        choices=["solo", "coop"],
        default="solo",
        help="solo: the agent plays alone and runs the clock; coop: real time "
        "with human players",
    )
    q.add_argument("--seed", type=int)
    q.add_argument(
        "--mods",
        help="use exactly these mods (comma-separated) instead of the ones "
        "enabled in your game",
    )
    q.add_argument(
        "--agent-name", help="name shown over the agent's character and in chat"
    )
    q.add_argument(
        "--from-save", help="use this existing save instead of generating a map"
    )
    q.add_argument(
        "--map-gen-settings",
        help="map generator settings JSON (default: the game's defaults)",
    )
    q.add_argument(
        "--map-settings",
        help="map settings JSON (default: the game's defaults)",
    )
    q.add_argument("--no-start", action="store_true", help="only create it")
    _server_options(q)
    ss.add_parser("list", help="all sessions")
    q = ss.add_parser(
        "mods",
        help="compare the session's mods with your game's; --sync to adopt "
        "your game's",
    )
    q.add_argument(
        "--sync",
        action="store_true",
        help="make the session use the mods enabled in your game",
    )
    q.add_argument(
        "--set",
        help="make the session use exactly these mods (comma-separated)",
    )
    q = ss.add_parser("use", help="make a session the current one")
    q.add_argument("name")
    q = ss.add_parser("info", help="settings and paths of a session")
    q.add_argument("name", nargs="?")
    q = ss.add_parser(
        "set",
        help="change settings (server options take effect at the next server "
        "start)",
    )
    q.add_argument("--agent-name")
    _server_options(q)

    # -- server
    p = sub.add_parser(
        "server", help="start, stop or inspect the session's game server"
    )
    p.add_argument(
        "action",
        choices=["start", "stop", "restart", "status", "inject", "log"],
    )
    p.add_argument(
        "--save", help="save to start from (default: the session's last one)"
    )
    p = sub.add_parser(
        "password",
        help="set or clear the password players need to join (co-op)",
    )
    p.add_argument("value", nargs="?")
    p.add_argument("--clear", action="store_true")
    p = sub.add_parser(
        "attach",
        help="play on a server run elsewhere (it must have the agent script, "
        "see prepare-save)",
    )
    p.add_argument("address", nargs="?", help="HOST:RCON_PORT")
    p.add_argument(
        "--password-file",
        help="file holding the RCON password (or set FXA_RCON_PASSWORD)",
    )
    p.add_argument(
        "--detach", action="store_true", help="forget the attached server"
    )
    p = sub.add_parser(
        "prepare-save",
        help="copy a save with the agent script added, to host it elsewhere",
    )
    p.add_argument("source")
    p.add_argument("dest")
    sub.add_parser(
        "join", help="open your game connected to this session's server"
    )
    p = sub.add_parser(
        "client",
        help="(experimental) the agent plays through a game client of its own, "
        "as a real player",
    )
    cs = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    q = cs.add_parser(
        "launch",
        help="open the game logged in as the agent's account, connected to a "
        "server",
    )
    q.add_argument(
        "address", help="HOST:PORT of a server whose save has the agent script"
    )
    q.add_argument(
        "--udp-port",
        type=int,
        default=34300,
        help="local port the client listens on for the agent",
    )
    q.add_argument("--password", help="game password of the server")
    q = cs.add_parser(
        "call",
        help="send one request to the client: hello, state, walk, stop, say",
    )
    q.add_argument("op")
    q.add_argument("args", nargs="?", default="{}")
    q.add_argument(
        "--udp-port",
        type=int,
        help="default: the port of the last `fx client launch`",
    )

    # -- multiplayer
    p = sub.add_parser(
        "mode",
        help="switch between solo and coop (also restart the server for its "
        "network settings)",
    )
    p.add_argument("mode", choices=["solo", "coop"])
    p = sub.add_parser("chat", help="recent chat")
    p.add_argument(
        "--since", type=int, default=0, help="only lines after this id"
    )
    p.add_argument("--limit", type=int, default=30)
    p.add_argument(
        "--follow",
        action="store_true",
        help="keep printing new lines (stop with Ctrl+C)",
    )
    p = sub.add_parser("say", help="write in the game chat")
    p.add_argument("text")
    p.add_argument("--to", help="only to this player")
    sub.add_parser("players", help="players on the server")
    p = sub.add_parser(
        "wait",
        help="block until someone writes in chat (or the timeout passes)",
    )
    p.add_argument(
        "--since", type=int, help="chat id to wait after (default: now)"
    )
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument(
        "--mention",
        action="store_true",
        help="only lines that mention the agent",
    )

    # -- knowledge and skills
    p = sub.add_parser("kb", help="knowledge: list, show, search, add, promote")
    ks = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    q = ks.add_parser(
        "list", help="knowledge that applies to this session, by layer"
    )
    q.add_argument(
        "--all",
        action="store_true",
        help="include items that do not apply, and overridden ones",
    )
    q = ks.add_parser("show", help="print one item")
    q.add_argument("id")
    q = ks.add_parser("search", help="items containing all these words")
    q.add_argument("words", nargs="+")
    q = ks.add_parser(
        "add",
        help="write an item into a layer (default: session) from a file or "
        "stdin",
    )
    q.add_argument("id")
    q.add_argument("--file")
    q.add_argument("--title")
    q.add_argument("--tags", default="")
    q.add_argument("--layer", default="session")
    q.add_argument(
        "--force",
        action="store_true",
        help="replace an existing item in that layer",
    )
    q = ks.add_parser(
        "promote",
        help="copy an item to a lower layer: user, base, core or mod:NAME",
    )
    q.add_argument("id")
    q.add_argument("--to", required=True)
    q.add_argument("--force", action="store_true")

    p = sub.add_parser(
        "skill",
        help="skills: sandboxed scripts that play through the same orders",
    )
    ks = p.add_subparsers(dest="action", required=True, metavar="ACTION")
    q = ks.add_parser("list", help="skills available in this session")
    q.add_argument("--all", action="store_true")
    q = ks.add_parser("show", help="print a skill's source")
    q.add_argument("name")
    q = ks.add_parser(
        "run", help="run a skill: fx skill run NAME key=value ..."
    )
    q.add_argument("name")
    q.add_argument("params", nargs="*")
    q.add_argument("--max-steps", type=int)
    q = ks.add_parser("check", help="check a skill file without running it")
    q.add_argument("path")
    q = ks.add_parser(
        "promote",
        help="copy a skill to a lower layer: user, base, core or mod:NAME",
    )
    q.add_argument("name")
    q.add_argument("--to", required=True)
    q.add_argument("--force", action="store_true")

    # -- playing
    sub.add_parser("state", help="character, inventory, research, mode")
    p = sub.add_parser(
        "scan",
        help="summary of an area: ore patches, water, trees, enemies, own "
        "buildings",
    )
    _area(p, 64)
    p = sub.add_parser("map", help="tile map, one character per tile")
    p.add_argument("x", type=float, nargs="?")
    p.add_argument("y", type=float, nargs="?")
    p.add_argument("-w", type=int, default=64)
    p.add_argument("-H", type=int, default=32, dest="h")
    p.add_argument(
        "--scale",
        type=int,
        default=1,
        help="tiles per character (zoomed-out view)",
    )
    p = sub.add_parser(
        "ents",
        help="entities in detail (own buildings unless --name/--type/--all)",
    )
    _area(p, 20)
    p.add_argument("--name")
    p.add_argument("--type")
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int)
    p = sub.add_parser(
        "status",
        help="own buildings by status; positions of the ones not working",
    )
    _area(p, 60)
    p = sub.add_parser("find", help="nearest entities of a name")
    p.add_argument("name")
    p.add_argument("-r", type=float, default=150)
    p.add_argument(
        "--type", action="store_true", help="treat NAME as an entity type"
    )
    p.add_argument("--limit", type=int)
    p = sub.add_parser("recipe", help="recipes by name or product")
    p.add_argument("name")
    p = sub.add_parser("tech", help="one technology")
    p.add_argument("name")
    sub.add_parser("techs", help="technologies that can be researched now")
    p = sub.add_parser("prod", help="production statistics")
    p.add_argument("names", nargs="*")
    sub.add_parser("enemies", help="known nests, evolution, pollution")
    sub.add_parser("power", help="electric network near the character")
    sub.add_parser("mods", help="mods active in the game")
    p = sub.add_parser(
        "do",
        help="queue orders and run until they finish",
        description=dsl.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("orders")
    p.add_argument(
        "--ticks", type=int, default=36000, help="give up after this many ticks"
    )
    p = sub.add_parser(
        "run",
        help="let the game run for a number of ticks (co-op: wait that long)",
    )
    p.add_argument("ticks", type=int)
    sub.add_parser(
        "resume", help="continue queued orders after an interruption"
    )
    sub.add_parser("cancel", help="drop queued orders")
    p = sub.add_parser("research", help="queue technologies")
    p.add_argument("techs", nargs="*")
    p.add_argument("--clear", action="store_true")
    p = sub.add_parser(
        "speed", help="show or set the speed of solo runs (1-64)"
    )
    p.add_argument("value", type=float, nargs="?")
    p = sub.add_parser("save", help="write a named checkpoint save")
    p.add_argument("name")
    p = sub.add_parser(
        "apidoc",
        help="look up the game's Lua API reference (harness development)",
    )
    p.add_argument(
        "queries",
        nargs="+",
        help="Class.member, event:NAME, concept:NAME, define:PATH, class:NAME",
    )
    p = sub.add_parser("call", help="raw request: OP [JSON-ARGS]")
    p.add_argument("op")
    p.add_argument("args", nargs="?", default="{}")
    return parser


def _server_options(p):
    g = p.add_argument_group("server options (co-op)")
    g.add_argument(
        "--bind",
        help="address players connect to "
        "(coop default 0.0.0.0, solo 127.0.0.1)",
    )
    g.add_argument(
        "--port", type=int, help="UDP game port (coop default 34197)"
    )
    g.add_argument("--max-players", type=int)
    g.add_argument(
        "--admin",
        action="append",
        help="player name with admin rights (repeatable)",
    )
    g.add_argument(
        "--lan",
        dest="lan",
        action="store_true",
        default=None,
        help="show on the local network",
    )
    g.add_argument("--no-lan", dest="lan", action="store_false")
    g.add_argument(
        "--public",
        dest="public",
        action="store_true",
        default=None,
        help="list on the public server browser",
    )
    g.add_argument("--no-public", dest="public", action="store_false")
    g.add_argument(
        "--no-verify",
        dest="verify_users",
        action="store_false",
        default=None,
        help="let players join without a factorio.com login (offline LAN; "
        "admin names can then be spoofed)",
    )
    g.add_argument(
        "--no-auto-pause",
        dest="auto_pause",
        action="store_false",
        default=None,
        help="keep the game running while nobody is connected",
    )
    g.add_argument("--description")


def _server_fields(args):
    fields = {}
    for key in (
        "bind",
        "port",
        "max_players",
        "lan",
        "public",
        "verify_users",
        "auto_pause",
        "description",
    ):
        value = getattr(args, key, None)
        if value is not None:
            fields[key] = value
    if getattr(args, "admin", None):
        fields["admins"] = args.admin
    return fields


# ---------------------------------------------------------------------------
# setup, doctor


def cmd_setup(args):
    cfg = paths.config()
    game = cfg.setdefault("game", {})
    if args.game:
        found = install.probe(args.game)
        game["server"] = str(found.binary)
        if found.headless:
            print(
                "note: that is a headless build: it runs the servers but "
                "cannot be played; "
                "give the game you play with as --client-game"
            )
        else:
            game["client"] = str(found.binary)
    if args.server_game:
        game["server"] = str(install.probe(args.server_game).binary)
    if args.client_game:
        game["client"] = str(install.probe(args.client_game).binary)
    if not (args.game or args.server_game or args.client_game):
        found = install.search(steam=args.steam, gog=args.gog)
        if not found:
            print(
                "No Factorio install found in the usual places for standalone "
                "installs.\n"
                "  - give its folder (the one with bin/ and data/): fx setup "
                "--game PATH\n"
                "  - or let the harness use your Steam or GOG copy: fx setup "
                "--steam  (or --gog)\n"
                "  - on Linux the free headless server can run the games: fx "
                "setup --server-game PATH"
            )
            return 1
        print("Found:")
        for f in found:
            print("  " + f.describe())
        full = [f for f in found if not f.headless]
        game["server"] = str(found[0].binary)
        game["client"] = str((full or found)[0].binary)
    if args.agent_name:
        cfg["agent_name"] = args.agent_name
    paths.save_config(cfg)
    print(
        f"server: {game.get('server')}\nclient: {game.get('client')}\nsaved in "
        f"{paths.home() / 'config.json'}"
    )
    print(
        "Next: ./fx selftest  (checks the interface works with this game "
        "version)"
    )
    return 0


def cmd_doctor(args):
    from fxa import __version__, build_info

    problems = 0

    def line(ok, text):
        nonlocal problems
        problems += 0 if ok else 1
        print(("ok    " if ok else "FAIL  ") + text)

    print(f"factorio-agent {__version__} {build_info()}")
    line(
        sys.version_info >= (3, 10),
        f"Python {platform.python_version()} on {platform.system()} "
        f"{platform.release()} ({platform.machine()})",
    )
    home = paths.home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".write-test"
        probe.write_text("x")
        probe.unlink()
        line(True, f"data directory {home}")
    except OSError as err:
        line(False, f"data directory {home} is not writable: {err}")
    for role in ("server", "client"):
        try:
            found = install.configured(role)
            store = install.store_of(found.binary)
            line(
                True,
                f"{role}: {found.describe()}"
                + (f" ({store} install)" if store else ""),
            )
            for note in install.version_notes(found):
                print("      " + note)
            if role == "server":
                if not found.headless:
                    print(
                        "      (the full game runs servers too; on Linux the "
                        "free headless build is lighter)"
                    )
                line(
                    install.selftest_passed(found),
                    "selftest passed for this install and version"
                    if install.selftest_passed(found)
                    else "selftest has not passed with this install and "
                    "version yet: run ./fx selftest",
                )
            if role == "client":
                mods = install.enabled_mods(found)
                listed = (
                    ", ".join(mods) if mods else "unknown (no mod-list.json)"
                )
                print(f"      mods enabled in your game: {listed}")
        except install.InstallError as err:
            if role == "client":
                # Only needed to open the game (fx join) and to copy its mod
                # list; servers and
                # development containers have none.
                print(
                    "note  client: none configured (needed for fx join and "
                    f"for using your game's mods): {err}"
                )
            else:
                line(False, f"{role}: {err}")
    try:
        server.free_port("udp", "0.0.0.0", 34197, tries=1)
        line(True, "UDP port 34197 is free (default co-op port)")
    except server.ServerError:
        print(
            "note  UDP port 34197 is in use (another Factorio server?); co-op "
            "will pick the next free port"
        )
    try:
        s = session.current(args.session)
        srv = server.Server(s)
        state = (
            "running"
            if srv.running()
            else ("attached" if s.meta.get("attach") else "stopped")
        )
        line(True, f"session {s.name} ({s.mode}) at {s.dir}, server {state}")
        try:
            game = install.configured("server")
            if (
                s.meta.get("game_version")
                and s.meta["game_version"] != game.version_str
            ):
                print(
                    "      the game was updated since this session last ran "
                    f"({s.meta['game_version']} -> {game.version_str})"
                )
        except install.InstallError:
            pass
        _mods_notice(s, indent="      ")
    except session.SessionError as err:
        print(f"note  {err}")
    print("all good" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


def cmd_selftest(args):
    game = install.configured("server")
    env = dict(os.environ)
    env["FXA_LIVE"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "unittest",
        "-v",
        "tests.test_live",
        "tests.test_cli_live",
    ]
    if args.k:
        cmd += ["-k", args.k]
    print(f"testing with {game.describe()} (under a minute)...", flush=True)
    code = subprocess.call(cmd, cwd=paths.REPO, env=env)
    if code == 0 and not args.k:
        install.record_selftest(game)
        print(
            f"selftest passed: Factorio {game.version_str} works with this "
            "harness"
        )
    elif code:
        print(
            "selftest FAILED: please report the output above (see "
            "docs/USER_GUIDE.md, Troubleshooting)"
        )
    return code


def _configure(game_conn, s):
    return game_conn.call("configure", mode=s.mode, name=s.agent_name)


def _with_deps(mods):
    """Add the mods these require (Space Age needs quality and elevated-rails,
    for example)."""
    try:
        game = install.configured("server")
    except install.InstallError:
        game = None
    try:
        source = install.user_mods_dir(install.configured("client"))
    except install.InstallError:
        source = None
    return install.with_dependencies(mods, game, source)


def _mods_notice(s, indent="note: "):
    """Tell the user when their game's mods and the session's differ (never
    changes anything)."""
    try:
        mine = install.enabled_mods(install.configured("client"))
    except install.InstallError:
        return
    if mine is None:
        return
    extra = [m for m in mine if m not in s.mods]
    missing = [m for m in s.mods if m not in mine]
    if extra:
        print(
            f"{indent}your game has mods this session does not use: "
            f"{', '.join(extra)}; "
            "`fx session mods --sync` adds them (the save is migrated when the "
            "server next starts)"
        )
    if missing:
        print(
            f"{indent}this session uses mods your game has disabled: "
            f"{', '.join(missing)}; enable them to join, "
            "or `fx session mods --sync` to drop them (their buildings "
            "disappear from the map)"
        )


def _start_server(s, save=None):
    game = install.configured("server")
    for note in install.version_notes(game):
        print("note: " + note)
    if not install.selftest_passed(game):
        print("note: ./fx selftest has not passed with this game version yet")
    _mods_notice(s)
    if (
        s.meta.get("game_version")
        and s.meta["game_version"] != game.version_str
    ):
        print(
            "note: the game was updated since this session last ran "
            f"({s.meta['game_version']} -> {game.version_str}); "
            "knowledge marked as verified on the old version may be out of date"
        )
    info = server.Server(s).start(game, save)
    with Game(server.Server(s).target(), s) as g:
        _configure(g, s)
        st = g.state()
        if not st.get("started"):
            g.call("start")
            if s.mode == "solo":
                g.run(SETTLE_TICKS)
    where = f"{info['bind']}:{info['game_port']}"
    print(
        f"server started (pid {info['pid']}), {s.mode}, players connect to "
        f"{where}"
    )
    if s.mode == "coop" and info["bind"] in ("0.0.0.0", "::"):
        print(
            "  from other machines use this machine's address; across the "
            "internet forward UDP "
            f"{info['game_port']} or use a VPN such as Tailscale or ZeroTier"
        )
    return info


def cmd_session(args):
    action = args.action
    if action == "new":
        cfg = paths.config()
        if args.mods is not None:
            mods, source = (
                [m.strip() for m in args.mods.split(",") if m.strip()],
                "--mods",
            )
        else:
            try:
                mods = install.enabled_mods(install.configured("client"))
            except install.InstallError:
                mods = None
            source = "your game's mod list"
            if mods is None:
                mods, source = ["base"], "default (no game mod list found)"
        mods = _with_deps(mods)
        s = session.create(
            args.name,
            directory=args.dir,
            mode=args.mode,
            mods=mods,
            agent_name=args.agent_name or cfg.get("agent_name") or "Agent",
            seed=args.seed,
            server=_server_fields(args),
        )
        session.use(s)
        print(f"session {s.name} created at {s.dir} (now the current session)")
        print(f"mods: {', '.join(s.mods)} (from {source})")
        game = install.configured("server")
        srv = server.Server(s)
        if args.from_save:
            path = savefile.copy_in(args.from_save, s.saves_dir, "game")
            print(f"save copied to {path}")
        else:
            path = srv.create_map(
                game,
                "game",
                seed=args.seed,
                map_gen_settings=args.map_gen_settings,
                map_settings=args.map_settings,
            )
            print(f"map created: {path}")
        if not args.no_start:
            _start_server(s)
        return 0
    if action == "list":
        cur = None
        try:
            cur = session.current(args.session).dir
        except session.SessionError:
            pass
        found = session.all_sessions()
        if not found:
            print("no sessions yet: fx session new NAME")
        for name, path in found.items():
            try:
                s = session.Session(path)
                state = "running" if server.Server(s).running() else "stopped"
                print(
                    f"{'*' if s.dir == cur else ' '} {name:20s} {s.mode:5s} "
                    f"{state:8s} {path}"
                )
            except session.SessionError:
                print(f"  {name:20s} (missing) {path}")
        return 0
    if action == "mods":
        s = session.current(args.session)
        mine = None
        try:
            mine = install.enabled_mods(install.configured("client"))
        except install.InstallError:
            pass
        if args.set or args.sync:
            if args.set:
                new = ["base"] + [
                    m.strip()
                    for m in args.set.split(",")
                    if m.strip() and m.strip() != "base"
                ]
            elif mine is None:
                print(
                    "cannot read your game's mod list (no client install "
                    "configured, or no mod-list.json)",
                    file=sys.stderr,
                )
                return 1
            else:
                new = mine
            new = _with_deps(new)
            s.update(mods=new)
            print(
                f"session mods: {', '.join(new)}; restart the server to apply "
                "(fx server restart)"
            )
            return 0
        print(f"session:   {', '.join(s.mods)}")
        print(f"your game: {', '.join(mine) if mine else 'unknown'}")
        _mods_notice(s, indent="")
        return 0
    if action == "use":
        s = session.find(args.name)
        session.use(s)
        print(f"current session: {s.name} ({s.dir})")
        return 0
    if action == "info":
        s = (
            session.find(args.name)
            if args.name
            else session.current(args.session)
        )
        srv = server.Server(s)
        print(
            f"{s.name}: {s.mode}, agent {s.agent_name}, mods "
            f"{', '.join(s.mods)}, game {s.meta.get('game_version', '?')}"
        )
        print(
            f"  dir:       {s.dir}\n  notes:     {s.dir / 'NOTES.md'}\n  "
            f"knowledge: {s.knowledge_dir}\n  skills:    {s.skills_dir}\n  "
            f"saves:     {s.saves_dir}"
        )
        info = srv.info()
        if s.meta.get("attach"):
            print(
                "  attached to "
                f"{s.meta['attach']['host']}:{s.meta['attach']['port']}"
            )
        elif srv.running():
            print(
                f"  server running: pid {info['pid']}, players connect to "
                f"{info['bind']}:{info['game_port']}"
            )
        else:
            print("  server stopped")
        print("  server options: " + json.dumps(s.server_settings))
        return 0
    if action == "set":
        s = session.current(args.session)
        if args.agent_name:
            s.update(agent_name=args.agent_name)
        fields = _server_fields(args)
        if fields:
            s.update(server={**(s.meta.get("server") or {}), **fields})
        print(
            json.dumps(
                {"agent_name": s.agent_name, "server": s.server_settings},
                indent=2,
            )
        )
        return 0
    return 1


def cmd_server(args):
    s = session.current(args.session)
    srv = server.Server(s)
    action = args.action
    if action == "status":
        info = srv.info()
        if s.meta.get("attach"):
            print(
                f"{s.name}: attached to "
                f"{s.meta['attach']['host']}:{s.meta['attach']['port']}"
            )
        elif srv.running():
            print(
                f"{s.name}: running (pid {info['pid']}), {s.mode}, players "
                f"connect to {info['bind']}:{info['game_port']}, "
                f"Factorio {info.get('version')}"
            )
        else:
            print(f"{s.name}: stopped")
        return 0
    if action == "log":
        print(srv.log_tail(60))
        return 0
    if action in ("stop", "restart", "inject"):
        print("stopped (map saved)" if srv.stop() else "was not running")
    if action == "inject":
        save = args.save or s.meta.get("save") or "game"
        print(
            "scripts replaced: " + ", ".join(savefile.inject(s.save_path(save)))
        )
    if action in ("start", "restart", "inject"):
        _start_server(s, args.save)
    return 0


def cmd_password(args):
    s = session.current(args.session)
    if args.clear:
        s.set_secret("game_password", None)
        print("game password cleared (takes effect at the next server start)")
    elif args.value:
        s.set_secret("game_password", args.value)
        print("game password set (takes effect at the next server start)")
    else:
        print(
            "a game password is set"
            if s.secret("game_password")
            else "no game password"
        )
    return 0


def cmd_attach(args):
    s = session.current(args.session)
    if args.detach:
        s.meta.pop("attach", None)
        s.save()
        s.set_secret("attach_password", None)
        print("detached")
        return 0
    if not args.address or ":" not in args.address:
        print("fx attach HOST:RCON_PORT --password-file FILE", file=sys.stderr)
        return 1
    host, port = args.address.rsplit(":", 1)
    password = os.environ.get("FXA_RCON_PASSWORD")
    if args.password_file:
        password = Path(args.password_file).read_text(encoding="utf-8").strip()
    if not password:
        print(
            "give the RCON password with --password-file or FXA_RCON_PASSWORD",
            file=sys.stderr,
        )
        return 1
    target = server.Target(host, int(port), password, label=args.address)
    with Game(target, s) as g:
        st = g.state()
        s.update(attach={"host": host, "port": int(port)})
        s.set_secret("attach_password", password)
        _configure(g, s)
        if not st.get("started"):
            g.call("start")
        print(
            f"attached to {args.address}: tick {st.get('tick')}, mode {s.mode}"
        )
    return 0


def cmd_prepare_save(args):
    dest = Path(args.dest)
    if dest.exists():
        print(f"{dest} exists", file=sys.stderr)
        return 1
    savefile.inject(args.source, target=dest)
    print(
        f"wrote {dest}: host it with your server, add RCON "
        "(--rcon-bind/--rcon-password), then `fx attach HOST:PORT`"
    )
    return 0


def _launch_client(extra):
    client = install.configured("client")
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    kwargs.update(server._detached())
    return subprocess.Popen([str(client.binary)] + extra, **kwargs)


def cmd_client(args):
    from fxa import link

    state_file = paths.home() / "client-link.json"
    if args.action == "launch":
        extra = [
            "--mp-connect",
            args.address,
            "--enable-lua-udp",
            str(args.udp_port),
        ]
        if args.password:
            extra += ["--password", args.password]
        proc = _launch_client(extra)
        paths.write_json(
            state_file,
            {
                "udp_port": args.udp_port,
                "pid": proc.pid,
                "address": args.address,
            },
        )
        print(
            f"opened the game (pid {proc.pid}) connecting to {args.address}; "
            "it listens for the agent on UDP "
            f"{args.udp_port}. Check with: fx client call hello"
        )
        return 0
    port = args.udp_port or (paths.read_json(state_file, {}) or {}).get(
        "udp_port"
    )
    if not port:
        print("no client launched: fx client launch HOST:PORT", file=sys.stderr)
        return 1
    client = link.ClientLink(port)
    try:
        reply = client.call(args.op, **json.loads(args.args))
    except link.LinkError as err:
        print(f"fx: {err}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(
        json.dumps(reply)
        if args.json
        else fmt.fields(
            {k: v for k, v in reply.items() if k not in ("ok", "id")}
        )
    )
    return 0


def cmd_join(args):
    s = session.current(args.session)
    info = server.Server(s).info()
    if not server.Server(s).running():
        print(
            "the session's server is not running (fx server start)",
            file=sys.stderr,
        )
        return 1
    host = (
        "127.0.0.1"
        if info["bind"] in ("0.0.0.0", "127.0.0.1")
        else info["bind"]
    )
    extra = ["--mp-connect", f"{host}:{info['game_port']}"]
    if s.secret("game_password"):
        extra += ["--password", s.secret("game_password")]
    proc = _launch_client(extra)
    print(
        f"opening your game (pid {proc.pid}) connected to "
        f"{host}:{info['game_port']}; if it is already open, "
        f"use Multiplayer > Connect to address instead"
    )
    return 0


# ---------------------------------------------------------------------------
# multiplayer


def cmd_mode(args, g):
    s = g.session
    reply = g.call("configure", mode=args.mode)
    if s:
        s.update(mode=args.mode)
    print(
        f"mode {reply['mode']}"
        + (
            "; restart the server (fx server restart) so it accepts players "
            "over the network"
            if args.mode == "coop"
            else ""
        )
    )
    return 0


def cmd_chat(args, g):
    since = args.since
    lines, seq = g.chat(since=since, limit=args.limit)
    print(fmt.chat(lines) if not args.json else json.dumps(lines))
    if not args.follow:
        return 0
    since = seq
    try:
        while True:
            lines, since = g.wait_chat(since, timeout=60)
            for line in lines:
                print(fmt.chat_line(line), flush=True)
    except KeyboardInterrupt:
        return 0


def cmd_wait(args, g):
    since = args.since if args.since is not None else g.chat(since=10**9)[1]
    lines, seq = g.wait_chat(
        since, timeout=args.timeout, mention_only=args.mention
    )
    if args.json:
        print(json.dumps({"lines": lines, "seq": seq}))
    else:
        print(
            fmt.chat(lines)
            if lines
            else f"(nothing in {args.timeout:.0f}s; chat #{seq})"
        )
    return 0


# ---------------------------------------------------------------------------
# knowledge and skills


def cmd_kb(args):
    from fxa import layers

    s = session.find_quiet(args.session) if args.session else _current_quiet()
    stack = layers.stack(s)
    if args.action == "list":
        print(layers.render_list(stack, "knowledge", show_all=args.all))
    elif args.action == "show":
        item = layers.resolve(stack, "knowledge", args.id)
        print(layers.render_item(item))
    elif args.action == "search":
        for item in layers.search(stack, args.words):
            print(f"{item.id:40s} [{item.layer.name}] {item.title}")
    elif args.action == "add":
        text = (
            Path(args.file).read_text(encoding="utf-8")
            if args.file
            else sys.stdin.read()
        )
        path = layers.add(
            stack,
            args.layer,
            args.id,
            text,
            title=args.title,
            tags=args.tags,
            force=args.force,
        )
        print(f"wrote {path}")
    elif args.action == "promote":
        path = layers.promote(
            stack, "knowledge", args.id, args.to, force=args.force
        )
        print(f"copied to {path}" + _review_hint(path))
    return 0


def _review_hint(path):
    if paths.REPO not in Path(path).resolve().parents:
        return ""
    if (paths.REPO / ".git").exists():
        return (
            "\nThis file is inside the repository: review it (git diff) "
            "and commit it, or open a pull request."
        )
    return (
        "\nThis copy of the harness is a release archive, not a git checkout: "
        "the file will be replaced at the "
        "next upgrade. Prefer --to user, or send the file to the maintainers."
    )


def _current_quiet():
    try:
        return session.current()
    except session.SessionError:
        return None


def cmd_skill(args):
    from fxa import layers, skills

    s = session.find_quiet(args.session) if args.session else _current_quiet()
    stack = layers.stack(s)
    if args.action == "list":
        print(layers.render_list(stack, "skills", show_all=args.all))
        return 0
    if args.action == "show":
        item = layers.resolve(stack, "skills", args.name)
        print(
            f"# {item.path} [{item.layer.name}]\n"
            + item.path.read_text(encoding="utf-8")
        )
        return 0
    if args.action == "check":
        problems = skills.check_file(args.path)
        print("\n".join(problems) if problems else "ok")
        return 1 if problems else 0
    if args.action == "promote":
        path = layers.promote(
            stack, "skills", args.name, args.to, force=args.force
        )
        print(f"copied to {path}" + _review_hint(path))
        return 0
    if args.action == "run":
        params = skills.parse_params(args.params)
        with Game.for_session(args.session) as g:
            result = skills.run(
                stack, args.name, params, g, max_steps=args.max_steps
            )
        print(
            result.output,
            end=""
            if result.output.endswith("\n") or not result.output
            else "\n",
        )
        if result.value is not None:
            print(
                json.dumps(result.value)
                if args.json
                else fmt.fields(result.value)
                if isinstance(result.value, dict)
                else result.value
            )
        print(f"({result.steps} steps)")
        return 0
    return 1


# ---------------------------------------------------------------------------
# playing


def game_command(args, game):
    command = args.command
    show = None

    def point():
        return {"x": args.x, "y": args.y}

    if command == "state":
        reply, show = game.state(), fmt.state
    elif command == "scan":
        reply, show = game.call("scan", r=args.r, **point()), fmt.scan
    elif command == "map":
        reply, show = (
            game.call("map", w=args.w, h=args.h, scale=args.scale, **point()),
            fmt.tile_map,
        )
    elif command == "ents":
        reply = game.call(
            "entities",
            r=args.r,
            name=args.name,
            type=args.type,
            all=args.all or None,
            limit=args.limit,
            **point(),
        )
        show = fmt.entities
    elif command == "status":
        reply, show = game.call("buildings", r=args.r, **point()), fmt.status
    elif command == "find":
        key = "type" if args.type else "name"
        reply, show = (
            game.call("find", r=args.r, limit=args.limit, **{key: args.name}),
            fmt.found,
        )
    elif command == "recipe":
        reply, show = game.call("recipe", name=args.name), fmt.recipes
    elif command == "tech":
        reply, show = game.call("tech", name=args.name), fmt.tech
    elif command == "techs":
        reply, show = game.call("techs"), fmt.techs
    elif command == "prod":
        names = {name: True for name in args.names} or None
        reply, show = game.call("production", names=names), fmt.production
    elif command == "power":
        reply, show = game.call("power"), fmt.power
    elif command == "enemies":
        reply, show = game.call("enemies"), fmt.enemies
    elif command == "mods":
        reply = game.call("mods")
        show = lambda r: ", ".join(
            f"{k} {v}" for k, v in sorted((r.get("mods") or {}).items())
        )
    elif command == "players":
        reply = game.call("players")
        show = lambda r: fmt.players(r.get("players"))
    elif command == "say":
        line = game.say(args.text, to=args.to)
        print(fmt.chat_line(line))
        return 0
    elif command == "mode":
        return cmd_mode(args, game)
    elif command == "chat":
        return cmd_chat(args, game)
    elif command == "wait":
        return cmd_wait(args, game)
    elif command in ("do", "run", "resume"):
        if command == "do":
            report = game.do(dsl.parse(args.orders), max_ticks=args.ticks)
        elif command == "run":
            report = game.run(args.ticks)
        else:
            report = game.resume()
        print(json.dumps(report.raw) if args.json else str(report))
        return 0 if report.ok else 2
    elif command == "cancel":
        reply = game.cancel()
    elif command == "research":
        reply = game.research(*args.techs, clear=args.clear)
        show = lambda r: (
            "queue: "
            + (", ".join(fmt.seq(r.get("queue"))) or "-")
            + "".join(
                f"\n  could not queue {name}"
                for name, ok in (r.get("added") or {}).items()
                if not ok
            )
        )
    elif command == "speed":
        reply = game.call("speed", speed=args.value)
    elif command == "save":
        print(f"saved {game.save(args.name)}")
        return 0
    elif command == "call":
        reply = game.call(args.op, **json.loads(args.args))
    else:
        raise GameError(f"unknown command {command}")

    if args.json or show is None:
        print(json.dumps(reply))
    else:
        print(show(reply))
    return 0


def cmd_apidoc(args):
    from fxa import apidoc

    apidoc.main(args.queries)
    return 0


LOCAL = {
    "apidoc": cmd_apidoc,
    "setup": cmd_setup,
    "doctor": cmd_doctor,
    "selftest": cmd_selftest,
    "session": cmd_session,
    "server": cmd_server,
    "password": cmd_password,
    "attach": cmd_attach,
    "prepare-save": cmd_prepare_save,
    "join": cmd_join,
    "client": cmd_client,
    "kb": cmd_kb,
    "skill": cmd_skill,
}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    from fxa import layers, sandbox, skills

    errors = (
        GameError,
        RconError,
        server.ServerError,
        session.SessionError,
        install.InstallError,
        savefile.SaveError,
        dsl.ParseError,
        layers.LayerError,
        sandbox.SandboxError,
        skills.SkillError,
        ValueError,
        OSError,
    )
    try:
        handler = LOCAL.get(args.command)
        if handler:
            return handler(args) or 0
        with Game.for_session(args.session) as game:
            return game_command(args, game)
    except errors as err:
        sys.stdout.flush()
        print(f"fx: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
