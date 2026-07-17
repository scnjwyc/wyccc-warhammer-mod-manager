# Non-Spell Friendly-Fire KV Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:systematic-debugging and superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the four reference global projectile friendly-fire rules whenever non-spell friendly-fire removal is enabled.

**Architecture:** Add `_kv_rules_tables` version-0 parsing to the existing focused DB schema. `backend/game_data.py` will emit a four-row, priority-safe table entry rather than duplicating the complete rule table. The builder-version bump makes launch-time fingerprinting regenerate affected existing patches.

**Tech Stack:** Python 3, PFH5/CA DB binary parsing, `unittest`.

## Global Constraints

- Preserve unrelated uncommitted files and edits.
- Do not package, publish, tag, or commit.
- Do not read the reference Pack at runtime.
- Write and run regression tests before production changes.

---

### Task 1: Specify the generated rule behavior

**Files:**

- Modify: `tests/test_game_data.py`

- [x] **Step 1: Write the failing non-spell fixture**

```python
result = build_game_data_entries(
    [high_priority_kv_source],
    {"disable_unit_friendly_fire": True, "disable_spell_friendly_fire": False},
)
assert generated_kv_rules == REFERENCE_KV_RULES
```

- [x] **Step 2: Run the focused test to verify it fails**

Run: `./.venv-build/Scripts/python.exe -m unittest tests.test_game_data.GameDataPatchTests.test_non_spell_friendly_fire_adds_reference_kv_rules -v`

Expected: the generated `_kv_rules_tables` entry is absent before the implementation.

### Task 2: Emit the priority-safe reference rows

**Files:**

- Modify: `backend/wh3_db_schema.json`
- Modify: `backend/game_data.py`

- [x] **Step 1: Add the version-0 key/value schema and table metadata**

```python
"_kv_rules_tables": {"0": [["key", "StringU8"], ["value", "F32"]]}
```

- [x] **Step 2: Add the four embedded rows and serialize only those rows**

```python
REFERENCE_NON_SPELL_FRIENDLY_FIRE_KV_RULES = (
    ("projectile_friendly_fire_man_height_coefficient", 0.6),
    ("projectile_friendly_fire_man_radius_coefficient", 1.2),
    ("projectile_friendly_fire_ignore_allies_height_coefficient", 0.6),
    ("projectile_friendly_fire_ignore_allies_radius_coefficient", 1.2),
)
```

- [x] **Step 3: Verify the focused test passes**

Run: `./.venv-build/Scripts/python.exe -m unittest tests.test_game_data.GameDataPatchTests.test_non_spell_friendly_fire_adds_reference_kv_rules -v`

Expected: PASS, with a generated filename that sorts ahead of the fixture source table.

### Task 3: Regenerate pre-change patches

**Files:**

- Modify: `backend/game_data_patch_state.py`
- Modify: `tests/test_game_data_patch_state.py`

- [x] **Step 1: Update the expected builder version test**

```python
self.assertEqual(GAME_DATA_BUILDER_VERSION, 4)
```

- [x] **Step 2: Increment the production builder version to 4**

```python
GAME_DATA_BUILDER_VERSION = 4
```

- [x] **Step 3: Verify game-data and patch-state tests**

Run: `./.venv-build/Scripts/python.exe -m unittest tests.test_game_data tests.test_game_data_patch_state -v`

Expected: PASS.

### Task 4: Verify integration quality

**Files:**

- Modify: `tests/test_main.py`

- [x] **Step 1: Add a catalog-completeness regression assertion for the launch-time changelog import**

```python
referenced_keys = {
    key
    for release in CHANGELOG_STRUCTURE
    for title_key, changes in release["entries"]
    for key in (title_key, *(text_key for _kind, text_key in changes))
}
for language, catalog in CHANGELOG_TEXT.items():
    self.assertSetEqual(referenced_keys - set(catalog), set(), language)
```

- [x] **Step 2: Run full verification**

Run: `./.venv-build/Scripts/python.exe -m unittest discover -s tests -v`

Expected: all tests pass; then run `python -m compileall backend main.py` and `git diff --check`.
