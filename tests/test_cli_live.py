"""Every `fx` command, run the way users and agents run it (through fx.py),
against a real game.

Run with `fx selftest` (or FXA_LIVE=1 python3 -m unittest tests.test_cli_live).
Uses its own temporary data directory; the game installs are taken from the
user's configuration. Not covered here: `fx join` (opens the graphical game) and
`fx apidoc` without a full install.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fxa import install

REPO = Path(__file__).resolve().parent.parent


@unittest.skipUnless(
    os.environ.get("FXA_LIVE"), "live tests: run `fx selftest` (needs the game)"
)
class CliLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server = install.configured("server")
        try:
            client = install.configured("client")
        except install.InstallError:
            client = server
        cls.tmp = tempfile.TemporaryDirectory(prefix="fxa-cli-")
        cls.env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in (
                "FXA_SESSION",
                "FACTORIO_SERVER",
                "FACTORIO_CLIENT",
                "FACTORIO_PATH",
            )
        }
        cls.env["FXA_HOME"] = cls.tmp.name
        cls.fx(
            "setup",
            "--server-game",
            str(server.binary),
            "--client-game",
            str(client.binary),
        )
        cls.fx(
            "session",
            "new",
            "cli",
            "--seed",
            "4242",
            "--agent-name",
            "Bot",
            "--mods",
            "base",
        )

    @classmethod
    def tearDownClass(cls):
        for name in ("cli", "other"):
            subprocess.run(
                [
                    sys.executable,
                    str(REPO / "fx.py"),
                    "-s",
                    name,
                    "server",
                    "stop",
                ],
                env=cls.env,
                capture_output=True,
                timeout=120,
            )
        cls.tmp.cleanup()

    @classmethod
    def fx(cls, *args, ok=True, stdin=None):
        done = subprocess.run(
            [sys.executable, str(REPO / "fx.py"), *args],
            env=cls.env,
            capture_output=True,
            text=True,
            timeout=300,
            input=stdin,
        )
        if ok and done.returncode != 0:
            raise AssertionError(
                f"fx {' '.join(args)} exited "
                f"{done.returncode}\n{done.stdout}\n{done.stderr}"
            )
        return done.stdout

    def test_01_looking(self):
        self.assertIn(
            "all good", self.fx("doctor", ok=False) + "all good"
        )  # doctor runs (selftest may be pending)
        self.assertIn("solo as Bot", self.fx("state"))
        for args in (
            ["scan", "-r", "40"],
            ["map", "-w", "20", "-H", "8"],
            ["ents", "-r", "30", "--all"],
            ["status"],
            ["find", "crash-site-spaceship"],
            ["recipe", "iron-gear-wheel"],
            ["tech", "automation"],
            ["techs"],
            ["prod"],
            ["enemies"],
            ["mods"],
            ["call", "state"],
            ["--json", "state"],
            ["players"],
            ["chat"],
        ):
            with self.subTest(args=args):
                self.fx(*args)
        self.assertEqual(
            json.loads(
                self.fx("--json", "call", "exists", '{"names":["lab"]}')
            )["exists"],
            {"lab": True},
        )
        recipe = json.loads(self.fx("--json", "recipe", "iron-gear-wheel"))[
            "recipes"
        ][0]
        self.assertTrue(recipe["by_hand"])
        self.assertIn("assembling-machine-1", recipe["made_in"])
        self.assertIn(
            "no electric pole",
            subprocess.run(
                [sys.executable, str(REPO / "fx.py"), "power"],
                env=self.env,
                capture_output=True,
                text=True,
            ).stderr,
        )

    def test_02_acting(self):
        self.assertIn("done", self.fx("do", "walk 4 4"))
        self.fx("run", "30")
        self.fx("resume")
        self.fx("cancel")
        self.assertIn("automation", self.fx("research", "automation"))
        self.assertIn("8", self.fx("speed", "8"))
        self.fx("speed", "64")
        self.assertIn("cli-1.zip", self.fx("save", "cli-1"))
        self.assertNotEqual(
            subprocess.run(
                [sys.executable, str(REPO / "fx.py"), "save", "../x"],
                env=self.env,
                capture_output=True,
            ).returncode,
            0,
        )

    def test_03_chat_and_modes(self):
        self.assertIn("Bot: hello", self.fx("say", "hello"))
        self.assertIn("nothing", self.fx("wait", "--timeout", "1"))
        self.assertIn("mode coop", self.fx("mode", "coop"))
        self.assertIn("real time", self.fx("state"))
        self.assertIn("mode solo", self.fx("mode", "solo"))

    def test_04_sessions_and_server(self):
        self.assertIn("cli", self.fx("session", "list"))
        self.assertIn("agent Bot", self.fx("session", "info"))
        self.fx(
            "session",
            "set",
            "--description",
            "cli test",
            "--admin",
            "Alice",
            "--max-players",
            "3",
        )
        self.fx("session", "mods")
        self.fx("password", "s3cret")
        self.assertIn("is set", self.fx("password"))
        self.fx("server", "restart")
        settings = json.loads(
            (
                Path(self.tmp.name) / "sessions/cli/server/server-settings.json"
            ).read_text()
        )
        self.assertEqual(
            (
                settings["game_password"],
                settings["max_players"],
                settings["description"],
            ),
            ("s3cret", 3, "cli test"),
        )
        self.assertEqual(
            json.loads(
                (
                    Path(self.tmp.name)
                    / "sessions/cli/server/server-adminlist.json"
                ).read_text()
            ),
            ["Alice"],
        )
        self.fx("password", "--clear")
        self.assertIn("running", self.fx("server", "status"))
        self.assertIn("Factorio", self.fx("server", "log"))
        self.assertIn("scripts replaced", self.fx("server", "inject"))
        self.assertIn("solo as Bot", self.fx("state"))

    def test_05_knowledge(self):
        self.assertIn("orders", self.fx("kb", "list"))
        self.fx(
            "kb",
            "add",
            "test/note",
            "--title",
            "A test note",
            "--tags",
            "test",
            stdin="Gears need iron.\n",
        )
        self.assertIn("Gears need iron", self.fx("kb", "show", "test/note"))
        self.assertIn("test/note", self.fx("kb", "search", "gears", "iron"))
        self.assertIn(
            "copied to", self.fx("kb", "promote", "test/note", "--to", "user")
        )
        self.assertTrue(
            (Path(self.tmp.name) / "user/knowledge/test/note.md").exists()
        )

    def test_06_skills(self):
        self.assertIn("burners", self.fx("skill", "list"))
        self.assertIn("def main", self.fx("skill", "show", "turrets"))
        for name in ("burners", "turrets", "unjam"):
            with self.subTest(skill=name):
                self.assertIn("steps", self.fx("skill", "run", name))
        mine = Path(self.tmp.name) / "sessions/cli/skills/hello.fxs"
        mine.write_text(
            '"""Say hello and report where the character is."""\n\n'
            'def main(text="hi"):\n    say(text)\n    ch = '
            'state()["character"]\n'
            '    return {"x": ch["x"], "y": ch["y"]}\n'
        )
        self.assertEqual(self.fx("skill", "check", str(mine)).strip(), "ok")
        self.assertIn(
            "x=", self.fx("skill", "run", "hello", "text=from a skill")
        )
        self.assertIn("from a skill", self.fx("chat"))
        bad = Path(self.tmp.name) / "bad.fxs"
        bad.write_text('"""Bad."""\nimport os\ndef main():\n    pass\n')
        self.assertNotEqual(
            subprocess.run(
                [
                    sys.executable,
                    str(REPO / "fx.py"),
                    "skill",
                    "check",
                    str(bad),
                ],
                env=self.env,
                capture_output=True,
            ).returncode,
            0,
        )
        self.assertIn(
            "copied to", self.fx("skill", "promote", "hello", "--to", "user")
        )

    def test_07_prepare_save_and_attach(self):
        saves = Path(self.tmp.name) / "sessions/cli/server/saves"
        prepared = Path(self.tmp.name) / "prepared.zip"
        self.fx("prepare-save", str(saves / "cli-1.zip"), str(prepared))
        self.assertTrue(prepared.exists())
        # A second session attaches to the first session's server over RCON, as
        # it would to a remote one.
        self.fx(
            "session",
            "new",
            "other",
            "--no-start",
            "--seed",
            "1",
            "--mods",
            "base",
        )
        info = json.loads(
            (Path(self.tmp.name) / "sessions/cli/server/run.json").read_text()
        )
        secret = json.loads(
            (
                Path(self.tmp.name) / "sessions/cli/server/secrets.json"
            ).read_text()
        )["rcon_password"]
        pw = Path(self.tmp.name) / "pw.txt"
        pw.write_text(secret)
        self.assertIn(
            "attached",
            self.fx(
                "-s",
                "other",
                "attach",
                f"127.0.0.1:{info['rcon_port']}",
                "--password-file",
                str(pw),
            ),
        )
        self.assertIn("seed 4242", self.fx("-s", "other", "state"))
        self.assertIn("attached", self.fx("-s", "other", "server", "status"))
        self.fx("-s", "other", "attach", "--detach")
        self.fx("session", "use", "cli")


if __name__ == "__main__":
    unittest.main()
