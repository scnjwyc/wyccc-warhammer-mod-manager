# Single-Entity Health Mode Design

## Goal

Add a selectable rule for one-model regular monsters to the existing unit-scale feature. The default remains model-count scaling. In health mode, eligible regular monsters receive the same total-health multiplier while retaining one model.

## Eligibility

An eligible unit must satisfy all of the following after enabled MOD rows and the vanilla DB have been resolved:

- Its `main_units_tables.num_men` is exactly `1`.
- Its `main_units_tables.is_monstrous` flag is true.
- Its caste is neither `lord` nor `hero`.
- Its referenced `land_units_tables` row has no `engine` binding and no `num_engines` value greater than zero.

This includes ordinary monsters such as the Star Dragon. It excludes lords, heroes, artillery, and any other engine-backed unit. The engine exclusion remains explicit even when a MOD marks an engine as monstrous.

## Settings and Runtime Flow

- Persist `single_entity_unit_mode` as either `scale` or `health`; normalize invalid and legacy values to `scale`.
- Default new and migrated settings to `scale`, preserving current behaviour.
- Include the normalized mode in the game-data patch fingerprint and increment the game-data builder version so installed patches are rebuilt once.
- Apply the selected mode only when the Dynamic Unit Size Workshop dependency is available. Without that dependency, use `scale` as the effective mode.
- Continue to treat a multiplier of `1` as disabled. The selected mode alone never creates a patch.

## Patch Generation

In `scale` mode, retain current `num_men`, `num_mounts`, and `num_engines` multiplication for every non-lord, non-hero unit.

In `health` mode, identify eligible regular monsters before mutating rows. For each one, leave `main_units_tables.num_men`, `land_units_tables.num_mounts`, and `land_units_tables.num_engines` unchanged. Resolve its `land_units_tables.man_entity`, calculate `battle_entities_tables.hit_points + land_units_tables.bonus_hit_points`, multiply that total, and write the remainder to `bonus_hit_points`. Keep `battle_entities_tables` input-only.

Apply the model-count decision by `main_units_tables` row, not merely by `land_unit` key. If a non-eligible main-unit row shares a land-unit row with an eligible monster, it continues through the normal model-count scaling path.

Other non-character units, including engine units, retain the normal scale-mode path. The existing lord/hero health checkbox stays independent.

## UI and Observability

- Add an inline binary range control below the unit-scale multiplier, titled “Single-entity unit rule”, with `Health` and `Scale` endpoints.
- Explain that health mode applies only to ordinary single-entity monsters and keeps engine units on the scale rule.
- Disable the control together with the unit-scale feature when its Workshop dependency is unavailable.
- Include mode-specific statistics in the generated patch result so logs and status can distinguish model-scaled units from health-scaled single-entity monsters.
- Add all new UI strings to Chinese, English, Korean, Russian, Japanese, and Spanish catalogs.

## Verification

- A health-mode fixture must show a Star-Dragon-like monster retaining one model while its complete HP is multiplied exactly.
- A one-model monstrous engine fixture must retain the existing model/engine scaling and receive no health change.
- Default scale mode must preserve the current unit scaling result.
- Settings persistence, API filtering, fingerprint invalidation, UI save payload, and translation coverage must all be covered by automated tests.
