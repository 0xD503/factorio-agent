"""The blueprint codec, the layout helper and the modules. No game needed."""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.blueprints import codec  # noqa: E402
from tools.blueprints.layout import COPPER, NORTH, Module  # noqa: E402
from tools.blueprints.modules import all_modules, smelter  # noqa: E402


class CodecTest(unittest.TestCase):
    def test_round_trip(self):
        data = {
            "blueprint": {"item": "blueprint", "entities": [], "version": 1}
        }
        string = codec.encode(data)
        self.assertTrue(string.startswith("0"))
        self.assertEqual(codec.decode(string), data)

    def test_decode_ignores_surrounding_whitespace(self):
        data = {"blueprint": {"item": "blueprint"}}
        self.assertEqual(codec.decode(f"  {codec.encode(data)}\n"), data)

    def test_unknown_version_byte_is_refused(self):
        with self.assertRaises(ValueError):
            codec.decode("1abc")

    def test_game_version_layout(self):
        self.assertEqual(
            codec.game_version(2, 1, 24), (2 << 48) + (1 << 32) + (24 << 16)
        )


class LayoutTest(unittest.TestCase):
    def test_centres_follow_entity_size(self):
        module = Module("t")
        belt = module.add("transport-belt", 3, 4)
        furnace = module.add("stone-furnace", 10, 10)
        machine = module.add("assembling-machine-1", 20, 20)
        self.assertEqual(belt["position"], {"x": 3.5, "y": 4.5})
        self.assertEqual(furnace["position"], {"x": 11.0, "y": 11.0})
        self.assertEqual(machine["position"], {"x": 21.5, "y": 21.5})

    def test_north_is_left_out(self):
        self.assertNotIn("direction", Module("t").add("pipe", 0, 0, NORTH))

    def test_overlap_is_refused(self):
        module = Module("t")
        module.add("assembling-machine-1", 0, 0)
        with self.assertRaises(ValueError):
            module.add("transport-belt", 2, 2)

    def test_poles_out_of_reach_are_refused(self):
        module = Module("t")
        module.add("small-electric-pole", 0, 0)
        module.add("small-electric-pole", 20, 0)
        with self.assertRaises(ValueError):
            module.wires()

    def test_circuit_wire_out_of_reach_is_refused(self):
        module = Module("t")
        a = module.add("storage-tank", 0, 0)
        b = module.add("pump", 20, 0)
        module.circuit_links.append((a, b))
        with self.assertRaises(ValueError):
            module.blueprint()

    def test_auto_poles_power_everything_and_connect(self):
        module = Module("t")
        for x in range(0, 40, 4):
            module.add("assembling-machine-2", x, 0)
            module.add("inserter", x + 1, 3)
        module.add("assembling-machine-2", 0, 20)
        module.auto_poles()
        self.assertEqual(module.unpowered(), [])
        module.wires()

    def test_wires_join_every_pole_once(self):
        module = Module("t")
        for x in (0, 5, 10):
            module.add("small-electric-pole", x, 0)
        wires = module.wires()
        self.assertEqual(len(wires), 2)
        for wire in wires:
            self.assertEqual((wire[1], wire[3]), (COPPER, COPPER))


class ModulesTest(unittest.TestCase):
    def test_every_string_decodes_to_its_module(self):
        for name, module in all_modules().items():
            with self.subTest(name):
                body = codec.decode(module.string())["blueprint"]
                self.assertEqual(body["label"], name)
                self.assertEqual(len(body["entities"]), len(module.entities))
                json.dumps(body)

    def test_every_machine_has_power_and_all_poles_connect(self):
        for name, module in all_modules().items():
            if name.startswith("PROBE"):
                continue
            with self.subTest(name):
                self.assertEqual(module.unpowered(), [])
                module.wires()

    def test_smelter_tiers_share_one_geometry(self):
        def shape(module):
            return sorted(
                (e["position"]["x"], e["position"]["y"], e.get("direction"))
                for e in module.entities
                if "pole" not in e["name"]
            )

        stone = smelter("a", "iron-ore", "iron-plate", "stone")
        steel = smelter("b", "iron-ore", "iron-plate", "steel")
        self.assertEqual(shape(stone), shape(steel))
        self.assertEqual(stone.box(), (13, 53))
        self.assertEqual(stone.bill()["stone-furnace"], 48)
        self.assertEqual(steel.bill()["steel-furnace"], 48)


if __name__ == "__main__":
    unittest.main()
