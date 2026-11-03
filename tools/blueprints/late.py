"""Modules for robots, purple and yellow science, and the rocket.

Same conventions as modules.py: feed belts on rows 6 and 7 flowing east,
machines above (rows 2-4) and below (rows 9-11), outputs on rows 0 and 13.
Poles are placed by Module.auto_poles.
"""

from tools.blueprints.layout import EAST, NORTH, SOUTH, WEST, Module
from tools.blueprints.modules import (
    AM2,
    BELT,
    FAST,
    INS,
    LONG,
    _join,
    _science_cell,
)

PLANT = "chemical-plant"
PIPE = "pipe"


def frames(name="FRAME"):
    """Flying robot frames, 13.5 a minute: enough for yellow science and bots.

    Rows 1 to 8 make the parts. Lubricant comes from heavy oil in the plant at
    the head and runs along row 1 to three electric engine machines, which
    take engines and green circuits from row 6 and drop on row 7's right lane.
    Two battery plants under row 8 (iron and copper) take acid from row 13
    and drop on row 7's left lane. Six frame machines further east take both
    lanes of row 7, green circuits from row 6, steel from row 0 and put frames
    on row -1, reaching over row 0.
    """
    module = Module(name, "13.5 robot frames a minute")
    # Lubricant: heavy in from the north, out of the south-west outlet.
    module.add(PIPE, -4, -4)
    module.add(PLANT, -4, -3, recipe="lubricant")
    # Which outlet a one-fluid recipe uses is not checked, so both are joined.
    for x in (-4, -3, -2):
        module.add(PIPE, x, 0)
    for x in range(-2, 8):
        module.add(PIPE, x, 1)
    for x in (0, 3, 6):
        module.add(AM2, x, 2, recipe="electric-engine-unit")
        module.add(INS, x, 5, SOUTH)
        module.add(LONG, x + 1, 5, NORTH)
    # Batteries, upside down so their inlets face row 13.
    for x in (0, 4):
        module.add(PLANT, x, 10, SOUTH, recipe="battery")
        module.add(INS, x, 9, NORTH)
        module.add(LONG, x + 1, 9, SOUTH)
    for x in range(-1, 8):
        module.add(PIPE, x, 13)
    module.row(BELT, 6, -1, 30, EAST)
    module.row(BELT, 7, 0, 30, EAST)
    module.row(BELT, 8, -1, 7, EAST)
    # Frames.
    for index in range(6):
        x = 12 + index * 3
        module.add(AM2, x, 2, recipe="flying-robot-frame")
        module.add(INS, x, 5, SOUTH)
        module.add(LONG, x + 1, 5, SOUTH)
        module.add(INS, x, 1, NORTH)
        module.add(LONG, x + 1, 1, SOUTH)
    module.row(BELT, 0, 31, 11, WEST)
    module.row(BELT, -1, 12, 31, EAST)
    module.auto_poles()
    module.port("heavy", "fluid-in", -4, -4, ["heavy-oil"])
    module.port("acid", "fluid-in", -1, 13, ["sulfuric-acid"])
    module.port(
        "engine-green",
        "belt-in",
        -1,
        6,
        ["engine-unit", "electronic-circuit"],
    )
    module.port("iron-copper", "belt-in", -1, 8, ["iron-plate", "copper-plate"])
    module.port("steel", "belt-in", 31, 0, ["steel-plate"])
    module.port("out", "belt-out", 31, -1, ["flying-robot-frame"])
    module.targets = {"flying-robot-frame": 13}
    return module


def robots(name="BOTS"):
    """Roboports, robots and logistic chests into chests, from frames.

    Row 6 carries steel and gears, row 7 green and red circuits, row 8 frames
    for the robot machines below. Logistic chests are made from a steel chest
    machine passing to its neighbours.
    """
    module = Module(name, "roboports, robots and logistic chests")
    module.row(BELT, 6, -1, 26, EAST)
    module.row(BELT, 7, -1, 26, EAST)
    module.row(BELT, 8, -1, 26, EAST)
    uppers = [
        (0, "roboport", 1),
        (4, "passive-provider-chest", 1),
        (8, "steel-chest", 0),
        (12, "storage-chest", 1),
        (16, "requester-chest", 1),
        (20, "steel-chest", 0),
        (24, "buffer-chest", 1),
    ]
    for x, recipe, bar in uppers:
        module.add(AM2, x, 2, recipe=recipe)
        module.add(INS, x, 5, SOUTH)
        module.add(LONG, x + 1, 5, SOUTH)
        if bar:
            module.add(INS, x + 1, 1, SOUTH)
            module.add("iron-chest", x + 1, 0, bar=bar)
    for gap, pick in ((7, EAST), (11, WEST), (19, EAST), (23, WEST)):
        module.add(INS, gap, 3, pick)
    for x, recipe in ((0, "construction-robot"), (4, "logistic-robot")):
        module.add(AM2, x, 10, recipe=recipe)
        module.add(INS, x, 9, NORTH)
        module.add(LONG, x + 1, 9, NORTH)
        module.add(INS, x + 1, 13, NORTH)
        module.add("iron-chest", x + 1, 14, bar=1)
    module.auto_poles()
    module.port(
        "steel-gears", "belt-in", -1, 6, ["steel-plate", "iron-gear-wheel"]
    )
    module.port(
        "circuits", "belt-in", -1, 7, ["electronic-circuit", "advanced-circuit"]
    )
    module.port("frames", "belt-in", -1, 8, ["flying-robot-frame"])
    module.stock = {
        "roboport": 1,
        "passive-provider-chest": 1,
        "storage-chest": 1,
        "requester-chest": 1,
        "buffer-chest": 1,
        "construction-robot": 1,
        "logistic-robot": 1,
    }
    return module


def science_p(name="SCI-P"):
    """Purple science, 32 a minute, with its furnaces, modules and rails.

    West part: two electric furnace machines above rows 6 (steel, bricks) and
    7 (red, green circuits), four productivity module machines below. Their
    output rows side-load one belt, furnaces left and modules right, which
    becomes row 6 of the east part. There, three rail machines below (stone and
    steel from row 13, sticks passed from their neighbour, which takes iron
    from row 14) fill row 7 with rails, and five pack machines above take both
    rows.
    """
    module = Module(name, "32 purple science a minute")
    module.row(BELT, 6, -1, 11, EAST)
    module.row(BELT, 7, -1, 11, EAST)
    for x in (0, 3):
        _science_cell(module, x, True, "electric-furnace", near=FAST)
    for x in (0, 3, 6, 9):
        _science_cell(module, x, False, "productivity-module")
    module.row(BELT, 0, 1, 12, EAST)
    module.row(BELT, 13, 1, 12, EAST)
    _join(module, 13)
    # East part.
    module.row(BELT, 6, 15, 33, EAST)
    module.row(BELT, 7, 16, 33, EAST)
    for index in range(5):
        _science_cell(module, 18 + index * 3, True, "production-science-pack")
    module.row(BELT, 0, 19, 34, EAST)
    for x, recipe in ((16, "rail"), (20, "iron-stick"), (24, "rail")):
        module.add(AM2, x, 9, recipe=recipe)
    for x in (16, 24):
        module.add(FAST, x, 12, SOUTH)
        module.add(FAST, x + 1, 12, SOUTH)
        module.add(FAST, x + 1, 8, SOUTH)
    # Sticks for 6 rails/s need 1.5 iron/s, more than one long-handed
    # inserter's 1.2.
    for x in (20, 21, 22):
        module.add(LONG, x, 12, SOUTH)
    module.add(FAST, 19, 10, EAST)
    module.add(FAST, 23, 10, WEST)
    module.row(BELT, 13, 15, 27, EAST)
    module.row(BELT, 14, 15, 23, EAST)
    module.auto_poles()
    module.port(
        "steel-bricks", "belt-in", -1, 6, ["steel-plate", "stone-brick"]
    )
    module.port(
        "circuits", "belt-in", -1, 7, ["advanced-circuit", "electronic-circuit"]
    )
    module.port("stone-steel", "belt-in", 15, 13, ["stone", "steel-plate"])
    module.port("iron", "belt-in", 15, 14, ["iron-plate"])
    module.port("out", "belt-out", 34, 0, ["production-science-pack"])
    module.targets = {"production-science-pack": 30}
    return module


def low_density(name="LDS"):
    """Low density structures, 30 a minute: ten machines.

    Row 6 brings copper on both lanes (a machine takes 1/s), row 7 steel and
    plastic.
    """
    module = Module(name, "30 low density structures a minute")
    width = 15
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(BELT, 7, -1, width - 1, EAST)
    for index in range(5):
        x = index * 3
        _science_cell(module, x, True, "low-density-structure", near=FAST)
        _science_cell(module, x, False, "low-density-structure")
    module.row(BELT, 0, 0, width, EAST)
    module.row(BELT, 13, 0, width, EAST)
    _join(module, width + 1)
    module.auto_poles()
    module.port("copper", "belt-in", -1, 6, ["copper-plate"])
    module.port(
        "steel-plastic", "belt-in", -1, 7, ["steel-plate", "plastic-bar"]
    )
    module.port("out", "belt-out", width + 2, 6, ["low-density-structure"])
    module.targets = {"low-density-structure": 30}
    return module


def blue_circuits(name="BLUE", count=6):
    """Processing units, 4.5 a minute a machine, acid along row 1.

    A machine takes green circuits from row 6 (fast) and red from row 7, and
    puts processing units on row 7's right lane, long-handed. A filter splitter
    at the end lets only processing units leave; red circuits wait behind it.
    """
    module = Module(name, f"{count * 4.5:g} processing units a minute")
    width = count * 3
    for x in range(0, width):
        module.add(PIPE, x, 1)
    for index in range(count):
        x = index * 3
        module.add(AM2, x, 2, recipe="processing-unit")
        module.add(FAST, x, 5, SOUTH)
        module.add(LONG, x + 1, 5, SOUTH)
        module.add(LONG, x + 2, 5, NORTH)
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(BELT, 7, -1, width - 1, EAST)
    module.add(
        "splitter",
        width,
        7,
        EAST,
        filter={"name": "processing-unit"},
        output_priority="left",
    )
    module.row(BELT, 7, width + 1, width + 2, EAST)
    module.add(BELT, width + 1, 8, EAST)
    module.auto_poles()
    module.port("acid", "fluid-in", 0, 1, ["sulfuric-acid"])
    module.port("green", "belt-in", -1, 6, ["electronic-circuit"])
    module.port("red", "belt-in", -1, 7, ["advanced-circuit", ""])
    module.port("out", "belt-out", width + 2, 7, ["processing-unit"])
    module.targets = {"processing-unit": count * 4.5 * 0.95}
    return module


def science_y(name="SCI-Y"):
    """Yellow science, 32 a minute: five machines above two rows."""
    module = Module(name, "32 yellow science a minute")
    width = 15
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(BELT, 7, -1, width - 1, EAST)
    for index in range(5):
        _science_cell(module, index * 3, True, "utility-science-pack")
    module.row(BELT, 0, 0, width, EAST)
    module.auto_poles()
    module.port(
        "lds-pu", "belt-in", -1, 6, ["low-density-structure", "processing-unit"]
    )
    module.port("frames", "belt-in", -1, 7, ["flying-robot-frame"])
    module.port("out", "belt-out", width, 0, ["utility-science-pack"])
    module.targets = {"utility-science-pack": 30}
    return module


def rocket_fuel(name="RF"):
    """Rocket fuel, 24 a minute, with the solid fuel it needs.

    Eight machines above take light oil from row 1 and solid fuel from row 6,
    and drop rocket fuel on row 7. Four plants below, upside down so their
    inlets face the light oil on row 12, drop solid fuel on row 6's left lane;
    its right lane takes solid fuel from elsewhere, such as the oil block's
    petroleum overflow.
    """
    module = Module(name, "24 rocket fuel a minute")
    width = 24
    for x in range(-1, width):
        module.add(PIPE, x, 1)
        module.add(PIPE, x, 12)
    for index in range(8):
        x = index * 3
        module.add(AM2, x, 2, recipe="rocket-fuel")
        module.add(INS, x, 5, SOUTH)
        module.add(LONG, x + 1, 5, NORTH)
    for index in range(4):
        x = index * 6
        module.add(PLANT, x, 9, SOUTH, recipe="solid-fuel-from-light-oil")
        module.add(LONG, x + 1, 8, SOUTH)
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(BELT, 7, 0, width, EAST)
    module.auto_poles()
    module.port("light-top", "fluid-in", -1, 1, ["light-oil"])
    module.port("light-bottom", "fluid-in", -1, 12, ["light-oil"])
    module.port("solid", "belt-in", -1, 6, ["", "solid-fuel"])
    module.port("out", "belt-out", width, 7, ["rocket-fuel"])
    module.targets = {"rocket-fuel": 24}
    return module


def _requests(items):
    """A requester chest's `request_filters` for item -> count."""
    filters = [
        {
            "index": index,
            "name": name,
            "quality": "normal",
            "comparator": "=",
            "count": count,
        }
        for index, (name, count) in enumerate(items.items(), 1)
    ]
    return {"sections": [{"index": 1, "filters": filters}]}


def silo(name="SILO"):
    """The rocket silo, fed from the west, with satellites and a landing pad.

    Column -2 carries processing units and low density structures, column -3
    rocket fuel on its left lane, both flowing north; inserters feed the silo
    from them. Put the four productivity modules in by hand.

    After the launch, satellites make space science. The feed columns also
    keep three passive provider chests below the silo topped up, one per part;
    a satellite machine north of the silo asks robots for its six parts (solar
    panels, accumulators and radars come from SAT) and puts each satellite
    straight into the silo, which launches by itself (the print turns on the
    silo's automatic launch, which is off by default). The 1000 space science
    packs land on the pad to the east and leave on column 19. The roboport is
    for this, and stays a ghost until robots are researched.
    """
    module = Module(name, "rocket silo, satellites and landing pad")
    # Off by default: without it a rocket with a satellite waits for a click.
    module.add("rocket-silo", 0, 0, launch_to_orbit_automatically=True)
    module.belt(BELT, -2, 0, 11, NORTH)
    module.belt(BELT, -3, 0, 11, NORTH)
    for y in (1, 3):
        module.add(INS, -1, y, WEST)
    for y in (5, 7):
        module.add(LONG, -1, y, WEST)
    # Parts for satellites into the logistic network, one chest each: in a
    # shared chest one part would fill every slot and starve the other.
    for y, item, bar in (
        (9, "processing-unit", 1),
        (10, "low-density-structure", 2),
    ):
        only = {"index": 1, "name": item, "quality": "normal"}
        only["comparator"] = "="
        module.add(FAST, -1, y, WEST, filters=[only], use_filters=True)
        module.add("passive-provider-chest", 0, y, bar=bar)
    module.add(LONG, -1, 11, WEST)
    module.add("passive-provider-chest", 1, 11, bar=5)
    # The satellite machine.
    module.add(
        "requester-chest",
        3,
        -6,
        request_filters=_requests(
            {
                "low-density-structure": 100,
                "processing-unit": 100,
                "rocket-fuel": 50,
                "solar-panel": 100,
                "accumulator": 100,
                "radar": 5,
            }
        ),
    )
    module.add(FAST, 3, -5, NORTH)
    module.add(AM2, 3, -4, recipe="satellite")
    module.add(INS, 4, -1, NORTH)
    module.add("roboport", 10, 0)
    # Landing pad, emptied onto column 19.
    module.add("cargo-landing-pad", 10, 5)
    for y in (6, 8, 10):
        module.add(FAST, 18, y, WEST)
    module.belt(BELT, 19, 5, 12, NORTH)
    module.auto_poles()
    module.port(
        "pu-lds",
        "belt-in",
        -2,
        11,
        ["processing-unit", "low-density-structure"],
    )
    module.port("fuel", "belt-in", -3, 11, ["rocket-fuel", ""])
    module.port("space", "belt-out", 19, 5, ["space-science-pack"])
    # Parts a minute the silo must reach with unlimited input: the rocket
    # modules supply 2.4.
    module.rocket_parts = 2.4
    # One launch with a satellite within the run.
    module.totals = {"space-science-pack": 1000}
    module.supply = {"solar-panel": 100, "accumulator": 100, "radar": 5}
    return module


def satellite_parts(name="SAT"):
    """Solar panels, accumulators and radars for satellites, into chests.

    Rows 6 (steel, copper) and 7 (green circuits, iron). Above: solar panels,
    and radars with gears passed from their neighbour. Below: two battery
    plants, upside down so their inlets face the acid on row 12, pass to the
    accumulator machine between them. Outputs go to passive provider chests,
    where robots take them to the satellite machine at the silo. About 22
    minutes of output per satellite.
    """
    module = Module(name, "solar panels, accumulators and radars")
    module.row(BELT, 6, -1, 11, EAST)
    module.row(BELT, 7, -1, 11, EAST)
    module.add(AM2, 0, 2, recipe="solar-panel")
    module.add(INS, 0, 5, SOUTH)
    module.add(LONG, 1, 5, SOUTH)
    module.add(INS, 1, 1, SOUTH)
    module.add("passive-provider-chest", 1, 0, bar=2)
    module.add(AM2, 4, 2, recipe="iron-gear-wheel")
    module.add(LONG, 5, 5, SOUTH)
    module.add(INS, 7, 3, WEST)
    module.add(AM2, 8, 2, recipe="radar")
    module.add(LONG, 9, 5, SOUTH)
    module.add(INS, 9, 1, SOUTH)
    module.add("passive-provider-chest", 9, 0, bar=1)
    for x in (0, 8):
        module.add(PLANT, x, 9, SOUTH, recipe="battery")
        module.add(INS, x, 8, NORTH)
        module.add(LONG, x + 1, 8, NORTH)
    module.add(INS, 3, 10, WEST)
    module.add(INS, 7, 10, EAST)
    module.add(AM2, 4, 9, recipe="accumulator")
    module.add(INS, 4, 8, NORTH)
    module.add(INS, 5, 12, NORTH)
    module.add("passive-provider-chest", 5, 13, bar=2)
    for x in range(-1, 3):
        module.add(PIPE, x, 12)
    for x in range(7, 11):
        module.add(PIPE, x, 12)
    module.auto_poles()
    module.port(
        "steel-copper", "belt-in", -1, 6, ["steel-plate", "copper-plate"]
    )
    module.port(
        "green-iron", "belt-in", -1, 7, ["electronic-circuit", "iron-plate"]
    )
    module.port("acid", "fluid-in", -1, 12, ["sulfuric-acid"])
    module.port("acid-east", "fluid-in", 10, 12, ["sulfuric-acid"])
    module.stock = {"solar-panel": 10, "accumulator": 10, "radar": 2}
    return module


def concrete(name="CONCRETE"):
    """Concrete, 90 a minute into chests: 1000 for the silo in 11 minutes.

    The machines stand upside down, so their water inlet faces row 5. Bricks
    and iron ore come along row 0, and long-handed inserters reach over it to
    the chests on row -1.
    """
    module = Module(name, "90 concrete a minute")
    for x in range(-1, 6):
        module.add(PIPE, x, 5)
    module.row(BELT, 0, -1, 5, EAST)
    for x in (0, 3):
        module.add(AM2, x, 2, SOUTH, recipe="concrete")
        module.add(INS, x, 1, NORTH)
        module.add(LONG, x + 2, 1, SOUTH)
        module.add("iron-chest", x + 2, -1, bar=8)
    module.auto_poles()
    module.port("water", "fluid-in", -1, 5, ["water"])
    module.port("bricks-ore", "belt-in", -1, 0, ["stone-brick", "iron-ore"])
    module.stock = {"concrete": 100}
    return module


def modules_line(name="MOD"):
    """Productivity modules 1, 2 and 3, each passed to the next machine.

    Rows 6 (green, red circuits) and 7 (processing units, red circuits). Each
    machine also fills a chest above it, for labs, assemblers and the silo.
    """
    module = Module(name, "productivity modules 1 to 3")
    module.row(BELT, 6, -1, 11, EAST)
    module.row(BELT, 7, -1, 11, EAST)
    chain = [
        (0, "productivity-module"),
        (4, "productivity-module-2"),
        (8, "productivity-module-3"),
    ]
    for x, recipe in chain:
        module.add(AM2, x, 2, recipe=recipe)
        module.add(INS, x, 5, SOUTH)
        module.add(LONG, x + 1, 5, SOUTH)
        module.add(INS, x + 1, 1, SOUTH)
        module.add("iron-chest", x + 1, 0, bar=1)
    module.add(INS, 3, 3, WEST)
    module.add(INS, 7, 3, WEST)
    module.auto_poles()
    module.port(
        "green-red",
        "belt-in",
        -1,
        6,
        ["electronic-circuit", "advanced-circuit"],
    )
    module.port(
        "pu-red", "belt-in", -1, 7, ["processing-unit", "advanced-circuit"]
    )
    module.stock = {
        "productivity-module": 1,
        "productivity-module-2": 1,
        "productivity-module-3": 1,
    }
    return module


def late_modules():
    return [
        frames(),
        robots(),
        science_p(),
        low_density(),
        blue_circuits(),
        science_y(),
        rocket_fuel(),
        silo(),
        satellite_parts(),
        concrete(),
        modules_line(),
    ]
