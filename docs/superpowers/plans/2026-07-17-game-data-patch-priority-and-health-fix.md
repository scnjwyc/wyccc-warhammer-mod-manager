# Game Data Patch Priority and Character Health Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development and superpowers:systematic-debugging. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every generated unit-scale DB row wins runtime conflicts and every opted-in lord/hero receives an exact total-health multiplier.

**Architecture:** `backend/game_data.py` will select a verified dynamic internal filename priority and use `battle_entities_tables` as a read-only dependency for character total-health calculations. `backend/game_data_patch_state.py` will invalidate all version-2 generated patches.

**Tech Stack:** Python 3, PFH5/CA DB binary parsing, `unittest`.

## Global Constraints

- Preserve unrelated uncommitted files and edits.
- Do not package, publish, tag, or commit.
- Write regression tests before production changes.

---

### Task 1: Reproduce DB internal-name override

**Files:**
- Modify: `tests/test_game_data.py`
- Modify: `backend/game_data.py`

- [ ] Add a fixture whose source table name starts with seven `!` characters.
- [ ] Build the patch and merge the generated/source rows with the existing priority resolver.
- [ ] Verify the test fails because the source row wins.
- [ ] Generate a table name with one more leading `!` than every effective source candidate and verify it sorts first.
- [ ] Run `.\.venv-build\Scripts\python.exe -m unittest tests.test_game_data -v`.

### Task 2: Scale complete character health

**Files:**
- Modify: `backend/wh3_db_schema.json`
- Modify: `backend/game_data.py`
- Modify: `tests/test_game_data.py`

- [ ] Add schema coverage for supported `battle_entities_tables` versions.
- [ ] Add a lord/hero fixture where `hit_points` is material and assert exact total-health scaling.
- [ ] Verify the old bonus-only implementation fails.
- [ ] Resolve `man_entity`, scale `hit_points + bonus_hit_points`, and write the calculated bonus only.
- [ ] Add unresolved-reference failure coverage.
- [ ] Run `.\.venv-build\Scripts\python.exe -m unittest tests.test_game_data -v`.

### Task 3: Invalidate old output and verify launch regressions

**Files:**
- Modify: `backend/game_data_patch_state.py`
- Test: `tests/test_game_data_patch_state.py`
- Test: `tests/test_start_options.py`
- Test: `tests/test_storage_and_api.py`

- [ ] Bump `GAME_DATA_BUILDER_VERSION`.
- [ ] Run focused patch-state and launch suites.
- [ ] Audit a real installed Workshop corpus against the generated internal table names.
- [ ] Run the complete backend test suite, compile checks, and `git diff --check`.
