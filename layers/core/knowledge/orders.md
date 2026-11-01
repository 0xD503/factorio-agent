---
title: How orders behave
tags: basics, orders
game: >=2.0
verified: 2.0.77
author: Claude (first run, 2026-10)
---

- `craft` only queues and returns at once. A `place` right after it fails with "no X in inventory"; use `craft X N wait` or `wait craft` first.
- Hand-crafting uses whatever is in the inventory as an ingredient: a refinery ate the pipes made for its plumbing, long inserters eat inserters, labs eat belts. Craft the consumer first, then the parts to place.
- The hand-crafting queue is first in, first out: 64 productivity modules once blocked every repair craft for 16 minutes. `uncraft RECIPE [N]` cancels queued crafts and returns the ingredients.
- `craft transport-belt N` counts crafts, not belts: N crafts make 2N belts.
- A failed order drops every order queued after it. Put risky steps at the end of a batch or in their own call.
- `mine X Y` with a bare position takes what is on that tile only. After any bulk removal run `fx status` and look for `no_power` (removing a pole by accident cuts a whole block).
- `place` of an assembling machine ignores the direction; its fluid inlet ends up where the default puts it. For fluid recipes check `pipes=` in `fx ents` and `rotate X Y DIR` until the inlet sits on the pipe.
- `place` walks to wherever the engine finds reach, which can be on the wrong side of the target (towards a nest). In danger, walk explicitly to a safe point within reach first.
- Reach: buildings about 9 tiles; ore 2.7 tiles; trees and rocks only when adjacent. `mine` and `place` walk into reach by themselves.
- `walk` to a water tile fails with "no walkable path"; pick a land tile.
- Never send the character on a long walk with only a destination: the pathfinder takes the shortest way, past nests if need be. Give waypoints.
- A corpse lying on a belt or building: `take` picks the building. Use `fx call` with `"name": "character-corpse"`.
- Mining a turret returns its magazines (into the ammo slots first). `put` also draws from the ammo slots.
- `equip ITEM [SLOT]` moves a gun, armour or ammunition into its slot; after a respawn and corpse recovery, `equip submachine-gun 1`.
