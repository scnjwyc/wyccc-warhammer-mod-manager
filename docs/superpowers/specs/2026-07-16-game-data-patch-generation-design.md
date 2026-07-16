# Game Data Patch Generation Design

## Goal

Move game-data patch creation out of the game-launch path. Users can generate the patch from the Game Data Modification window, and saving changed settings automatically generates it when the same draft has not already been generated during the current window session.

## User interaction

- The Game Data Modification footer contains Cancel, Generate patch, and Save changes.
- Generate patch uses the current draft, saves those settings, creates the persistent patch when an effective option is enabled, removes it when all effective options are disabled, keeps the window open, and reports success.
- Save changes compares the draft with persisted settings. If values changed and the current draft was not successfully generated in this window session, Save runs the same save-and-generate operation before closing.
- If the current draft was already generated, Save does not generate it a second time.
- When all effective options are disabled, generation removes the old patch so disabled behavior cannot remain active.
- All controls are disabled while generation is running. The main Launch, Continue, and save-launch controls remain disabled through the shared busy state.

## Patch architecture

- `!!!!wyccc_game_data_patch.pack` is stored under the manager runtime directory and remains outside the game Data and Workshop folders.
- Explicit generation resolves the current playset against vanilla `db.pack` and the currently enabled MOD Packs, then writes the high-priority incremental DB entries to that dedicated Pack.
- `!!!!wyccc_runtime_options.pack` continues to contain only the other launch enhancements, such as custom-battle permissions, script logging, and intro overrides.
- Game launch never calls the game-data DB transformer. It only appends an already existing game-data patch to the internal launch order.
- The internal patch is not scanned into the MOD list.

## Backend flow

1. `generate_game_data_patch(changes, ordered_mod_ids)` validates the three supported settings and verifies that the game is not running.
2. It normalizes a candidate settings payload without persisting it, refreshes fixed Workshop subscription status, and builds the patch from the current scanned assets.
3. After a successful atomic Pack write or deletion, it persists the normalized settings and returns public settings plus patch statistics.
4. A shared non-blocking lock protects both generation and game launch. Launch attempted during generation returns a clear error; generation attempted during launch or gameplay is rejected.
5. Launch builds only ordinary runtime options and appends any existing persistent game-data patch to `wyccc_launch_mods.txt`.

## Frontend flow

- The store exposes `generateGameDataPatch(changes)` and a stable signature for the three settings.
- The App resets a per-open generated signature when the window opens and records it only after successful explicit generation.
- The store's save action automatically delegates to generation when values changed and the supplied generated signature does not match the current draft.
- The shared `busy` value uses a localized patch-generation label, which disables all launch controls for the full operation.

## Error handling

- Failed generation leaves the previously persisted settings unchanged.
- Atomic Pack writing preserves the previous valid patch if serialization or replacement fails.
- Missing game data, invalid paths, or missing required DB tables surface through the existing RPC error toast.
- A failed generation does not mark the draft as generated, so Save retries it.

## Verification

- Backend unit tests cover dedicated patch creation/removal, launch-time non-generation, inclusion of an existing patch, settings persistence only after success, and generation/launch mutual exclusion.
- Frontend tests cover the Generate button payload, changed-setting auto-generation, no duplicate generation, and launch rejection while generation owns the busy state.
- Five-language UI copy and the concise 0.6.0 changelog describe manual and automatic patch generation without implementation details.
