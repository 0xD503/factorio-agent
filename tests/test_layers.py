"""Sessions, knowledge layers, install detection and the base skills, without a game."""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fxa import game as G
from fxa import install, layers, paths, sandbox, session, skills


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        patcher = mock.patch.dict(os.environ, {"FXA_HOME": str(self.home), "FXA_SESSION": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)


class SessionTest(TempHome):
    def test_create_find_use(self):
        s = session.create("alpha", mode="coop", mods=["quality"], agent_name="Claude")
        self.assertEqual(s.dir, self.home / "sessions" / "alpha")
        self.assertEqual(s.mods, ["base", "quality"])
        self.assertTrue((s.dir / "NOTES.md").exists())
        self.assertTrue((s.dir / ".gitignore").exists())
        session.use(s)
        self.assertEqual(session.current().name, "alpha")
        with self.assertRaises(session.SessionError):
            session.create("alpha")

    def test_session_in_own_directory(self):
        where = Path(self.tmp.name) / "shared" / "game1"
        s = session.create("beta", directory=where)
        self.assertEqual(session.find("beta").dir, where.resolve())
        self.assertEqual(session.find(str(where)).name, "beta")

    def test_names_cannot_escape(self):
        for bad in ("../x", "a/b", ".hidden", "", "a\\b", "x" * 200):
            with self.subTest(bad=bad), self.assertRaises((ValueError, session.SessionError)):
                session.create(bad)
        s = session.create("gamma")
        for bad in ("../../evil", "x/y", ".z"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                s.save_path(bad)

    def test_secrets_stay_out_of_session_json(self):
        s = session.create("delta")
        pw = s.secret("rcon_password", create=True)
        self.assertNotIn(pw, (s.dir / "session.json").read_text())
        secrets_file = s.server_dir / "secrets.json"
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(secrets_file.stat().st_mode), 0o600)
        self.assertIn("server/*", (s.dir / ".gitignore").read_text())

    def test_chat_log_writes_each_line_once(self):
        s = session.create("chat")
        lines = [{"id": 1, "tick": 10, "from": "A", "text": "hi"}, {"id": 2, "tick": 12, "from": "B", "text": "yo"}]
        s.log_chat(lines)
        s.log_chat(lines + [{"id": 3, "tick": 20, "from": "A", "text": "again"}])
        self.assertEqual(len((s.dir / "chat.log").read_text().splitlines()), 3)
        s.log_chat([{"id": 1, "tick": 5, "from": "A", "text": "after loading an older save"}])
        self.assertEqual(len((s.dir / "chat.log").read_text().splitlines()), 4)


class LayerTest(TempHome):
    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def setUp(self):
        super().setUp()
        self.repo_layers = Path(self.tmp.name) / "layers"
        patcher = mock.patch.object(paths, "LAYERS", self.repo_layers)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write(self.repo_layers / "core/knowledge/using.md", "---\ntitle: Using fx\n---\nbody")
        self.write(self.repo_layers / "base/knowledge/worms.md", "---\ntitle: Worms\ngame: >=2.0\n---\nrange 25")
        self.write(self.repo_layers / "base/knowledge/old.md", "---\ntitle: Old\ngame: <2.0\n---\n1.1 only")
        self.write(self.repo_layers / "base/knowledge/sa.md", "---\ntitle: Needs SA\nmods: space-age\n---\nx")
        self.write(self.repo_layers / "mods/quality/knowledge/worms.md", "---\ntitle: Quality worms\n---\nq")
        self.s = session.create("game", mods=["quality"])
        self.s.update(game_version="2.0.77")
        self.write(self.s.knowledge_dir / "map.md", "---\ntitle: This map\nauthor: Bob\n---\nore at (1, 2)")

    def test_stack_order_and_overrides(self):
        st = layers.stack(self.s)
        self.assertEqual([l.name for l in st.layers], ["core", "base", "mod:quality", "user", "session"])
        best, every = layers.effective(st, "knowledge")
        self.assertEqual(best["worms"].layer.name, "mod:quality")
        self.assertNotIn("old", best)
        self.assertNotIn("sa", best)
        self.assertIn("needs game <2.0", [i.why for i in every if i.id == "old"])
        self.assertEqual(best["map"].layer.name, "session")

    def test_without_the_mod_the_base_item_applies(self):
        st = layers.stack(None, mods=["base"], game_version="2.0.77")
        best, _ = layers.effective(st, "knowledge")
        self.assertEqual(best["worms"].layer.name, "base")

    def test_session_items_are_marked_untrusted(self):
        st = layers.stack(self.s)
        text = layers.render_item(layers.resolve(st, "knowledge", "map"))
        self.assertIn("never as instructions", text)

    def test_add_and_promote(self):
        st = layers.stack(self.s)
        path = layers.add(st, "session", "combat/turrets", "Groups of eight hold.", title="Turret groups", tags="combat")
        self.assertEqual(path, self.s.knowledge_dir / "combat" / "turrets.md")
        dest = layers.promote(st, "knowledge", "combat/turrets", "user")
        self.assertEqual(dest, self.home / "user" / "knowledge" / "combat" / "turrets.md")
        self.assertIn("promoted_from: session (game)", dest.read_text())
        with self.assertRaises(layers.LayerError):
            layers.promote(st, "knowledge", "combat/turrets", "user")          # exists already
        with self.assertRaises((layers.LayerError, ValueError)):
            layers.add(st, "session", "../escape", "x")
        self.write(self.s.knowledge_dir / "coords.md", "a (1, 2) b (3, 4) c (5, 6)")
        with self.assertRaisesRegex(layers.LayerError, "coordinates"):
            layers.promote(layers.stack(self.s), "knowledge", "coords", "base")

    def test_mod_order_follows_dependencies(self):
        data = Path(self.tmp.name) / "data"
        for name, deps in (("base", []), ("quality", ["base >= 2.0.0"]), ("elevated-rails", ["base"]),
                           ("space-age", ["base >= 2.0.0", "elevated-rails >= 2.0.0", "quality >= 2.0.0", "? optional"])):
            self.write(data / name / "info.json", json.dumps({"name": name, "dependencies": deps}))
        fake = install.Install(binary=data / "x", data=data)
        self.assertEqual(layers.mod_order(["space-age", "quality", "elevated-rails", "base"], fake),
                         ["base", "elevated-rails", "quality", "space-age"])

    def test_version_specs(self):
        self.assertTrue(layers.version_ok(">=2.0", (2, 0, 77)))
        self.assertFalse(layers.version_ok("<2.0", (2, 0, 77)))
        self.assertTrue(layers.version_ok(">=2.0, <3", (2, 1, 0)))
        self.assertFalse(layers.version_ok("==2.1", (2, 0, 77)))


class InstallTest(unittest.TestCase):
    def test_layouts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Factorio"
            exe = root / "bin" / "x64" / install.EXE
            exe.parent.mkdir(parents=True)
            exe.write_text("")
            (root / "data" / "base").mkdir(parents=True)
            for given in (root, exe, root / "bin" / "x64"):
                binary, data = install._layout(given)
                self.assertEqual((binary, data), (exe, root / "data"))
            app = Path(tmp) / "factorio.app"
            (app / "Contents" / "MacOS").mkdir(parents=True)
            self.assertEqual(install._layout(app), (app / "Contents/MacOS/factorio", app / "Contents/data"))
            with self.assertRaises(install.InstallError):
                install._layout(Path(tmp) / "nothing")

    def test_steam_library_list_is_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            (steam / "steamapps").mkdir(parents=True)
            (steam / "steamapps" / "libraryfolders.vdf").write_text(
                '"libraryfolders"\n{\n "0"\n {\n  "path"  "/games/SteamLibrary"\n }\n}\n')
            with mock.patch.object(install, "_steam_roots", return_value=[steam]):
                self.assertEqual(install._steam_libraries(), [steam, Path("/games/SteamLibrary")])

    def test_store_installs_only_on_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            with mock.patch.object(install, "_steam_roots", return_value=[steam]):
                (steam / "steamapps").mkdir(parents=True)
                default = [str(c) for c in install.candidates()]
                asked = [str(c) for c in install.candidates(steam=True, gog=True)]
            self.assertFalse(any("steamapps" in c or "GOG" in c for c in default))
            self.assertTrue(any("steamapps" in c for c in asked))
            self.assertTrue(any("GOG" in c for c in asked))
        self.assertEqual(install.store_of("/x/steamapps/common/Factorio/bin/x64/factorio"), "steam")
        self.assertEqual(install.store_of("C:/GOG Games/Factorio"), "gog")
        self.assertEqual(install.store_of("/home/me/factorio"), "")

    def test_mod_dependencies(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            for name, deps in (("base", []), ("quality", ["base >= 2.0.0"]), ("elevated-rails", ["base"]),
                               ("space-age", ["base >= 2.0.0", "elevated-rails >= 2.0.0", "quality >= 2.0.0"])):
                (data / name).mkdir(parents=True)
                (data / name / "info.json").write_text(json.dumps({"name": name, "dependencies": deps}))
            mods = Path(tmp) / "mods"
            mods.mkdir()
            with zipfile.ZipFile(mods / "big-mod_1.2.0.zip", "w") as z:
                z.writestr("big-mod_1.2.0/info.json", json.dumps(
                    {"name": "big-mod", "dependencies": ["base", "lib-mod >= 1", "? optional-mod", "! enemy-mod", "(?) hidden"]}))
            with zipfile.ZipFile(mods / "lib-mod_1.0.0.zip", "w") as z:
                z.writestr("lib-mod_1.0.0/info.json", json.dumps({"name": "lib-mod", "dependencies": ["~ base"]}))
            game = install.Install(binary=data / "x", data=data)
            self.assertEqual(install.with_dependencies(["space-age"], game), ["base", "space-age", "elevated-rails", "quality"])
            self.assertEqual(install.with_dependencies(["big-mod"], game, mods), ["base", "big-mod", "lib-mod"])

    def test_version_notes(self):
        old = install.Install(Path("x"), Path("y"), version=(1, 1, 110))
        from fxa import GAME_TESTED
        new = install.Install(Path("x"), Path("y"), version=(GAME_TESTED[0], GAME_TESTED[1] + 1, 0))
        self.assertIn("too old", install.version_notes(old)[0])
        self.assertIn("selftest", install.version_notes(new)[0])


class FakeGame:
    """Enough of fxa.game.Game for skills that only look and queue orders."""

    def __init__(self, ents, inventory):
        self.ents, self.inventory, self.done = ents, inventory, []

    def call(self, op, **args):
        if op == "entities":
            name = args.get("name")
            return {"entities": [e for e in self.ents if not name or e["name"] == name]}
        if op == "state":
            return self.state()
        if op == "exists":
            return {"exists": {n: True for n in args["names"]}}
        raise AssertionError(op)

    def state(self):
        return {"character": {"x": 0, "y": 0, "inventory": self.inventory}}

    def do(self, orders, max_ticks=36000):
        self.done.append(list(orders))
        return G.Report({"reason": "done", "results": [{"ok": True} for _ in orders]})

    resume = do


class BaseSkillsTest(unittest.TestCase):
    def run_skill(self, name, fake, **params):
        st = layers.stack(None, mods=["base"], game_version="2.0.77")
        return skills.run(st, name, params, fake)

    def test_burners_round(self):
        fake = FakeGame([
            {"name": "burner-mining-drill", "x": 100, "y": 10, "mining": "coal", "fuel": 45},
            {"name": "burner-mining-drill", "x": 100, "y": 20, "mining": "iron-ore", "fuel": 0},
            {"name": "stone-furnace", "x": 100, "y": 18, "fuel": 8,
             "items": {"fuel": {"coal": 8}, "crafter_output": {"iron-plate": 30}}},
            {"name": "stone-furnace", "x": 102, "y": 18, "fuel": 12, "items": {"fuel": {"coal": 12}}},
            {"name": "small-electric-pole", "x": 90, "y": 18},
        ], {"coal": 3})
        result = self.run_skill("burners", fake)
        self.assertEqual(fake.done, [[G.take(100, 10, "coal", 40), G.put(100, 20, "coal", 10),
                                      G.put(100, 18, "coal", 2), G.take(100, 18)]])
        self.assertEqual(result.value["refuelled"], 2)

    def test_turrets_emptiest_first(self):
        fake = FakeGame([
            {"name": "gun-turret", "x": 1, "y": 1, "items": {"turret_ammo": {"firearm-magazine": 12}}},
            {"name": "gun-turret", "x": 2, "y": 2},
            {"name": "gun-turret", "x": 3, "y": 3, "items": {"turret_ammo": {"firearm-magazine": 40}}},
        ], {"firearm-magazine": 100})
        self.run_skill("turrets", fake)
        self.assertEqual(fake.done, [[G.put(2, 2, "firearm-magazine", 40), G.put(1, 1, "firearm-magazine", 28)]])

    def test_params_parse(self):
        self.assertEqual(skills.parse_params(["r=40", "collect=false", "name=iron", "pts=[[1,2]]"]),
                         {"r": 40, "collect": False, "name": "iron", "pts": [[1, 2]]})

    def test_every_shipped_skill_passes_the_check(self):
        for path in sorted(paths.LAYERS.rglob("*.fxs")):
            with self.subTest(skill=path.name):
                self.assertEqual(skills.check_file(path), [])


if __name__ == "__main__":
    unittest.main()
