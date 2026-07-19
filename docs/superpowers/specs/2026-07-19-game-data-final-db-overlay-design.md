# Game Data Final DB Overlay Design

## Goal

Generate every launch-time game-data patch from the effective DB rows produced
after applying vanilla and all enabled MOD Packs in the manager's actual load
order.

## Confirmed root cause

The current merge comparator checks an entry's internal DB filename before it
checks the source Pack's load-order rank. That makes internal names global
across all Packs. For example, the installed
`sfo_grimhammer_3_main.pack` stores most `main_units_tables` rows in
`SFO_data`, while vanilla `db.pack` stores them in `data__`. The current
comparator selects vanilla `data__` because it sorts before `SFO_data`, even
though SFO is an enabled higher-priority Pack.

This was reproduced against the installed SFO Pack. For
`wh2_dlc09_tmb_cav_necropolis_knights_0`, vanilla supplies 24 models and SFO
supplies 32, but the current effective-row collector returns vanilla's 24.
Applying a 2x multiplier therefore produces 48 instead of the expected 64.

## Overlay semantics

The source sequence is already constructed in manager load order:

1. enabled MOD Packs, in canonical `active_ids` order;
2. vanilla `db.pack` as the lowest-priority fallback.

Effective-row precedence will become:

1. lower source rank wins, so the enabled Pack order is authoritative;
2. within the same Pack, the existing internal DB filename comparator decides
   which table file supplies a duplicate key;
3. if both Pack and internal name are equal, entry rank and row rank provide a
   deterministic fallback.

This means a high-priority compatibility patch can override SFO, SFO can
override vanilla regardless of names such as `SFO_data`, and multiple table
files inside one Pack continue to obey their internal filename priority.

## Patch generation

`build_game_data_entries` continues to receive `DbSource` objects and to
serialize complete effective output tables. Only effective-row selection
changes. All existing transformations—unit model multiplier, recruitment
capacity, character/single-entity health, and friendly-fire controls—therefore
operate on the final values supplied by the enabled MOD stack.

Generated table naming remains unchanged. It still creates a table name that
outranks every source internal name so the generated Pack remains the final
runtime override.

## Cache invalidation

Increment `GAME_DATA_BUILDER_VERSION` from 8 to 9. The existing fingerprint
already contains the ordered active MOD IDs, every source Pack's file
signature, and vanilla `db.pack`; the builder-version bump is sufficient to
invalidate every patch created with the old overlay semantics.

## Error handling

Existing parse and reference failures remain launch-blocking. Missing enabled
assets remain represented in the fingerprint and are rejected by the load
order path before generation. No partially merged DB or stale patch is used
when generation fails.

## Verification

- A higher-priority MOD row must beat a vanilla row even when its internal DB
  filename sorts after vanilla's filename.
- Two enabled MODs that modify the same key must resolve according to their
  `active_ids` order, and reversing that order must reverse the winner.
- Duplicate rows inside one Pack must continue to resolve by internal DB
  filename.
- An SFO-shaped fixture with vanilla 24 and MOD 32 must produce 64 at 2x, not
  48.
- Builder version 9 must invalidate a version-8 manifest.
- Existing game-data, patch-state, launch, backend, and frontend tests must
  remain green.

## Scope

This is a source-and-test fix only. It does not change application version
metadata, package a release, update public manifests, create commits on
`main`, or publish artifacts.
