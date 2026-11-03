---
title: Ghosts, blueprints, chest limits and robots
tags: basics, orders, robots, blueprints
game: >=2.0
verified: 2.1.24
author: Claude (speedrun harness work, 2026-11)
---

- `limit X Y SLOTS` caps a chest (it needs reach); `limit X Y` removes the cap.
  `fx ents` shows `limit=`.
- `ghost ITEM X Y [DIR] [recipe=NAME] [ug=input|output]` plans one building. It
  needs no item and no reach, only ground that has been seen, and it fails on a
  tree or a rock. A `place` on a ghost replaces the ghost.
- `blueprint NAME X1 Y1 X2 Y2` copies the buildings in an area with their
  recipes, directions, chest limits, inserter filters and modules, but not
  circuit wires. Poles connect themselves when built. Blueprints stay in the
  save.
- `stamp NAME X Y [DIR]` makes the ghosts, with the top-left tile of the copied
  area at tile (X, Y). With a direction the area turns around that corner, so
  `e` puts it to the left of X. It reports `ghosts` and `of`: fewer means
  something was in the way. Trees and rocks in the way are marked for robots
  instead.
- `fill X1 Y1 X2 Y2` builds the ghosts in an area by hand, nearest first,
  walking into reach. It reports `built`, `missing` (items not in the inventory)
  and `blocked` (something stands there). This is how a stamp gets built before
  there are robots.
- Robots: a roboport with power and construction robots builds ghosts within
  about 25 tiles on each side, but only with items in the same network, usually
  a storage or passive provider chest. Each separate network needs its own
  chest.
- `deconstruct X1 Y1 X2 Y2` marks own buildings; `tree`, `rock` or a building
  name narrows it. `deconstruct X1 Y1 X2 Y2 entity-ghost` removes ghosts at
  once. `upgrade X1 Y1 X2 Y2 FROM TO` marks buildings to replace (stone to steel
  furnace, belts). `modules X1 Y1 X2 Y2 MODULE [NAME]` asks robots to fill free
  module slots. `unmark X1 Y1 X2 Y2` takes back deconstruct and upgrade marks.
- `fx bots` shows networks and free robots, how many ghosts and marks are
  waiting, ghosts out of every network's range, ghosts whose item the network
  lacks, and the blueprints. Check it before giving robots more work.
- Not available: requester chest requests, personal logistics and importing
  blueprint strings.
