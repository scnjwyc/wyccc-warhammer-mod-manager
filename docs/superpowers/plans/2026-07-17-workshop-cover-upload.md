# Workshop Cover Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upload a same-name PNG cover alongside each published MOD Pack and reject covers over 1 MiB.

**Architecture:** Derive the cover from the Pack path in the backend, stage both files in the temporary Steam content directory, and submit that staged PNG as the Steam preview. The Vue dialog renders the derived path as read-only guidance rather than accepting arbitrary preview input.

**Tech Stack:** Python 3.11, pywebview RPC, Vue 3, Vitest, unittest.

## Global Constraints

- A publishable `example.pack` requires sibling `example.png`.
- Cover maximum is exactly `1_024 * 1_024` bytes.
- The staged Workshop content contains both files.
- Do not run packaging, release, or modify `G:\Wyccc's Mod Manager`.

---

### Task 1: Lock the backend package contract

**Files:**
- Modify: `tests/test_storage_and_api.py`
- Modify: `backend/api.py`

**Interfaces:**
- Consumes: a local `ModAsset.path` ending in `.pack`.
- Produces: a temporary `content/<pack>.pack` and `content/<pack>.png` pair for `publish_workshop_item`.

- [x] **Step 1: Write failing API tests**

Create `my_own_mod.png` beside `my_own_mod.pack`. In the fake bridge, assert
`content/my_own_mod.pack` and `content/my_own_mod.png` both exist, assert
`preview_path == content/my_own_mod.png`, then add independent calls that fail
when the sibling PNG is absent and when it is `1_024 * 1_024 + 1` bytes.

- [x] **Step 2: Run the focused test**

Run: `.\\.venv-build\\Scripts\\python.exe -m unittest tests.test_storage_and_api`

Expected before implementation: the staged PNG assertion fails because the
current uploader only stages the Pack.

- [x] **Step 3: Implement canonical cover resolution and staging**

Add a focused helper that maps `source_pack` to `source_pack.with_suffix('.png')`,
requires a file at that exact location, enforces the 1 MiB limit, and returns
the path. In `_publish_workshop_item`, stage that cover with the Pack and pass
the staged PNG as `preview_path`.

- [x] **Step 4: Run the focused test again**

Run: `.\\.venv-build\\Scripts\\python.exe -m unittest tests.test_storage_and_api`

Expected after implementation: all tests pass.

### Task 2: Make the publish dialog reflect the enforced contract

**Files:**
- Modify: `frontend/src/components/WorkshopPublishModal.vue`
- Modify: `frontend/src/languages.js`
- Modify: `frontend/src/__tests__/publishAndListComponents.test.js`

**Interfaces:**
- Consumes: `mod.path` ending in `.pack`.
- Produces: a read-only display of the derived `<stem>.png` path and a payload
  containing only publish metadata.

- [x] **Step 1: Write the failing component assertion**

Mount the upload dialog with `G:/game/data/my_own_mod.pack`. Assert that it
shows `G:/game/data/my_own_mod.png`, has no editable preview file input or
Browse button, and emits no arbitrary `preview_path` value.

- [x] **Step 2: Run the focused component test**

Run: `& 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\bin\\node.exe' node_modules/vitest/vitest.mjs run src/__tests__/publishAndListComponents.test.js`

Working directory: `frontend`

Expected before implementation: the dialog still renders the editable preview
input and emits `preview_path`.

- [x] **Step 3: Implement the read-only cover field and localized copy**

Derive the cover with a case-insensitive `.pack` replacement in the component.
Replace the browseable preview control with a read-only field plus a help line
that states the same-name PNG and 1 MiB rule. Update all five language entries.

- [x] **Step 4: Run the focused component test again**

Run the Task 2 test command and expect it to pass.

### Task 3: Regression verification

**Files:**
- Verify: `tests/test_storage_and_api.py`
- Verify: `tests/test_steamworks_bridge.py`
- Verify: `frontend/src/__tests__/publishAndListComponents.test.js`

- [x] **Step 1: Run backend publishing coverage**

Run: `.\\.venv-build\\Scripts\\python.exe -m unittest tests.test_storage_and_api tests.test_steamworks_bridge tests.test_scanner`

- [x] **Step 2: Run frontend publishing coverage and production build**

Run from `frontend`:

```powershell
& 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\bin\\node.exe' node_modules/vitest/vitest.mjs run src/__tests__/publishAndListComponents.test.js
& 'C:\\Users\\Administrator\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\node\\bin\\node.exe' node_modules/vite/bin/vite.js build
```

- [x] **Step 3: Inspect the final scope**

Run `git diff --check` and `git status --short`. Confirm that the change is
limited to source, tests, and internal design/plan documents.
