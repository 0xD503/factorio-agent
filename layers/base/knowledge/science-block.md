---
title: Belts, lanes and a science block that worked
tags: logistics, layout, science
game: >=2.0
verified: 2.0.77
author: Claude (first run to a rocket launch, 2026-10)
---

- Two belts side by side; assemblers in a band beside them take from the near
  belt with an inserter and from the far belt with a long-handed inserter, both
  on the same side of the machine. Intermediates pass between neighbours by an
  inserter in the one-tile gap. Labs straddle the last two assemblers and take
  packs by direct insertion; a second lab is chained with an inserter.
- An inserter drops on the far lane of a belt. A belt joining another from the
  side puts everything on the near lane. Turns keep lanes. That gives every belt
  two private lanes (e.g. iron and gears, copper and transport belts).
- The first assembler on a belt takes everything it can: a gear assembler turned
  all the iron into gears while something downstream kept removing gears. A
  chest at a belt end is such a sink unless its inserter is filtered
  (`filter X Y iron-plate`).
- Low-volume branches do not need a splitter: an inserter taking from the belt
  onto the first tile of a new belt is enough.
- Electric drill straight into a furnace, coal by long inserter from a belt two
  tiles away, plates out by inserter onto a belt: a unit with no ore belt. Stone
  furnace 19 plates a minute, steel furnace 30 (drill-limited).
- A drill whose 5x5 area touches a second ore mines both, and puts the wrong ore
  on the belt. `fx ents` shows `mining=`; keep the whole area on one ore.
- Mixed-item lanes plus long inserters are fragile: when a machine vanishes for
  a moment (rebuild, upgrade) its inserters grab whatever passes and jam. The
  `unjam` skill finds and resets them; filtered fast inserters prevent it.
- Do not leave the character standing on a belt; it gets carried to the end.
