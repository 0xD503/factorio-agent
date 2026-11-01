---
title: Steam power
tags: power
game: >=2.0
verified: 2.0.77
author: Claude (first run to a rocket launch, 2026-10)
---

- An electric drill on coal dropping onto a short belt, with one inserter at the
  end, keeps a boiler fuelled with no attention. One drill fuels about one
  boiler at full load.
- A boiler with no fuel takes the whole network down silently; `fx status` shows
  `no_fuel` / `no_power`. When every boiler says `no_input_fluid`, look for a
  broken water pipe first.
- Small pole: 5x5 supply area, reaches 7.5 tiles. Big poles connect 31 tiles
  apart but only supply a 4x4 area: put them right beside what they power.
- Coal drills run out. Plan a second fuel (solid fuel from oil works in boilers)
  before the first coal patch under the drills is gone.
