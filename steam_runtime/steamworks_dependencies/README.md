# Steamworks dependency-query runtime

This isolated native runtime provides `workshop.getItemDependencies()`, which
maps to Steamworks `ISteamUGC::GetQueryUGCChildren`. It is loaded only for
Workshop dependency refreshes; all other Workshop operations continue to use
the localized-update build in `../steamworks/`.

Source provenance:

- Repository: `https://github.com/Shazbot/WH3-Mod-Manager`
- Commit adding the custom Steamworks build: `83d046c7e4797577a6f5bc3979ee32fe8b547a43`
- Upstream: `ceifa/steamworks.js`
- License: MIT, recorded in `../../licenses/steamworks.js-LICENSE.txt`

The native module and its matching Steam redistributable must remain together
in `dist/win64`; loading either DLL from the localized-update runtime is not
ABI-compatible with this build.

SHA-256 values:

- `steamworksjs.win32-x64-msvc.node`:
  `FDD4C70A16A7AB8BC1F1167932506F1662815C823A68A52CC0AE2231F3FDE73E`
- `steam_api64.dll`:
  `E3FE06E2D802C2F753AEB46869E2AF898F34715CE85F08001456FD8A80ECD21E`
