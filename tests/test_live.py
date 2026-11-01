"""End-to-end tests against the real game, in a throwaway session.

Run with `fx selftest` (or FXA_LIVE=1 python3 -m unittest tests.test_live). Each run makes a
fresh fixed-seed map in a temporary FXA_HOME, using the configured server install. Setup may
hand out items through the Lua console; that is only ever done in this test session.
"""

import math
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from fxa import install, savefile, server, session
from fxa.game import Game, craft, mine, place, put, take, wait, walk

SEED = 12345
WALK_SPEED = 0.15       # tiles per tick
ORE_TICKS = 120         # hand-mining one ore
GEAR_TICKS = 30         # hand-crafting one gear
RESPAWN_TICKS = 600


@unittest.skipUnless(os.environ.get("FXA_LIVE"), "live tests: run `fx selftest` (needs the game)")
class LiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install = install.configured("server")          # from the user's settings, before FXA_HOME moves
        cls.tmp = tempfile.TemporaryDirectory(prefix="fxa-selftest-")
        cls.env = {k: os.environ.get(k) for k in ("FXA_HOME", "FXA_SESSION", "FACTORIO_SERVER")}
        os.environ.update(FXA_HOME=cls.tmp.name, FXA_SESSION="", FACTORIO_SERVER=str(cls.install.binary))
        cls.session = session.create("selftest", agent_name="Tester", seed=SEED)
        cls.srv = server.Server(cls.session)
        cls.srv.create_map(cls.install, "live", seed=SEED)
        cls.srv.start(cls.install, "live")
        cls.game = Game(cls.srv.target(), cls.session)
        cls.console = cls.srv.target().connect()
        # The first console command on a map only prints a warning.
        cls.console.lua("rcon.print(1)")
        cls.game.call("configure", mode="solo", name="Tester")
        cls.started = cls.game.call("start")
        cls.game.run(120)

    @classmethod
    def tearDownClass(cls):
        cls.game.close()
        cls.console.close()
        cls.srv.stop()
        for key, value in cls.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.tmp.cleanup()

    def lua(self, code):
        return self.console.lua(code).strip()

    def give(self, **items):
        for name, count in items.items():
            self.lua(f"storage.agent.character.insert{{name='{name.replace('_', '-')}', count={count}}}")

    def character(self):
        return self.game.state()["character"]

    def count(self, item):
        return self.character()["inventory"].get(item, 0)

    def nearest(self, name):
        found = self.game.call("find", name=name, r=300)["found"]
        self.assertTrue(found, f"no {name} on the map")
        return found[0]

    def distance_to(self, x, y):
        ch = self.character()
        return math.hypot(ch["x"] - x, ch["y"] - y)

    def do(self, *orders):
        report = self.game.do(*orders)
        self.assertTrue(report.ok, str(report))
        return report

    # -- setup and time ----------------------------------------------------

    def test_01_starts_like_freeplay(self):
        self.assertTrue(self.started.get("started"))
        state = self.game.call("state")
        self.assertEqual(state["character"]["guns"], {"pistol": 1})
        scan = self.game.call("scan", x=0, y=0, r=60)
        in_wrecks = sum(box["items"].get("iron-plate", 0) for box in scan["containers"])
        on_hand = state["character"]["inventory"].get("iron-plate", 0)
        self.assertEqual(in_wrecks + on_hand, 8)
        total_ammo = state["character"]["ammo"].get("firearm-magazine", 0) + sum(
            box["items"].get("firearm-magazine", 0) for box in scan["containers"])
        self.assertEqual(total_ammo, 10)

    def test_02_paused_between_calls(self):
        first = self.game.state()["tick"]
        self.assertEqual(self.game.state()["tick"], first)
        report = self.game.run(100)
        self.assertEqual(report.reason, "ticks elapsed")
        self.assertEqual(report.tick - first, 100)
        self.assertEqual(self.game.state()["tick"], report.tick)

    def test_03_only_base_game(self):
        mods = self.lua("local names = {}; for name in pairs(script.active_mods) do names[#names + 1] = name end;"
                        " table.sort(names); rcon.print(table.concat(names, ','))")
        self.assertEqual(mods, "base")

    # -- actions cost what they cost a player --------------------------------

    def test_10_walking_takes_time(self):
        start = self.character()
        report = self.do(walk(start["x"] + 15, start["y"]))
        self.assertGreaterEqual(report.results[0]["ticks"], 14 / WALK_SPEED)
        self.assertLess(self.distance_to(start["x"] + 15, start["y"]), 1)

    def test_11_mining_ore_takes_time_and_reach(self):
        ore = self.nearest("iron-ore")
        before = self.count("iron-ore")
        report = self.do(mine(ore["x"], ore["y"], name="iron-ore", count=3, radius=4))
        self.assertEqual(self.count("iron-ore") - before, 3)
        self.assertGreaterEqual(report.results[0]["ticks"], 3 * ORE_TICKS)
        self.assertLess(self.distance_to(ore["x"], ore["y"]), 4 + 2.7)

    def test_12_mining_a_tree_gives_wood(self):
        scan = self.game.call("scan", r=150)
        x, y = scan["trees"]["nearest"]
        before = self.count("wood")
        self.do(mine(x, y, kind="tree", count=1, radius=3))
        self.assertGreater(self.count("wood"), before)

    def test_13_crafting_needs_ingredients_and_time(self):
        self.lua("storage.agent.character.clear_items_inside()")
        failed = self.game.do(craft("iron-gear-wheel", 2))
        self.assertFalse(failed.ok)
        self.assertEqual(self.count("iron-gear-wheel"), 0)

        self.give(iron_plate=4)
        report = self.do(craft("iron-gear-wheel", 2, wait=True))
        self.assertEqual(self.count("iron-gear-wheel"), 2)
        self.assertEqual(self.count("iron-plate"), 0)
        self.assertGreaterEqual(report.results[0]["ticks"], 2 * GEAR_TICKS)

    def test_14_placing_needs_the_item(self):
        here = self.character()
        spot = (round(here["x"]) + 3, round(here["y"]) + 3)
        failed = self.game.do(place("stone-furnace", *spot))
        self.assertFalse(failed.ok)
        self.assertIn("no stone-furnace", failed.failures[0]["error"])
        self.assertEqual(self.game.call("entities", x=spot[0], y=spot[1], r=3)["total"], 0)

        self.give(stone_furnace=1)
        self.do(place("stone-furnace", *spot))
        self.assertEqual(self.count("stone-furnace"), 0)
        built = self.game.call("entities", x=spot[0], y=spot[1], r=3)["entities"]
        self.assertEqual([e["name"] for e in built], ["stone-furnace"])

    def test_15_far_actions_walk_into_reach_first(self):
        furnace = self.game.call("find", name="stone-furnace")["found"][0]
        self.give(coal=5, iron_ore=4)
        self.do(walk(furnace["x"] + 40, furnace["y"]))
        self.assertGreater(self.distance_to(furnace["x"], furnace["y"]), 30)
        report = self.do(put(furnace["x"], furnace["y"], "coal", 5))
        self.assertGreaterEqual(report.results[0]["ticks"], 25 / WALK_SPEED)
        self.assertLessEqual(self.distance_to(furnace["x"], furnace["y"]), 11)
        self.assertEqual(self.count("coal"), 0)

    def test_16_smelting_and_collecting(self):
        furnace = self.game.call("find", name="stone-furnace")["found"][0]
        x, y = furnace["x"], furnace["y"]
        self.do(put(x, y, "iron-ore", 4), wait(item="iron-plate", count=4, x=x, y=y, max=2000), take(x, y))
        self.assertEqual(self.count("iron-plate"), 4)
        self.assertEqual(self.count("iron-ore"), 0)
        made = self.game.call("production", names={"iron-plate": True})["items"]["iron-plate"]["made"]
        self.assertEqual(made, 4)

    def test_17_cannot_give_more_than_it_has(self):
        furnace = self.game.call("find", name="stone-furnace")["found"][0]
        failed = self.game.do(put(furnace["x"], furnace["y"], "copper-ore", 5))
        self.assertFalse(failed.ok)
        self.assertIn("no copper-ore", failed.failures[0]["error"])

    def test_18_failure_drops_later_orders(self):
        here = self.character()
        report = self.game.do(place("lab", round(here["x"]) + 2, round(here["y"])), walk(here["x"] + 30, here["y"]))
        self.assertEqual(report.reason, "order failed")
        self.assertEqual(report.dropped, 1)
        self.assertLess(self.distance_to(here["x"], here["y"]), 1)

    # -- what the agent may see ----------------------------------------------

    def test_20_unseen_chunks_are_hidden(self):
        far = self.game.call("map", x=2000, y=2000, w=8, h=4)
        self.assertEqual(far["rows"], ["?" * 8] * 4)
        self.lua("game.surfaces.nauvis.request_to_generate_chunks({2000, 2000}, 1);"
                 " game.surfaces.nauvis.force_generate_chunk_requests();"
                 " game.surfaces.nauvis.create_entity{name='stone-furnace', position={2000, 2000}, force='player'}")
        self.assertEqual(self.game.call("find", name="stone-furnace", x=2000, y=2000, r=50)["found"], {})
        self.assertEqual(self.game.call("entities", x=2000, y=2000, r=50)["total"], 0)

    def test_21_map_shows_the_character(self):
        rows = self.game.call("map", w=9, h=9)["rows"]
        self.assertIn("@", "".join(rows))

    # -- things the game does for a player and we do for the character --------

    def test_30_hand_crafted_lab_unlocks_science(self):
        self.lua("local f = game.forces.player; f.technologies['electronics'].researched = true;"
                 " f.technologies['steam-power'].researched = true")
        self.assertFalse(self.game.call("tech", name="automation-science-pack")["researched"])
        self.give(electronic_circuit=10, iron_gear_wheel=10, transport_belt=4)
        report = self.game.do(craft("lab", 1, wait=True))
        self.assertTrue(report.results[0]["ok"], str(report))
        self.assertTrue(self.game.call("tech", name="automation-science-pack")["researched"])
        self.assertIn("automation-science-pack", [e.get("name") for e in report.events])
        self.assertEqual(self.game.call("production", names={"lab": True})["items"]["lab"]["made"], 1)

    def test_31_death_and_respawn(self):
        self.lua("storage.agent.character.die()")
        report = self.game.do(walk(5, 5))
        self.assertEqual(report.reason, "character died")
        self.assertTrue(report.state.get("dead"))
        report = self.game.run(RESPAWN_TICKS + 5)
        self.assertEqual(report.reason, "character respawned")
        state = self.game.state()
        self.assertEqual(state["deaths"], 1)
        self.assertEqual(state["character"]["guns"], {"pistol": 1})
        self.assertEqual(state["character"]["ammo"], {"firearm-magazine": 10})

    # -- multiplayer -----------------------------------------------------------

    def test_50_chat_in_and_out(self):
        _, seq = self.game.chat(since=10**9)
        self.console.command("hello tester, are you there?")          # a chat line from the server console
        self.console.command("unrelated line")
        lines, _ = self.game.chat(since=seq)
        self.assertEqual([(l["from"], l.get("mention", False)) for l in lines], [("<server>", True), ("<server>", False)])
        line = self.game.say("yes, here")
        self.assertTrue(line["self"])
        self.assertIn("Tester: yes, here", (self.session.dir / "chat.log").read_text())
        with self.assertRaises(Exception):
            self.game.say("hi", to="nobody")

    def test_51_mention_interrupts_and_reports_chat(self):
        self.console.command("tester stop that")
        report = self.game.run(60)
        self.assertEqual(report.reason, "chat")
        self.assertIn("tester stop that", [l["text"] for l in report.chat])

    def test_52_players_and_batch(self):
        self.assertEqual(self.game.players(), [])
        replies = self.game.batch(("status", {}), ("exists", {"names": ["iron-plate", "no-such-thing"]}), ("nope", {}))
        self.assertTrue(replies[0]["ok"])
        self.assertEqual(replies[1]["exists"], {"iron-plate": True, "no-such-thing": False})
        self.assertFalse(replies[2]["ok"])

    def test_53_coop_runs_in_real_time(self):
        self.game.call("configure", mode="coop")
        try:
            first = self.game.state()["tick"]
            time.sleep(1.0)
            self.assertGreater(self.game.state()["tick"] - first, 30)
            with self.assertRaises(Exception):
                self.game.call("speed", speed=8)
            here = self.character()
            report = self.game.do(walk(here["x"] + 5, here["y"]))
            self.assertEqual(report.reason, "done")
        finally:
            self.game.call("configure", mode="solo")
        first = self.game.state()["tick"]
        time.sleep(0.5)
        self.assertEqual(self.game.state()["tick"], first)

    def test_54_save_names_are_checked_in_game_too(self):
        for bad in ("../escape", "a/b", "..", ""):
            with self.subTest(bad=bad), self.assertRaises(Exception):
                self.game.call("save", name=bad)

    # -- saves ----------------------------------------------------------------

    def test_40_checkpoint_carries_the_scripts(self):
        path = self.game.save("checkpoint")
        self.assertEqual(path, self.session.save_path("checkpoint"))
        with zipfile.ZipFile(path) as archive:
            inner = {name.split("/", 1)[1] for name in archive.namelist()}
        self.assertLessEqual({"control.lua", "agent/main.lua", "agent/orders.lua", "agent/social.lua"}, inner)

    def test_41_script_swap_keeps_the_game(self):
        self.give(wood=7)
        before = self.game.state()
        type(self).game.close()
        type(self).console.close()
        self.srv.stop()
        savefile.inject(self.session.save_path("live"))
        self.srv.start(self.install, "live")
        type(self).game = Game(self.srv.target(), self.session)
        type(self).console = self.srv.target().connect()
        after = self.game.state()
        self.assertEqual(after["tick"], before["tick"])
        self.assertEqual(after["character"]["inventory"], before["character"]["inventory"])
        self.assertEqual(after["deaths"], before["deaths"])


if __name__ == "__main__":
    unittest.main()
