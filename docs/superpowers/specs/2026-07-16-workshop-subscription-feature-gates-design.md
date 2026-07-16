# Workshop Subscription Feature Gates Design

## Approved behavior

- `Dynamic Unit Size` is available whenever Steam reports Workshop item `3765783838` as subscribed.
- `Dynamic No Friendly Fire` is available whenever Steam reports Workshop item `3765783977` as subscribed.
- Neither feature MOD needs to be enabled in a WMM playset.
- Both feature MODs are internal entitlement markers and never appear in WMM's active or inactive MOD lists.
- An unavailable control says that the named MOD is not subscribed. UI text uses the Workshop titles, never Pack filenames.

## Architecture

The backend owns a fixed registry containing each feature key, Workshop ID, title, and Pack filename. Steamworks subscription queries populate a small in-memory status cache exposed in bootstrap data and through a refresh RPC. Launch refreshes the same status and passes subscribed Workshop IDs to the runtime DB builder; Pack presence and playset activation are deliberately ignored.

The scanner filters registry Workshop IDs and Pack filenames before returning assets, so the feature MODs cannot enter either WMM list. Previously stored playset identifiers for these Workshop items are silently discarded instead of being reported as missing.

## Failure behavior

If Steam subscription lookup fails, WMM retains the latest successful in-memory result. With no prior result it fails closed: controls remain unavailable and launch skips the corresponding DB edits while the game can still launch normally.

## Verification

- Backend tests prove active/local Pack files do not unlock either feature.
- Backend tests prove each Workshop subscription independently unlocks only its matching DB settings.
- Scanner/API tests prove both internal items are absent from scan results and stale playset entries are discarded.
- Frontend tests prove subscription status controls availability and prompts contain MOD titles without `.pack` filenames.
