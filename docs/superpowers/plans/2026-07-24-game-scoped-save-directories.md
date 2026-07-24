# Game-Scoped Save Directories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every save operation uses the save directory of the currently selected game.

**Architecture:** Make `default_save_directory` game-aware while retaining global environment overrides. Rebuild the API's `SaveGameService` after selected-game changes so list, MOD extraction, launch, and continue share one current-game directory.

**Tech Stack:** Python 3.11, pytest.

## Global Constraints

- `warhammer3` uses `%APPDATA%\\The Creative Assembly\\Warhammer3\\save_games`.
- `three_kingdoms` uses `%APPDATA%\\The Creative Assembly\\ThreeKingdoms\\save_games`.
- `WYCCC_MM_SAVE_DIR`, `WYCCC_WM_SAVE_DIR`, and `WYCCC_WMM_SAVE_DIR` remain highest-priority global overrides.
- Invalid or omitted game IDs keep the Warhammer 3 default.

---

### Task 1: Resolve save directories by game

**Files:**

- Modify: `backend/save_games.py`
- Test: `tests/test_save_games.py`

**Interfaces:**

- Produces: `default_save_directory(game_id: str | None = None) -> Path`
- Produces: `SaveGameService(save_directory: Path | None = None, game_id: str | None = None)`

- [ ] **Step 1: Write the failing tests**

Add tests that patch `APPDATA` and assert `three_kingdoms` resolves to `The Creative Assembly/ThreeKingdoms/save_games`, while `warhammer3` and unknown IDs resolve to `Warhammer3/save_games`. Add a separate test that `WYCCC_MM_SAVE_DIR` overrides the Three Kingdoms directory.

- [ ] **Step 2: Verify RED**

Run `python -m pytest tests/test_save_games.py -q`.

Expected: Three Kingdoms resolves to Warhammer 3 or the constructor does not accept `game_id`.

- [ ] **Step 3: Implement the minimal resolver**

Keep the existing environment override block first, add a profile-directory mapping keyed by game ID, and pass `game_id` through `SaveGameService` when no directory is injected.

- [ ] **Step 4: Verify GREEN and commit**

Run `python -m pytest tests/test_save_games.py -q`, then commit `backend/save_games.py` and `tests/test_save_games.py` with message `feat: resolve save directories by game`.

### Task 2: Synchronize saves after selected-game changes

**Files:**

- Modify: `backend/api.py`
- Test: `tests/test_save_games.py`

**Interfaces:**

- Produces: `API._sync_save_games()` that rebuilds `self.save_games` from `self._active_game().id`.

- [ ] **Step 1: Write the failing switch test**

Patch the default resolver to return separate temporary Warhammer 3 and Three Kingdoms roots. After `save_settings` selects Three Kingdoms, assert `list_save_games`, `get_save_mods`, and `continue_game` use `three.save`; after switching back, assert the list uses `warhammer.save`.

- [ ] **Step 2: Verify RED**

Run `python -m pytest tests/test_save_games.py -q`.

Expected: the API remains on the original Warhammer 3 directory after selecting Three Kingdoms.

- [ ] **Step 3: Implement synchronization**

Add `_sync_save_games()` using `SaveGameService(game_id=self._active_game().id)`. Call it from `API.__init__` after settings are available and from `_save_settings` immediately after saving changes.

- [ ] **Step 4: Verify GREEN and commit**

Run `python -m pytest tests/test_save_games.py -q`, then commit `backend/api.py` and the test with message `fix: sync saves with selected game`.

### Task 3: Regression verification

- [ ] Run `python -m pytest -q`, `python -m ruff check backend tests`, and `git diff --check`.
- [ ] Confirm there is no direct `SaveGameService()` construction in `backend/api.py` outside `_sync_save_games()`, and no UI, version, or release changes.
