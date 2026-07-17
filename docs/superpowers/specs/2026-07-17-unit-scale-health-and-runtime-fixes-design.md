# Unit Scale, Character Health, and Runtime Fixes Design

## Scope

This change updates three connected launch and game-data behaviors:

1. Rename the visible “unit model multiplier” concept to “unit scale multiplier”, restrict it to integer values from 1 through 5, and use a slider.
2. Add an opt-in setting that scales lord and hero health by the same multiplier.
3. Remove the blocking delay when opening Game Data Modification and make Skip Intro match the supplied working reference Pack.

The work is source-only. It does not package, publish, or modify the supplied Workshop Pack.

## Unit scale contract

- Keep the persisted key `unit_model_multiplier` for compatibility with existing settings and manifests.
- Canonical values are integers `1`, `2`, `3`, `4`, or `5`.
- Legacy decimals are migrated to the nearest supported integer using half-up rounding after finite-value validation and range clamping.
- The frontend uses `input[type="range"]` with `min=1`, `max=5`, and `step=1`, plus a visible current `×` value and tick labels.
- All five built-in languages rename the feature from model-count multiplier to unit-scale multiplier and state that only whole-number multiples are supported.

Keeping the existing storage key avoids a needless destructive migration. Allowing the frontend to use integers while retaining float behavior in the backend was rejected because RPC callers and old settings could still create unsupported decimal fingerprints.

## Lord and hero health

- Add the persisted boolean `scale_lord_hero_health`, defaulting to `false`.
- The setting is exposed as a checkbox directly below the unit-scale slider and is gated by the Dynamic Unit Size subscription, just like the multiplier.
- When the multiplier is greater than one and the checkbox is enabled:
  - `main_units_tables` rows whose `caste` is `lord` or `hero` keep their existing `num_men`;
  - their referenced `land_units_tables` rows have `bonus_hit_points` multiplied by the canonical integer multiplier;
  - mounts and engines for ordinary non-character units continue using the existing scaling behavior.
- Add `lord_hero_health_rows_scaled` to generation statistics and zero-modification detection.
- Include the new boolean in saved settings, launch fingerprints, enabled-option reporting, and the strict game-data RPC allowlist.

The focused `bonus_hit_points` transformation is selected because it is the character-specific health carrier already present in every supported `land_units_tables` schema. Expanding into the full entity, mount, and engine graph would broaden the feature beyond the requested character health control and introduce unrelated table ownership.

## Non-blocking dialog opening

Current evidence shows `openGameDataModification()` waits for `get_game_data_feature_status`, which invokes the Steam subscription bridge, before setting the modal open flag.

The modal will be opened first. Subscription status refresh will then run asynchronously and update the existing reactive feature records when it completes. Expected Steam query failures remain represented by the backend warning payload; unexpected frontend invocation rejection is contained so it cannot close or delay the modal.

## Skip Intro reference parity

The supplied `skip_it_all.pack` contains 22 movie overrides:

- 13 localized epilepsy warnings: `br`, `cn`, `cz`, `de`, `en`, `es`, `fr`, `it`, `kr`, `pl`, `ru`, `tr`, and `zh`;
- `movies\gam_int.ca_vp8`;
- `movies\startup_movie_01.ca_vp8` through `startup_movie_08.ca_vp8`.

Every override has a zero-byte payload. The current implementation covers only English plus startup movies 1–4 and writes a synthetic VP8 payload. The runtime Pack will use the exact reference path set and zero-byte payload behavior. RPFM metadata entries from the reference Pack are editor metadata and are not copied.

## Validation

- Backend settings tests cover integer migration, bounds, invalid values, and the new default.
- Game-data tests prove ordinary unit scaling remains unchanged, lord/hero model counts remain unchanged, health is unchanged by default, and opt-in health scaling patches only referenced lord/hero land rows.
- Fingerprint and API tests cover the fourth game-data setting.
- Component tests cover the slider contract, tick/current-value display, checkbox default, emitted payload, reset behavior, and subscription gating.
- App source/component coverage proves modal visibility is set before subscription refresh.
- Runtime Pack tests compare the exact 22-entry reference path set and assert every payload is empty.
- Full backend, frontend, build, Ruff, compile, and diff checks run before completion.
