---
title: Blueprint design lessons
tags: blueprints, oil, inserters, circuits
game: >=2.0
verified: 2.1.24
author: Claude (blueprint bench work with 0xD503, 2026-11)
written: 2026-11-02
---

- Ghosts of buildings and recipes not yet researched can be placed from a
  blueprint, and keep their recipes. A module can be one blueprint from the
  start and fill in as research arrives.
- Basic and advanced oil processing use the same refinery inlet for crude and
  the same outlet for petroleum. A refinery block plumbed for advanced oil runs
  basic oil unchanged; only the recipe changes.
- A refinery stops when any output is full, including petroleum while
  something still wants light oil. Give petroleum an overflow (solid fuel from
  petroleum behind a pump that opens at a high tank level).
- A storage tank connects at two opposite corners. A tank beside a pipe can
  join two pipes you meant to keep apart, such as both sides of a gating pump.
- Circuit wires in a blueprint longer than the wire reach (9 tiles for a pump
  and a tank) are dropped when it is built, without a warning. A pump on no
  circuit network ignores its condition and simply runs. Route the wire
  through a pole in between.
- Single-inserter throughput bounds many machines: a basic inserter moves
  about 50 items a minute. Recipes with many parts (grenades take 15 items,
  inserters three, walls five bricks) need a second inserter or a fast one.
- Two items into one chest with a slot limit: whichever comes first fills every
  slot and the other never gets in. Give each item its own chest, filled by a
  filter inserter (fast inserters take filters).
- After the launch, satellites make space science in the base game: 1000 packs
  a launch, landing on a cargo landing pad (unlocked with the silo; 8x8, 80
  slots), from which inserters take them. A rocket with a satellite waits for
  a click unless the silo's automatic launch is on; it is off by default, and
  a blueprint can turn it on (`launch_to_orbit_automatically`).
- The first launch ends a freeplay game with the victory screen; choose to
  continue.
