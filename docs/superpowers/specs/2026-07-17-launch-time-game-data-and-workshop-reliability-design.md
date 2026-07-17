# Launch-Time Game Data and Workshop Reliability Design

## Status and scope

This design supersedes the explicit game-data generation flow in
`2026-07-16-game-data-patch-generation-design.md`. It covers three related reliability
changes:

1. Validate and, when needed, rebuild the game-data patch inside the manager's launch
   path.
2. Resolve Workshop author names through Steam Friends first, with a controlled HTTP
   fallback and observable results.
3. Split the Workshop context-menu destination into browser and Steam-client actions.

The implementation changes source, tests, and documentation only. It does not run the
release packaging workflow or write to the installed release directory.

## Game-data patch lifecycle

### User interaction

- Remove the explicit **Generate patch** button and its `generate` event.
- Remove the public `generate_game_data_patch` RPC; patch construction becomes an
  internal launch responsibility.
- Saving the Game Data Modification dialog only persists the three supported settings:
  `unit_model_multiplier`, `disable_unit_friendly_fire`, and
  `disable_spell_friendly_fire`.
- Replace the manual-regeneration reminder with five-language text explaining that the
  manager validates and generates the patch when it launches the game.
- Launch, Continue, and save-game launch all use the same backend launch path and
  therefore the same patch validation.
- Unrelated settings such as theme or interface language do not invalidate the patch.

### Manifest and fingerprint

Store `!!!!wyccc_game_data_patch.json` beside
`!!!!wyccc_game_data_patch.pack` in the runtime directory. The manifest schema is
versioned and contains both the canonical inputs and their SHA-256 digest so the launch
path can report why an input changed.

The canonical fingerprint inputs are:

- fingerprint schema version and game-data builder version;
- current playset ID;
- the complete, canonical enabled MOD ID order;
- the three normalized game-data settings;
- the last verified subscription state of both feature Workshop items;
- for every enabled source Pack, in load order: canonical MOD ID, pack name, resolved
  path, file size, and `st_mtime_ns`;
- for vanilla `db.pack`: resolved path, file size, and `st_mtime_ns`.

`db.pack` does not expose a useful standalone content version in the existing parser, so
its resolved path, size, and nanosecond modification time form its version signature.
Source Pack content is likewise represented by size and nanosecond modification time to
avoid hashing every enabled Pack on every launch.

For a generated patch, the manifest also records generation time, enabled options,
entry count, modification statistics, patch size, and patch SHA-256. A matching input
fingerprint is reusable only when the recorded output status expects a Pack, the Pack
exists, and its size and SHA-256 still match. For a recorded zero-modification result,
an absent Pack is the expected valid state.

### Launch flow

The existing non-blocking game-data lock continues to cover the complete launch
operation. After the manager saves and canonicalizes the requested load order, but
before it creates `wyccc_launch_mods.txt`, it performs these steps:

1. Resolve live feature subscription status.
2. Build the canonical fingerprint from the saved playset/order, current settings,
   current file metadata, and subscription status.
3. Load the previous manifest and classify changed input groups: schema, settings,
   playset, order, source Packs, subscription state, or `db.pack`.
4. Reuse a valid matching patch, or rebuild when the manifest is missing, any input
   differs, or the output Pack is missing or altered.
5. Append the patch after user MODs only when the result contains an effective Pack.
6. Launch the game only after validation or generation completes successfully.

Any enabled MOD, its order, its Pack path/size/time, the current playset, a game-data
setting, feature subscription state, or `db.pack` metadata changing invalidates the
fingerprint and rebuilds the patch.

When all effective options are disabled, or enabled options change zero rows, remove the
old Pack and persist a zero-modification manifest. A failure before atomic Pack
replacement preserves the previous Pack. A failure after Pack replacement but before
manifest replacement leaves a deliberately non-matching output/manifest pair that cannot
be reused. In either case the current launch is aborted so a stale or uncommitted snapshot
cannot enter the game, and the next launch attempts generation again.

### Subscription-state failure

- A successful Steam query replaces the in-memory state and is written into the
  manifest used for this launch.
- If the live query fails, reuse a previously successful in-memory state, otherwise the
  last manifest subscription snapshot, and log that the source was cached.
- If no trustworthy subscription snapshot exists and all requested game-data options
  are disabled, record zero modification and continue launching.
- If no trustworthy subscription snapshot exists while any game-data option is
  requested, log the subscription error and abort launch. Do not delete a previous
  valid patch or silently launch without the requested behavior.

### Logging and result classification

Use the existing application logger and structured key/value messages. Every launch
records exactly one terminal patch status:

- `generated`: a new effective patch was written; include fingerprint prefix, invalidated
  groups, entries, and all changed-row counters.
- `reused`: the input fingerprint and output Pack validation matched.
- `zero_modification`: no effective settings or no changed rows; include the reason.
- `subscription_error`: no usable subscription state was available for requested
  features; include the bridge error and abort launch.
- `generation_failed`: fingerprinting, parsing, serialization, Pack replacement, or
  manifest persistence failed; include the exception and abort launch.

A live subscription failure that successfully falls back to cached state is logged as a
warning in addition to the final terminal status.

## Workshop author resolution

### Steam Friends primary resolver

Add a focused Python adapter around the flat C exports already present in the bundled
`steam_api64.dll`. It does not replace the locally patched steamworks.js binary.

The adapter:

- serializes access with a module lock;
- initializes Steam for app ID `1142710`, restoring temporary environment values after
  use;
- acquires `ISteamFriends` v017;
- calls `RequestUserInformation(steam_id, true)` for all pending unique Steam IDs;
- pumps `SteamAPI_RunCallbacks` at least 20 times per second and polls
  `GetFriendPersonaName` until all names resolve or the bounded deadline expires;
- accepts neither an empty string nor `[unknown]` as a resolved name;
- always shuts down its Steam API instance and returns resolved names plus unresolved
  IDs, or raises a classified Steam resolver error.

The Workshop metadata refresh remains a background operation, so the bounded resolver
wait does not block the main UI thread.

### HTTP fallback

Only IDs unresolved by Steam Friends enter the profile XML fallback:

- maximum concurrency: 2;
- per-request timeout: 5 seconds;
- maximum attempts: 3;
- exponential delays before retries: 0.5 seconds and 1.0 seconds;
- overall fallback deadline: 90 seconds;
- retry only timeouts, HTTP 429, HTTP 5xx, and temporary network errors.

Classify final errors as `steam_unavailable`, `steam_timeout`, `http_429`, `http_4xx`,
`http_5xx`, `network`, `timeout`, `xml_parse`, `missing_name`, `deadline`, or
`unexpected`. Permanent HTTP 4xx, invalid XML after a completed response, and missing
persona names are not retried.

### Cache semantics and author logs

- A successful name remains fresh for seven days.
- A failed refresh never overwrites a non-empty cached name or avatar.
- Record `last_error_at`, `last_error_code`, and `last_attempt_at` separately from the
  last successful `fetched_at`.
- Empty or stale failed entries may retry after 30 minutes instead of being hidden for
  six hours.
- New schema fields are backward-compatible with existing schema-6 cache records.

Every author refresh logs total unique authors, fresh-cache skips, pending count, Steam
successes, HTTP successes, retained stale names, final failures, and counts grouped by
error code. Use INFO when all pending authors resolve and WARNING when any resolver or
author remains failed.

## Workshop context-menu destinations

For MODs with a Workshop ID, place these adjacent top-level actions immediately before
the existing **Steam actions** submenu:

1. `跳转到创意工坊（浏览器）`
2. `跳转到创意工坊（客户端）`

Remove the former browser action from the Steam submenu. Unsubscribe, force update,
upload, and update remain inside that submenu.

The browser action keeps the existing HTTPS URL and RPC behavior. Add a separate client
RPC that opens `steam://url/CommunityFilePage/<WorkshopID>` through the operating-system
URI handler. Batch selection keeps the existing count suffix and invokes each action for
every selected MOD that has a Workshop ID. Add equivalent English, Korean, Russian, and
Japanese labels.

## Error handling and atomicity

- Patch Pack writes remain atomic.
- Manifest writes use an atomic JSON replacement and happen only after the output state
  is known.
- A manifest write failure is a generation failure and prevents launch.
- Browser/client actions reject MODs without a Workshop ID. Failure to dispatch the
  Steam URI returns the existing RPC error path.
- Steam Friends initialization or query failures never prevent Workshop metadata from
  using the HTTP fallback.
- HTTP fallback exhaustion never removes an existing author display name.

## Verification

Follow test-driven development and observe each new behavior fail before implementation.

Backend coverage will verify:

- every fingerprint input category invalidates the manifest;
- unchanged valid inputs reuse the patch without invoking the DB builder;
- a missing or altered output Pack rebuilds despite a matching input digest;
- zero settings and zero changed rows remove the Pack and persist a reusable zero result;
- launch generates before calling the game launcher and aborts on generation failure;
- live, cached, missing, and failed subscription-state paths produce the required logs;
- Steam Friends immediate, asynchronous, partial, timeout, and initialization failures;
- HTTP retry classification, two-worker limit, deadline, stale-name preservation, and
  aggregate author logging;
- browser and Steam-client Workshop RPCs use the correct destinations.

Frontend coverage will verify:

- the game-data dialog has only Cancel and Save and emits no generation event;
- saving settings calls only `save_game_data_settings`;
- all five languages describe launch-time automatic generation;
- the two Workshop destinations are adjacent top-level context-menu items in the required
  order and emit distinct actions;
- the old nested browser action is absent while other Steam submenu operations remain.

Final verification runs the complete backend suite, complete frontend suite, frontend
production build, `git diff --check`, and a clean-status review. No release package is
created.
