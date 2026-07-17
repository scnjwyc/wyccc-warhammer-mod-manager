# Save MOD Extraction Compatibility Design

## Goal

Make “Enable MODs used in save” read MOD Pack names from current WARHAMMER III
saves again, while retaining compatibility with the older NUL-delimited layout.

## Evidence and Root Cause

The current parser only searches for `b".pack\\0"`. A real local WH3 save
contains `*.pack` strings, but they are serialized as a little-endian uint32
length followed by the UTF-8 name. The byte after the Pack name is the next
record field, not a NUL terminator. Consequently, every current save produces
an empty `pack_names` list before the frontend can match it to installed MODs.

## Chosen Design

- Search for the case-insensitive `.pack` suffix without assuming its following
  byte.
- Reuse the existing bounded token extraction and accept a candidate only when
  one of these layouts is verified:
  - legacy: the Pack string is immediately NUL-terminated;
  - current: the four bytes immediately before the extracted token decode as a
    little-endian length exactly equal to the token byte count.
- Preserve existing filename validation, vanilla Pack exclusion, case-insensitive
  de-duplication, and source order.
- Keep the RPC and Vue enable/compare behavior unchanged: they already consume
  `pack_names` correctly once the backend returns real names.

## Rejected Alternatives

- Searching for every `.pack` suffix would fix the symptom but could treat an
  unrelated string in a save as a load-order MOD.
- Changing only the suffix to `.pack` without validating a record boundary would
  have the same false-positive risk.

## Validation

- Add a realistic length-prefixed fixture whose Pack strings are followed by a
  non-NUL field byte; it must fail against the old parser and pass after the
  change.
- Include an unframed `*.pack` string to prove the new parser does not accept
  arbitrary text.
- Keep the existing legacy NUL-delimited test green.
- Run the save-game test module, the relevant frontend save-selection test, and
  the full backend/frontend regressions after the implementation.
