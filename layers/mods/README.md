# Mod layers

One folder per mod, named exactly as the mod (`space-age`, `quality`, `elevated-rails`,
or a portal mod's name), with `knowledge/` and `skills/` inside, like `layers/base/`.

A mod's layer is used only when that mod is active in the session, and it sits above the
layers of the mods it depends on (read from the mod's `info.json`), so base knowledge and
skills keep applying unless a mod layer overrides an item with the same id.

Items can narrow themselves further with `mods:` and `game:` in their header, and skills can
list the prototypes they need in `META["requires"]`; a skill whose prototypes a mod removed
refuses to run.

Nothing has been written for any mod yet.
