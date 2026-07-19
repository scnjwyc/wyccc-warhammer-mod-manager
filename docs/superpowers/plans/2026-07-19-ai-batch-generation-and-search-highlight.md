# AI Batch Generation and Search Highlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver WMM 0.8.2 batch AI user-data generation and persistent in-place search highlighting.

**Architecture:** Keep the backend RPC unchanged.  The Pinia store owns sequential batch generation and a persisted search display mode; `App.vue` routes menu actions, supplies list match IDs, and requests first-result focus.  `ModList.vue` renders match and muted row state without changing selection or ordering.

**Tech Stack:** Vue 3, Pinia, Vitest, Python unittest, Vite.

## Global Constraints

- Use the existing `generate_mod_user_data` RPC only; do not add a batch backend endpoint.
- Show the batch action only with configured AI and more than one selected MOD.
- Process selected MODs serially and continue after individual failures.
- Persist highlight mode in settings; default to the existing filtered-list experience.
- Do not package, publish, tag, commit, or update the public 0.8.1 release manifest.
- Preserve source version, changelog, translations, package metadata, Windows metadata, documentation, and tests in lockstep at 0.8.2.

---

### Task 1: Batch AI action and sequential store queue

**Files:**
- Modify: `frontend/src/components/ModContextMenu.vue`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/store.js`
- Test: `frontend/src/components/__tests__/ModContextMenu.test.js`
- Test: `frontend/src/__tests__/selection.test.js`

**Interfaces:**
- Consumes: `settings.ai_enabled`, `selectedActionIds(modId)`, and `generateModUserData(modId)`.
- Produces: `generateModUserDataMany(modIds): Promise<{ succeeded: string[], failed: string[] }>` and context action `generate-user-data`.

- [ ] **Step 1: Write failing UI and store tests**

```js
expect(wrapper.find('[data-testid="context-generate-user-data"]').text()).toContain('AI 生成（3 项）')
await store.generateModUserDataMany(['a', 'b', 'c'])
expect(invoke).toHaveBeenNthCalledWith(1, 'generate_mod_user_data', 'a')
expect(invoke).toHaveBeenNthCalledWith(3, 'generate_mod_user_data', 'c')
```

- [ ] **Step 2: Run focused tests and confirm the batch action is absent**

Run: `pnpm vitest run src/components/__tests__/ModContextMenu.test.js src/__tests__/selection.test.js`

- [ ] **Step 3: Add the minimal menu, routing, and serial queue implementation**

```js
for (const modId of normalizedIds) {
  try { await this.generateModUserData(modId) } catch { failed.push(modId) }
}
```

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `pnpm vitest run src/components/__tests__/ModContextMenu.test.js src/__tests__/selection.test.js`

### Task 2: Persistent search-highlight display mode

**Files:**
- Modify: `frontend/src/store.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/TagSearchBox.vue`
- Modify: `frontend/src/components/ModList.vue`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/languages.js`
- Test: `frontend/src/__tests__/modSearch.test.js`
- Test: `frontend/src/components/__tests__/ModList.test.js`
- Test: `frontend/src/__tests__/gameDataSettings.test.js`

**Interfaces:**
- Consumes: `matchesSearchTokens(mod, tokens, logic, typeMap)` and persisted `settings`.
- Produces: `settings.search_highlight_mode`, complete display lists in highlight mode, `matchIds` list prop, and `scroll-to-first-match` list prop.

- [ ] **Step 1: Write failing tests for persisted mode and row state**

```js
store.setSearchHighlightMode(true)
expect(store.settings.search_highlight_mode).toBe(true)
expect(wrapper.get('[data-testid="mod-list"] .mod-row.search-match').exists()).toBe(true)
expect(wrapper.get('[data-testid="mod-list"] .mod-row.search-muted').exists()).toBe(true)
```

- [ ] **Step 2: Run focused tests and confirm missing settings and row classes fail**

Run: `pnpm vitest run src/__tests__/modSearch.test.js src/components/__tests__/ModList.test.js src/__tests__/gameDataSettings.test.js`

- [ ] **Step 3: Add mode state, localized toggle, unfiltered display lists, row styling, and first-result scroll**

```js
const isSearchMatch = modId => props.searchActive && props.matchIds.includes(modId)
const isSearchMuted = modId => props.searchActive && !isSearchMatch(modId)
```

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `pnpm vitest run src/__tests__/modSearch.test.js src/components/__tests__/ModList.test.js src/__tests__/gameDataSettings.test.js`

### Task 3: Version, changelog, and full regression verification

**Files:**
- Modify: `backend/constants.py`
- Modify: `backend/changelog.py`
- Modify: `backend/workshop_collections.py`
- Modify: `frontend/package.json`
- Modify: `frontend/src/store.js`
- Modify: `packaging/version_info.txt`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `APP_VERSION`, `CHANGELOG_STRUCTURE`, localized changelog catalogs, and public update manifest.
- Produces: source version `0.8.2` while manifest version remains `0.8.1`.

- [ ] **Step 1: Write the version contract test**

```python
self.assertEqual(APP_VERSION, "0.8.2")
self.assertEqual(update_manifest["version"], "0.8.1")
self.assertFalse(is_newer_version(update_manifest["version"], APP_VERSION))
```

- [ ] **Step 2: Run the focused backend test and confirm it fails on the old source version**

Run: `python -m unittest tests.test_main.MainTests.test_version_metadata_and_changelog_are_synced`

- [ ] **Step 3: Update all source version and localized 0.8.2 changelog surfaces**

```python
APP_VERSION = "0.8.2"
```

- [ ] **Step 4: Run full verification**

Run: `python -m unittest discover -s tests -v; pnpm test; pnpm build; git diff --check`

