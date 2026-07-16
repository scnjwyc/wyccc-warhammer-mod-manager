# Local Steamworks patch

The bundled native module is based on:

- `ceifa/steamworks.js` commit `80c5fd7c4958ba90cf87403c3f967b8a6d748473`
- `Noxime/steamworks-rs` commit `fbb79635b06b4feea8261e5ca3e8ea3ef42facf9`

The local patch adds only the missing localized-update path:

1. `steamworks-rs::UpdateHandle::update_language` calls
   `SteamAPI_ISteamUGC_SetItemUpdateLanguage`.
2. `steamworks.js::workshop::UgcUpdate` accepts `language` and applies it before
   title and description.
3. `workshop.supportsUpdateLanguage()` identifies a compatible bundled module,
   preventing silent fallback when an older binary is accidentally restored.

It was built for `x86_64-pc-windows-gnu` with Rust 1.97.0. The matching
`steam_api64.dll` is the redistributable shipped by the pinned `steamworks-sys`
source; the module and redistributable must be updated together.

Current SHA-256 values:

- `steamworksjs.win32-x64-msvc.node`:
  `778B6EF75B470B64CEFDCDF7814D722C71C416BA2EE168E1FAE62B24842D4F65`
- `steam_api64.dll`:
  `1ADD7F151FA644870A735AE86E68D1F019F296130D8E7C0A7ED3ECC7482DCCBC`

Although the historical filename contains `msvc`, Node loads the module through
the stable N-API ABI; the current binary is the GNU-target build documented
above.

The dependency-query build is intentionally isolated from this localized-update
build. Its provenance and hashes are documented in `../steamworks_dependencies/README.md`.
