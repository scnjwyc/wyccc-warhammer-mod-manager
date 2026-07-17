# Unit Scale, Character Health, and Runtime Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide an integer 1–5 unit-scale slider, optional lord/hero health scaling, non-blocking Game Data Modification opening, and reference-compatible intro skipping.

**Architecture:** Preserve `unit_model_multiplier` as the compatibility storage key while enforcing one canonical integer normalization at every backend boundary. Extend the existing `main_units_tables` to `land_units_tables` transformation for opt-in character `bonus_hit_points`, and keep UI subscription refresh asynchronous. Replace the incomplete synthetic intro payload list with the exact zero-byte movie overrides from the supplied reference Pack.

**Tech Stack:** Python 3.11, WH3 PFH5/DB tables, Vue 3, Pinia, Vitest, unittest.

## Global Constraints

- Only values `1`, `2`, `3`, `4`, and `5` are supported.
- `scale_lord_hero_health` defaults to `false`.
- Lord and hero `num_men` values must never be changed by this option.
- All five built-in interface languages must remain synchronized.
- Do not package, publish, commit, or write outside `G:\git\wyccc-warhammer-mod-manager`.

---

### Task 1: Lock integer settings and character health behavior

**Files:**
- Modify: `tests/test_app_settings.py`
- Modify: `tests/test_game_data.py`
- Modify: `tests/test_game_data_patch_state.py`
- Modify: `tests/test_start_options.py`
- Modify: `tests/test_storage_and_api.py`

**Interfaces:**
- Consumes: persisted `unit_model_multiplier` and new `scale_lord_hero_health`.
- Produces: canonical integer multiplier, character-health row statistics, and a four-key RPC contract.

- [x] **Step 1: Write failing backend tests**

Add assertions equivalent to:

```python
self.assertEqual(service.save({"unit_model_multiplier": 2.5})["unit_model_multiplier"], 3)
self.assertFalse(default_settings()["scale_lord_hero_health"])
self.assertEqual(land_rows["land_lord"]["bonus_hit_points"], 3000)
self.assertEqual(main_rows["unit_lord"]["num_men"], 1)
```

The game-data fixture must first prove no character HP change when the boolean is false, then prove only lord/hero referenced land rows change when true.

- [x] **Step 2: Verify backend RED**

Run:

```powershell
.\.venv-build\Scripts\python.exe -m unittest tests.test_app_settings tests.test_game_data tests.test_game_data_patch_state tests.test_start_options tests.test_storage_and_api -v
```

Expected: failures for decimal persistence, missing `scale_lord_hero_health`, missing health statistics, and the three-key RPC allowlist.

- [x] **Step 3: Implement integer and health behavior**

Update:

```python
UNIT_MODEL_MULTIPLIER_MIN = 1
UNIT_MODEL_MULTIPLIER_MAX = 5
```

Use finite-value validation, clamp, and `math.floor(value + 0.5)` canonicalization in settings, fingerprinting, effective settings, and DB generation. Add `scale_lord_hero_health` to defaults, normalization, allowlists, fingerprints, and effective settings. In `build_game_data_entries`, collect lord/hero referenced land-unit keys and multiply only their `bonus_hit_points` when opted in.

- [x] **Step 4: Verify backend GREEN**

Re-run the Step 2 command and require zero failures.

### Task 2: Replace the numeric editor with a slider

**Files:**
- Modify: `frontend/src/components/__tests__/GameDataModificationModal.test.js`
- Modify: `frontend/src/__tests__/gameDataSettings.test.js`
- Modify: `frontend/src/__tests__/languages.test.js`
- Modify: `frontend/src/components/GameDataModificationModal.vue`
- Modify: `frontend/src/languages.js`

**Interfaces:**
- Produces: range input `data-testid="unit-model-multiplier"` and checkbox `data-testid="scale-lord-hero-health"`.

- [x] **Step 1: Write failing component and language tests**

Assert:

```javascript
expect(slider.attributes('type')).toBe('range')
expect(slider.attributes('min')).toBe('1')
expect(slider.attributes('max')).toBe('5')
expect(slider.attributes('step')).toBe('1')
expect(wrapper.get('[data-testid="scale-lord-hero-health"]').element.checked).toBe(false)
```

Also assert emitted values are integer and include the new boolean, and every language has non-empty synchronized strings.

- [x] **Step 2: Verify frontend RED**

Run:

```powershell
pnpm --dir frontend exec vitest run src/components/__tests__/GameDataModificationModal.test.js src/__tests__/gameDataSettings.test.js src/__tests__/languages.test.js
```

Expected: failures because the input is numeric, decimals remain supported, and the checkbox/text keys do not exist.

- [x] **Step 3: Implement the slider and five-language copy**

Use:

```vue
<input v-model.number="draft.unit_model_multiplier" type="range" min="1" max="5" step="1" />
<input v-model="draft.scale_lord_hero_health" type="checkbox" />
```

Show the current `×` value and labels `1` through `5`, reset the checkbox from saved settings, and emit it on save.

- [x] **Step 4: Verify frontend GREEN**

Re-run the Step 2 command and require zero failures.

### Task 3: Make dialog opening non-blocking

**Files:**
- Modify: `frontend/src/__tests__/scope.test.js`
- Modify: `frontend/src/App.vue`

- [x] **Step 1: Write a failing ordering test**

Assert the `openGameDataModification` source sets `showGameDataModification.value = true` before calling `store.refreshGameDataFeatures()`, and no longer awaits that refresh before the visibility assignment.

- [x] **Step 2: Verify RED**

Run:

```powershell
pnpm --dir frontend exec vitest run src/__tests__/scope.test.js
```

Expected: failure because the current handler awaits Steam status first.

- [x] **Step 3: Open first and refresh asynchronously**

Set modal visibility immediately, then launch the refresh as a contained promise:

```javascript
showGameDataModification.value = true
void store.refreshGameDataFeatures().catch(() => {})
```

- [x] **Step 4: Verify GREEN**

Re-run the Step 2 command and require zero failures.

### Task 4: Match the working Skip It All Pack

**Files:**
- Modify: `tests/test_start_options.py`
- Modify: `backend/start_options.py`

- [x] **Step 1: Write a failing exact-parity test**

Build the runtime Pack with `skip_intro_movies=true`, assert its entry names equal the 13 warning locales plus `gam_int` and startup movies 1–8, and assert:

```python
self.assertTrue(all(payload == b"" for payload in entries.values()))
```

- [x] **Step 2: Verify RED**

Run:

```powershell
.\.venv-build\Scripts\python.exe -m unittest tests.test_start_options.StartOptionsPackTests.test_runtime_pack_contains_all_three_reference_features -v
```

Expected: missing localized warnings and startup movies 5–8, plus non-empty payload failures.

- [x] **Step 3: Implement exact movie overrides**

Replace the six-path tuple with the exact 22-path reference set and emit `PackEntry(name, b"")`. Remove the unused synthetic VP8 constant and Base64 import.

- [x] **Step 4: Verify GREEN**

Re-run the Step 2 command and require zero failures.

### Task 5: Full verification

**Files:**
- Review every modified source, test, and document above.

- [x] **Step 1: Run the complete backend suite**

```powershell
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -v
```

- [x] **Step 2: Run the complete frontend suite and production build**

```powershell
pnpm --dir frontend test
pnpm --dir frontend build
```

- [x] **Step 3: Run static and repository checks**

```powershell
.\.venv-build\Scripts\python.exe -m ruff check backend tests
.\.venv-build\Scripts\python.exe -m compileall -q backend main.py
git diff --check
```

- [x] **Step 4: Confirm scope**

Verify `git status --short` contains only source, tests, and documentation under the repository and no packaging, release, or generated distribution changes.
