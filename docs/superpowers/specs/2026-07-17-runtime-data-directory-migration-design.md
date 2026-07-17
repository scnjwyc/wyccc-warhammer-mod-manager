# Runtime Data Directory Migration Design

## Status

Approved under the user's standing instruction to continue implementation without additional confirmation.

## Problem

Frozen builds currently create `data/` beside the executable before any network request. When a player runs the single-file release from the Desktop, that portable directory is therefore created on the Desktop. The delayed background Workshop refresh makes the timing look network-related, but VPN availability is not part of the directory-selection logic.

The same behavior exists in both 0.6.0 and 0.6.5.

## Goals

- Store frozen-build runtime data under the normal per-user application data directory by default.
- Never create a sibling `data/` directory for a new frozen-build installation.
- Preserve settings, playsets, state, logs, and caches created by earlier portable releases.
- Keep explicit `--data-dir` and `WYCCC_MM_DATA_DIR`-family overrides unchanged.
- Keep the application usable if automatic migration fails.

## Non-goals

- Do not delete the legacy portable directory automatically.
- Do not merge two non-empty data directories.
- Do not change game `Data` directory handling.
- Do not rewrite an already published release tag.

## Selected Design

`resolve_runtime_data_dir()` will continue honoring the command-line override first and environment overrides through `default_data_dir()`.

For a frozen build without an explicit override:

1. Resolve the normal per-user destination with `default_data_dir()`.
2. Treat `<EXE directory>/data` as a legacy portable source only; never create it.
3. If the per-user destination already contains data, use it and do not touch the portable source.
4. If the destination is absent or empty and the portable source exists, copy the complete portable source into a temporary sibling directory under the destination parent.
5. Atomically rename the staged copy into the destination.
6. Leave the portable source intact so migration never destroys the only known-good copy.
7. If inspection, copying, or activation fails, use the portable source for that run.

For development builds, or when no portable source exists, return `default_data_dir()` unchanged. Normal logging and service initialization will create the selected destination later.

## Error Handling

- A non-directory destination or an unreadable destination falls back to the existing portable source when available.
- A failed staged copy is cleaned up without modifying the portable source.
- An existing non-empty destination is authoritative and is never overwritten or merged.
- An empty destination may be removed only immediately before the staged directory is atomically activated.

## Tests

- A frozen build on a simulated Desktop returns the user-data path and does not create `Desktop/data`.
- Existing portable data is copied to an empty user-data destination and remains present at the source.
- Existing non-empty user data wins over portable data without being overwritten.
- A migration copy failure falls back to the portable source.
- Explicit command-line data-directory overrides continue to win.
- The full backend, frontend, lint, compile, build, and diff checks remain green.

## Release Impact

The already published 0.6.5 tag and GitHub asset still contain the old behavior and must not be force-moved. This fix should be released as a subsequent patch version rather than silently replacing 0.6.5.
