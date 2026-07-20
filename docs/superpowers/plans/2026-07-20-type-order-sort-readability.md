# 类型顺序、类型排序与界面可读性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task with verification checkpoints.

**Goal:** Persist a shared order for built-in and custom MOD types, expose type-based display sorting and manual type entry, and improve the small text areas shown in the supplied screenshots.

**Architecture:** Store the ordered type IDs in the existing `app_state` table behind storage/API methods. Keep display sorting pure in `frontend/src/modSearch.js`, with the Pinia store passing the current type rank map. Keep TypeManagerModal and ModContextMenu presentational; App/store own persistence, prompt, creation, and batch application.

**Tech Stack:** Python 3, SQLite, existing backend command dispatcher, Vue 3 `<script setup>`, Pinia, Vitest, Vite.

## Global Constraints

- All built-in and custom type IDs share one persisted order.
- Manual type input reuses a case-insensitive existing type or creates a custom type before applying it.
- Non-priority display sorting must not be overridden by inactive manual load-order customization.
- Do not revert unrelated existing working-tree changes in `frontend/src/components/WorkshopPublishModal.vue`, `frontend/src/styles.css`, or `frontend/src/__tests__/publishAndListComponents.test.js`.

---

### Task 1: Persist and expose type order in backend storage/API

**Files:**
- Modify: `backend/storage.py` near `PLAYSET_SCHEMA_VERSION`, schema helpers, and `list_mod_types`/type CRUD methods
- Modify: `backend/api.py` command map and type handlers
- Modify: `tests/test_storage_and_api.py`

**Interfaces:**
- Produce `StateRepository.list_mod_types()` returning the current ordered list.
- Produce `StateRepository.reorder_mod_types(type_ids)` returning the ordered list.
- Produce API command `reorder_mod_types` returning `{"items": [...]}`.

- [ ] **Step 1: Write failing storage tests**

Add tests that create a temporary repository, assert the initial built-in order, reorder all IDs, verify the new order after a fresh repository instance, verify a newly created type is appended, and verify deleting a custom type removes its ID from the persisted order.

- [ ] **Step 2: Run the backend tests to verify the new behavior fails**

Run `python -m pytest tests/test_storage_and_api.py -q`.
Expected: failures because `reorder_mod_types` and the persisted ordering do not exist.

- [ ] **Step 3: Implement the minimal storage/API behavior**

Use an `app_state` key such as `mod_type_order`. Normalize a requested list by keeping valid IDs once, preserving the requested order, then appending any current IDs not supplied. `list_mod_types` should read/repair this key, return defaults plus custom rows in the repaired order, append newly discovered IDs, and write repairs. Creation appends the new ID; deletion removes it. Register the API handler and return refreshed items.

- [ ] **Step 4: Run storage/API tests**

Run `python -m pytest tests/test_storage_and_api.py -q`.
Expected: all tests in the file pass.

- [ ] **Step 5: Run formatting checks for backend changes**

Run `python -m compileall backend` and `git diff --check`.
Expected: exit code 0 for both.

### Task 2: Add store action and type-based display sorting

**Files:**
- Modify: `frontend/src/modSearch.js`
- Modify: `frontend/src/store.js`
- Modify: `frontend/src/components/SortMenu.vue`
- Modify: `frontend/src/languages.js`
- Test: `frontend/src/__tests__/modSearch.test.js` and the relevant store test file

**Interfaces:**
- Extend `SORT_OPTIONS` with `{ id: 'type', labelKey: 'search.sortType' }`.
- Extend `sortDisplayedMods(mods, mode, descending, typeRanks)` with a type comparator.
- Produce Pinia action `reorderModTypes(typeIds)`.

- [ ] **Step 1: Write failing sorting/store tests**

Add a pure sorting test with a custom type rank map, multiple types, unknown fallback, ascending and descending assertions. Add a store test proving `setSortMode('type')` selects visual sorting and calls `invoke('reorder_mod_types', ids)` through `reorderModTypes`.

- [ ] **Step 2: Run targeted frontend tests to verify failure**

From `frontend`, run `pnpm exec vitest run src/__tests__/modSearch.test.js` and the store test file.
Expected: failures because the type sort option/comparator/action are absent.

- [ ] **Step 3: Implement the comparator and store wiring**

Use the first valid assigned type as the primary rank; rank missing/unknown types after configured types. Use existing filename comparison as the stable secondary key. Pass `this.modTypeRanks` from both display getters. Change inactive display override to apply only when `sortMode === 'priority'`. Add the sort label translations and the store action that updates `modTypes` from the API response.

- [ ] **Step 4: Run targeted tests to verify green**

Run the same Vitest commands from Step 2.
Expected: all targeted tests pass.

### Task 3: Add type-manager move controls and App persistence handler

**Files:**
- Modify: `frontend/src/components/TypeManagerModal.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/store.js`
- Modify: `frontend/src/languages.js`
- Test: `frontend/src/components/__tests__/TypeManagerModal.test.js`

**Interfaces:**
- TypeManagerModal emits `move` with `{ id, direction }` where direction is `-1` or `1`.
- App handles the event by calling `store.reorderModTypes` with the moved list.

- [ ] **Step 1: Write failing component tests**

Mount a three-item type list and assert every row has up/down controls, the first up and last down controls are disabled, and clicking a middle-row control emits the expected direction and ID.

- [ ] **Step 2: Run the TypeManagerModal test to verify failure**

Run `pnpm exec vitest run src/components/__tests__/TypeManagerModal.test.js` from `frontend`.
Expected: failure because move controls and the `move` event do not exist.

- [ ] **Step 3: Implement move controls and App/store wiring**

Render accessible icon/text buttons in a dedicated action column, keep edit/delete behavior for custom types, and use localized titles. Add the App handler and pass `@move`. Preserve current busy guards and update the local list from the API response.

- [ ] **Step 4: Run component tests**

Run `pnpm exec vitest run src/components/__tests__/TypeManagerModal.test.js`.
Expected: pass.

### Task 4: Add manual type entry to the context menu

**Files:**
- Modify: `frontend/src/components/ModContextMenu.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/languages.js`
- Test: `frontend/src/components/__tests__/ModContextMenu.test.js` and an App/store behavior test where practical

**Interfaces:**
- Context menu emits `{ action: 'manual-type', mod }` from the first type-submenu item.
- App handles the action by prompting, reusing a case-insensitive type, or creating one, then applying it to all selected IDs.

- [ ] **Step 1: Write failing context-menu tests**

Assert the type submenu starts with “手动输入”, includes a `Shift + F` shortcut label, and clicking it emits `manual-type` without closing the parent menu unexpectedly.

- [ ] **Step 2: Run the context-menu tests to verify failure**

Run `pnpm exec vitest run src/components/__tests__/ModContextMenu.test.js` from `frontend`.
Expected: failure because the menu item and action are absent.

- [ ] **Step 3: Implement prompt/create/apply flow**

Add translations and a fixed `Shift + F` display. In App, prompt with the current type name as the default. Trim and cancel safely; find an existing type by case-folded localized or stored name; otherwise await `store.createModType`. Apply the resulting ID to every selected MOD using existing `toggleModType`/`setModTypes` behavior, preserving batch semantics and shared toast handling.

- [ ] **Step 4: Run context-menu tests**

Run `pnpm exec vitest run src/components/__tests__/ModContextMenu.test.js`.
Expected: pass.

### Task 5: Improve screenshot-targeted typography

**Files:**
- Modify: `frontend/src/styles.css`
- Test: `frontend/src/__tests__/scope.test.js` or a focused new CSS contract test

- [ ] **Step 1: Write a failing CSS contract test**

Assert the stylesheet contains the targeted selectors with the new minimum readable sizes: details metadata at least 11/12px, action buttons at least 14px, type-manager labels/inputs at least 12px, and settings tab copy at least 13px for secondary text.

- [ ] **Step 2: Run the CSS test to verify failure**

Run `pnpm exec vitest run src/__tests__/scope.test.js` from `frontend`.
Expected: failure against the current 9–12px declarations.

- [ ] **Step 3: Apply local typography changes**

Raise only the selectors listed in the design, including compatible line-height/min-height adjustments. Do not change the global body scale or unrelated workshop BBCode sizing.

- [ ] **Step 4: Run the CSS test**

Run `pnpm exec vitest run src/__tests__/scope.test.js`.
Expected: pass.

### Task 6: Full verification and handoff

**Files:**
- Verify: all changed files and existing uncommitted user changes

- [ ] **Step 1: Run the complete backend suite**

Run `python -m pytest -q`.
Expected: zero failures.

- [ ] **Step 2: Run the complete frontend suite and production build**

From `frontend`, run `pnpm test` and `pnpm build`.
Expected: all Vitest files/tests pass and Vite exits successfully.

- [ ] **Step 3: Run final repository checks**

Run `git diff --check` and inspect `git status --short`/`git diff --stat`.
Expected: no whitespace errors, only intended files changed, and no generated artifacts staged.

- [ ] **Step 4: Review requirement coverage**

Verify manually from the diff that all built-in/custom types can move, type sorting uses persisted order, manual input is topmost with `Shift + F`, and all four screenshot areas receive readable typography updates.

