---
title: Running the game, interruptions, saves
tags: basics, harness
game: >=2.0
verified: 2.0.77
author: Claude (first run, 2026-10)
---

- Solo: the game is paused between calls; `fx do` runs until the orders finish or something interrupts: `enemy nearby`, `character damaged`, `building destroyed`, `research queue empty`, `chat` (someone mentioned the agent), `character died`. `fx resume` continues the queue.
- Co-op: the game never pauses for the agent. Orders start as soon as they are queued; `fx do` only waits for them. Keep batches short enough to answer chat in time.
- Biters come to wherever the character is, within 25 tiles, and interrupt a wait. Wait in the middle of the base.
- After any fight: `fx state` (deaths, health) and `fx find character-corpse`. Respawn is at the spawn point after 10 seconds; the corpse keeps everything, and `take X Y` on it gives it all back.
- Rolling saves `auto-1..5` are written every 10 minutes of played time (solo) or by the server (co-op). `fx save NAME` writes a checkpoint. Loading a checkpoint is allowed but must be reported to the players.
- A server writes its save over the file it was started from when it stops. Never copy a save over the one a running server was started from.
- Each RCON call costs one server update (1/60 s) however small; `fx call batch` sends several requests in one.
