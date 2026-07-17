# Single-Entity Health Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let players choose whether eligible ordinary single-entity monsters scale by health or by model count.

**Architecture:** A normalized `single_entity_unit_mode` setting flows from the modal through the API, launch-time effective settings, and patch fingerprint. The DB builder resolves effective `main_units`, `land_units`, and `battle_entities` rows, then routes only non-engine monstrous single entities through total-health scaling when health mode is selected.

**Tech Stack:** Vue 3, JavaScript/Vitest, Python 3/unittest, WH3 DB binary parsing.

## Global Constraints

- Preserve all unrelated uncommitted work in the shared `G:\git\wyccc-warhammer-mod-manager` workspace.
- Do not package, publish, tag, or commit.
- Use tests before production changes.
- Keep `scale` as the persisted default and preserve all existing scale-mode behavior.
- Provide all new interface text in Chinese, English, Korean, Russian, Japanese, and Spanish.

---

### Task 1: Define and persist the normalized mode

**Files:**
- Modify: `backend/game_data_settings.py`
- Modify: `backend/app_settings.py`
- Modify: `backend/api.py`
- Modify: `backend/game_data_patch_state.py`
- Test: `tests/test_app_settings.py`
- Test: `tests/test_storage_and_api.py`
- Test: `tests/test_game_data_patch_state.py`

**Interfaces:**
- Produces `normalize_single_entity_unit_mode(value: Any) -> str` with only `scale` and `health` results.
- Adds `single_entity_unit_mode` to persisted game-data settings and the game-data API allowlist.

- [ ] **Step 1: Write failing settings, API, and fingerprint tests**

```python
assert service.save({"single_entity_unit_mode": "health"})["single_entity_unit_mode"] == "health"
assert service.save({"single_entity_unit_mode": "unknown"})["single_entity_unit_mode"] == "scale"
assert result["data"]["settings"]["single_entity_unit_mode"] == "health"
assert fingerprint_game_data_inputs(health_mode) != fingerprint_game_data_inputs(scale_mode)
```

- [ ] **Step 2: Run the focused tests and confirm the new-field assertions fail**

Run: `\.venv-build\Scripts\python.exe -m unittest tests.test_app_settings tests.test_storage_and_api tests.test_game_data_patch_state -v`

Expected: failures for the missing `single_entity_unit_mode` setting and API field.

- [ ] **Step 3: Add the minimal normalized setting flow**

```python
def normalize_single_entity_unit_mode(value: Any) -> str:
    return "health" if str(value or "").strip().casefold() == "health" else "scale"
```

Add this normalized value to default settings, migration normalization, `GAME_DATA_SETTING_KEYS`, effective settings, and fingerprint input normalization. Increment `GAME_DATA_BUILDER_VERSION`.

- [ ] **Step 4: Re-run the focused tests**

Run: `\.venv-build\Scripts\python.exe -m unittest tests.test_app_settings tests.test_storage_and_api tests.test_game_data_patch_state -v`

Expected: PASS.

### Task 2: Route eligible single entities to total-health scaling

**Files:**
- Modify: `backend/game_data.py`
- Modify: `backend/start_options.py`
- Test: `tests/test_game_data.py`
- Test: `tests/test_start_options.py`

**Interfaces:**
- Consumes `settings["single_entity_unit_mode"]` after normalization.
- Produces `single_entity_health_rows_scaled` and leaves engine-backed rows on the existing scale path.

- [ ] **Step 1: Write a failing health-mode regression fixture**

```python
settings = {"unit_model_multiplier": 3, "single_entity_unit_mode": "health"}
assert main_rows["unit_star_dragon"]["num_men"] == 1
assert entity_hp + land_rows["land_star_dragon"]["bonus_hit_points"] == original_total_hp * 3
assert main_rows["unit_monster_engine"]["num_men"] == 3
assert land_rows["land_monster_engine"]["num_engines"] == 3
```

The fixture must set `is_monstrous=True` on both one-model records and give the engine record an `engine` reference or positive `num_engines`.
Include a non-monstrous main-unit row sharing the regular monster's land-unit key and assert that it still receives model-count scaling.

- [ ] **Step 2: Run the regression test and confirm it fails under the current all-model scaling behavior**

Run: `\.venv-build\Scripts\python.exe -m unittest tests.test_game_data.GameDataPatchTests.test_single_entity_health_mode_scales_only_regular_monsters -v`

Expected: FAIL because the regular monster model count is multiplied and no single-entity health statistic exists.

- [ ] **Step 3: Implement eligibility and total-health patching**

```python
eligible = (
    int(main_values.get("num_men") or 0) == 1
    and bool(main_values.get("is_monstrous"))
    and caste not in {"lord", "hero"}
    and not str(land_values.get("engine") or "").strip()
    and int(land_values.get("num_engines") or 0) <= 0
)
```

Load `battle_entities_tables` when health mode is active, leave eligible model/engine counts untouched, and scale their `hit_points + bonus_hit_points` total through `bonus_hit_points`. Reuse the existing unresolved-reference error behavior and keep battle entity rows out of output. Add the new statistic to the changed-row total.

- [ ] **Step 4: Re-run game-data and start-options tests**

Run: `\.venv-build\Scripts\python.exe -m unittest tests.test_game_data tests.test_start_options -v`

Expected: PASS.

### Task 3: Add the modal rule control and localized copy

**Files:**
- Modify: `frontend/src/components/GameDataModificationModal.vue`
- Modify: `frontend/src/languages.js`
- Test: `frontend/src/components/__tests__/GameDataModificationModal.test.js`
- Test: `frontend/src/__tests__/languages.test.js`

**Interfaces:**
- The modal emits `single_entity_unit_mode: 'health' | 'scale'` with the existing game-data settings.
- The binary control exposes `data-testid="single-entity-unit-mode"`.

- [ ] **Step 1: Write a failing modal payload test**

```javascript
await wrapper.get('[data-testid="single-entity-unit-mode"]').setValue('0')
await wrapper.get('form').trigger('submit')
expect(wrapper.emitted('save')[0][0].single_entity_unit_mode).toBe('health')
```

Also assert default `scale`, Health/Scale endpoint copy, disabled state without the unit-size dependency, and translation availability in all six languages.

- [ ] **Step 2: Run the focused frontend tests and confirm the control is absent**

Run: `npm run test -- --run src/components/__tests__/GameDataModificationModal.test.js src/__tests__/languages.test.js`

Expected: FAIL because the selector and translations do not yet exist.

- [ ] **Step 3: Add the range control and translations**

```vue
<input
  :value="draft.single_entity_unit_mode === 'health' ? 0 : 1"
  type="range"
  min="0"
  max="1"
  step="1"
  data-testid="single-entity-unit-mode"
  @input="draft.single_entity_unit_mode = Number($event.target.value) === 0 ? 'health' : 'scale'"
/>
```

Normalize the persisted value in the draft, include it in `currentSettings`, and style endpoint labels so they align with the binary track. Add the title, help text, and endpoint labels to every language catalog.

- [ ] **Step 4: Re-run frontend tests**

Run: `npm run test -- --run src/components/__tests__/GameDataModificationModal.test.js src/__tests__/languages.test.js`

Expected: PASS.

### Task 4: Verify the integrated change

**Files:**
- Verify modified source and tests from Tasks 1-3

- [ ] **Step 1: Run targeted backend and frontend suites**

Run: `\.venv-build\Scripts\python.exe -m unittest tests.test_game_data tests.test_game_data_patch_state tests.test_app_settings tests.test_storage_and_api tests.test_start_options -v`

Run: `npm run test -- --run src/components/__tests__/GameDataModificationModal.test.js src/__tests__/languages.test.js`

Expected: PASS.

- [ ] **Step 2: Run project-wide validation**

Run: `\.venv-build\Scripts\python.exe -m unittest discover -s tests -v`

Run: `npm run test -- --run`

Run: `\.venv-build\Scripts\python.exe -m compileall backend`

Run: `git diff --check`

Expected: all commands exit successfully without whitespace errors.
