# Artillery and War Machine Scale Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent health-only, half-scale, and full-scale policies for artillery and war-machine units while preserving full global-multiplier total health.

**Architecture:** Normalize the two new persisted modes in `game_data_settings.py`, then resolve one `_UnitScalePolicy` per effective unit in `game_data.py` using the approved priority order. Apply the resolved policy consistently to `main_units` and shared `land_units`, and propagate the new settings through persistence, RPC, patch fingerprints, launch summaries, and the Vue modal.

**Tech Stack:** Python 3.11, pytest, Vue 3, Vitest, Vite.

## Global Constraints

- Classification priority is `lord/hero > single entity > artillery > war machine > normal`.
- Single entity means non-character `num_men == 1` and `is_monstrous == true`, even when the unit is engine-backed.
- New settings are `artillery_unit_mode` and `war_machine_unit_mode`, with `health`, `half`, and `full`; both default to `full`.
- Half scale is `1 + (global_multiplier - 1) * 0.5`.
- New fractional model-count calculations use standard half-up rounding, not the existing ceiling helper.
- Health-only and half-scale modes keep aggregate health at the full global multiplier through `land_units.bonus_hit_points`.
- Engine-backed `land_units.num_mounts` remains unchanged.
- Do not modify shared `battle_entities` rows.

---

### Task 1: Normalize and persist category modes

**Files:**
- Modify: `backend/game_data_settings.py`
- Modify: `backend/app_settings.py`
- Modify: `backend/api.py`
- Test: `tests/test_app_settings.py`
- Test: `tests/test_storage_and_api.py`

**Interfaces:**
- Produces: `normalize_category_unit_mode(value: Any) -> str`
- Produces: constants `CATEGORY_UNIT_MODE_HEALTH`, `CATEGORY_UNIT_MODE_HALF`, and `CATEGORY_UNIT_MODE_FULL`
- Produces: persisted keys `artillery_unit_mode` and `war_machine_unit_mode`

- [ ] **Step 1: Write failing normalization and persistence tests**

Add assertions equivalent to:

```python
self.assertEqual(default_settings()["artillery_unit_mode"], "full")
self.assertEqual(default_settings()["war_machine_unit_mode"], "full")
self.assertEqual(normalize_category_unit_mode("health"), "health")
self.assertEqual(normalize_category_unit_mode("HALF"), "half")
self.assertEqual(normalize_category_unit_mode("unexpected"), "full")
```

Extend the existing settings save/reopen test to save `artillery_unit_mode="half"` and `war_machine_unit_mode="health"`, then verify both values survive reopen. Extend the API filtering test to verify both keys are accepted and normalized.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_app_settings.py tests/test_storage_and_api.py -q
```

Expected: failures for missing category-mode constants, normalizer, defaults, or RPC keys.

- [ ] **Step 3: Implement category-mode normalization and persistence**

Add:

```python
CATEGORY_UNIT_MODE_HEALTH = "health"
CATEGORY_UNIT_MODE_HALF = "half"
CATEGORY_UNIT_MODE_FULL = "full"

def normalize_category_unit_mode(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    return (
        normalized
        if normalized in {
            CATEGORY_UNIT_MODE_HEALTH,
            CATEGORY_UNIT_MODE_HALF,
            CATEGORY_UNIT_MODE_FULL,
        }
        else CATEGORY_UNIT_MODE_FULL
    )
```

Add both default keys in `default_settings()`, normalize both keys in `SettingsService._normalize`, and add both to `GAME_DATA_SETTING_KEYS`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_app_settings.py tests/test_storage_and_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/game_data_settings.py backend/app_settings.py backend/api.py tests/test_app_settings.py tests/test_storage_and_api.py
git commit -m "feat: persist artillery and war machine scale modes"
```

### Task 2: Resolve unit policies and apply scale and health compensation

**Files:**
- Modify: `backend/game_data.py`
- Test: `tests/test_game_data.py`

**Interfaces:**
- Consumes: `normalize_category_unit_mode`
- Produces: `_UnitScalePolicy` and a single classification resolver for `main_units` plus `land_units`
- Produces: `_round_half_up_i32(value: int | float, minimum: int | None = None) -> int`
- Produces: aggregate-health compensation based on actual rounded `num_men`

- [ ] **Step 1: Write failing policy and half-up rounding tests**

Create focused tests proving:

```python
# Three models at global 2x and half mode become five, not six.
assert main_rows["artillery"]["num_men"] == 5

# 4.2 rounds to four while 4.5 rounds to five.
assert _round_half_up_i32(4.2) == 4
assert _round_half_up_i32(4.5) == 5
```

Add fixtures for one `artillery` row, one `war_machine` row, a `lord` whose land category is `war_machine`, and an engine-backed `num_men=1`, `is_monstrous=true` unit. Verify the latter two use character and single-entity behavior respectively.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_game_data.py -q
```

Expected: missing mode behavior, missing resolver, or incorrect existing full-scale output.

- [ ] **Step 3: Implement the unified policy resolver**

Add a private immutable policy type carrying:

```python
@dataclass(frozen=True)
class _UnitScalePolicy:
    kind: str
    priority: int
    size_multiplier: float
    compensate_health: bool
```

Resolve policies in this order:

```python
if caste in {"lord", "hero"}:
    kind = "character"
elif num_men == 1 and is_monstrous:
    kind = "single_entity"
elif category == "artillery":
    kind = "artillery"
elif category == "war_machine":
    kind = "war_machine"
else:
    kind = "normal"
```

For category modes, calculate size multiplier as 1, `1 + (M - 1) * 0.5`, or `M`. When multiple main rows share a land row, retain the lowest numeric priority and a stable representative main row.

- [ ] **Step 4: Implement standard half-up count scaling**

Use:

```python
def _round_half_up_i32(value: int | float, minimum: int | None = None) -> int:
    rounded = math.floor(float(value) + 0.5)
    if minimum is not None:
        rounded = max(rounded, minimum)
    return _clamped_i32(rounded)
```

Apply the policy multiplier to `num_men`, `num_engines`, `rank_depth`, and non-engine `num_mounts`. Preserve engine-backed `num_mounts`.

- [ ] **Step 5: Implement aggregate-health compensation**

For policies requiring compensation, calculate:

```python
actual_size_ratio = new_num_men / original_num_men
health_multiplier = global_multiplier / actual_size_ratio
new_bonus = round_half_up(
    (entity_hit_points + old_bonus) * health_multiplier
) - entity_hit_points
```

Use `man_entity` and `bonus_hit_points`; do not patch `battle_entities`. Include clear missing-reference errors containing the land-unit and entity keys. Add separate stats for artillery and war-machine compensated rows so launch reporting counts them.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_game_data.py -q
```

Expected: all game-data tests pass, including existing Fully Custom Garrison and engine-mount regressions.

- [ ] **Step 7: Commit**

```powershell
git add backend/game_data.py tests/test_game_data.py
git commit -m "feat: apply category-specific unit scale policies"
```

### Task 3: Include modes in patch fingerprints and launch behavior

**Files:**
- Modify: `backend/game_data_patch_state.py`
- Modify: `backend/start_options.py`
- Test: `tests/test_game_data_patch_state.py`
- Test: `tests/test_start_options.py`

**Interfaces:**
- Consumes: `normalize_category_unit_mode`
- Produces: effective settings, enabled option names, fingerprint values, and changed-row totals for both modes

- [ ] **Step 1: Write failing fingerprint and launch tests**

Extend the canonical settings fixtures with:

```python
"artillery_unit_mode": "full",
"war_machine_unit_mode": "full",
```

Verify changing either mode changes the input fingerprint when the global scale multiplier is active. Verify unavailable unit-size support forces both modes to `full`. Verify `_enabled_game_data_options` reports a non-default category mode only while unit scaling is active.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_game_data_patch_state.py tests/test_start_options.py -q
```

Expected: fingerprints remain unchanged or effective settings omit the new keys.

- [ ] **Step 3: Implement patch-state and launch plumbing**

Normalize both fields in `_normalized_settings()` and `_effective_game_data_settings()`. Increment `GAME_DATA_BUILDER_VERSION` from 10 to 11. Add non-`full` modes to `_enabled_game_data_options()` only under active unit scaling, and add the new health-compensation stats to `_changed_game_data_rows()`.

Do not change `game_data_settings_requested()` or `_game_data_enabled()` to activate a patch when the global multiplier is 1; this preserves automatic patch deletion when all other modifications are disabled.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_game_data_patch_state.py tests/test_start_options.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/game_data_patch_state.py backend/start_options.py tests/test_game_data_patch_state.py tests/test_start_options.py
git commit -m "feat: fingerprint category unit scale modes"
```

### Task 4: Add independent Vue controls and translations

**Files:**
- Modify: `frontend/src/components/GameDataModificationModal.vue`
- Modify: `frontend/src/languages.js`
- Modify: `frontend/src/components/__tests__/GameDataModificationModal.test.js`
- Modify: `frontend/src/__tests__/gameDataSettings.test.js`

**Interfaces:**
- Consumes and emits: `artillery_unit_mode` and `war_machine_unit_mode`
- Produces: two independent three-button groups with `health`, `half`, and `full`

- [ ] **Step 1: Write failing modal and store tests**

Mount the modal with:

```javascript
settings: {
  unit_model_multiplier: 2,
  artillery_unit_mode: 'half',
  war_machine_unit_mode: 'health',
}
```

Verify independent pressed states using `data-testid` values:

```javascript
artillery-unit-mode-health
artillery-unit-mode-half
artillery-unit-mode-full
war-machine-unit-mode-health
war-machine-unit-mode-half
war-machine-unit-mode-full
```

Click artillery `full` and war-machine `half`, submit, and assert both emitted values. Extend the store test to verify both keys pass unchanged to `save_game_data_settings`.

- [ ] **Step 2: Run frontend tests and verify RED**

Run:

```powershell
pnpm --dir frontend test -- GameDataModificationModal.test.js gameDataSettings.test.js
```

Expected: missing controls and missing emitted keys.

- [ ] **Step 3: Implement modal state and controls**

Add a category-mode normalizer defaulting to `full`, include both keys in `draft`, `resetDraft()`, and `currentSettings()`, then render two independent three-button groups near the single-entity rule.

Reuse the existing mode-choice visual style, expanding selectors only as needed. Disable all six buttons when the unit-size Workshop feature is unavailable or the modal is busy.

- [ ] **Step 4: Add localized text**

Add localization keys for:

```text
gameData.artilleryUnitMode
gameData.artilleryUnitModeHelp
gameData.warMachineUnitMode
gameData.warMachineUnitModeHelp
gameData.categoryUnitHealth
gameData.categoryUnitHalf
gameData.categoryUnitFull
```

Provide Chinese and English wording that exactly describes the full-health behavior. Fill the other currently supported languages with clear localized or English fallback text using the existing `languages.js` structure.

- [ ] **Step 5: Run frontend tests and build**

Run:

```powershell
pnpm --dir frontend test
pnpm --dir frontend build
```

Expected: all Vitest tests pass and Vite exits successfully.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/GameDataModificationModal.vue frontend/src/languages.js frontend/src/components/__tests__/GameDataModificationModal.test.js frontend/src/__tests__/gameDataSettings.test.js
git commit -m "feat: add artillery and war machine rule controls"
```

### Task 5: Full regression verification

**Files:**
- Verify: all modified files

**Interfaces:**
- Verifies the complete feature and existing game-data behavior.

- [ ] **Step 1: Run the full backend suite**

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run static checks**

```powershell
python -m ruff check backend tests
git diff --check
```

Expected: no Ruff violations and no whitespace errors.

- [ ] **Step 3: Run full frontend verification**

```powershell
pnpm --dir frontend test
pnpm --dir frontend build
```

Expected: all tests pass and the production build succeeds.

- [ ] **Step 4: Review the final diff**

Confirm every modified production field has a corresponding test, both category controls are independent, no changelog or version files changed, and the worktree contains no unrelated edits.
