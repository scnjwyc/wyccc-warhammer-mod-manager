# Game Data Patch Priority and Character Health Fix Design

## Goal

Make launch-time unit-scale patches reliably win every enabled DB-table row conflict, and make the optional lord/hero health setting scale the character's complete base health instead of only its bonus component.

## Confirmed root causes

The generated DB entries currently use the fixed internal name `!!!!wyccc_game_data_vNNNN`. Total War resolves conflicting DB rows by internal table-file name, independently of external Pack load order. Enabled MODs with names such as `!!!!_...` or `!!!!!!!...` therefore override the generated rows again. This explains both a completely ineffective generated Pack and partial results inside one MOD.

Lord/hero health currently multiplies only `land_units_tables.bonus_hit_points`. Displayed base health is the sum of that value and the referenced `battle_entities_tables.hit_points`. Custom entities can put a material share of health in the latter field, so multiplying only the bonus produces an incomplete or nearly invisible change.

## Design

- Derive each generated table entry's leading `!` prefix from the highest-priority effective source entry for that table. Use one more leading `!` than any source and verify the resulting name compares ahead of every source candidate before writing the Pack.
- Read all supported `battle_entities_tables` versions as an input-only table when character health scaling is enabled.
- For each effective lord/hero land unit, resolve `man_entity`, calculate `base_health = hit_points + bonus_hit_points`, multiply that total, and write the remainder back to `bonus_hit_points`. Do not modify shared battle-entity rows.
- Treat an unresolved character land-unit or battle-entity reference as generation failure instead of logging a misleading success.
- Keep `battle_entities_tables` out of the generated Pack because it is only needed to calculate character-specific bonus health.
- Bump the builder version so every existing fingerprint is invalidated on the next launch.

## Verification

- A regression fixture with a seven-`!` MOD table must still resolve to the scaled generated row after simulating Total War's internal table priority.
- A character with substantial entity HP must end with an exactly multiplied total HP while its model count remains unchanged.
- Existing unit, friendly-fire, fingerprint, launch, and Pack tests must remain green.
- A real installed Workshop corpus audit must show that every generated table name outranks every enabled source table name.
