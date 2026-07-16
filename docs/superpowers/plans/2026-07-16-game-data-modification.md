# Game Data Modification Implementation Plan

> **For Codex:** Execute this plan in the current session with test-driven development and verify every generated Pack path without running release packaging.

**Goal:** Add a bottom-left “游戏数据修改” dialog that persists a unit model-count multiplier plus unit/spell friendly-fire switches and explicitly generates a late-loading DB patch from vanilla and currently enabled Pack data.

**Architecture:** Use a dedicated persistent game-data Pack alongside the existing runtime-options pipeline. A focused WH3 DB reader will parse only five confirmed tables using a bundled subset of the current WH3 schema, resolve duplicate DB rows by internal packed-file priority, patch only the confirmed numeric/ally-damage fields, and serialize high-priority incremental tables. Original Packs remain read-only. A dedicated RPC saves the three settings after successful patch generation so the modal does not clear or rescan the current playset.

**Tech Stack:** Python 3.11 backend, PFH5/WH3 binary DB tables, Vue 3, Pinia, Vitest, unittest.

---

### Task 1: Lock the backend contract with failing tests

**Files:**
- Modify: `tests/test_start_options.py`
- Modify: `tests/test_app_settings.py`
- Modify: `tests/test_storage_and_api.py`

1. Add binary-table fixtures for `main_units`, `land_units`, `projectiles`, `projectiles_explosions`, and `battle_vortexs`.
2. Assert model counts, mounts, and engines are ceiling-scaled while lord/hero model counts stay unchanged.
3. Assert unit and spell friendly-fire switches patch only rows matching `is_spell`, including explosion/vortex carriers.
4. Assert settings default, normalization, persistence, and dedicated RPC behavior.
5. Run the focused tests and confirm they fail because the new contract is not implemented.

### Task 2: Implement schema-backed game-data transformations

**Files:**
- Create: `backend/wh3_db_schema.json`
- Create: `backend/game_data.py`
- Modify: `backend/start_options.py`

1. Bundle only the five required tables and all known versions from the locally verified WH3 schema.
2. Parse PFH5 entries and DB row boundaries without rewriting source Packs.
3. Resolve duplicate keys by internal DB file priority, with current playset order as the exact-name tie-breaker.
4. Apply the reference model-count formulas to non-lord/non-hero `main_units` and their referenced `land_units` rows.
5. Disable ally damage only in projectiles, projectile explosions, and battle vortexes; leave ability phases untouched so buffs and healing keep affecting allies.
6. Serialize one high-priority incremental entry per table version into the dedicated persistent game-data Pack.
7. Run focused backend tests until green.

### Task 3: Persist and expose game-data settings

**Files:**
- Modify: `backend/app_settings.py`
- Modify: `backend/api.py`
- Modify: `frontend/src/store.js`

1. Add schema-versioned defaults for multiplier `1.0` and both friendly-fire switches disabled.
2. Clamp multiplier to `0.5–5.0` and normalize switches as booleans.
3. Add `save_game_data_settings` RPC with a strict three-key allowlist.
4. Add a Pinia action that updates settings in place without clearing scanned mods.
5. Run backend API/settings tests until green.

### Task 4: Add the bottom-left button and modal

**Files:**
- Create: `frontend/src/components/GameDataModificationModal.vue`
- Create: `frontend/src/components/__tests__/GameDataModificationModal.test.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/languages.js`

1. Add a failing component test for draft initialization, valid range, all three emitted settings, and reopen reset behavior.
2. Add the “游戏数据修改” button to the left footer group.
3. Build a focused modal with the multiplier input, two switches, a Generate patch button, and a clear persistent-patch explanation.
4. Add all new strings in Chinese, English, Korean, Russian, and Japanese.
5. Run frontend tests until green.

### Task 5: Verify the complete change

**Files:**
- Review all files above.

1. Run all Python unit tests.
2. Run all frontend Vitest tests.
3. Run the production frontend build.
4. Run Ruff (when available), `git diff --check`, and inspect the final diff for unrelated changes.
5. Confirm no release/package command ran and no original game or Workshop Pack was modified.
