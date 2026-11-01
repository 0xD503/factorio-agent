---
title: Enemies, defence and turret creep
tags: combat, defence, enemies
game: >=2.0
verified: 2.0.77
author: Claude (first run to a rocket launch, 2026-10)
---

Ranges from the game data: gun turret 18; small worm 25 (200 hp), medium worm 30
(500 hp, 5 flat physical resistance), big worm 38; small spitter 13, medium
spitter 14.

- Worms outrange gun turrets and pick them off one by one: every turret must be
  within 18 tiles of every worm it is meant to kill.
- Turret creep: stand at least 25 tiles (better 30) from any live spawner while
  turrets go down. Groups of 8 turrets with 40 magazines each wiped a 44-spitter
  group in seconds; groups of 4 with 20 got eaten. Ammunition depth matters more
  than turret count.
- Waiting far behind the turrets is worse than close: out of their cover,
  spitters walk round and kill the character. Wait 4 to 6 tiles behind the
  turret group.
- Spitter and worm acid stays on the ground and keeps burning; a fight took the
  character from 250 to 5 health. Walk away after a fight and let health
  recover.
- A gun turret holds one ammunition type at a time; `put` of a second type
  fails. The `turrets` skill tops up a whole base.
- Raids grow with evolution (0.06 at 2h40m, 0.17 at 5h26m, 0.54 at 30h in the
  first run). They come from the nearest nests and hit the edges first: put
  turrets down together with any new polluting building on the edge.
- A raid group can still be inside the base after the buildings are gone: check
  for units (`fx ents X Y -r 40 --type unit --all`) before walking in to
  rebuild.
- Clearing the nests that raids come from stops the raids for hours; clearing
  them early is cheaper than rebuilding.
- In light armour, turret creep against medium worms or many spitters is how
  most of the first run's deaths happened (12 of 13). Get heavy armour and
  piercing rounds first.
