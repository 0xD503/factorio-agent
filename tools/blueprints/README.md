# The 6-hour rocket blueprint set

A set of modules for a base game (no Space Age) run on default settings: 60 red,
green and blue science a minute, 30 purple and yellow, about 15 military, and a
rocket about half an hour after the silo research. Everything keeps running
after the launch.

Status: every module passes the bench (`python3 tools/bench/run.py all`), and
the first ones were checked by eye in the game. The set has not been played as
a whole yet: the build order and times below are a plan until a timed run
replaces them.

## Getting the blueprints

```
python3 tools/blueprints/build.py
```

writes one string per module to `dist/blueprints/`, and `BOOK.txt` with every
module of the run in build order. In the game: blueprint library, "Import
string", paste. `python3 tools/blueprints/plan.py` lists how many copies of each
module the run needs, the area they cover and what it takes to build them.

## How the modules fit

- Most modules have two feed belts on rows 6 and 7, flowing east, with machines
  above and below. Each module's description (shown in the game) says what goes
  on which lane. Outputs leave on the east side.
- Lanes matter: a feed like "copper left, iron right" means one item per lane.
  Side-load a belt from the left to fill the left lane, from the right for the
  right lane.
- Each module is one blueprint. Ghosts of buildings and recipes you have not
  researched yet can be placed and keep their recipes, so paste the final
  module early and let it fill in.
- Stone furnaces and yellow belts upgrade in place to steel furnaces and red
  belts: every smelter position stays the same.

## Build order

| Stage | Build | Then research |
|---|---|---|
| 0, burner | Burner drills on iron, coal and stone; stone furnaces; one boiler and engine; a lab | `automation`, `logistics`, `gun-turret` |
| 1, seed | `PWR` (fill it as you go), `MINE`, `SMELT-H` iron and copper (stone), `TUR` by the first polluters | `stone-wall`, `military`, `steel-processing`, `logistic-science-pack`, `fast-inserter` |
| 2, mall | `MALL-1` on the half-lane iron, copper for its circuits | `electric-energy-distribution-1`, `automation-2`, `advanced-material-processing` |
| 3, science | `SMELT` columns, `STEEL`, `BRICK`, `SCI-RG`, `LAB`, `SCI-M`, `MALL-2` | `engine`, `fluid-handling`, `oil-gathering`, `plastics`, `sulfur-processing`, `advanced-circuit`, `chemical-science-pack`, `heavy-armor`, `military-2`, `military-science-pack`, `logistics-2`, `research-speed-1`, `research-speed-2`, `circuit-network` |
| 4, oil and blue | `OIL` (on basic oil until researched), `CHEM`, `GREEN`, `RED` x2, `ENGINE`, `SCI-B` | `advanced-oil-processing`, `lubricant`, `battery`, `electric-engine`, `robotics`, `construction-robotics`, `logistic-robotics`, `worker-robots-speed-1` |
| 5, robots | `FRAME`, `BOTS`; from here robots build the rest | `railway`, `modules`, `productivity-module`, `speed-module`, `flammables`, `rocket-fuel`, `low-density-structure`, `processing-unit`, `advanced-material-processing-2`, `production-science-pack`, `utility-science-pack`, `research-speed-3`, `research-speed-4` |
| 6, late science | `SCI-P`, `LDS`, `BLUE`, `SCI-Y` | `solar-energy`, `electric-energy-accumulators`, `concrete`, `radar`, `speed-module-2`, `productivity-module-2`, `speed-module-3`, `productivity-module-3`, `logistic-system`, `rocket-silo` |
| 7, rocket | `MOD`, `RF`, `CONCRETE`, `SILO` | after launch: mining productivity, robot speed |

That queue costs about 8,150 red, 7,900 green, 5,000 blue, 1,600 purple and
1,500 yellow (checked against the game's data), plus military research for
defence.

## What to stock before each stage

- Before stage 3: about 100 stone furnaces by hand (5 stone each) for the first
  two smelter columns, and boilers and engines for the next `PWR`.
- Before stage 4: the oil block takes 7 refineries, 8 chemical plants, about
  430 pipes and 60 underground pipes (from `MALL-2`), plus pumpjacks for about
  1,300% total yield.
- Before stage 7: the silo takes 1,000 steel, 1,000 concrete (`CONCRETE` makes
  it in 11 minutes), 200 electric engines, 200 processing units and 100 pipes;
  four productivity module 3s come from `MOD`.

## After the launch

- Build `SAT` near the silo, inside its roboport's area: it makes solar panels,
  accumulators and radars into passive provider chests. The silo module's
  satellite machine asks robots for those and for processing units, low
  density structures and rocket fuel, which the silo's feed belts keep in two
  passive provider chests. A satellite goes into the silo by inserter and the
  rocket launches by itself.
- 1000 space science packs land on the pad and leave on its belt; run it to the
  free rows next to the labs (rows -1 and 14 of `LAB`, reachable with
  long-handed inserters).
- `python3 tools/blueprints/plan.py` lists the copies that take purple and
  yellow to 60 and the extra oil and smelting for them.

## Things the bench found that matter when you build

- One basic inserter moves about 50 items a minute. A recipe with many parts
  (grenades, inserters, walls) needs two inserters or a fast one.
- The oil block's light-oil cracking is gated by a tank and a pump on a wire.
  If you move parts of it, keep the wire within 9 tiles and keep the tank's
  other corner off the gated pipe, or the gate stops working without any sign.
- Full petroleum would stop the refineries; the block turns surplus into solid
  fuel on a belt. Send that belt to rocket fuel or to boilers.
