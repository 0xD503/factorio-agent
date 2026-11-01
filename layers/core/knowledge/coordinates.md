---
title: Coordinates, tiles and entity sizes
tags: basics, placement
game: >=2.0
verified: 2.0.77
author: Claude (first run, 2026-10)
---

- Tile (x, y) has its centre at (x+0.5, y+0.5). 1x1 and 3x3 entities sit on .5 centres; 2x2 entities on whole-number centres. The game snaps; the result of `place` reports where the entity ended up.
- `fx map` rows are labelled by tile y; the tile's centre is y+0.5.
- Layout helpers in skills (`belt_path`, `at_tiles`, `inserter`) take whole tile numbers and add the 0.5 themselves.
- Observation only covers chunks the character or a radar has revealed (in co-op also what players revealed). Unknown chunks show `?`.
