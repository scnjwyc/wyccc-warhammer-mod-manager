# Non-Spell Friendly-Fire KV Rules Design

## Goal

When the game-data setting for non-spell friendly-fire removal is enabled, include the four global projectile friendly-fire rules used by `!no_friendly_dmg.pack` in the generated runtime patch.

## Reference evidence

`X:\SteamLibrary\steamapps\common\Total War WARHAMMER III\data\!no_friendly_dmg.pack` contains `db\_kv_rules_tables\!!!friendly_fire` with these version-0 rows:

- `projectile_friendly_fire_man_height_coefficient = 0.6`
- `projectile_friendly_fire_man_radius_coefficient = 1.2`
- `projectile_friendly_fire_ignore_allies_height_coefficient = 0.6`
- `projectile_friendly_fire_ignore_allies_radius_coefficient = 1.2`

## Design

- Embed those four rows in the generator; do not read the reference Pack at runtime.
- Generate the rows only when `disable_unit_friendly_fire` is true. Spell-only friendly-fire removal must not add them.
- Read enabled `_kv_rules_tables` entries only to derive a generated internal DB filename that sorts ahead of every active source table. Emit only the four reference rows rather than copying the whole rules table.
- Add `_kv_rules_tables` version 0 to the focused DB schema so source table names and generated binary rows are validated through the same parser/serializer path.
- Record the four added rule rows in game-data statistics and count them as a real modification, so a patch is emitted even if no projectile row changed.
- Increment the game-data builder version. Existing fingerprints from before this behavior will regenerate at the next launch.

## Verification

- A regression test must prove the four rows are generated with the reference values only for the non-spell switch and that the generated table name outranks a high-priority source table.
- A spell-only fixture must prove no `_kv_rules_tables` entry is emitted.
- Patch-state tests must prove the builder version invalidates old generated output.
- Run focused game-data and patch-state tests, then the full backend suite, compile check, and whitespace check.
