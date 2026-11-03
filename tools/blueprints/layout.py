"""Building a blueprint from whole tile coordinates.

Every entity is placed by its top-left tile, so a layout reads like the map.
Blueprint positions are entity centres: 1x1 and 3x3 entities sit on .5 centres,
2x2 entities on whole numbers. A module also names its ports, which is what
other modules and the bench connect to.
"""

from tools.blueprints import codec

NORTH, EAST, SOUTH, WEST = 0, 4, 8, 12

# Tile width and height, facing north. Anything not listed is 1x1.
SIZES = {
    "stone-furnace": (2, 2),
    "steel-furnace": (2, 2),
    "assembling-machine-1": (3, 3),
    "assembling-machine-2": (3, 3),
    "assembling-machine-3": (3, 3),
    "electric-furnace": (3, 3),
    "chemical-plant": (3, 3),
    "lab": (3, 3),
    "beacon": (3, 3),
    "roboport": (4, 4),
    "substation": (2, 2),
    "storage-tank": (3, 3),
    "oil-refinery": (5, 5),
    "rocket-silo": (9, 9),
    "cargo-landing-pad": (8, 8),
    "electric-mining-drill": (3, 3),
    "boiler": (3, 2),
    "steam-engine": (3, 5),
    "gun-turret": (2, 2),
    "splitter": (2, 1),
    "pump": (1, 2),
    "fast-splitter": (2, 1),
}

# Wire reach in tiles and supply-area width, from the game's prototypes.
POLES = {
    "small-electric-pole": (7.5, 5),
    "medium-electric-pole": (9.0, 7),
    "big-electric-pole": (30.0, 4),
    "substation": (18.0, 18),
}

# Entities that need a pole's supply area to run.
POWERED = {
    "inserter",
    "long-handed-inserter",
    "fast-inserter",
    "bulk-inserter",
    "assembling-machine-1",
    "assembling-machine-2",
    "assembling-machine-3",
    "electric-mining-drill",
    "electric-furnace",
    "chemical-plant",
    "oil-refinery",
    "lab",
    "beacon",
    "roboport",
    "pump",
    "steam-engine",
    "rocket-silo",
    "cargo-landing-pad",
}

# Wire connector id of a pole's copper connection in a blueprint's `wires`.
COPPER = 5
GREEN = 2
CIRCUIT_REACH = 9

GAME_VERSION = codec.game_version(2, 1, 24)


class Port:
    """Where a module meets the outside.

    kind: belt-in, belt-out, fluid-in or fluid-out. `x, y` is the tile of the
    module's own belt or pipe. `items` is what a belt carries, one entry per
    lane (left, right) when the lanes differ.
    """

    def __init__(self, name, kind, x, y, items, rate=None):
        self.name, self.kind, self.x, self.y = name, kind, x, y
        self.items, self.rate = list(items), rate
        self.blocked = False

    def as_dict(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "items": self.items,
            "rate": self.rate,
            "blocked": self.blocked,
        }


class Module:
    def __init__(self, name, description=""):
        self.name, self.description = name, description
        self.entities, self.ports = [], []
        # What the bench checks, per minute: item -> minimum.
        self.targets = {}
        # What the bench checks in chests: item -> minimum held.
        self.stock = {}
        # Bench settings: ore to lay under the module, power to draw in watts,
        # generated power to reach in watts.
        self.ore = None
        self.power_demand = None
        self.power_target = None
        # Research to run (name, research speed bonus) and units a minute.
        self.research = None
        self.research_target = None
        # (entity, entity) joined by green wire, and bench fluid targets per
        # minute.
        self.circuit_links = []
        self.fluid_targets = {}
        # Bench: minute at which refineries change to advanced oil processing.
        self.switch_at = None
        # Bench: rocket parts the silo must reach.
        self.rocket_parts = None
        # Bench: totals that must have left by the end (item -> count), and
        # items the bench keeps in a logistic network for the module.
        self.totals = {}
        self.supply = {}
        self._taken = {}

    def add(self, name, x, y, direction=NORTH, **fields):
        """Place `name` with its top-left tile at (x, y)."""
        width, height = SIZES.get(name, (1, 1))
        if direction in (EAST, WEST):
            width, height = height, width
        for tx in range(x, x + width):
            for ty in range(y, y + height):
                other = self._taken.get((tx, ty))
                if other:
                    raise ValueError(
                        f"{self.name}: {name} at ({x},{y}) overlaps {other}"
                    )
                self._taken[(tx, ty)] = f"{name} at ({x},{y})"
        entity = {
            "entity_number": len(self.entities) + 1,
            "name": name,
            "position": {"x": x + width / 2, "y": y + height / 2},
        }
        if direction:
            entity["direction"] = direction
        entity.update(fields)
        self.entities.append(entity)
        return entity

    def belt(self, name, x, y1, y2, direction=NORTH):
        """A straight vertical run of belt between two tile rows."""
        for y in range(min(y1, y2), max(y1, y2) + 1):
            self.add(name, x, y, direction)

    def row(self, name, y, x1, x2, direction=EAST):
        """A straight horizontal run of belt between two tile columns."""
        for x in range(min(x1, x2), max(x1, x2) + 1):
            self.add(name, x, y, direction)

    def unpowered(self):
        """Names and positions of machines outside every pole's supply area."""
        areas = []
        for e in self.entities:
            if e["name"] in POLES:
                half = POLES[e["name"]][1] / 2
                x, y = e["position"]["x"], e["position"]["y"]
                areas.append((x - half, y - half, x + half, y + half))
        missing = []
        for e in self.entities:
            if e["name"] not in POWERED:
                continue
            width, height = SIZES.get(e["name"], (1, 1))
            if e.get("direction") in (EAST, WEST):
                width, height = height, width
            x, y = e["position"]["x"], e["position"]["y"]
            left, right = x - width / 2, x + width / 2
            top, bottom = y - height / 2, y + height / 2
            if not any(
                left < x2 and right > x1 and top < y2 and bottom > y1
                for x1, y1, x2, y2 in areas
            ):
                missing.append((e["name"], x, y))
        return missing

    def _footprint(self, e):
        width, height = SIZES.get(e["name"], (1, 1))
        if e.get("direction") in (EAST, WEST):
            width, height = height, width
        x, y = e["position"]["x"], e["position"]["y"]
        return x - width / 2, y - height / 2, x + width / 2, y + height / 2

    def auto_poles(self, name="medium-electric-pole"):
        """Add poles until every machine has power and all poles connect.

        Greedy: each pole goes on the free tile that powers the most machines
        still without power; then poles bridge whatever groups are left.
        """
        reach, supply = POLES[name]
        half = supply / 2
        xs = [x for x, _ in self._taken]
        ys = [y for _, y in self._taken]
        free = [
            (tx, ty)
            for tx in range(min(xs) - 1, max(xs) + 2)
            for ty in range(min(ys) - 1, max(ys) + 2)
            if (tx, ty) not in self._taken
        ]

        def covers(tile, box):
            cx, cy = tile[0] + 0.5, tile[1] + 0.5
            left, top, right, bottom = box
            return (
                left < cx + half
                and right > cx - half
                and top < cy + half
                and bottom > cy - half
            )

        while True:
            missing = self.unpowered()
            if not missing:
                break
            boxes = [
                self._footprint(e)
                for e in self.entities
                if e["name"] in POWERED
                and (e["name"], e["position"]["x"], e["position"]["y"])
                in missing
            ]
            best = max(free, key=lambda t: sum(covers(t, b) for b in boxes))
            if not any(covers(best, b) for b in boxes):
                raise ValueError(f"{self.name}: no tile powers {missing[0]}")
            self.add(name, *best)
            free.remove(best)

        def dist(a, b):
            return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

        while True:
            groups = self._pole_groups()
            if len(groups) <= 1:
                return
            # Bridge from the first group toward its nearest other pole.
            first, rest = groups[0], [p for g in groups[1:] for p in g]
            _, a, b = min(
                (dist(p, q), p, q) for p in first for q in rest
            )
            candidates = [
                t for t in free if dist((t[0] + 0.5, t[1] + 0.5), a) <= reach
            ]
            if not candidates:
                raise ValueError(f"{self.name}: cannot bridge poles")
            best = min(
                candidates, key=lambda t: dist((t[0] + 0.5, t[1] + 0.5), b)
            )
            self.add(name, *best)
            free.remove(best)

    def _pole_groups(self):
        """Poles as (x, y, name), grouped by what their wires can reach."""
        poles = [
            (e["position"]["x"], e["position"]["y"], e["name"])
            for e in self.entities
            if e["name"] in POLES
        ]
        groups, left = [], list(poles)
        while left:
            group, edge = [left.pop()], 0
            while edge < len(group):
                p = group[edge]
                edge += 1
                for q in list(left):
                    d = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5
                    if d <= min(POLES[p[2]][0], POLES[q[2]][0]):
                        group.append(q)
                        left.remove(q)
            groups.append(group)
        return groups

    def port(self, name, kind, x, y, items, rate=None):
        self.ports.append(Port(name, kind, x, y, items, rate))

    def bill(self):
        """Items needed to build this module, name -> count."""
        out = {}
        for entity in self.entities:
            out[entity["name"]] = out.get(entity["name"], 0) + 1
        return dict(sorted(out.items()))

    def box(self):
        """Width and height of the area the module's entities cover."""
        xs = [x for x, _ in self._taken]
        ys = [y for _, y in self._taken]
        return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1

    def wires(self):
        """Copper links joining all poles, shortest first (a spanning tree).

        Raises if the poles cannot all reach each other.
        """
        poles = [e for e in self.entities if e["name"] in POLES]
        if not poles:
            return []

        def distance(a, b):
            ax, ay = a["position"]["x"], a["position"]["y"]
            bx, by = b["position"]["x"], b["position"]["y"]
            return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

        links, joined = [], {poles[0]["entity_number"]}
        while len(joined) < len(poles):
            best = None
            for a in poles:
                if a["entity_number"] not in joined:
                    continue
                for b in poles:
                    if b["entity_number"] in joined:
                        continue
                    reach = min(POLES[a["name"]][0], POLES[b["name"]][0])
                    d = distance(a, b)
                    if d <= reach and (best is None or d < best[0]):
                        best = (d, a, b)
            if best is None:
                raise ValueError(f"{self.name}: poles do not all connect")
            _, a, b = best
            joined.add(b["entity_number"])
            links.append(
                [a["entity_number"], COPPER, b["entity_number"], COPPER]
            )
        return links

    def blueprint(self):
        """The dict a blueprint string holds."""
        body = {
            "item": "blueprint",
            "label": self.name,
            "entities": self.entities,
            "version": GAME_VERSION,
        }
        if self.description:
            body["description"] = self.description
        wires = self.wires()
        for a, b in self.circuit_links:
            ax, ay = a["position"]["x"], a["position"]["y"]
            bx, by = b["position"]["x"], b["position"]["y"]
            if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 > CIRCUIT_REACH:
                raise ValueError(
                    f"{self.name}: {a['name']} and {b['name']} are too far "
                    "apart for a circuit wire"
                )
            wires.append(
                [a["entity_number"], GREEN, b["entity_number"], GREEN]
            )
        if wires:
            body["wires"] = wires
        return {"blueprint": body}

    def string(self):
        return codec.encode(self.blueprint())
