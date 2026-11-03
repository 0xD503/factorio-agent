"""End-to-end tests against the real game, in a throwaway session.

Run with `fx selftest` (or FXA_LIVE=1 python3 -m unittest tests.test_live). Each
run makes a fresh fixed-seed map in a temporary FXA_HOME, using the configured
server install. Setup may hand out items through the Lua console; that is only
ever done in this test session.
"""

import math
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from fxa import install, savefile, server, session
from fxa.game import (
    Game,
    blueprint,
    craft,
    deconstruct,
    fill,
    ghost,
    limit,
    mine,
    modules,
    place,
    put,
    stamp,
    take,
    unmark,
    upgrade,
    wait,
    walk,
)

SEED = 12345
WALK_SPEED = 0.15  # tiles per tick
ORE_TICKS = 120  # hand-mining one ore
GEAR_TICKS = 30  # hand-crafting one gear
RESPAWN_TICKS = 600


@unittest.skipUnless(
    os.environ.get("FXA_LIVE"), "live tests: run `fx selftest` (needs the game)"
)
class LiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.install = install.configured(
            "server"
        )  # from the user's settings, before FXA_HOME moves
        cls.tmp = tempfile.TemporaryDirectory(prefix="fxa-selftest-")
        cls.env = {
            k: os.environ.get(k)
            for k in ("FXA_HOME", "FXA_SESSION", "FACTORIO_SERVER")
        }
        os.environ.update(
            FXA_HOME=cls.tmp.name,
            FXA_SESSION="",
            FACTORIO_SERVER=str(cls.install.binary),
        )
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
            item = name.replace("_", "-")
            self.lua(
                "storage.agent.character.insert"
                f"{{name='{item}', count={count}}}"
            )

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
        in_wrecks = sum(
            box["items"].get("iron-plate", 0) for box in scan["containers"]
        )
        on_hand = state["character"]["inventory"].get("iron-plate", 0)
        self.assertEqual(in_wrecks + on_hand, 8)
        total_ammo = state["character"]["ammo"].get(
            "firearm-magazine", 0
        ) + sum(
            box["items"].get("firearm-magazine", 0)
            for box in scan["containers"]
        )
        self.assertEqual(total_ammo, 10)

    def test_02_paused_between_calls(self):
        first = self.game.state()["tick"]
        self.assertEqual(self.game.state()["tick"], first)
        report = self.game.run(100)
        self.assertEqual(report.reason, "ticks elapsed")
        self.assertEqual(report.tick - first, 100)
        self.assertEqual(self.game.state()["tick"], report.tick)

    def test_03_only_base_game(self):
        mods = self.lua(
            "local names = {}; for name in pairs(script.active_mods) do "
            "names[#names + 1] = name end;"
            " table.sort(names); rcon.print(table.concat(names, ','))"
        )
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
        report = self.do(
            mine(ore["x"], ore["y"], name="iron-ore", count=3, radius=4)
        )
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
        self.assertEqual(
            self.game.call("entities", x=spot[0], y=spot[1], r=3)["total"], 0
        )

        self.give(stone_furnace=1)
        self.do(place("stone-furnace", *spot))
        self.assertEqual(self.count("stone-furnace"), 0)
        built = self.game.call("entities", x=spot[0], y=spot[1], r=3)[
            "entities"
        ]
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
        self.do(
            put(x, y, "iron-ore", 4),
            wait(item="iron-plate", count=4, x=x, y=y, max=2000),
            take(x, y),
        )
        self.assertEqual(self.count("iron-plate"), 4)
        self.assertEqual(self.count("iron-ore"), 0)
        made = self.game.call("production", names={"iron-plate": True})[
            "items"
        ]["iron-plate"]["made"]
        self.assertEqual(made, 4)

    def test_17_cannot_give_more_than_it_has(self):
        furnace = self.game.call("find", name="stone-furnace")["found"][0]
        failed = self.game.do(put(furnace["x"], furnace["y"], "copper-ore", 5))
        self.assertFalse(failed.ok)
        self.assertIn("no copper-ore", failed.failures[0]["error"])

    def test_18_failure_drops_later_orders(self):
        here = self.character()
        report = self.game.do(
            place("lab", round(here["x"]) + 2, round(here["y"])),
            walk(here["x"] + 30, here["y"]),
        )
        self.assertEqual(report.reason, "order failed")
        self.assertEqual(report.dropped, 1)
        self.assertLess(self.distance_to(here["x"], here["y"]), 1)

    def test_19_machine_orders(self):
        here = self.character()
        x, y = round(here["x"]) + 6.5, round(here["y"]) + 0.5
        self.give(
            fast_inserter=1,
            assembling_machine_2=1,
            chemical_plant=1,
            iron_plate=20,
        )
        # Into the main inventory, as after looting a corpse (given directly, a
        # gun goes to its slot).
        self.lua(
            "storage.agent.character.get_main_inventory()"
            ".insert{name='submachine-gun', count=1}"
        )
        self.do(place("fast-inserter", x, y, "w"))
        self.do({"type": "rotate", "x": x, "y": y, "dir": "s"})
        self.assertEqual(
            self.game.call("entities", x=x, y=y, r=0.5)["entities"][0]["dir"],
            "s",
        )
        self.do({"type": "filter", "x": x, "y": y, "items": ["iron-plate"]})
        self.assertEqual(
            self.game.call("entities", x=x, y=y, r=0.5)["entities"][0].get(
                "filter"
            ),
            "iron-plate",
        )
        ax, ay = x + 4, y + 0.0
        self.do(
            place("assembling-machine-2", ax, ay),
            {"type": "recipe", "x": ax, "y": ay, "recipe": "iron-gear-wheel"},
        )
        self.assertEqual(
            self.game.call("entities", x=ax, y=ay, r=1)["entities"][0][
                "recipe"
            ],
            "iron-gear-wheel",
        )
        cx, cy = x + 4, y + 5
        self.do(
            place("chemical-plant", cx, cy, recipe="lubricant"),
            {"type": "mirror", "x": cx, "y": cy},
        )
        self.do({"type": "equip", "item": "submachine-gun"})
        self.assertIn("submachine-gun", self.game.state()["character"]["guns"])
        plates = self.count("iron-plate")
        self.do(craft("iron-gear-wheel", 5))
        self.do({"type": "uncraft", "recipe": "iron-gear-wheel"})
        self.assertEqual(self.count("iron-plate"), plates)
        self.do({"type": "pickup", "ticks": 10})

    # -- planning: limits, ghosts, blueprints, robots --------------------------

    def ent(self, x, y, name=None):
        args = {"x": x, "y": y, "r": 0.4}
        if name:
            args["name"] = name
        found = self.game.call("entities", **args)["entities"]
        return found[0] if found else None

    def plan_site(self):
        """Open ground near the character: scenery cleared by hand, which only
        this test session may do."""
        here = self.character()
        x, y = round(here["x"]) + 0.5, round(here["y"]) + 12.5
        self.lua(
            "for _, e in pairs(game.surfaces[1].find_entities_filtered{"
            f"area={{{{{x - 30},{y - 30}}},{{{x + 100},{y + 50}}}}}, "
            "type={'tree','simple-entity'}}) do e.destroy() end"
        )
        return x, y

    def test_22_chest_limit(self):
        x, y = self.plan_site()
        self.give(wooden_chest=1)
        self.do(place("wooden-chest", x, y))
        self.do(limit(x, y, 2))
        self.assertEqual(self.ent(x, y)["limit"], 2)
        self.do(limit(x, y))
        self.assertNotIn("limit", self.ent(x, y))
        self.do(mine(x, y))

    def test_23_ghosts_need_no_item_or_reach(self):
        x, y = self.plan_site()
        before = self.character()
        self.assertEqual(self.count("assembling-machine-1"), 0)
        self.do(
            ghost("assembling-machine-1", x, y, recipe="iron-gear-wheel"),
            ghost("underground-belt", x + 4, y, "e", ug_type="output"),
        )
        self.assertEqual(self.character()["x"], before["x"])
        machine = self.ent(x, y, "entity-ghost")
        self.assertEqual(machine["ghost"], "assembling-machine-1")
        self.assertEqual(machine["recipe"], "iron-gear-wheel")
        self.assertEqual(self.ent(x + 4, y)["ghost"], "underground-belt")
        self.assertEqual(self.game.call("bots")["ghosts"], 2)
        report = self.game.do(ghost("lab", 100000.5, 100000.5))
        self.assertFalse(report.ok)
        self.do(deconstruct(x - 3, y - 3, x + 6, y + 3, "entity-ghost"))
        self.assertEqual(self.game.call("bots")["ghosts"], 0)

    def test_24_placing_on_a_ghost_replaces_it(self):
        x, y = self.plan_site()
        self.give(inserter=1)
        self.do(ghost("inserter", x, y, "e"), place("inserter", x, y, "e"))
        self.assertEqual(self.ent(x, y)["name"], "inserter")
        self.assertEqual(self.game.call("bots")["ghosts"], 0)
        self.do(mine(x, y))

    def test_25_blueprint_stamps_at_the_exact_offset(self):
        x, y = self.plan_site()
        self.give(
            wooden_chest=1,
            assembling_machine_1=1,
            inserter=1,
            transport_belt=2,
            underground_belt=2,
            stone_furnace=1,
        )
        self.do(
            place("assembling-machine-1", x, y, recipe="iron-gear-wheel"),
            place("inserter", x + 2, y, "w"),
            place("wooden-chest", x + 3, y),
            limit(x + 3, y, 3),
            place("transport-belt", x - 2, y + 3, "e"),
            place("underground-belt", x - 1, y + 3, "e", ug_type="input"),
            place("underground-belt", x + 2, y + 3, "e", ug_type="output"),
            place("stone-furnace", x + 4.5, y + 3.5),
        )
        area = (x - 3, y - 2, x + 6, y + 5)
        report = self.do(blueprint("cell", *area))
        self.assertEqual(report.results[0]["info"]["entities"], 7)
        dx, dy = 20, 3
        self.do(stamp("cell", area[0] + dx, area[1] + dy))
        machine = self.ent(x + dx, y + dy, "entity-ghost")
        self.assertEqual(machine["ghost"], "assembling-machine-1")
        self.assertEqual(machine["recipe"], "iron-gear-wheel")
        self.assertEqual(self.ent(x + 2 + dx, y + dy)["dir"], "w")
        self.assertEqual(
            self.ent(x + 4.5 + dx, y + 3.5 + dy, "entity-ghost")["ghost"],
            "stone-furnace",
        )
        self.assertEqual(self.game.call("bots")["ghosts"], 7)

        # By hand: what is in the inventory gets built, the rest is reported.
        self.give(
            wooden_chest=1,
            assembling_machine_1=1,
            transport_belt=1,
            underground_belt=2,
            stone_furnace=1,
        )
        self.lua(
            "storage.agent.character.remove_item{name='inserter', count=1000}"
        )
        report = self.do(
            fill(area[0] + dx, area[1] + dy, area[2] + dx, area[3] + dy)
        )
        result = report.results[0]["info"]
        self.assertEqual(result["built"], 6)
        self.assertEqual(result["missing"], {"inserter": 1})
        built = self.ent(x + dx, y + dy, "assembling-machine-1")
        self.assertEqual(built["recipe"], "iron-gear-wheel")
        self.assertEqual(self.ent(x + 3 + dx, y + dy)["limit"], 3)
        self.assertEqual(self.ent(x + 2 + dx, y + 3 + dy)["ug"], "output")
        self.assertEqual(self.count("assembling-machine-1"), 0)
        self.assertEqual(self.game.call("bots")["ghosts"], 1)

        # Turned, the area's corner stays at the position given.
        self.do(stamp("cell", x + 60.5, y, "e"))
        belt = self.game.call(
            "entities", x=x + 57, y=y + 2, r=9, name="entity-ghost"
        )["entities"]
        directions = {e["dir"] for e in belt if e["ghost"] == "transport-belt"}
        self.assertEqual(directions, {"s"})
        self.do(
            deconstruct(x + 40, y - 10, x + 70, y + 20, "entity-ghost"),
            deconstruct(
                area[0] + dx,
                area[1] + dy,
                area[2] + dx,
                area[3] + dy,
                "entity-ghost",
            ),
        )
        self.assertFalse(self.game.do(stamp("nothing-here", x, y)).ok)
        self.assertFalse(
            self.game.do(blueprint("../bad", *area)).ok,
        )

    def test_26_marks_for_robots(self):
        x, y = self.plan_site()
        self.give(
            transport_belt=2,
            lab=1,
            speed_module=2,
        )
        self.do(
            place("transport-belt", x, y, "e"),
            place("transport-belt", x + 1, y, "e"),
            place("lab", x, y + 3),
        )
        area = (x - 2, y - 1, x + 3, y + 1)
        self.assertEqual(
            self.do(
                upgrade(*area, "transport-belt", "fast-transport-belt")
            ).results[0]["info"]["marked"],
            2,
        )
        self.assertEqual(self.ent(x, y)["marked"], "upgrade")
        self.assertEqual(
            self.do(unmark(*area)).results[0]["info"]["cleared"], 2
        )
        self.assertNotIn("marked", self.ent(x, y))
        self.assertEqual(
            self.do(deconstruct(*area)).results[0]["info"]["marked"], 2
        )
        self.assertEqual(self.ent(x, y)["marked"], "deconstruct")
        self.assertEqual(self.game.call("bots")["deconstruct"], 2)
        self.assertEqual(
            self.do(unmark(*area)).results[0]["info"]["cleared"], 2
        )
        report = self.do(
            modules(x - 3, y + 1, x + 3, y + 5, "speed-module", "lab")
        )
        self.assertEqual(report.results[0]["info"]["machines"], 1)
        self.assertEqual(report.results[0]["info"]["modules"], 2)
        self.assertEqual(
            self.game.call("find", name="item-request-proxy", r=300)["found"][
                0
            ]["x"],
            x,
        )
        self.assertFalse(
            self.game.do(modules(*area, "iron-plate")).ok,
        )

    def test_27_robots_build_a_stamp(self):
        x, y = self.plan_site()
        # Power for the roboport, set up by hand: only in this test session.
        self.lua(
            "local s = game.surfaces[1]; "
            f"local e = s.create_entity{{name='electric-energy-interface', "
            f"position={{{x - 6},{y}}}, force='player'}}; "
            "e.electric_buffer_size = 1e9; e.power_production = 1e7"
        )
        self.give(
            roboport=1,
            storage_chest=1,
            small_electric_pole=1,
            construction_robot=5,
            inserter=3,
        )
        self.do(
            place("small-electric-pole", x - 3, y),
            place("roboport", x, y),
            place("storage-chest", x + 3, y),
            put(x + 3, y, "inserter", 3),
            take(x + 3, y, "inserter", 1),
            put(x + 3, y, "inserter", 1),
            put(x, y, "construction-robot", 5),
        )
        self.do(ghost("inserter", x + 5, y + 5, "e"))
        self.do(ghost("inserter", x + 70.5, y, "e"))
        bots = self.game.call("bots")
        self.assertEqual(bots["out_of_range"], 1)
        self.assertEqual(len(bots["networks"]), 1)
        self.game.run(1200)
        self.assertEqual(
            self.ent(x + 5, y + 5, "inserter")["name"],
            "inserter",
        )
        self.do(deconstruct(x + 69, y - 1, x + 72, y + 1, "entity-ghost"))
        self.assertEqual(self.game.call("bots")["ghosts"], 0)

        # Marks: robots really remove, replace and fill, using the network's
        # items.
        self.give(
            transport_belt=2,
            fast_transport_belt=1,
            lab=1,
            speed_module=4,
        )
        self.do(
            place("transport-belt", x + 8, y + 8, "e"),
            place("transport-belt", x + 10, y + 8, "e"),
            place("lab", x + 3, y + 8),
            put(x + 3, y, "fast-transport-belt", 1),
            # Two for the lab of the marks test, whose request is still open.
            put(x + 3, y, "speed-module", 4),
            deconstruct(x + 7.5, y + 7.5, x + 8.5, y + 8.5),
            upgrade(
                x + 9.5,
                y + 7.5,
                x + 10.5,
                y + 8.5,
                "transport-belt",
                "fast-transport-belt",
            ),
            modules(x + 1, y + 6, x + 5, y + 10, "speed-module"),
        )
        self.game.run(1800)
        self.assertIsNone(self.ent(x + 8, y + 8, "transport-belt"))
        self.assertEqual(self.ent(x + 10, y + 8)["name"], "fast-transport-belt")
        lab = self.ent(x + 3, y + 8, "lab")
        self.assertEqual(lab["items"]["lab_modules"], {"speed-module": 2})

    # -- what the agent may see ----------------------------------------------

    def test_20_unseen_chunks_are_hidden(self):
        far = self.game.call("map", x=2000, y=2000, w=8, h=4)
        self.assertEqual(far["rows"], ["?" * 8] * 4)
        self.lua(
            "game.surfaces.nauvis.request_to_generate_chunks({2000, 2000}, 1);"
            " game.surfaces.nauvis.force_generate_chunk_requests();"
            " game.surfaces.nauvis.create_entity{name='stone-furnace', "
            "position={2000, 2000}, force='player'}"
        )
        self.assertEqual(
            self.game.call("find", name="stone-furnace", x=2000, y=2000, r=50)[
                "found"
            ],
            {},
        )
        self.assertEqual(
            self.game.call("entities", x=2000, y=2000, r=50)["total"], 0
        )

    def test_21_map_shows_the_character(self):
        rows = self.game.call("map", w=9, h=9)["rows"]
        self.assertIn("@", "".join(rows))

    # -- things the game does for a player and we do for the character --------

    def test_30_hand_crafted_lab_unlocks_science(self):
        self.lua(
            "local f = game.forces.player; "
            "f.technologies['electronics'].researched = true;"
            " f.technologies['steam-power'].researched = true"
        )
        self.assertFalse(
            self.game.call("tech", name="automation-science-pack")["researched"]
        )
        self.give(electronic_circuit=10, iron_gear_wheel=10, transport_belt=4)
        report = self.game.do(craft("lab", 1, wait=True))
        self.assertTrue(report.results[0]["ok"], str(report))
        self.assertTrue(
            self.game.call("tech", name="automation-science-pack")["researched"]
        )
        self.assertIn(
            "automation-science-pack", [e.get("name") for e in report.events]
        )
        self.assertEqual(
            self.game.call("production", names={"lab": True})["items"]["lab"][
                "made"
            ],
            1,
        )

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
        self.console.command(
            "hello tester, are you there?"
        )  # a chat line from the server console
        self.console.command("unrelated line")
        lines, _ = self.game.chat(since=seq)
        self.assertEqual(
            [(l["from"], l.get("mention", False)) for l in lines],
            [("<server>", True), ("<server>", False)],
        )
        line = self.game.say("yes, here")
        self.assertTrue(line["self"])
        self.assertIn(
            "Tester: yes, here", (self.session.dir / "chat.log").read_text()
        )
        with self.assertRaises(Exception):
            self.game.say("hi", to="nobody")

    def test_51_mention_interrupts_and_reports_chat(self):
        self.console.command("tester stop that")
        report = self.game.run(60)
        self.assertEqual(report.reason, "chat")
        self.assertIn("tester stop that", [l["text"] for l in report.chat])

    def test_52_players_and_batch(self):
        self.assertEqual(self.game.players(), [])
        replies = self.game.batch(
            ("status", {}),
            ("exists", {"names": ["iron-plate", "no-such-thing"]}),
            ("nope", {}),
        )
        self.assertTrue(replies[0]["ok"])
        self.assertEqual(
            replies[1]["exists"], {"iron-plate": True, "no-such-thing": False}
        )
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
        self.assertLessEqual(
            {
                "control.lua",
                "agent/main.lua",
                "agent/orders.lua",
                "agent/social.lua",
            },
            inner,
        )

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
        self.assertEqual(
            after["character"]["inventory"], before["character"]["inventory"]
        )
        self.assertEqual(after["deaths"], before["deaths"])


if __name__ == "__main__":
    unittest.main()
