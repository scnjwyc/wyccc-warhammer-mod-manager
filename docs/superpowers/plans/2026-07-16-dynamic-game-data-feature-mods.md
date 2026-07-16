# Dynamic Game Data Feature MODs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require two exact enabled Pack files before the manager can generate dynamic unit-size or friendly-fire runtime DB changes, create those Pack files and covers, and publish both items to Steam Workshop.

**Architecture:** The manager continues to generate the DB overrides in its disposable runtime Pack so subscribed source Packs stay immutable. Two harmless marker Packs act as explicit feature dependencies: backend launch generation enforces the dependency, while the modal derives installed/enabled status from the current scanned playset and disables unavailable controls with localized guidance.

**Tech Stack:** Python 3.11, PFH5 Pack writer, Vue 3, Pinia, Vitest, unittest, built-in image generation, local Steamworks bridge.

## Global Constraints

- Unit model scaling requires the exact enabled Pack name `wyccc_dynamic_unit_size.pack`.
- Both friendly-fire switches require the exact enabled Pack name `wyccc_dynamic_no_friendly_fire.pack`.
- Missing and installed-but-disabled states must both disable their corresponding controls and display distinct guidance.
- Workshop titles are exactly `Dynamic Unit Size` and `Dynamic No Friendly Fire`; descriptions and change notes are empty.
- Source/subscribed Pack files remain immutable; generated DB rows stay in `!!!!wyccc_runtime_options.pack`.
- Do not run the application release-packaging workflow, create Git commits/tags, or write to the application release directory.

---

### Task 1: Lock backend dependency enforcement with failing tests

**Files:**
- Modify: `tests/test_start_options.py`
- Modify: `backend/start_options.py`

**Interfaces:**
- Consumes: `assets: dict[str, ModAsset]`, `active_ids: list[str]`, persisted game-data settings.
- Produces: exact constants for both Pack names and effective launch settings with unavailable features reset only for runtime generation.

- [ ] Add a test proving a multiplier does not invoke `build_game_data_entries` when `wyccc_dynamic_unit_size.pack` is absent or inactive.
- [ ] Update the composition test with a real active marker Pack and assert the multiplier reaches the DB builder.
- [ ] Add a partial-availability test proving the unit-size Pack unlocks only the multiplier and the no-friendly-fire Pack unlocks both friendly-fire switches.
- [ ] Run `python -m unittest tests.test_start_options -v` and confirm the new tests fail for missing enforcement.
- [ ] Implement case-insensitive exact Pack-name detection from installed active assets and pass only effective settings to the DB builder.
- [ ] Re-run the focused backend tests and confirm they pass.

### Task 2: Disable unavailable modal controls and explain why

**Files:**
- Create: `frontend/src/gameDataRequirements.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/GameDataModificationModal.vue`
- Modify: `frontend/src/languages.js`
- Modify: `frontend/src/__tests__/gameDataSettings.test.js`
- Modify: `frontend/src/components/__tests__/GameDataModificationModal.test.js`

**Interfaces:**
- Produces: `requiredGameDataModStatus(mods, activeIds, packName) -> 'enabled' | 'disabled' | 'missing'` and exact exported Pack-name constants.
- Consumes: modal props `unitSizeModStatus` and `friendlyFireModStatus`.

- [ ] Add utility tests for missing, installed-but-disabled, and enabled Pack states.
- [ ] Add component tests asserting the multiplier input and both checkboxes are disabled independently and render the exact required Pack name.
- [ ] Run the focused Vitest files and confirm they fail because status handling is absent.
- [ ] Implement the shared status utility and App computed values.
- [ ] Add modal props, disabled states, missing/disabled guidance, unavailable styling, and disable Save only when neither dependency is active.
- [ ] Add the new guidance strings in Simplified Chinese, English, Korean, Russian, and Japanese.
- [ ] Re-run the focused Vitest files and confirm they pass.

### Task 3: Correct the 0.6.0 changelog for dependency Packs

**Files:**
- Modify: `backend/changelog.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: existing `v060_game_data_*` changelog keys.
- Produces: four translated 0.6.0 game-data bullets that explicitly name both required Packs.

- [ ] Keep the dedicated game-data changelog group and update the runtime-patch bullet so it no longer claims no subscription is required.
- [ ] Mention the exact unit-size and friendly-fire Pack requirements in every built-in language.
- [ ] Extend the localized changelog test to require both exact Pack names.
- [ ] Run the focused changelog tests and confirm all five languages build successfully.

### Task 4: Create two marker Packs and two Workshop covers

**Files:**
- Create: `<ModSourceRoot>/Dynamic Unit Size/wyccc_dynamic_unit_size.pack`
- Create: `<ModSourceRoot>/Dynamic Unit Size/preview.jpg`
- Create: `<ModSourceRoot>/Dynamic No Friendly Fire/wyccc_dynamic_no_friendly_fire.pack`
- Create: `<ModSourceRoot>/Dynamic No Friendly Fire/preview.jpg`

**Interfaces:**
- Each Pack contains `wyccc_dynamic_feature/manifest.json` with schema version, exact required Pack name, and supported feature IDs.
- Each preview is a square JPEG under the Workshop 1 MiB limit.

- [ ] Generate a text-free dark-fantasy square cover for Dynamic Unit Size using the built-in image tool.
- [ ] Generate a distinct text-free dark-fantasy square cover for Dynamic No Friendly Fire using the built-in image tool.
- [ ] Copy the generated images to the permanent MOD source directories, resize/compress them to Workshop-safe JPEGs, and visually inspect both.
- [ ] Build both deterministic PFH5 marker Packs with the existing writer.
- [ ] Re-read each Pack, validate its manifest, Pack type, exact filename, nonzero size, and SHA-256.
- [ ] Copy both local Pack files into the WH3 Data directory so the manager can detect them as installed local MODs.

### Task 5: Publish and verify both Workshop items

**Files:**
- Read: `backend/steamworks_bridge.py`
- Read/write external Steam Workshop state through the existing bridge.

**Interfaces:**
- Calls: `publish_workshop_item(content_path, preview_path, title, description='', change_note='', tags, visibility=0, language='english')`.
- Produces: two numeric Workshop IDs and public item URLs.

- [ ] Confirm Steam is running and Warhammer III is closed.
- [ ] Stage one content directory per item containing only its exact Pack.
- [ ] Publish `Dynamic Unit Size` with tags `mod, units`, public visibility, blank description, and blank change note.
- [ ] Publish `Dynamic No Friendly Fire` with tags `mod, battle`, public visibility, blank description, and blank change note.
- [ ] Query the returned IDs and verify title, visibility, preview/content submission, and owner where Steam exposes them.
- [ ] If Steam reports a pending legal agreement, preserve the successful item IDs and report the agreement URL without accepting legal terms on the user's behalf.

### Task 6: Final regression verification

**Files:**
- Review all files touched above.

- [ ] Run all Python unittests.
- [ ] Run all frontend Vitest tests.
- [ ] Run the frontend production build.
- [ ] Run `python -m compileall`, schema/Pack validation, `git diff --check`, and inspect the final diff.
- [ ] Confirm no application release package, Git commit, tag, or release-directory write occurred.
