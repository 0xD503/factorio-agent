"""Tests that need no game: order syntax, save patching, text output."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from fxa import dsl, fmt, game, savefile


class DslTest(unittest.TestCase):
    def test_sequence(self):
        self.assertEqual(
            dsl.parse("walk 3 -4.5; craft iron-gear-wheel 2 wait ;"),
            [game.walk(3, -4.5), game.craft("iron-gear-wheel", 2, wait=True)],
        )

    def test_mine_forms(self):
        self.assertEqual(dsl.parse("mine 10 20"), [game.mine(10, 20)])
        self.assertEqual(
            dsl.parse("mine iron-ore 10 20 x5 r6"),
            [game.mine(10, 20, name="iron-ore", count=5, radius=6)],
        )
        self.assertEqual(
            dsl.parse("mine tree -4 42 x3"),
            [game.mine(-4, 42, kind="tree", count=3)],
        )

    def test_place_options(self):
        self.assertEqual(
            dsl.parse(
                "place assembling-machine-1 1.5 2.5 recipe=iron-gear-wheel"
            ),
            [
                game.place(
                    "assembling-machine-1", 1.5, 2.5, recipe="iron-gear-wheel"
                )
            ],
        )
        self.assertEqual(
            dsl.parse("place underground-belt 0.5 0.5 e ug=output"),
            [
                game.place(
                    "underground-belt", 0.5, 0.5, dir="e", ug_type="output"
                )
            ],
        )

    def test_planning_orders(self):
        self.assertEqual(dsl.parse("limit 1 2 3"), [game.limit(1, 2, 3)])
        self.assertEqual(dsl.parse("limit 1 2"), [game.limit(1, 2)])
        self.assertEqual(
            dsl.parse("ghost underground-belt 1 2 e ug=output"),
            [game.ghost("underground-belt", 1, 2, "e", ug_type="output")],
        )
        self.assertEqual(
            dsl.parse("blueprint cell 1 2 3 4; stamp cell 5 6 w"),
            [game.blueprint("cell", 1, 2, 3, 4), game.stamp("cell", 5, 6, "w")],
        )
        self.assertEqual(dsl.parse("fill 1 2 3 4"), [game.fill(1, 2, 3, 4)])
        self.assertEqual(
            dsl.parse("deconstruct 1 2 3 4 tree"),
            [game.deconstruct(1, 2, 3, 4, "tree")],
        )
        self.assertEqual(
            dsl.parse("upgrade 1 2 3 4 a b"),
            [game.upgrade(1, 2, 3, 4, "a", "b")],
        )
        self.assertEqual(
            dsl.parse("modules 1 2 3 4 m lab"),
            [game.modules(1, 2, 3, 4, "m", "lab")],
        )
        self.assertEqual(dsl.parse("unmark 1 2 3 4"), [game.unmark(1, 2, 3, 4)])
        with self.assertRaises(dsl.ParseError):
            dsl.parse("fill 1 2 3")

    def test_bots_view(self):
        text = fmt.bots(
            {
                "networks": [
                    {
                        "at": [1, 2],
                        "roboports": 3,
                        "construction": 10,
                        "construction_free": 4,
                        "logistic": 0,
                        "logistic_free": 0,
                    }
                ],
                "ghosts": 5,
                "deconstruct": 1,
                "upgrade": 0,
                "out_of_range": 2,
                "out_of_range_at": [[7, 8]],
                "waiting": {"lab": 2},
                "blueprints": [
                    {"name": "cell", "entities": 9, "width": 8, "height": 4}
                ],
            }
        )
        self.assertIn("3 roboports, construction 4/10 free", text)
        self.assertIn("ghosts out of range: 2 at (7,8)", text)
        self.assertIn("no item in their network: lab 2", text)
        self.assertIn("blueprint cell: 9 entities, 8x4", text)
        self.assertEqual(
            fmt.bots(
                {"ghosts": 0, "deconstruct": 0, "upgrade": 0}
            ).splitlines()[0],
            "no robot networks",
        )

    def test_put_take_wait(self):
        self.assertEqual(dsl.parse("put 1 2 coal"), [game.put(1, 2, "coal")])
        self.assertEqual(
            dsl.parse("put 1 2 coal 5"), [game.put(1, 2, "coal", 5)]
        )
        self.assertEqual(dsl.parse("take 1 2"), [game.take(1, 2)])
        self.assertEqual(
            dsl.parse("take 1 2 iron-plate 7"),
            [game.take(1, 2, "iron-plate", 7)],
        )
        self.assertEqual(dsl.parse("wait 60"), [game.wait(ticks=60)])
        self.assertEqual(dsl.parse("wait craft"), [game.wait(craft=True)])
        self.assertEqual(
            dsl.parse("wait have wood 4"), [game.wait(have="wood", count=4)]
        )
        self.assertEqual(
            dsl.parse("wait item 1 2 iron-plate 5"),
            [game.wait(item="iron-plate", count=5, x=1, y=2)],
        )

    def test_filter(self):
        self.assertEqual(
            dsl.parse("filter 1.5 2.5 iron-plate coal"),
            [game.filter(1.5, 2.5, "iron-plate", "coal")],
        )
        self.assertEqual(dsl.parse("filter 1.5 2.5")[0]["items"], [])

    def test_whole_numbers_stay_integers(self):
        order = dsl.parse("walk 3 4.5")[0]
        self.assertIsInstance(order["x"], int)
        self.assertIsInstance(order["y"], float)

    def test_errors(self):
        for text in (
            "dance 1 2",
            "walk 1",
            "walk a b",
            "walk 1 2 3",
            "craft gear 0",
            "put 1 2",
            "place belt 1",
        ):
            with self.subTest(text=text), self.assertRaises(dsl.ParseError):
                dsl.parse(text)

    def test_unset_fields_are_omitted(self):
        self.assertEqual(
            game.place("pipe", 1, 2),
            {"type": "place", "item": "pipe", "x": 1, "y": 2},
        )


class InjectTest(unittest.TestCase):
    def make_save(self, folder):
        path = Path(folder) / "renamed.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("original/control.lua", "require('stock')")
            archive.writestr("original/level.dat0", b"\x00\x01map")
            archive.writestr(
                "original/claude/gone.lua", "-- from the first version"
            )
            archive.writestr(
                "original/agent/stale.lua", "-- from an older build"
            )
            archive.writestr("original/locale/en/freeplay.cfg", "x=y")
        return path

    def make_lua(self, folder):
        lua = Path(folder) / "lua"
        (lua / "agent").mkdir(parents=True)
        (lua / "control.lua").write_text("require('agent.main')")
        (lua / "agent" / "main.lua").write_text("return {}")
        return lua

    def test_replaces_scripts_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_save(folder)
            replaced = savefile.inject(path, self.make_lua(folder))
            self.assertEqual(replaced, ["agent/main.lua", "control.lua"])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    [
                        "original/agent/main.lua",
                        "original/control.lua",
                        "original/level.dat0",
                        "original/locale/en/freeplay.cfg",
                    ],
                )
                self.assertEqual(
                    archive.read("original/control.lua"),
                    b"require('agent.main')",
                )
                self.assertEqual(
                    archive.read("original/level.dat0"), b"\x00\x01map"
                )
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_repeatable(self):
        with tempfile.TemporaryDirectory() as folder:
            path, lua = self.make_save(folder), self.make_lua(folder)
            savefile.inject(path, lua)
            savefile.inject(path, lua)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(
                    len(archive.namelist()), len(set(archive.namelist()))
                )

    def test_needs_control_lua(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_save(folder)
            empty = Path(folder) / "empty"
            empty.mkdir()
            with self.assertRaises(savefile.SaveError):
                savefile.inject(path, empty)

    def test_copy_to_another_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_save(folder)
            out = Path(folder) / "hosted.zip"
            savefile.inject(path, self.make_lua(folder), target=out)
            self.assertTrue(savefile.has_agent(out))
            with zipfile.ZipFile(path) as archive:
                self.assertIn(
                    "original/claude/gone.lua", archive.namelist()
                )  # source untouched


class FormatTest(unittest.TestCase):
    def test_items(self):
        self.assertEqual(fmt.items({"wood": 3, "coal": 12}), "coal 12, wood 3")
        self.assertEqual(fmt.items({}), "-")
        self.assertEqual(fmt.items({"iron-ore": 378000}), "iron-ore 378k")

    def test_changes(self):
        self.assertEqual(
            fmt.changes({"wood": -2, "coal": 5}), "coal +5, wood -2"
        )

    def test_empty_lua_array(self):
        self.assertEqual(fmt.seq({}), [])
        self.assertEqual(fmt.seq([1]), [1])

    def test_tile_map_ruler_lines_up(self):
        text = fmt.tile_map(
            {"x": -12, "y": 5, "w": 25, "h": 2, "rows": ["." * 25, "." * 25]}
        )
        ruler, first, second = text.split("\n")
        self.assertEqual(ruler.index("-10"), first.index(".") + 2)
        self.assertEqual(
            ruler.index("10", ruler.index("-10") + 3), first.index(".") + 22
        )
        self.assertTrue(first.startswith("    5 "))
        self.assertTrue(second.startswith("    6 "))

    def test_report(self):
        rep = game.Report(
            {
                "tick": 90,
                "reason": "order failed",
                "dropped": 2,
                "results": [
                    {
                        "n": 1,
                        "type": "walk",
                        "ok": True,
                        "ticks": 30,
                        "info": {"x": 1.5, "y": 2},
                    },
                    {
                        "n": 2,
                        "type": "place",
                        "ok": False,
                        "error": "no pipe in inventory",
                    },
                ],
                "events": [{"type": "damaged", "tick": 80, "health": 200}],
                "state": {"x": 1.5, "y": 2, "health": 200, "crafting": 0},
                "changed": {"wood": -1},
            }
        )
        self.assertFalse(rep.ok)
        self.assertEqual(
            str(rep),
            "\n".join(
                [
                    "[tick 90] order failed",
                    "  1 walk ok 30t x=1.5 y=2",
                    "  2 place FAILED: no pipe in inventory",
                    "  dropped 2 later orders",
                    "  ! damaged@80 health=200",
                    "at (1.5, 2) hp 200 crafting 0",
                    "inv changes: wood -1",
                ]
            ),
        )

    def test_chat_lines(self):
        line = {
            "id": 4,
            "from": "Ann",
            "text": "come to [gps=10,-20] please\x1b[2J",
            "mention": True,
        }
        self.assertEqual(
            fmt.chat_line(line), "#4 Ann (@): come to [at 10,-20] please[2J"
        )

    def test_report_ok(self):
        self.assertTrue(
            game.Report({"reason": "done", "results": [{"ok": True}]}).ok
        )
        self.assertFalse(
            game.Report({"reason": "enemy nearby", "results": []}).ok
        )


class OverviewFormatTest(unittest.TestCase):
    def test_scaled_ruler_and_rows(self):
        text = fmt.tile_map(
            {
                "x": -80,
                "y": 16,
                "w": 30,
                "h": 2,
                "scale": 8,
                "rows": ["." * 30, "." * 30],
            }
        )
        ruler, first, second = text.split("\n")
        self.assertEqual(ruler.index("-80"), first.index("."))
        self.assertEqual(
            ruler.index("0", ruler.index("-80") + 3), first.index(".") + 10
        )
        self.assertTrue(first.startswith("   16 "))
        self.assertTrue(second.startswith("   24 "))


if __name__ == "__main__":
    unittest.main()
