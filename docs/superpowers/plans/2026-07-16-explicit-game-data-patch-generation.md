# Explicit Game Data Patch Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the game-data DB patch from the Game Data Modification window and make game launch consume only an already generated persistent patch.

**Architecture:** Split game-data transformation out of `build_runtime_options_pack` into `build_game_data_patch`, expose an atomic save-and-generate RPC, and append the persistent Pack to the internal launch order without rebuilding it. The frontend tracks the settings signature generated during the current modal session so Save can generate changed settings exactly once.

**Tech Stack:** Python 3.11, PFH5/WH3 DB tables, pywebview RPC, Vue 3, Pinia, Vitest, unittest.

## Global Constraints

- The persistent Pack is named `!!!!wyccc_game_data_patch.pack` and stays under the manager runtime directory.
- Game launch must not call `build_game_data_entries` or refresh game-data Workshop subscriptions.
- Generate patch saves only `unit_model_multiplier`, `disable_unit_friendly_fire`, and `disable_spell_friendly_fire` after successful generation.
- Launch, Continue, and save launch remain unavailable during generation.
- Existing original, Data, Workshop, and enabled MOD Packs remain read-only.

---

### Task 1: Separate persistent game-data Pack creation

**Files:**
- Modify: `tests/test_start_options.py`
- Modify: `backend/start_options.py`

**Interfaces:**
- Produces: `GAME_DATA_PATCH_NAME: str`
- Produces: `build_game_data_patch(output_dir, data_path, assets, active_ids, settings, subscribed_workshop_ids) -> dict[str, Any]`
- Changes: `build_runtime_options_pack(output_dir, data_path, assets, active_ids, settings)` no longer accepts subscriptions or creates game-data entries.

- [ ] **Step 1: Write failing tests for the split**

```python
def test_runtime_builder_does_not_generate_game_data(self):
    with patch("backend.start_options.build_game_data_entries") as builder:
        result = build_runtime_options_pack(runtime, data, {}, [], {"unit_model_multiplier": 2})
    builder.assert_not_called()
    self.assertEqual(result["path"], "")

def test_explicit_game_data_builder_writes_dedicated_pack(self):
    result = build_game_data_patch(runtime, data, {}, [], settings, (UNIT_SIZE_FEATURE_WORKSHOP_ID,))
    self.assertEqual(Path(result["path"]).name, GAME_DATA_PATCH_NAME)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv-build\Scripts\python.exe -m unittest tests.test_start_options`

Expected: import/signature failures because the dedicated builder does not exist and the runtime builder still performs game-data work.

- [ ] **Step 3: Implement the dedicated builder**

```python
GAME_DATA_PATCH_NAME = "!!!!wyccc_game_data_patch.pack"

def build_game_data_patch(
    output_dir: Path,
    data_path: str,
    assets: dict[str, ModAsset],
    active_ids: list[str],
    settings: dict[str, Any],
    subscribed_workshop_ids: Iterable[str] = (),
) -> dict[str, Any]:
    effective = _effective_game_data_settings(settings, subscribed_workshop_ids)
    output_path = Path(output_dir) / GAME_DATA_PATCH_NAME
    if not _game_data_enabled(effective):
        output_path.unlink(missing_ok=True)
        return {"path": "", "options": [], "entry_count": 0, "game_data": {}}
    sources = _collect_game_data_sources(data_path, assets, active_ids)
    game_data = build_game_data_entries(sources, effective)
    enabled = _enabled_game_data_options(effective)
    write_pfh5_pack(output_path, [PackEntry(item.name, item.payload) for item in game_data.entries])
    return {"path": str(output_path.resolve(strict=False)), "options": enabled, "entry_count": len(game_data.entries), "game_data": game_data.stats}
```

Remove the game-data branch and subscription parameter from `build_runtime_options_pack` while retaining the other launch enhancements.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `.venv-build\Scripts\python.exe -m unittest tests.test_start_options`

Expected: all start-options tests pass.

---

### Task 2: Add atomic generation RPC and launch mutual exclusion

**Files:**
- Modify: `backend/app_settings.py`
- Modify: `backend/api.py`
- Modify: `tests/test_app_settings.py`
- Modify: `tests/test_storage_and_api.py`

**Interfaces:**
- Produces: `SettingsService.normalize_changes(changes) -> dict[str, Any]`
- Produces RPC: `generate_game_data_patch(changes: dict, ordered_mod_ids: list[str]) -> {settings, patch}`
- Consumes: `GAME_DATA_PATCH_NAME` and `build_game_data_patch` from Task 1.

- [ ] **Step 1: Write failing API tests**

```python
def test_generate_game_data_patch_saves_settings_after_success(self):
    result = api.call("generate_game_data_patch", [changes, [mod_id]])
    self.assertTrue(result["ok"])
    self.assertEqual(result["data"]["settings"]["unit_model_multiplier"], 2.0)

def test_failed_patch_generation_does_not_save_settings(self):
    with patch("backend.api.build_game_data_patch", side_effect=ValueError("bad table")):
        result = api.call("generate_game_data_patch", [changes, []])
    self.assertFalse(result["ok"])
    self.assertEqual(api.settings_service.get()["unit_model_multiplier"], 1.0)

def test_launch_during_patch_generation_is_rejected(self):
    started = threading.Event()
    release = threading.Event()
    def blocking_builder(*args, **kwargs):
        started.set()
        release.wait(5)
        return {"path": "", "options": [], "entry_count": 0, "game_data": {}}
    # Start generate_game_data_patch in a thread, wait for started, call launch_game,
    # assert launch is rejected, then set release and join the worker.
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv-build\Scripts\python.exe -m unittest tests.test_app_settings tests.test_storage_and_api`

Expected: missing RPC, launch still refreshes subscriptions, and generation does not own a shared lock.

- [ ] **Step 3: Implement normalized preview and RPC**

```python
def normalize_changes(self, changes):
    current = self.get()
    for key, value in changes.items():
        if key in self.ALLOWED_KEYS:
            current[key] = value
    return self._normalize(current)

def _generate_game_data_patch(self, changes, ordered_mod_ids):
    if self._current_runtime_running():
        raise ValueError("游戏运行时无法生成游戏数据补丁")
    if not self._game_data_patch_lock.acquire(blocking=False):
        raise ValueError("游戏正在启动或补丁正在生成")
    try:
        candidate = self.settings_service.normalize_changes(_game_data_changes(changes))
        patch = build_game_data_patch(
            self.data_dir / "runtime",
            paths.data_path,
            self._assets,
            self._canonicalize_mod_ids(ordered_mod_ids),
            candidate,
            subscribed_workshop_ids=subscribed_ids,
        )
        self.settings_service.save(_game_data_changes(changes))
        return {"settings": self.settings_service.get_public(), "patch": patch}
    finally:
        self._game_data_patch_lock.release()
```

Register the RPC and make `_launch_game` acquire the same lock non-blockingly before entering the order/launch sequence.

- [ ] **Step 4: Make launch append, not generate, the persistent patch**

Build an internal asset list from the existing `!!!!wyccc_game_data_patch.pack` and ordinary runtime-options Pack, append both after user MODs, and create `wyccc_launch_mods.txt` once. Remove the subscription query and subscription argument from launch.

- [ ] **Step 5: Run focused backend tests and verify GREEN**

Run: `.venv-build\Scripts\python.exe -m unittest tests.test_app_settings tests.test_storage_and_api tests.test_start_options`

Expected: all focused backend tests pass.

---

### Task 3: Add store generation and save-time auto-generation

**Files:**
- Modify: `frontend/src/__tests__/gameDataSettings.test.js`
- Modify: `frontend/src/store.js`

**Interfaces:**
- Produces: `gameDataSettingsSignature(settings) -> string`
- Produces: `generateGameDataPatch(changes) -> Promise<object>`
- Changes: `saveGameDataSettings(changes, generatedSignature = '')` automatically generates changed, not-yet-generated drafts.

- [ ] **Step 1: Write failing store tests**

```javascript
it('generates changed settings exactly once', async () => {
  await store.saveGameDataSettings(changes, '')
  expect(invokeMock).toHaveBeenCalledWith('generate_game_data_patch', changes, store.activeIds)
})

it('does not launch while patch generation owns busy state', async () => {
  const pending = store.generateGameDataPatch(changes)
  await expect(store.launch()).rejects.toThrow('正在')
  expect(invokeMock).not.toHaveBeenCalledWith('launch_game', expect.anything(), expect.anything())
  resolveGeneration({ settings: changes, patch: {} })
  await pending
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm exec vitest run src/__tests__/gameDataSettings.test.js`

Expected: missing generation action/signature and Save still calls only `save_game_data_settings`.

- [ ] **Step 3: Implement the store actions**

Use the three normalized fields for the signature, flush playset writes before generation, wrap generation in `withBusy(t('busy.generateGameDataPatch'), () => invoke('generate_game_data_patch', changes, this.activeIds))`, update settings only from a successful response, and show `toast.gameDataPatchGenerated`.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pnpm exec vitest run src/__tests__/gameDataSettings.test.js`

Expected: all game-data store tests pass.

---

### Task 4: Add the Generate patch control and session signature

**Files:**
- Modify: `frontend/src/components/__tests__/GameDataModificationModal.test.js`
- Modify: `frontend/src/components/GameDataModificationModal.vue`
- Modify: `frontend/src/App.vue`

**Interfaces:**
- Modal emits: `generate` with the normalized three-setting payload.
- App tracks: `gameDataGeneratedSignature: Ref<string>`.

- [ ] **Step 1: Write a failing component test**

```javascript
await wrapper.get('[data-testid="generate-game-data-patch"]').trigger('click')
expect(wrapper.emitted('generate')[0][0]).toEqual(expectedSettings)
expect(wrapper.emitted('save')).toBeUndefined()
```

- [ ] **Step 2: Run the component test and verify RED**

Run: `pnpm exec vitest run src/components/__tests__/GameDataModificationModal.test.js`

Expected: the Generate patch button and event do not exist.

- [ ] **Step 3: Implement modal and App orchestration**

Add a type=button Generate control between Cancel and Save. Reset the session signature on open, record it after successful explicit generation, pass it into Save, and leave the modal open after explicit generation. Close only after Save succeeds.

- [ ] **Step 4: Run component/store tests and verify GREEN**

Run: `pnpm exec vitest run src/components/__tests__/GameDataModificationModal.test.js src/__tests__/gameDataSettings.test.js`

Expected: both files pass.

---

### Task 5: Update user-facing copy and release notes

**Files:**
- Modify: `frontend/src/languages.js`
- Modify: `frontend/src/__tests__/languages.test.js`
- Modify: `backend/changelog.py`
- Modify: `tests/test_main.py`

**Interfaces:** Five complete variants for `gameData.generatePatch`, `busy.generateGameDataPatch`, and `toast.gameDataPatchGenerated`.

- [ ] **Step 1: Add failing localization assertions**

Assert that every language describes explicit generation, contains a Generate patch label, and no longer says the patch is rebuilt on every launch.

- [ ] **Step 2: Run language/changelog tests and verify RED**

Run: `pnpm exec vitest run src/__tests__/languages.test.js` and `.venv-build\Scripts\python.exe -m unittest tests.test_main`

Expected: old launch-time wording remains and new keys are absent.

- [ ] **Step 3: Update five-language copy and concise 0.6.0 notes**

Describe one-click patch generation and automatic generation when changed settings are saved. Avoid DB implementation details in the changelog.

- [ ] **Step 4: Run language/changelog tests and verify GREEN**

Run `pnpm exec vitest run src/__tests__/languages.test.js` and `.venv-build\Scripts\python.exe -m unittest tests.test_main`; expected all pass.

---

### Task 6: Full verification

**Files:** Review all files above.

- [ ] Run `.venv-build\Scripts\python.exe -m unittest discover -s tests`.
- [ ] Run `pnpm test` under `frontend`.
- [ ] Run `pnpm build` under `frontend`.
- [ ] Run `.venv-build\Scripts\python.exe -m ruff check backend tests main.py scripts`.
- [ ] Run `git diff --check`.
- [ ] Search for launch-time game-data generation wording and calls, confirming `_launch_game` never invokes the transformer or subscription refresh.
