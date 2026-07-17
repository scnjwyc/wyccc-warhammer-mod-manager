# Save MOD Extraction Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse both current length-prefixed and legacy NUL-delimited MOD Pack
names from WARHAMMER III saves.

**Architecture:** Keep parsing in `SaveGameService.pack_names`. Candidates remain
bounded to a Pack filename, but must pass either a legacy terminator check or a
strict matching little-endian string-length check before existing filtering and
de-duplication run.

**Tech Stack:** Python 3.11, unittest, Vue 3, Vitest.

## Global Constraints

- Do not change save discovery, the RPC name, or frontend MOD matching behavior.
- Preserve the legacy NUL-delimited format.
- A length-prefixed candidate is valid only when its four-byte little-endian
  length equals the exact raw token length.
- Do not run packaging, release, or modify `G:\Wyccc's Mod Manager`.

---

### Task 1: Reproduce current WH3 serialization in tests

**Files:**
- Modify: `tests/test_save_games.py`

**Interfaces:**
- Consumes: `SaveGameService.pack_names(save_name, excluded_pack_names)`.
- Produces: ordered, filtered `pack_names` for the save RPC.

- [x] **Step 1: Add a failing current-format fixture**

Add a test containing entries constructed as
`len(name).to_bytes(4, 'little') + name`; put a non-NUL byte after each Pack
name. Assert vanilla `data.pack` is excluded and custom Packs are returned in
stored order.

- [x] **Step 2: Add a malformed-candidate assertion**

Place an unframed `ignored.pack` string adjacent to a valid length-prefixed
entry. Assert only the valid entry is returned.

- [x] **Step 3: Run the focused module and observe RED**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_save_games`

Expected before the parser change: the new current-format test fails because
the old code searches only for `b'.pack\\0'`.

### Task 2: Implement verified dual-format extraction

**Files:**
- Modify: `backend/save_games.py`
- Test: `tests/test_save_games.py`

**Interfaces:**
- Consumes: the raw save bytes, marker position, and bounded token range.
- Produces: only Pack names with a legacy NUL terminator or matching uint32
  length prefix.

- [x] **Step 1: Add record-layout helpers**

Implement a helper for the legacy terminator and one that reads the four bytes
before the token with `int.from_bytes(..., 'little')`, returning true only on
an exact token-length match.

- [x] **Step 2: Relax marker discovery and require a verified layout**

Search for `.pack`, derive the bounded token exactly as before, then discard it
unless either layout helper validates it. Leave filename validation, exclusions,
de-duplication, and ordering unchanged.

- [x] **Step 3: Run the focused module and observe GREEN**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_save_games`

Expected after the change: all save-game tests pass, including the existing
legacy-layout test.

### Task 3: Regression verification

**Files:**
- Verify: `backend/save_games.py`
- Verify: `tests/test_save_games.py`
- Verify: `frontend/src/__tests__/selection.test.js`

- [x] **Step 1: Run backend tests**

Run: `.\.venv-build\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'`

- [x] **Step 2: Run frontend save-action coverage**

Run from `frontend`:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' node_modules\vitest\vitest.mjs run src\__tests__\selection.test.js
```

- [x] **Step 3: Inspect final scope**

Run `git diff --check` and `git status --short`; confirm the change is limited
to the parser, regression tests, and internal design/plan documents.
