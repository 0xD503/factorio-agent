---
title: Directions, drop positions and fluid connections
tags: placement, fluids
game: >=2.0
verified: 2.0.77
author: Claude (first run to a rocket launch, 2026-10)
---

- Inserter `dir` is the side it takes from; it drops on the opposite side. To move items west to east, place it with `w`. The map arrow shows the direction items move.
- Burner drill drop positions: facing `n` at (X, Y) drops at (X-0.5, Y-1.3); facing `e` at (X+1.3, Y-0.5); facing `w` at (X-1.3, Y+0.5). A 2x2 stone furnace centred one tile past the drill's edge catches the drop. `fx ents` prints `drop=`.
- Drills drop on the near lane of the belt in front, so drills on both sides of a belt fill both lanes.
- Offshore pump: on the land tile at the shore with `dir` pointing at the water; the pipe connects on the land side. Few spots are valid: probe with `fx call can_place '{"item":"offshore-pump","x":..,"y":..,"dir":"w"}'`.
- Boiler facing north (3 wide, 2 tall): water in and out at the west and east ends of the south row, steam out of the middle of the north side. Boilers pass water through, so a new boiler can sit against an existing one.
- Steam engine facing north: 3 wide, 5 tall, a connection at each end of the long axis. It must also be inside a pole's supply area.
- `fx ents` prints `pipes=x,y ...` for anything with fluid connections: where a pipe must go. `(open)` means nothing is connected there.
- Underground pipe: a pair spans 11 tiles (pieces at x and x+10); the next pair starts at x+11. `dir` of a piece is the side of its open end. 121 tiles from a lake delivered water at once.
- Pumpjack output: facing `n` at (cx+1, cy-2), facing `s` at (cx-1, cy+2).
- Oil refinery facing `s`: crude in at (cx-1, cy-3). On basic oil processing the gas comes out of the right-hand outlet (cx+2 on the outlet side), not the left one.
- Chemical plant facing `n`: inlets at (cx-1, cy-2) and (cx+1, cy-2). If the fluids are on the wrong sides it shows `fluid_ingredient_shortage` with no fluids; `mirror X Y` swaps them.
- Pipes block walking like buildings (not checked in detail); leave gaps or go underground.
