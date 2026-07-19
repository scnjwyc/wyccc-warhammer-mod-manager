# Game Data Final DB Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate game-data patches from the effective DB produced by the enabled MOD Pack order instead of allowing vanilla internal table names to override enabled MOD rows.

**Architecture:** Keep the existing ordered `DbSource` pipeline. Change candidate precedence so source Pack rank is authoritative and internal DB filename rank applies only within one source Pack; then bump the builder version so cached patches built with the old semantics are regenerated.

**Tech Stack:** Python 3.11+, PFH5 reader/writer, existing WH3 DB schema parser, `unittest`.

## Global Constraints

- Preserve canonical `active_ids` order exactly.
- Treat enabled MOD Packs as higher priority than vanilla `db.pack`.
- Preserve internal DB filename priority within a single Pack.
- Do not change application version metadata, package a release, or publish artifacts.
- Follow red-green TDD for every production change.

---

### Task 1: Make Pack order authoritative for effective DB rows

**Files:**
- Modify: `backend/game_data.py`
- Modify: `tests/test_game_data.py`
- Modify: `tests/test_start_options.py`

**Interfaces:**
- Consumes: `Sequence[DbSource]` where index 0 is the highest-priority Pack.
- Produces: `_has_higher_priority(candidate: _Candidate, existing: _Candidate) -> bool` with Pack-first, table-name-second precedence.
- Preserves: `_collect_game_data_sources(...) -> tuple[DbSource, ...]` ordered as active MODs followed by vanilla `db.pack`.

- [ ] **Step 1: Add failing Pack-order regression tests**

Add tests that build synthetic `main_units_tables` rows with deliberately
conflicting internal names:

```python
def test_pack_load_order_outranks_internal_table_file_names(self) -> None:
    mod = DbSource(
        "sfo.pack",
        (
            GameDataEntry(
                "db\\main_units_tables\\SFO_data",
                _table_payload(
                    "main_units_tables",
                    7,
                    [{
                        "unit": "unit_knights",
                        "caste": "cavalry",
                        "land_unit": "land_knights",
                        "num_men": 32,
                    }],
                ),
            ),
            GameDataEntry(
                "db\\land_units_tables\\SFO_data",
                _table_payload(
                    "land_units_tables",
                    54,
                    [{"key": "land_knights", "num_mounts": 32}],
                ),
            ),
        ),
    )
    vanilla = DbSource(
        "db.pack",
        (
            GameDataEntry(
                "db\\main_units_tables\\data__",
                _table_payload(
                    "main_units_tables",
                    7,
                    [{
                        "unit": "unit_knights",
                        "caste": "cavalry",
                        "land_unit": "land_knights",
                        "num_men": 24,
                    }],
                ),
            ),
            GameDataEntry(
                "db\\land_units_tables\\data__",
                _table_payload(
                    "land_units_tables",
                    54,
                    [{"key": "land_knights", "num_mounts": 24}],
                ),
            ),
        ),
    )

    result = build_game_data_entries(
        [mod, vanilla],
        {"unit_model_multiplier": 2},
    )

    main_rows = {row["unit"]: row for row in _rows_for(result, "main_units_tables")}
    self.assertEqual(main_rows["unit_knights"]["num_men"], 64)
```

Add a second assertion/test that reverses two MOD `DbSource` objects and proves
the winner reverses, while a duplicate key in two entries of one `DbSource`
still follows `_compare_internal_names`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
. .\scripts\windows_bootstrap.ps1
$python = Get-WmmPython -Root (Get-Location)
& $python -m unittest tests.test_game_data -v
```

Expected: the SFO-shaped test reports the vanilla-derived value `48` instead
of the required MOD-derived value `64`.

- [ ] **Step 3: Implement Pack-first precedence**

Update `_has_higher_priority` so source rank is compared before internal names:

```python
def _has_higher_priority(candidate: _Candidate, existing: _Candidate) -> bool:
    if candidate.source_rank != existing.source_rank:
        return candidate.source_rank < existing.source_rank
    file_order = _compare_internal_names(
        candidate.internal_name,
        existing.internal_name,
    )
    if file_order:
        return file_order < 0
    return (
        candidate.entry_rank,
        candidate.row_rank,
    ) < (
        existing.entry_rank,
        existing.row_rank,
    )
```

Do not reverse `_collect_game_data_sources`; its current sequence already places
canonical active MODs before vanilla.

- [ ] **Step 4: Add source-sequence integration coverage**

In `tests/test_start_options.py`, create two PFH5 MOD fixtures and `ModAsset`
records, invoke `build_game_data_patch` with a mocked
`build_game_data_entries`, and assert:

```python
self.assertEqual(
    [source.name for source in builder.call_args.args[0]],
    ["high.pack", "low.pack", "db.pack"],
)
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
& $python -m unittest tests.test_game_data tests.test_start_options -v
```

Expected: all effective-row and source-order tests pass.

### Task 2: Invalidate patches generated with the old overlay semantics

**Files:**
- Modify: `backend/game_data_patch_state.py`
- Modify: `tests/test_game_data_patch_state.py`

**Interfaces:**
- Produces: `GAME_DATA_BUILDER_VERSION = 9`.
- Relies on: existing fingerprint classification returning `"builder"` when the stored builder version differs.

- [ ] **Step 1: Write the failing builder-version test**

Rename the existing builder-version test to describe final-DB overlay
invalidation and require version 9:

```python
def test_builder_version_invalidates_pre_final_db_overlay_patches(self) -> None:
    self.assertEqual(GAME_DATA_BUILDER_VERSION, 9)
```

Retain the existing fingerprint-change coverage that mutates
`builder_version`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
& $python -m unittest tests.test_game_data_patch_state -v
```

Expected: FAIL because the production builder version is still 8.

- [ ] **Step 3: Increment the builder version**

Change:

```python
GAME_DATA_BUILDER_VERSION = 9
```

- [ ] **Step 4: Verify focused GREEN**

Run:

```powershell
& $python -m unittest tests.test_game_data tests.test_start_options tests.test_game_data_patch_state -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Run complete verification**

Run:

```powershell
. .\scripts\windows_bootstrap.ps1
$python = Get-WmmPython -Root (Get-Location)
& $python -m unittest discover -s tests -t . -q
& $python -m compileall -q backend main.py
& $python -m ruff check backend tests main.py
$pnpm = Get-WmmPnpm
& $pnpm --dir frontend test -- --run
& $pnpm --dir frontend build
git diff --check
git status --short
```

Expected: backend, frontend, compilation, Ruff, build, and diff checks pass;
only intended source, test, spec, and plan changes are present.
