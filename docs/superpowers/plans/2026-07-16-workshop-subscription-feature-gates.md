# Workshop Subscription Feature Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace active-Pack feature gates with Steam Workshop subscription gates and hide both internal feature MODs from WMM.

**Architecture:** A backend feature registry is the single source of truth for Workshop IDs, titles, and Pack names. API subscription status feeds both the frontend and runtime DB builder, while the scanner filters internal feature assets.

**Tech Stack:** Python 3.12, Steamworks bridge, Vue 3, Pinia, unittest, Vitest

## Global Constraints

- Subscription alone unlocks a feature; playset activation never participates.
- Internal feature MODs never appear in WMM lists.
- Prompts use `Dynamic Unit Size` and `Dynamic No Friendly Fire`, never Pack filenames.
- Preserve blank Workshop descriptions and existing published items.

---

### Task 1: Backend subscription registry and runtime gate

**Files:**
- Modify: `backend/constants.py`
- Modify: `backend/start_options.py`
- Modify: `backend/api.py`
- Test: `tests/test_start_options.py`
- Test: `tests/test_storage_and_api.py`

**Interfaces:**
- Produces: `GAME_DATA_FEATURE_WORKSHOP_ITEMS` and `subscribed_workshop_ids` input to `build_runtime_options_pack`.
- Produces: `get_game_data_feature_status` RPC returning registry items with `subscribed` booleans.

- [ ] Write failing tests proving active Pack assets do not unlock features and Workshop IDs do.
- [ ] Run focused backend tests and confirm the old active-Pack implementation fails.
- [ ] Add the fixed registry, subscription query/cache, launch integration, and subscription-based runtime gating.
- [ ] Run focused backend tests and confirm they pass.

### Task 2: Internal feature MOD filtering

**Files:**
- Modify: `backend/scanner.py`
- Modify: `backend/api.py`
- Test: `tests/test_scanner.py`
- Test: `tests/test_storage_and_api.py`

**Interfaces:**
- Consumes: registry Workshop IDs and Pack filenames from Task 1.
- Produces: scan payloads that never contain internal feature MODs or report their old IDs as missing.

- [ ] Write failing scanner/API tests for Data copies, Workshop copies, and stale playset entries.
- [ ] Run focused tests and confirm internal items are currently returned.
- [ ] Filter exact internal IDs/names and discard their legacy playset identifiers.
- [ ] Run focused tests and confirm filtering passes.

### Task 3: Frontend subscription status and title prompts

**Files:**
- Modify: `frontend/src/store.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/GameDataModificationModal.vue`
- Modify: `frontend/src/languages.js`
- Test: `frontend/src/__tests__/gameDataSettings.test.js`
- Test: `frontend/src/components/__tests__/GameDataModificationModal.test.js`

**Interfaces:**
- Consumes: backend `game_data_features.items.unit_size` and `.friendly_fire`.
- Produces: disabled controls and title-based not-subscribed prompts.

- [ ] Write failing store/modal tests for subscribed and unsubscribed states.
- [ ] Run focused Vitest files and confirm failures mention the old Pack-status API/text.
- [ ] Store bootstrap/refreshed subscription data, refresh when opening the dialog, and render title-based prompts.
- [ ] Run focused Vitest files and confirm they pass.

### Task 4: Cleanup and full verification

**Files:**
- Remove installed copies only: `<SteamLibrary>/steamapps/common/Total War WARHAMMER III/data/wyccc_dynamic_unit_size.pack`
- Remove installed copies only: `<SteamLibrary>/steamapps/common/Total War WARHAMMER III/data/wyccc_dynamic_no_friendly_fire.pack`

**Interfaces:**
- Preserves source Pack/cover directories and Workshop items `3765783838` and `3765783977`.

- [ ] Query current Steam subscription state and subscribe the current account if needed.
- [ ] Remove the two obsolete Data copies after checking their exact absolute paths.
- [ ] Run the full backend and frontend suites, production frontend build, compileall, `git diff --check`, a real DB smoke test, and Steamworks status verification.
