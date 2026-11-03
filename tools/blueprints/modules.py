"""The modules of the blueprint set. Each function returns a Module."""

from tools.blueprints.layout import EAST, NORTH, SOUTH, WEST, Module

AM2 = "assembling-machine-2"
BELT, RED_BELT = "transport-belt", "fast-transport-belt"
MEDIUM = "medium-electric-pole"
INS, LONG, FAST = "inserter", "long-handed-inserter", "fast-inserter"

ROWS = 24  # furnaces per side of a smelter column

TIERS = {
    "stone": {
        "belt": "transport-belt",
        "under": "underground-belt",
        "splitter": "splitter",
        "furnace": "stone-furnace",
    },
    "steel": {
        "belt": "fast-transport-belt",
        "under": "fast-underground-belt",
        "splitter": "fast-splitter",
        "furnace": "steel-furnace",
    },
}


def smelter(name, ore, plate, tier="stone", half=False, rate=None):
    """A smelter column: 48 furnaces around one output belt.

    Columns, west to east (everything flows north):

        0 input belt, ore on one lane and coal on the other
        1 inserter east
        2-3 furnace
        4 inserter east, poles
        5 output belt
        6 inserter west, poles
        7-8 furnace
        9 inserter west
        10 input belt

    A lane holds half a belt, and 24 furnaces use exactly one lane: 7.5/s for
    stone on yellow, 15/s for steel on red. The two inserter rows drop on
    opposite lanes of the output, so it fills to a whole belt. Upgrading stone
    to steel and yellow to red keeps every position except the poles: stone
    uses small poles, because medium ones need steel.

    Below the column, the head loads the lanes. The ore belt comes up column 4
    under the coal row and a splitter sends it to the inner side of both input
    belts. Coal runs along row 51 from column -1, and an inserter at each end
    lifts it to the outer side, which is enough for the 0.54/s a side burns.
    Row 51 continues into the next column's coal row 13 tiles east, so columns
    stand side by side on one coal belt.

    With half=True only the west side is built, for the first half a lane. A
    full column of the same tier pasted over it adds the rest.

    Inserter direction is the side it takes from.
    """
    t = TIERS[tier]
    belt, furnace = t["belt"], t["furnace"]
    size = "half" if half else "48 furnaces"
    module = Module(name, f"{ore} to {plate}, {tier}, {size}")
    bottom = ROWS * 2 - 1
    module.belt(belt, 0, 0, bottom)
    module.belt(belt, 5, 0, bottom)
    if not half:
        module.belt(belt, 10, 0, bottom)
    for row in range(ROWS):
        y = row * 2
        module.add("inserter", 1, y, WEST)
        module.add(furnace, 2, y)
        module.add("inserter", 4, y, WEST)
        if not half:
            module.add("inserter", 6, y, EAST)
            module.add(furnace, 7, y)
            module.add("inserter", 9, y, EAST)
    if tier == "steel":
        for y in range(3, bottom, 8):
            module.add("medium-electric-pole", 4, y)
            module.add("medium-electric-pole", 6, y)
    else:
        for y in range(1, bottom, 4):
            module.add("small-electric-pole", 1, y)
            module.add("small-electric-pole", 4, y)
            if not half:
                module.add("small-electric-pole", 9, y)

    # Head: west side.
    module.add(belt, 0, 48, NORTH)
    module.add(belt, -1, 48, EAST)
    module.add(belt, -1, 49, NORTH)
    module.add("inserter", -1, 50, SOUTH)
    module.row(belt, 48, 4, 1, WEST)
    # Ore: under the coal row, then the splitter.
    module.add(t["under"], 4, 52, NORTH, type="input")
    module.add(t["under"], 4, 50, NORTH, type="output")
    module.add(t["splitter"], 4, 49, NORTH)
    last_coal = 4 if half else 11
    module.row(belt, 51, -1, last_coal, EAST)
    if tier == "steel":
        module.add("medium-electric-pole", 1, 50)
    else:
        # Reach: from the column's lowest poles, then along to the inserter.
        module.add("small-electric-pole", 1, 50)
        module.add("small-electric-pole", 1, 47)
    if not half:
        # East side.
        module.add(belt, 10, 48, NORTH)
        module.add(belt, 11, 48, WEST)
        module.add(belt, 11, 49, NORTH)
        module.add("inserter", 11, 50, SOUTH)
        module.row(belt, 48, 5, 9, EAST)
        if tier == "steel":
            module.add("medium-electric-pole", 9, 50)
        else:
            module.add("small-electric-pole", 9, 50)
            module.add("small-electric-pole", 9, 47)
    module.port("ore", "belt-in", 4, 52, [ore])
    module.port("coal", "belt-in", -1, 51, ["coal"])
    module.port("out", "belt-out", 5, 0, [plate])
    rate = rate or (900 if tier == "stone" else 1800)
    module.targets = {plate: rate / 2 if half else rate}
    return module


def miner(name, ore, groups=7):
    """Drills both sides of a belt flowing north: 4 drills in 7 rows, a group.

    A pole in the free row of each group reaches all four drills, and the next
    group's pole. Seven groups is 28 drills, 14/s, nearly a whole yellow belt.
    Drills that find no ore are simply not placed, so a paste can overlap the
    edge of a patch.
    """
    module = Module(name, f"{groups * 4} drills on {ore}")
    height = groups * 7
    module.belt("transport-belt", 3, 0, height - 1)
    for group in range(groups):
        y = group * 7
        module.add("small-electric-pole", 2, y + 3)
        for top in (y, y + 4):
            module.add("electric-mining-drill", 0, top, EAST)
            module.add("electric-mining-drill", 4, top, WEST)
    module.port("out", "belt-out", 3, 0, [ore])
    module.ore = ore
    module.targets = {ore: groups * 4 * 30}
    return module


def power(name="PWR", boilers=10):
    """Boilers in a row with two engines each, about 1.8 MW a boiler.

    Rows, north to south: engines 0-4 and 5-9, boilers 10-11, burner inserters
    12, coal belt 13 flowing east. Water runs through the boilers along row 11.
    Boilers stand in pairs with a one-tile gap inside each pair: the pipe
    across it carries the water, and the pole above it reaches the engines on
    both sides. Burner inserters fuel themselves from the belt, so the plant
    can start from nothing.
    """
    module = Module(name, f"{boilers} boilers, {boilers * 2} engines")
    x = 0
    module.add("pipe", -1, 11)
    for index in range(boilers):
        module.add("steam-engine", x, 0)
        module.add("steam-engine", x, 5)
        module.add("boiler", x, 10)
        module.add("burner-inserter", x + 1, 12, SOUTH)
        x += 3
        if index % 2 == 0 and index < boilers - 1:
            module.add("pipe", x, 11)
            module.add("small-electric-pole", x, 4)
            x += 1
    module.row("transport-belt", 13, -1, x - 1, EAST)
    module.port("water", "fluid-in", -1, 11, ["water"])
    module.port("coal", "belt-in", -1, 13, ["coal"])
    module.power_demand = boilers * 1.8e6 * 1.5
    module.power_target = boilers * 1.8e6 * 0.98
    return module


def turrets(name="TUR", count=6):
    """Gun turrets in a row, a tile apart, for hand-filled early defence."""
    module = Module(name, f"{count} gun turrets; fill with magazines")
    for index in range(count):
        module.add("gun-turret", index * 3, 0)
    return module


def _mall_cell(module, x, upper, recipe, machine, bar=3, chest=True):
    """One machine taking from both feed belts.

    The feed belts are rows 6 and 7. A machine's inserters stand at x+1 (near
    belt) and x+2 (far belt, long-handed); the pole at x+3 reaches them and the
    next cell's x+5. Output goes to a limited chest on the far side.
    """
    if upper:
        machine_y, feed_y, out_y, chest_y = 2, 5, 1, 0
        near_side, out_side = SOUTH, SOUTH
    else:
        machine_y, feed_y, out_y, chest_y = 9, 8, 12, 13
        near_side, out_side = NORTH, NORTH
    module.add(machine, x, machine_y, recipe=recipe)
    module.add("inserter", x + 1, feed_y, near_side)
    module.add("long-handed-inserter", x + 2, feed_y, near_side)
    module.add("small-electric-pole", x + 3, feed_y)
    if chest:
        module.add("inserter", x + 1, out_y, out_side)
        module.add("iron-chest", x + 1, chest_y, bar=bar)
        module.add("small-electric-pole", x + 3, out_y)


def mall_1(name="MALL-1"):
    """The first mall: what the science and smelting stages are built from.

    Rows 6 and 7 are feed belts flowing east. Row 6 carries iron plates on its
    right lane; its left lane stays free for steel, which MALL-2 needs. Row 7
    carries gears (right lane, from the upper machines at the head) and green
    circuits (left lane, from the lower ones), made here from row 6 and a
    copper belt on row 17. Inserters take only what a recipe needs, so lanes
    do not jam. Stone furnaces, boilers and engines are hand-crafted.

    A one-tile gap between cells holds a pole, and sometimes an inserter that
    passes a part directly to the next machine (belts into undergrounds and
    splitters, inserters into long-handed ones).
    """
    machine = "assembling-machine-1"
    module = Module(name, "gears, circuits and the items for the next stage")
    last = 37
    module.row("transport-belt", 6, -1, last, EAST)
    module.row("transport-belt", 7, 0, last, EAST)

    # Head, upper: gears onto row 7, with a hand chest.
    for x in (0, 4):
        module.add(machine, x, 2, recipe="iron-gear-wheel")
        module.add("inserter", x, 5, SOUTH)
        module.add("inserter", x + 1, 5, SOUTH)
        module.add("long-handed-inserter", x + 2, 5, NORTH)
    for x in (-1, 3, 7):
        module.add("small-electric-pole", x, 5)
    module.add("inserter", 1, 1, SOUTH)
    module.add("iron-chest", 1, 0, bar=1)
    module.add("small-electric-pole", 3, 1)

    # Head, lower: circuits onto row 7, each fed by its own cable machine.
    for x in (0, 4):
        near, far = (1, 2) if x == 0 else (5, 4)
        module.add(machine, x, 9, recipe="electronic-circuit")
        module.add("long-handed-inserter", near, 8, NORTH)
        module.add("inserter", far, 8, SOUTH)
        module.add("inserter", near, 12, SOUTH)
        module.add("inserter", far, 12, SOUTH)
        module.add(machine, x, 13, recipe="copper-cable")
        module.add("inserter", near, 16, SOUTH)
    for y in (8, 12, 16):
        module.add("small-electric-pole", 3, y)
    module.row("transport-belt", 17, 0, 22, EAST)
    # A hand chest for circuits.
    module.add("inserter", 7, 10, WEST)
    module.add("iron-chest", 8, 10, bar=1)
    module.add("small-electric-pole", 7, 8)

    # Cells, every four tiles. The first cell on a belt takes what it needs
    # first, so what the next stage needs most comes first and what costs the
    # most circuits and gears comes last. A chest holds whole stacks, which
    # is why splitters (50 a stack) sit at the very end.
    uppers = [
        (8, "transport-belt", 4),
        (12, "underground-belt", 1),
        (16, "electric-mining-drill", 1),
        (20, "inserter", 2),
        (24, "long-handed-inserter", 1),
        (28, "transport-belt", 0),
        (32, "splitter", 1),
    ]
    for x, recipe, bar in uppers:
        _mall_cell(module, x, True, recipe, machine, bar, chest=bar > 0)
    module.add("inserter", 11, 3, WEST)  # belts to undergrounds
    module.add("inserter", 23, 3, WEST)  # inserters to long-handed
    module.add("inserter", 31, 3, WEST)  # belts to splitters

    lowers = [
        (10, "assembling-machine-1", 1),
        (14, "pipe", 1),
        (18, "firearm-magazine", 1),
        (22, "gun-turret", 0),
    ]
    for x, recipe, bar in lowers:
        _mall_cell(module, x, False, recipe, machine, bar, chest=bar > 0)

    # Turret: copper comes up a short branch, output on the same side.
    module.add("inserter", 22, 16, SOUTH)
    module.belt("transport-belt", 22, 13, 15, NORTH)
    module.add("inserter", 22, 12, SOUTH)
    module.add("inserter", 23, 12, NORTH)
    module.add("iron-chest", 23, 13, bar=1)
    module.add("small-electric-pole", 21, 16)

    module.port("iron", "belt-in", -1, 6, ["", "iron-plate"])
    module.port("copper", "belt-in", 0, 17, ["copper-plate"])
    module.stock = {
        "iron-gear-wheel": 1,
        "electronic-circuit": 1,
        "underground-belt": 1,
        "transport-belt": 1,
        "splitter": 1,
        "inserter": 1,
        "long-handed-inserter": 1,
        "electric-mining-drill": 1,
        "gun-turret": 1,
        "pipe": 1,
        "assembling-machine-1": 1,
        "firearm-magazine": 1,
    }
    return module


def _mall2_lower(module, x, recipe, machine="assembling-machine-2", bar=1):
    """A machine with row 13 as a third feed, and its chest beyond that."""
    module.add(machine, x, 9, recipe=recipe)
    module.add("inserter", x + 1, 8, NORTH)
    module.add("long-handed-inserter", x + 2, 8, NORTH)
    module.add("small-electric-pole", x + 3, 8)
    module.add("inserter", x + 1, 12, SOUTH)
    module.add("long-handed-inserter", x + 2, 12, NORTH)
    module.add("small-electric-pole", x + 3, 12)
    module.add("iron-chest", x + 2, 14, bar=bar)


def mall_2(name="MALL-2"):
    """What needs steel: oil, red belts, fast inserters, assembler 2 and so on.

    It continues rows 6 and 7 of MALL-1 east, from column 38, so paste it with
    its column 38 right after MALL-1's column 37. Row 6 now also carries steel
    (left lane). Row 13 brings bricks (left lane) and pipes (right lane), for
    the lower machines, which reach row 7 directly and row 6 long-handed.
    Chests stand beyond row 13 on row 14. Gears get two more machines, because
    a red belt alone takes five. Copper for pole cable comes down row 0 from
    the east end.
    """
    machine = "assembling-machine-2"
    module = Module(name, "steel-based items; continues MALL-1 to the east")
    last = 92
    module.row("transport-belt", 6, 38, last, EAST)
    module.row("transport-belt", 7, 38, last, EAST)
    module.add("small-electric-pole", 37, 5)
    # More gears.
    for x in (38, 42):
        module.add(machine, x, 2, recipe="iron-gear-wheel")
        module.add("inserter", x, 5, SOUTH)
        module.add("inserter", x + 1, 5, SOUTH)
        module.add("long-handed-inserter", x + 2, 5, NORTH)
        module.add("small-electric-pole", x + 3, 5)
    uppers = [
        (46, "fast-inserter", 1),
        (50, "inserter", 0),
        (54, "fast-underground-belt", 1),
        (58, "underground-belt", 0),
        (62, "transport-belt", 0),
        (66, "fast-transport-belt", 4),
        (70, "fast-splitter", 1),
        (74, "splitter", 0),
        (78, "transport-belt", 0),
        (82, "iron-stick", 0),
        (86, "medium-electric-pole", 2),
    ]
    for x, recipe, bar in uppers:
        _mall_cell(module, x, True, recipe, machine, bar, chest=bar > 0)
    for gap, pick in (
        (49, EAST),
        (57, EAST),
        (61, EAST),
        (65, WEST),
        (73, EAST),
        (77, EAST),
        (85, WEST),
        (89, EAST),
    ):
        module.add("inserter", gap, 3, pick)
    module.add("small-electric-pole", 85, 1)
    # Cable for poles, from the copper on row 0.
    module.add(machine, 90, 2, recipe="copper-cable")
    module.add("inserter", 91, 1, NORTH)
    module.row("transport-belt", 0, 94, 90, WEST)
    # Lower: row 13 starts with bricks from the west; pipes join on the far
    # lane.
    module.row("transport-belt", 13, 37, 72, EAST)
    module.add(machine, 38, 9, recipe="pipe")
    module.add("long-handed-inserter", 40, 8, NORTH)
    module.add("inserter", 39, 12, NORTH)
    module.add("small-electric-pole", 41, 8)
    module.add("small-electric-pole", 41, 12)
    lowers = [
        (42, "pipe-to-ground", 1),
        (46, "oil-refinery", 1),
        (50, "chemical-plant", 1),
        (54, "pumpjack", 1),
        (58, "steel-furnace", 2),
        (62, "assembling-machine-1", 1),
        (66, "assembling-machine-2", 1),
        (70, "storage-tank", 1),
    ]
    for x, recipe, bar in lowers:
        _mall2_lower(module, x, recipe, machine, bar)
    module.add("inserter", 65, 10, WEST)  # assembler 1 into assembler 2
    module.port("steel-iron", "belt-in", 38, 6, ["steel-plate", "iron-plate"])
    module.port(
        "circuits-gears",
        "belt-in",
        38,
        7,
        ["electronic-circuit", "iron-gear-wheel"],
    )
    module.port("bricks", "belt-in", 37, 13, ["stone-brick", ""])
    module.port("copper", "belt-in", 94, 0, ["copper-plate"])
    module.stock = {
        "fast-inserter": 1,
        "fast-underground-belt": 1,
        "fast-transport-belt": 1,
        "fast-splitter": 1,
        "medium-electric-pole": 1,
        "pipe-to-ground": 1,
        "oil-refinery": 1,
        "chemical-plant": 1,
        "pumpjack": 1,
        "steel-furnace": 1,
        "assembling-machine-2": 1,
        "storage-tank": 1,
    }
    return module


def science_m(name="SCI-M"):
    """Military science, about 15 a minute, in two identical chains.

    Each chain runs along row 3: magazine, piercing rounds, pack, grenade, and
    every part passes straight to the next machine. Rows 6 and 7 carry iron
    and coal, steel and copper. Row 0 brings the walls the pack machines take.
    Long-handed inserters reach over it to the outgoing belt on row -1.
    """
    machine, pole = "assembling-machine-2", "small-electric-pole"
    module = Module(name, "military science from raw plates, about 15 a minute")
    belt = "transport-belt"
    width = 32
    module.row(belt, 6, -1, width - 1, EAST)
    module.row(belt, 7, -1, width - 1, EAST)
    module.row(belt, 0, 1, width - 4, EAST)
    module.row(belt, -1, 8, width + 1, EAST)
    # Walls.
    module.row(belt, 0, -6, -5, EAST)
    # 75 bricks a minute is more than a basic inserter carries.
    module.add("fast-inserter", -4, 0, WEST)
    module.add(machine, -3, -1, recipe="stone-wall")
    module.add("inserter", 0, 0, WEST)
    module.add(pole, -2, 2)
    for start in (0, 16):
        chain = [
            ("firearm-magazine", start),
            ("piercing-rounds-magazine", start + 4),
            ("military-science-pack", start + 8),
            ("grenade", start + 12),
        ]
        for recipe, x in chain:
            module.add(machine, x, 2, recipe=recipe)
            module.add(pole, x + 3, 5)
        module.add("inserter", start + 1, 5, SOUTH)  # iron for magazines
        module.add("inserter", start + 3, 3, WEST)
        module.add("long-handed-inserter", start + 5, 5, SOUTH)  # steel, copper
        module.add("inserter", start + 7, 3, WEST)
        module.add("inserter", start + 9, 1, NORTH)  # walls
        module.add("long-handed-inserter", start + 10, 1, SOUTH)  # packs out
        module.add(pole, start + 11, 1)
        module.add("inserter", start + 11, 3, EAST)
        # A grenade takes 15 items: one basic inserter would cap it at 3.3 a
        # minute.
        module.add("inserter", start + 13, 5, SOUTH)
        module.add("inserter", start + 14, 5, SOUTH)
    module.port("iron-coal", "belt-in", -1, 6, ["iron-plate", "coal"])
    module.port(
        "steel-copper", "belt-in", -1, 7, ["steel-plate", "copper-plate"]
    )
    module.port("bricks", "belt-in", -6, 0, ["stone-brick"])
    module.port("packs", "belt-out", width + 1, -1, ["military-science-pack"])
    module.targets = {"military-science-pack": 15}
    return module


def science_rg(name="SCI-RG"):
    """Red and green science, 60 a minute each, from iron and copper.

    Assembler 1 makes 6 red or 5 green a minute, hence 10 and 12 machines;
    upgrading to assembler 2 raises the block to 90 without moving anything.

    Row 6 carries copper (left lane) and iron (right lane). Row 7 carries
    circuits (left) and gears (right), made at the head. Red machines above
    take from both and output to row 0. Below, inserter and belt machines fill
    the two lanes of row 13, and green machines under it output to row 19. The
    pack rows meet at column 67 and leave east on one belt, red left and green
    right.
    """
    belt, machine = "transport-belt", "assembling-machine-1"
    pole = "small-electric-pole"
    module = Module(name, "60 red and 60 green a minute")
    module.row(belt, 6, -1, 41, EAST)
    module.row(belt, 7, 0, 41, EAST)

    # Gears: two inserters in, one long-handed out to row 7.
    for x in (0, 4, 8):
        module.add(machine, x, 2, recipe="iron-gear-wheel")
        module.add("inserter", x, 5, SOUTH)
        module.add("inserter", x + 1, 5, SOUTH)
        module.add("long-handed-inserter", x + 2, 5, NORTH)
    for x in (-1, 3, 7, 11):
        module.add(pole, x, 5)

    # Circuits: a cable machine passes to its neighbour through two inserters.
    for x in (0, 8):
        module.add(machine, x, 9, recipe="copper-cable")
        module.add("long-handed-inserter", x + 1, 8, NORTH)
        module.add("inserter", x + 3, 9, WEST)
        module.add("inserter", x + 3, 10, WEST)
        module.add(pole, x + 3, 8)
        module.add(machine, x + 4, 9, recipe="electronic-circuit")
        module.add("inserter", x + 4, 8, SOUTH)
        module.add("long-handed-inserter", x + 5, 8, NORTH)

    # Red.
    for index in range(10):
        x = 12 + index * 3
        module.add(machine, x, 2, recipe="automation-science-pack")
        module.add("inserter", x, 5, SOUTH)
        module.add("long-handed-inserter", x + 1, 5, SOUTH)
        module.add("inserter", x + 1, 1, SOUTH)
        if index % 2 == 0:
            module.add(pole, x + 2, 5)
            module.add(pole, x + 2, 1)
    module.row(belt, 0, 12, 66, EAST)

    module.add(pole, 15, 8)

    # Inserters drop on the far lane of row 13. Belts join from the north, so
    # they keep to the other lane.
    module.row(belt, 13, 15, 65, EAST)
    for x in (16, 20):
        # A recipe of two parts from row 7 needs two inserters to make 30 a
        # minute: one basic inserter carries about 50 items a minute.
        module.add(machine, x, 9, recipe="inserter")
        module.add("inserter", x, 8, NORTH)
        module.add("long-handed-inserter", x + 1, 8, NORTH)
        module.add("inserter", x + 2, 8, NORTH)
        module.add(pole, x + 3, 8)
        module.add("inserter", x + 1, 12, NORTH)
        module.add(pole, x + 3, 12)
    module.add(machine, 24, 9, recipe="transport-belt")
    module.add("inserter", 24, 8, NORTH)
    module.add("long-handed-inserter", 25, 8, NORTH)
    module.add(pole, 27, 8)
    module.add("inserter", 27, 9, WEST)
    module.add("inserter", 27, 10, WEST)
    module.belt(belt, 28, 9, 12, SOUTH)
    module.add(pole, 29, 11)

    # Green.
    for index in range(12):
        x = 30 + index * 3
        module.add("inserter", x + 1, 14, NORTH)
        module.add(machine, x, 15, recipe="logistic-science-pack")
        module.add("inserter", x + 1, 18, NORTH)
        if index % 2 == 0:
            module.add(pole, x + 2, 14)
            module.add(pole, x + 2, 18)
    module.row(belt, 19, 30, 66, EAST)

    # Both pack rows side-load into the outgoing belt.
    module.belt(belt, 67, 0, 8, SOUTH)
    module.belt(belt, 67, 10, 19, NORTH)
    module.add(belt, 67, 9, EAST)
    module.add(belt, 68, 9, EAST)
    module.port("iron-copper", "belt-in", -1, 6, ["copper-plate", "iron-plate"])
    module.port("packs", "belt-out", 68, 9, ["automation-science-pack"])
    module.targets = {
        "automation-science-pack": 60,
        "logistic-science-pack": 60,
    }
    return module


def labs(name="LAB", count=30):
    """Labs in two rows around two pack belts, with a third belt outside each.

    Rows: 0 purple and yellow, 1 inserters, 2-4 labs, 5 inserters, 6 red and
    green, 7 blue and military, 8 inserters, 9-11 labs, 12 inserters, 13 purple
    and yellow. Row -1 and row 14 stay free for space science, which a
    long-handed inserter can reach later. Belts flow east.
    """
    belt, pole = "transport-belt", "small-electric-pole"
    module = Module(name, f"{count} labs, all science on three belts")
    per_row = count // 2
    width = per_row * 3
    for y in (0, 6, 7, 13):
        module.row(belt, y, 0, width - 1, EAST)
    for index in range(per_row):
        x = index * 3
        module.add("lab", x, 2)
        module.add("inserter", x, 5, SOUTH)
        module.add("long-handed-inserter", x + 1, 5, SOUTH)
        module.add("inserter", x, 1, NORTH)
        module.add("lab", x, 9)
        module.add("inserter", x, 8, NORTH)
        module.add("long-handed-inserter", x + 1, 8, NORTH)
        module.add("inserter", x, 12, SOUTH)
        if index % 2 == 0:
            for y in (1, 5, 8, 12):
                module.add(pole, x + 2, y)
    pair = ["production-science-pack", "utility-science-pack"]
    module.port("py-north", "belt-in", 0, 0, pair)
    module.port("py-south", "belt-in", 0, 13, pair)
    module.port(
        "rg",
        "belt-in",
        0,
        6,
        ["automation-science-pack", "logistic-science-pack"],
    )
    module.port(
        "bm",
        "belt-in",
        0,
        7,
        ["chemical-science-pack", "military-science-pack"],
    )
    # 60-second techs that take five of the packs, at research speed 1-2: two
    # of them, so a long run does not finish them.
    module.research = {
        "names": ["mining-productivity-3", "rocket-silo"],
        "speed": 0.5,
    }
    module.research_target = count * 1.5
    return module


def oil(
    name="OIL",
    refineries=7,
    recipe="advanced-oil-processing",
    blocked=("heavy-oil", "light-oil"),
    targets=None,
    switch_at=None,
):
    """Refineries with every output plumbed, and cracking to keep them running.

    Rows from the top (y is the refineries' top row):

        y-6 heavy bus        y-4 light bus        y-2 petroleum bus
        y..y+4 refineries    y+6 crude bus        y+8 water bus

    A refinery's outputs are at columns x, x+2 and x+4 on row y-1, its inputs
    at x+1 (water) and x+3 (crude) on row y+5. Underground pipes hop the buses
    a connection has to cross. Basic oil processing uses the same crude inlet
    and petroleum outlet, so the only change between the two is the recipe.

    All five ports are on the west side, so the block grows by pasting a copy.

    East of the refineries, heavy cracks to light all the time, into the light
    bus. Light cracks to petroleum only past a pump that opens while the tank
    on the light bus is more than half full, so rocket fuel gets its light
    first and surplus still leaves. Light or heavy with nowhere to go can't
    stop a refinery, and neither can petroleum while the overflow's solid fuel
    has somewhere to go.
    """
    pipe, under = "pipe", "pipe-to-ground"
    machine, pole = "chemical-plant", "medium-electric-pole"
    module = Module(name, f"{refineries} refineries, cracking included")
    y = 0
    pitch = 6
    x_last = (refineries - 1) * pitch
    east = x_last + 10

    def bus(row, x1, x2):
        for tx in range(x1, x2 + 1):
            module.add(pipe, tx, row)

    for index in range(refineries):
        x = index * pitch
        module.add("oil-refinery", x, y, recipe=recipe)
        module.add(pole, x + 5, y + 2)
        # Outputs.
        module.add(under, x, y - 1, SOUTH)
        module.add(under, x, y - 5, NORTH)
        module.add(under, x + 2, y - 1, SOUTH)
        module.add(under, x + 2, y - 3, NORTH)
        module.add(pipe, x + 4, y - 1)
        # Inputs.
        module.add(pipe, x + 3, y + 5)
        module.add(under, x + 1, y + 5, NORTH)
        module.add(under, x + 1, y + 7, SOUTH)
    bus(y - 6, -1, east + 7)  # heavy, on over the heavy crackers
    bus(y - 4, -1, east - 2)  # light
    bus(y - 2, -1, east - 4)  # petroleum
    bus(y + 6, -1, x_last + 3)  # crude
    bus(y + 8, -1, x_last + 1)  # water
    # Light joins its east part, petroleum joins the row under the crackers.
    for row in range(y - 3, y + 1):
        module.add(pipe, east - 2, row)
    for row in range(y - 1, y + 11):
        module.add(pipe, east - 4, row)
    bus(y + 1, east - 2, east + 11)

    # Heavy to light: two plants, water on row y-4, heavy from row y-6.
    bus(y - 4, east, east + 24)
    for index in range(2):
        x = east + index * 4
        module.add(pipe, x, y - 3)
        module.add(under, x + 2, y - 3, SOUTH)
        module.add(under, x + 2, y - 5, NORTH)
        module.add(machine, x, y - 2, recipe="heavy-oil-cracking")
    relay = module.add(pole, east + 3, y - 1)

    # The tank and the pump that gates light cracking.
    # A tank connects at two opposite corners. This one reaches the light bus
    # with its south-east corner only: placed beside the bus, its other corner
    # would touch the gated row and let light bypass the pump.
    tank = module.add("storage-tank", east + 9, y - 2)
    gate = module.add(
        "pump",
        east - 1,
        y + 2,
        SOUTH,
        control_behavior={
            "circuit_condition": {
                "first_signal": {"type": "fluid", "name": "light-oil"},
                "comparator": ">",
                "constant": 12500,
            },
            "circuit_enabled": True,
        },
    )
    # Tank and pump are out of wire reach of each other, so the wire goes
    # through a pole. A pump on no network would ignore its condition.
    module.circuit_links.append((tank, relay))
    module.circuit_links.append((relay, gate))
    module.add(pole, east, y + 3)

    # Light to petroleum: six plants, gated light on row y+4, water on y+6,
    # petroleum out on row y+11.
    bus(y + 4, east - 1, east + 22)
    bus(y + 6, east, east + 24)
    for index in range(6):
        x = east + index * 4
        module.add(pipe, x, y + 7)
        module.add(under, x + 2, y + 7, SOUTH)
        module.add(under, x + 2, y + 5, NORTH)
        module.add(machine, x, y + 8, recipe="light-oil-cracking")
        if index % 2 == 0:
            module.add(pole, x + 3, y + 9)
    bus(y + 11, east - 4, east + 22)

    # Water for the crackers: from the refineries' bus, around to the east.
    for row in range(y + 9, y + 13):
        module.add(pipe, x_last + 1, row)
    bus(y + 13, x_last + 1, east + 24)
    for row in range(y - 3, y + 13):
        if row != y + 6:
            module.add(pipe, east + 24, row)

    # Petroleum overflow: past 80% in its own tank, it opens a pump to two solid
    # fuel plants, so full petroleum can't stop the refineries while something
    # still wants light. Solid fuel is what rocket fuel and boilers burn.
    px = x_last + 5
    module.add(under, px, y - 3, SOUTH)
    module.add(under, px, y - 7, NORTH)
    bus(y - 8, px, px + 5)
    gas_tank = module.add("storage-tank", px + 3, y - 11)
    gas_gate = module.add(
        "pump",
        px + 6,
        y - 8,
        EAST,
        control_behavior={
            "circuit_condition": {
                "first_signal": {"type": "fluid", "name": "petroleum-gas"},
                "comparator": ">",
                "constant": 20000,
            },
            "circuit_enabled": True,
        },
    )
    module.circuit_links.append((gas_tank, gas_gate))
    bus(y - 8, px + 8, px + 14)
    for index in range(2):
        x = px + 8 + index * 4
        module.add(
            machine, x, y - 11, SOUTH, recipe="solid-fuel-from-petroleum-gas"
        )
        module.add("inserter", x + 1, y - 12, SOUTH)
    module.row("transport-belt", y - 13, px + 8, px + 15, EAST)
    module.add(pole, px + 1, y - 3)
    module.add(pole, px + 6, y - 9)
    module.add(pole, px + 11, y - 12)

    module.port("crude", "fluid-in", -1, y + 6, ["crude-oil"])
    module.port("water", "fluid-in", -1, y + 8, ["water"])
    module.port("heavy", "fluid-out", -1, y - 6, ["heavy-oil"])
    module.port("light", "fluid-out", -1, y - 4, ["light-oil"])
    module.port("petroleum", "fluid-out", -1, y - 2, ["petroleum-gas"])
    module.port(
        "overflow-solid", "belt-out", px + 15, y - 13, ["solid-fuel"]
    )
    for port in module.ports:
        port.blocked = port.items[0] in blocked
    # Everything cracked: 11 + (9 + 5 * 0.75) * 2/3 = 19.5 petroleum/s each.
    module.fluid_targets = (
        {"petroleum-gas": round(refineries * 19.5 * 60)}
        if targets is None
        else targets
    )
    module.switch_at = switch_at
    return module


def oil_with_light_load(
    name, blocked=("heavy-oil", "light-oil"), target=240
):
    """OIL plus four real solid fuel plants on the light bus.

    A bench check, not a module to build: it shows whether a real consumer of
    light gets it first while the crackers are there too.
    """
    module = oil(name, blocked=blocked, targets={})
    for tx in range(-20, -1):
        module.add("pipe", tx, -4)
    for index in range(4):
        x = -19 + index * 4
        module.add("pipe", x, -3)
        module.add("chemical-plant", x, -2, recipe="solid-fuel-from-light-oil")
        # Long-handed, as in the rocket fuel module: a basic inserter would cap
        # a plant at 50 a minute.
        module.add("long-handed-inserter", x + 1, 1, NORTH)
        module.add("medium-electric-pole", x + 3, 1)
    module.add("medium-electric-pole", -1, 1)
    module.row("transport-belt", 3, -19, -3, EAST)
    module.port("solid", "belt-out", -3, 3, ["solid-fuel"])
    module.targets = {"solid-fuel": target}
    return module


def _join(module, x, belt=BELT, top=0, bottom=13, middle=6):
    """Rows `top` and `bottom` side-load one belt leaving east at `middle`."""
    module.belt(belt, x, top, middle - 1, SOUTH)
    module.belt(belt, x, middle + 1, bottom, NORTH)
    module.add(belt, x, middle, EAST)
    module.add(belt, x + 1, middle, EAST)


def _science_cell(module, x, upper, recipe, machine=AM2, near=INS, far=LONG):
    """A machine beside rows 6 and 7, with its output on row 0 or row 13."""
    if upper:
        module.add(machine, x, 2, recipe=recipe)
        module.add(near, x, 5, SOUTH)
        module.add(far, x + 1, 5, SOUTH)
        module.add(INS, x + 1, 1, SOUTH)
    else:
        module.add(machine, x, 9, recipe=recipe)
        module.add(near, x, 8, NORTH)
        module.add(far, x + 1, 8, NORTH)
        module.add(INS, x + 1, 12, NORTH)


def _strip(module, x0, cells, recipe, machine=AM2, near=INS, far=LONG):
    """`cells` machines above and below rows 6 and 7, from column x0.

    Medium poles every second column pair reach all of a machine's inserters.
    """
    for index in range(cells):
        x = x0 + index * 3
        _science_cell(module, x, True, recipe, machine, near, far)
        _science_cell(module, x, False, recipe, machine, near, far)
        if index % 2 == 0:
            for y in (1, 5, 8, 12):
                module.add(MEDIUM, x + 2, y)


def chemistry(name="CHEM"):
    """Plastic, sulfur and sulfuric acid.

    Eight plastic plants along row 0, which brings petroleum. Each takes coal
    long-handed from row 6 and drops plastic on red belt row 5, which flows
    west. East of them, sulfur and acid share a water row on -2.
    """
    plant, pipe, under = "chemical-plant", "pipe", "pipe-to-ground"
    module = Module(name, "plastic, sulfur and sulfuric acid")
    for tx in range(0, 23):
        module.add(pipe, tx, 0)
    for index in range(8):
        x = index * 3
        module.add(plant, x, 1, recipe="plastic-bar")
        module.add(LONG, x, 4, SOUTH)
        module.add(FAST, x + 1, 4, NORTH)
        if index % 2 == 0:
            module.add(MEDIUM, x + 2, 4)
    module.row(RED_BELT, 5, 23, -1, WEST)
    module.row(BELT, 6, -1, 23, EAST)
    # Petroleum on under the water to sulfur's second inlet.
    module.add(under, 23, 0, WEST)
    module.add(under, 25, 0, EAST)
    module.add(pipe, 26, 0)
    # Water.
    for tx in range(24, 29):
        module.add(pipe, tx, -2)
    module.add(pipe, 24, -1)
    module.add(pipe, 24, 0)
    module.add(pipe, 28, -1)
    module.add(pipe, 28, 0)
    # Sulfur onto row 5, flowing east past the acid plant.
    module.add(plant, 24, 1, recipe="sulfur")
    module.add(FAST, 25, 4, NORTH)
    module.row(BELT, 5, 24, 33, EAST)
    # Acid: sulfur from row 5, iron from the column to the east.
    module.add(plant, 28, 1, recipe="sulfuric-acid")
    module.add(INS, 29, 4, SOUTH)
    module.add(INS, 31, 2, EAST)
    module.belt(BELT, 32, 2, 3, NORTH)
    module.add(pipe, 30, 4)
    module.add(pipe, 31, 4)
    module.add(MEDIUM, 27, 4)
    module.add(MEDIUM, 31, 3)
    module.port("petroleum", "fluid-in", 0, 0, ["petroleum-gas"])
    module.port("water", "fluid-in", 24, -2, ["water"])
    module.port("coal", "belt-in", -1, 6, ["coal"])
    module.port("iron", "belt-in", 32, 3, ["iron-plate"])
    module.port("plastic", "belt-out", -1, 5, ["plastic-bar"])
    module.port("sulfur", "belt-out", 33, 5, ["sulfur"])
    module.port("acid", "fluid-out", 31, 4, ["sulfuric-acid"])
    module.targets = {"plastic-bar": 800, "sulfur": 60}
    # Batteries and blue circuits use about 460 a minute in the run base.
    module.fluid_targets = {"sulfuric-acid": 460}
    return module


def green_circuits(name="GREEN", units=3):
    """Green circuits by direct insertion, 18/s from 18 iron and 27 copper.

    A unit is cable, circuit, cable, circuit, cable along a row: three cable
    machines supply two circuit machines through pairs of fast inserters, with
    no cable on any belt. One unit stands above rows 6 (iron) and 7 (copper)
    and one below, each making 3/s. The rows must be red belt.
    """
    module = Module(name, f"{units * 2 * 3} green circuits a second")
    width = units * 20 - 1
    module.row(RED_BELT, 6, -1, width, EAST)
    module.row(RED_BELT, 7, -1, width, EAST)
    module.row(RED_BELT, 0, 0, width + 1, EAST)
    module.row(RED_BELT, 13, 0, width + 1, EAST)
    for unit in range(units):
        base = unit * 20
        for index in range(5):
            x = base + index * 4
            recipe = "copper-cable" if index % 2 == 0 else "electronic-circuit"
            module.add(AM2, x, 2, recipe=recipe)
            module.add(AM2, x, 9, recipe=recipe)
            if index % 2 == 0:
                # Cable: copper is the far belt above, the near one below.
                module.add(LONG, x, 5, SOUTH)
                module.add(LONG, x + 2, 5, SOUTH)
                module.add(FAST, x + 1, 8, NORTH)
            else:
                # Circuit: iron is the near belt above, the far one below.
                module.add(FAST, x + 1, 5, SOUTH)
                module.add(FAST, x + 1, 1, SOUTH)
                module.add(LONG, x, 8, NORTH)
                module.add(LONG, x + 2, 8, NORTH)
                module.add(FAST, x + 1, 12, NORTH)
            if index < 4:
                pick = WEST if index % 2 == 0 else EAST
                gap = x + 3
                module.add(FAST, gap, 2, pick)
                module.add(FAST, gap, 3, pick)
                module.add(FAST, gap, 10, pick)
                module.add(FAST, gap, 11, pick)
                module.add(MEDIUM, gap, 4)
                module.add(MEDIUM, gap, 9)
        if unit < units - 1:
            module.add(MEDIUM, base + 19, 4)
    _join(module, width + 2, RED_BELT)
    module.port("iron", "belt-in", -1, 6, ["iron-plate"])
    module.port("copper", "belt-in", -1, 7, ["copper-plate"])
    module.port("out", "belt-out", width + 3, 6, ["electronic-circuit"])
    module.targets = {"electronic-circuit": units * 2 * 3 * 60}
    return module


def red_circuits(name="RED"):
    """Sixteen red circuit machines, 2/s, with their cable made at the head.

    Row 6 carries green circuits and plastic, row 7 cable on red belt. Three
    cable machines below the head drop straight on row 7; copper reaches them
    along row 13, which ends before the outgoing row 13 starts.
    """
    module = Module(name, "2 red circuits a second")
    width = 36
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(RED_BELT, 7, 0, width - 1, EAST)
    module.row(BELT, 13, -1, 10, EAST)
    for x in (0, 4, 8):
        module.add(AM2, x, 9, recipe="copper-cable")
        module.add(FAST, x, 8, SOUTH)
        module.add(FAST, x + 2, 8, SOUTH)
        module.add(FAST, x + 1, 12, SOUTH)
        module.add(MEDIUM, x + 3, 8)
        module.add(MEDIUM, x + 3, 12)
    _strip(module, 12, 8, "advanced-circuit")
    module.row(BELT, 0, 12, width, EAST)
    module.row(BELT, 13, 12, width, EAST)
    _join(module, width + 1)
    module.port(
        "green-plastic",
        "belt-in",
        -1,
        6,
        ["electronic-circuit", "plastic-bar"],
    )
    module.port("copper", "belt-in", -1, 13, ["copper-plate"])
    module.port("out", "belt-out", width + 2, 6, ["advanced-circuit"])
    module.targets = {"advanced-circuit": 120}
    return module


def engines(name="ENGINE"):
    """Engine units, 81 a minute: 60 for blue science, the rest for robots.

    Row 6 carries steel and iron. Two gear machines above the head and three
    pipe machines below it fill row 7's two lanes: one fast inserter brings a
    gear machine about 1.1 gears a second, and a long-handed one a pipe
    machine 1.2 pipes, against 1.35 and 2.7 needed.
    """
    module = Module(name, "81 engine units a minute")
    width = 39
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(BELT, 7, 0, width - 1, EAST)
    for x in (0, 4):
        module.add(AM2, x, 2, recipe="iron-gear-wheel")
        module.add(FAST, x, 5, SOUTH)
        module.add(LONG, x + 2, 5, NORTH)
        module.add(MEDIUM, x + 3, 5)
    for x in (0, 4, 8):
        module.add(AM2, x, 9, recipe="pipe")
        module.add(LONG, x, 8, NORTH)
        module.add(FAST, x + 1, 8, SOUTH)
        module.add(MEDIUM, x + 3, 8)
    _strip(module, 12, 9, "engine-unit")
    module.row(BELT, 0, 12, width, EAST)
    module.row(BELT, 13, 12, width, EAST)
    _join(module, width + 1)
    module.port("steel-iron", "belt-in", -1, 6, ["steel-plate", "iron-plate"])
    module.port("out", "belt-out", width + 2, 6, ["engine-unit"])
    module.targets = {"engine-unit": 81}
    return module


def science_b(name="SCI-B"):
    """Blue science, 60 a minute: 16 machines at 3.75 each."""
    module = Module(name, "60 blue science a minute")
    width = 24
    module.row(BELT, 6, -1, width - 1, EAST)
    module.row(BELT, 7, -1, width - 1, EAST)
    _strip(module, 0, 8, "chemical-science-pack")
    module.row(BELT, 0, 0, width, EAST)
    module.row(BELT, 13, 0, width, EAST)
    _join(module, width + 1)
    module.port("engine-sulfur", "belt-in", -1, 6, ["engine-unit", "sulfur"])
    module.port("red", "belt-in", -1, 7, ["advanced-circuit"])
    module.port("out", "belt-out", width + 2, 6, ["chemical-science-pack"])
    module.targets = {"chemical-science-pack": 60}
    return module


def merge(name="MERGE", belt=RED_BELT):
    """Two belts into the two lanes of one: what most feed rows need.

    The belt arriving from the north (column 0, flowing south) fills the left
    lane of the outgoing belt; the one from the south fills the right lane.
    Rotate the print to suit; the lanes follow.
    """
    module = Module(name, "north belt to left lane, south belt to right lane")
    _join(module, 0, belt, top=0, bottom=6, middle=3)
    module.port("left", "belt-in", 0, 0, ["iron-plate"])
    module.port("right", "belt-in", 0, 6, ["copper-plate"])
    module.port("out", "belt-out", 1, 3, ["iron-plate"])
    module.targets = {"iron-plate": 900, "copper-plate": 900}
    return module


def probe_unresearched():
    """Answers: can a player place ghosts of what is not researched yet?

    Paste it on a new map before researching anything. Which of these appear
    as ghosts decides whether robot layers and recipes need separate prints.
    """
    module = Module("PROBE-unresearched", "paste on a new map, then report")
    module.add("roboport", 0, 0)
    module.add("assembling-machine-2", 5, 0, recipe="processing-unit")
    module.add("assembling-machine-1", 9, 0, recipe="automation-science-pack")
    module.add("assembling-machine-1", 13, 0, recipe="logistic-science-pack")
    module.add("oil-refinery", 17, 0, recipe="advanced-oil-processing")
    module.add("transport-belt", 23, 0, SOUTH)
    module.add("small-electric-pole", 24, 0)
    return module


def all_modules():
    modules = [
        smelter("SMELT-iron-stone", "iron-ore", "iron-plate"),
        smelter("SMELT-iron-steel", "iron-ore", "iron-plate", "steel"),
        smelter("SMELT-H-iron", "iron-ore", "iron-plate", half=True),
        smelter("SMELT-H-copper", "copper-ore", "copper-plate", half=True),
        smelter("SMELT-copper-stone", "copper-ore", "copper-plate"),
        smelter("SMELT-copper-steel", "copper-ore", "copper-plate", "steel"),
        smelter("STEEL-stone", "iron-plate", "steel-plate", rate=180),
        smelter("STEEL-steel", "iron-plate", "steel-plate", "steel", rate=360),
        # Two stone make a brick, so the ore lane (15/s on red) limits it.
        smelter(
            "BRICK-steel", "stone", "stone-brick", "steel", half=True, rate=900
        ),
        mall_2(),
        science_m(),
        science_rg(),
        oil(),
        chemistry(),
        green_circuits(),
        red_circuits(),
        engines(),
        science_b(),
        oil(
            "OIL-basic",
            recipe="basic-oil-processing",
            targets={"petroleum-gas": 7 * 9 * 60},
        ),
        oil("OIL-switch", recipe="basic-oil-processing", switch_at=10),
        oil_with_light_load("OIL-light-load"),
        oil_with_light_load(
            "OIL-light-load-gas-full",
            ("heavy-oil", "light-oil", "petroleum-gas"),
        ),
        labs(),
        merge(),
        miner("MINE-iron", "iron-ore"),
        power(),
        turrets(),
        mall_1(),
        probe_unresearched(),
    ]
    from tools.blueprints.late import late_modules

    modules[-1:-1] = late_modules()
    return {module.name: module for module in modules}
