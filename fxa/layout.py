"""Layout helpers available to skills: turn tile coordinates into place orders.

Tile (x, y) is the square whose centre is (x + 0.5, y + 0.5). Everything here
takes whole tile numbers for 1x1 things.
"""

from fxa.game import place

STEP_DIR = {(1, 0): "e", (-1, 0): "w", (0, 1): "s", (0, -1): "n"}


def tiles_along(corners):
    """Every tile on a path through the given corner tiles (axis-aligned
    legs)."""
    corners = [tuple(int(v) for v in c) for c in corners]
    path = [corners[0]]
    for x2, y2 in corners[1:]:
        x1, y1 = path[-1]
        if x1 != x2 and y1 != y2:
            raise ValueError(
                f"leg from {(x1, y1)} to {(x2, y2)} is not straight"
            )
        dx = (x2 > x1) - (x2 < x1)
        dy = (y2 > y1) - (y2 < y1)
        while (x1, y1) != (x2, y2):
            x1, y1 = x1 + dx, y1 + dy
            path.append((x1, y1))
        if len(path) > 100_000:
            raise ValueError("path too long")
    return path


def belt_path(corners, item="transport-belt", end_dir=None):
    """Belts along a path; each one points at the next, the last keeps going
    straight."""
    path = tiles_along(corners)
    orders = []
    for index, (x, y) in enumerate(path):
        if index + 1 < len(path):
            nx, ny = path[index + 1]
            direction = STEP_DIR[(nx - x, ny - y)]
        elif len(path) > 1:
            px, py = path[index - 1]
            direction = end_dir or STEP_DIR[(x - px, y - py)]
        else:
            direction = end_dir or "n"
        orders.append(place(item, x + 0.5, y + 0.5, direction))
    return orders


def at_tiles(item, tiles, direction=None):
    """One 1x1 entity per tile, e.g. poles or inserters."""
    return [place(item, x + 0.5, y + 0.5, direction) for x, y in tiles]


def inserter(x, y, takes_from, item="inserter"):
    """An inserter on tile (x, y). `takes_from` is the side it picks up from."""
    return place(item, x + 0.5, y + 0.5, takes_from)
