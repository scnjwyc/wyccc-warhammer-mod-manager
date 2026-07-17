# Launch-Time Game Data and Workshop Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically validate and regenerate the game-data patch at launch, make author-name resolution resilient and observable, and expose separate browser/client Workshop destinations in the top-level MOD context menu.

**Architecture:** A new `game_data_patch_state` module owns canonical inputs, sidecar manifests, output validation, and rebuild decisions; `API._launch_game_when_patch_idle` resolves subscription state and invokes it before constructing the launch plan. A new ctypes-based `steam_friends` adapter resolves persona names through the bundled Steam API, while `WorkshopMetadataService` retains a bounded HTTP fallback. Frontend changes remove manual patch generation and split the Workshop menu destination without changing unrelated Steam operations.

**Tech Stack:** Python 3, ctypes/Steamworks flat C API, SHA-256 and atomic JSON, unittest/mock, Vue 3, Pinia, Vitest.

## Global Constraints

- Modify only source, tests, and documentation under `G:\git\wyccc-warhammer-mod-manager`.
- Do not package, publish, tag, write the installed release directory, or create Git commits; repository rules reserve those operations for an explicitly authorized release.
- Keep all five built-in language variants synchronized for every changed user-visible string.
- Preserve existing Pack import/override assumptions and focus only on DB, script, launch, and application behavior.
- Follow TDD: each production behavior is implemented only after its focused test fails for the expected reason.

---

### Task 1: Canonical game-data inputs and manifest decisions

**Files:**
- Create: `backend/game_data_patch_state.py`
- Create: `tests/test_game_data_patch_state.py`
- Consume: `backend/start_options.py`
- Consume: `backend/json_store.py`

**Interfaces:**
- Produces `GAME_DATA_PATCH_MANIFEST_NAME: str`.
- Produces `game_data_settings_requested(settings: Mapping[str, Any]) -> bool`.
- Produces `load_manifest_subscription_state(output_dir: Path) -> dict[str, bool] | None`.
- Produces `ensure_game_data_patch(output_dir, data_path, assets, active_ids, playset_id, settings, subscription_state) -> dict[str, Any]` with `status`, `path`, `fingerprint`, `changed_inputs`, `entry_count`, `options`, and `game_data`.
- Consumes existing `build_game_data_patch` and `GAME_DATA_PATCH_NAME`.

- [x] **Step 1: Write failing canonical-input tests**

```python
class GameDataPatchStateTests(unittest.TestCase):
    def test_fingerprint_changes_for_every_required_input_group(self):
        base = make_fixture_inputs()
        digest = fingerprint_game_data_inputs(base)
        for changed in variants_for_settings_playset_order_source_subscription_and_db(base):
            self.assertNotEqual(fingerprint_game_data_inputs(changed), digest)

    def test_matching_manifest_and_output_reuses_without_building(self):
        first = ensure_game_data_patch(**self.base_kwargs)
        with patch("backend.game_data_patch_state.build_game_data_patch") as builder:
            second = ensure_game_data_patch(**self.base_kwargs)
        self.assertEqual(second["status"], "reused")
        builder.assert_not_called()

    def test_missing_or_modified_output_rebuilds_matching_inputs(self):
        first = ensure_game_data_patch(**self.base_kwargs)
        Path(first["path"]).write_bytes(b"changed")
        with patch("backend.game_data_patch_state.build_game_data_patch", return_value=built_result) as builder:
            result = ensure_game_data_patch(**self.base_kwargs)
        self.assertEqual(result["status"], "generated")
        builder.assert_called_once()
```

- [x] **Step 2: Run the new tests and verify RED**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_game_data_patch_state -v`

Expected: import failure for `backend.game_data_patch_state`.

- [x] **Step 3: Implement canonical input and manifest helpers**

```python
GAME_DATA_PATCH_MANIFEST_NAME = "!!!!wyccc_game_data_patch.json"
FINGERPRINT_SCHEMA_VERSION = 1
GAME_DATA_BUILDER_VERSION = 1

def _file_signature(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=False)
    if not resolved.is_file():
        return {"path": str(resolved), "missing": True}
    stat = resolved.stat()
    return {"path": str(resolved), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

def fingerprint_game_data_inputs(inputs: Mapping[str, Any]) -> str:
    encoded = json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def game_data_settings_requested(settings: Mapping[str, Any]) -> bool:
    return (
        not math.isclose(float(settings.get("unit_model_multiplier", 1.0)), 1.0)
        or bool(settings.get("disable_unit_friendly_fire"))
        or bool(settings.get("disable_spell_friendly_fire"))
    )
```

Build inputs with playset ID, ordered IDs, normalized settings, sorted subscription-state keys, an ordered source signature for every active ID, and the `db.pack` signature. Store and load the versioned manifest through `AtomicJsonStore`.

- [x] **Step 4: Implement output validation and ensure behavior**

```python
def ensure_game_data_patch(
    output_dir: Path,
    data_path: Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
    subscription_state: Mapping[str, bool],
) -> dict[str, Any]:
    inputs = build_game_data_inputs(
        data_path,
        assets,
        active_ids,
        playset_id,
        settings,
        subscription_state,
    )
    fingerprint = fingerprint_game_data_inputs(inputs)
    previous = _manifest_store(output_dir).load()
    changed_inputs = classify_input_changes(previous.get("inputs", {}), inputs)
    if previous.get("fingerprint") == fingerprint and _manifest_output_is_valid(previous, output_dir):
        return _result_from_manifest(previous, "reused")
    built = build_game_data_patch(
        output_dir, data_path, assets, active_ids, settings,
        subscribed_workshop_ids=[key for key, value in subscription_state.items() if value],
    )
    changed_rows = sum(
        int(value) for key, value in built.get("game_data", {}).items()
        if key.endswith("_scaled") or key.endswith("_rows_changed")
    )
    if not built.get("path") or changed_rows == 0:
        (Path(output_dir) / GAME_DATA_PATCH_NAME).unlink(missing_ok=True)
        output = {"status": "zero_modification", "reason": "no_effective_options" if not built.get("path") else "zero_changed_rows"}
    else:
        output = _generated_output_record(Path(built["path"]), built)
    manifest = {"schema_version": 1, "fingerprint": fingerprint, "inputs": inputs, "output": output, "generated_at": int(time.time() * 1000)}
    _manifest_store(output_dir).save(manifest)
    return _result_from_manifest(manifest, output["status"])
```

- [x] **Step 5: Run Task 1 tests and inspect the diff**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_game_data_patch_state tests.test_start_options -v`

Expected: all tests pass. Then run `git diff --check` and review only Task 1 files; do not commit.

### Task 2: Launch-time generation, subscription fallback, and logs

**Files:**
- Modify: `backend/api.py:83-130,289-342,403-457,721-810`
- Modify: `tests/test_storage_and_api.py:289-505`
- Test: `tests/test_game_data_patch_state.py`

**Interfaces:**
- Consumes `ensure_game_data_patch`, `game_data_settings_requested`, and `load_manifest_subscription_state`.
- Produces launch response field `game_data_patch`.
- Extends feature-status payload with `known: bool` and `source: "live" | "memory" | "unavailable"`.
- Removes public RPC `generate_game_data_patch`.

- [x] **Step 1: Replace explicit-generation tests with failing launch tests**

```python
def test_launch_generates_before_starting_game(self):
    patch_result = {
        "status": "generated",
        "path": str(patch_path),
        "fingerprint": "a" * 64,
        "changed_inputs": ["initial"],
        "entry_count": 1,
        "options": {},
        "game_data": {"unit_rows_changed": 1, "projectile_rows_changed": 0, "spell_rows_changed": 0},
    }
    with patch("backend.api.ensure_game_data_patch", return_value=patch_result) as ensure, \
         patch("backend.api.launch_game", return_value={"pid": 123}) as launch:
        result = api.call("launch_game", [active_ids, token])
    self.assertTrue(result["ok"])
    ensure.assert_called_once()
    launch.assert_called_once()
    self.assertEqual(result["data"]["game_data_patch"]["status"], "generated")

def test_launch_aborts_and_logs_generation_failure(self):
    with self.assertLogs("backend.api", level="ERROR") as logs, \
         patch("backend.api.ensure_game_data_patch", side_effect=ValueError("bad db")), \
         patch("backend.api.launch_game") as launch:
        result = api.call("launch_game", [[], token])
    self.assertFalse(result["ok"])
    self.assertIn("status=generation_failed", "\n".join(logs.output))
    launch.assert_not_called()

def test_unknown_subscription_with_requested_settings_aborts_and_logs(self):
    api._game_data_subscription_cache_known = False
    api.settings_service.update({"disable_unit_friendly_fire": True})
    with self.assertLogs("backend.api", level="ERROR") as logs, \
         patch.object(api, "_get_game_data_feature_status", return_value={
             "items": {}, "warning": "Steam unavailable", "known": False, "source": "unavailable"
         }), \
         patch("backend.api.load_manifest_subscription_state", return_value=None), \
         patch("backend.api.launch_game") as launch:
        result = api.call("launch_game", [[], token])
    self.assertFalse(result["ok"])
    self.assertIn("status=subscription_error", "\n".join(logs.output))
    launch.assert_not_called()
```

- [x] **Step 2: Run focused API tests and verify RED**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_storage_and_api.StorageAndApiTests.test_launch_generates_before_starting_game tests.test_storage_and_api.StorageAndApiTests.test_launch_aborts_and_logs_generation_failure -v`

Expected: missing launch-time `ensure_game_data_patch` calls and result field.

- [x] **Step 3: Add known/source subscription semantics**

```python
def _get_game_data_feature_status(self):
    cache_was_populated = self._game_data_subscription_cache_known
    live_success = False
    warning = None
    items = dict(self._game_data_subscription_cache)
    # Refresh through Steamworks; on success update items, mark cache known,
    # and set live_success. On failure retain the independent known flag.
    return {
        "items": items,
        "warning": warning,
        "known": bool(cache_was_populated),
        "source": "live" if live_success else ("memory" if cache_was_populated else "unavailable"),
    }
```

Track cache validity independently from false subscription values. On live failure, load manifest subscription state only when memory is not known. If requested settings have no trustworthy state, log `status=subscription_error` and raise `ValueError` before the launcher is called.

- [x] **Step 4: Integrate ensure and terminal logging into launch**

```python
patch_result = ensure_game_data_patch(
    self.data_dir / "runtime",
    paths.data_path,
    self._assets,
    saved["plan"]["ordered_mod_ids"],
    self.state_repository.get_current_playset_id(),
    self.settings_service.get(),
    subscription_state,
)
logger.info(
    "Game data patch status=%s fingerprint=%s changed_inputs=%s entries=%s game_data=%s",
    patch_result["status"], patch_result["fingerprint"][:12],
    ",".join(patch_result.get("changed_inputs", [])),
    patch_result.get("entry_count", 0), patch_result.get("game_data", {}),
)
```

Wrap only subscription resolution with `status=subscription_error`; wrap fingerprint/build/manifest work with `logger.exception("Game data patch status=generation_failed")`. Append the runtime patch only from `patch_result["path"]`. Remove `_generate_game_data_patch` and its RPC registration.

- [x] **Step 5: Run backend launch regressions and inspect the diff**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_storage_and_api tests.test_game_data_patch_state tests.test_start_options -v`

Expected: all pass; no explicit-generation API tests remain. Run `git diff --check`; do not commit.

### Task 3: Remove manual generation from the frontend

**Files:**
- Modify: `frontend/src/store.js:34-43,832-852`
- Modify: `frontend/src/App.vue:1-105,742-752`
- Modify: `frontend/src/components/GameDataModificationModal.vue:15-70,136-159`
- Modify: `frontend/src/languages.js:428-459,510-511`
- Modify: `frontend/src/__tests__/gameDataSettings.test.js`
- Modify: `frontend/src/__tests__/languages.test.js`
- Modify: `frontend/src/__tests__/scope.test.js`
- Modify: `frontend/src/components/__tests__/GameDataModificationModal.test.js`

**Interfaces:**
- `saveGameDataSettings(changes)` always invokes `save_game_data_settings`.
- `GameDataModificationModal` emits only `close` and `save`.
- The modal has exactly Cancel and Save buttons and five-language launch-time copy.

- [x] **Step 1: Write failing frontend expectations**

```javascript
it('saves settings without generating a patch', async () => {
  invokeMock.mockResolvedValue({ settings: changes })
  await store.saveGameDataSettings(changes)
  expect(invokeMock).toHaveBeenCalledWith('save_game_data_settings', changes)
  expect(invokeMock.mock.calls.some(([method]) => method === 'generate_game_data_patch')).toBe(false)
})

it('has no manual patch generation control', () => {
  const wrapper = mount(GameDataModificationModal, { props: { open: true } })
  expect(wrapper.find('[data-testid="generate-game-data-patch"]').exists()).toBe(false)
  expect(wrapper.findAll('.game-data-footer-actions button')).toHaveLength(2)
  expect(wrapper.text()).toContain('启动游戏时')
})
```

- [x] **Step 2: Run focused Vitest and verify RED**

Run: `pnpm --dir frontend test -- src/__tests__/gameDataSettings.test.js src/components/__tests__/GameDataModificationModal.test.js`

Expected: old generate RPC/button assertions fail.

- [x] **Step 3: Remove generation state and button**

```javascript
async saveGameDataSettings(changes) {
  return this.withBusy(t('busy.saveGameData'), async () => {
    const data = await invoke('save_game_data_settings', changes)
    this.settings = data.settings
    this.notify(t('toast.gameDataSaved'))
    return data
  })
}
```

Remove `gameDataSettingsSignature`, `generateGameDataPatch`, App session signature state, `@generate`, the modal `generate` emit/function/button, and obsolete generation-specific localization keys.

- [x] **Step 4: Add five-language automatic-generation copy**

```javascript
'gameData.autoGenerateOnLaunch': [
  '通过本管理器启动游戏时会自动校验补丁；游戏数据设置、配置组或顺序、启用 MOD、源 Pack 或 db.pack 变化时会自动重新生成。',
  'The patch is validated when the game is launched through this manager and is regenerated when game-data settings, the playset or order, enabled MODs, source Packs, or db.pack change.',
  '이 관리자로 게임을 실행할 때 패치를 자동으로 검증하며 게임 데이터 설정, 플레이 세트나 순서, 활성 MOD, 원본 Pack 또는 db.pack이 변경되면 다시 생성합니다.',
  'При запуске игры через этот менеджер патч проверяется автоматически и пересоздаётся при изменении настроек игровых данных, набора или порядка, включённых MOD, исходных Pack или db.pack.',
  'このマネージャーからゲームを起動するとパッチを自動検証し、ゲームデータ設定、プレイセットや順序、有効な MOD、元 Pack、db.pack の変更時に再生成します。',
]
```

- [x] **Step 5: Run frontend tests and inspect the diff**

Run: `pnpm --dir frontend test -- src/__tests__/gameDataSettings.test.js src/__tests__/languages.test.js src/__tests__/scope.test.js src/components/__tests__/GameDataModificationModal.test.js`

Expected: all pass. Run `git diff --check`; do not commit.

### Task 4: Steam Friends flat-API adapter

**Files:**
- Create: `backend/steam_friends.py`
- Create: `tests/test_steam_friends.py`
- Consume: `backend/steamworks_bridge.py:21-91`
- Consume: `steam_runtime/steamworks/dist/win64/steam_api64.dll`

**Interfaces:**
- Produces `SteamFriendsError(code: str, message: str)`.
- Produces immutable `SteamPersonaResult(names: dict[str, str], unresolved: tuple)` where every tuple value is a Steam ID string.
- Produces `query_steam_persona_names(steam_ids, app_id=1_142_710, root=None, timeout_seconds=5.0, poll_interval=0.05) -> SteamPersonaResult`.

- [x] **Step 1: Write failing adapter tests with a fake DLL**

```python
def test_requests_pending_users_and_pumps_callbacks_until_names_arrive(self):
    dll = FakeSteamDll(names_after_callbacks={"765": (2, "Author")})
    with patch("backend.steam_friends._load_library", return_value=dll), \
         patch("backend.steam_friends.os.name", "nt"), \
         patch("backend.steam_friends.time.sleep"):
        result = query_steam_persona_names(["765"], timeout_seconds=1)
    self.assertEqual(result.names, {"765": "Author"})
    self.assertEqual(dll.requested, [(765, True)])

def test_init_failure_has_classified_error(self):
    with self.assertRaisesRegex(SteamFriendsError, "Steam API initialization failed") as raised:
        query_steam_persona_names(["765"])
    self.assertEqual(raised.exception.code, "steam_unavailable")
```

- [x] **Step 2: Run adapter tests and verify RED**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_steam_friends -v`

Expected: import failure for `backend.steam_friends`.

- [x] **Step 3: Implement the ctypes signatures and lifecycle**

```python
@dataclass(frozen=True)
class SteamPersonaResult:
    names: dict[str, str]
    unresolved: tuple

class SteamFriendsError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

def query_steam_persona_names(
    steam_ids: Iterable[str],
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: float = 5.0,
    poll_interval: float = 0.05,
) -> SteamPersonaResult:
    ids = tuple(dict.fromkeys(str(value) for value in steam_ids if str(value).isdigit()))
    if not ids:
        return SteamPersonaResult({}, ())
    with _STEAM_FRIENDS_LOCK, _temporary_app_environment(app_id):
        dll = _load_library(root)
        _configure_signatures(dll)
        if not dll.SteamAPI_InitSafe():
            raise SteamFriendsError("steam_unavailable", "Steam API initialization failed")
        try:
            friends = dll.SteamAPI_SteamFriends_v017()
            for steam_id in ids:
                dll.SteamAPI_ISteamFriends_RequestUserInformation(friends, int(steam_id), True)
            return _poll_persona_names(dll, friends, ids, timeout_seconds, poll_interval)
        finally:
            dll.SteamAPI_Shutdown()
```

Reject `""` and `"[unknown]"`, pump callbacks at every poll, restore `SteamAppId` and `SteamGameId`, and classify missing DLL/interface/call failures as `steam_unavailable` or `unexpected`.

- [x] **Step 4: Run adapter tests and live-safe export verification**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_steam_friends -v`

Run: `.\.venv-build\Scripts\python.exe -c "from backend.steam_friends import query_steam_persona_names; print(query_steam_persona_names([]))"`

Expected: tests pass and the empty query returns without initializing Steam. Review diff; do not commit.

### Task 5: Author fallback, cache preservation, classification, and logs

**Files:**
- Modify: `backend/workshop.py:1-49,488-549`
- Modify: `tests/test_workshop.py:33-78`
- Consume: `backend/steam_friends.py`

**Interfaces:**
- Steam Friends is the primary batch resolver.
- HTTP fallback uses 2 workers, 5-second requests, 3 attempts, 0.5/1.0-second backoff, and a 90-second deadline.
- Cached author records gain `last_attempt_at`, `last_error_at`, and `last_error_code` without losing successful values.

- [x] **Step 1: Write failing author-resolution tests**

```python
def test_steam_friends_success_avoids_http(self):
    with patch("backend.workshop.query_steam_persona_names", return_value=SteamPersonaResult({steam_id: "Author"}, ())), \
         patch("backend.workshop.urllib.request.urlopen") as http:
        service.refresh(["123"])
    http.assert_called_once()  # published-file details only; no profile XML request

def test_failed_refresh_preserves_cached_name_and_logs_counts(self):
    cache_path.write_text(existing_named_author_json, encoding="utf-8")
    with self.assertLogs("backend.workshop", level="WARNING") as logs, \
         patch("backend.workshop.query_steam_persona_names", side_effect=SteamFriendsError("steam_unavailable", "offline")), \
         patch.object(WorkshopMetadataService, "_fetch_author_profile", side_effect=AuthorProfileError("timeout", "timeout")):
        service._refresh_author_profiles(authors, [steam_id])
    self.assertEqual(authors[steam_id]["name"], "Cached Author")
    self.assertEqual(authors[steam_id]["last_error_code"], "timeout")
    self.assertIn("failed=1", "\n".join(logs.output))

def test_transient_http_error_retries_but_permanent_404_does_not(self):
    transient = urllib.error.URLError(socket.timeout("timed out"))
    success = io.BytesIO(b"<profile><steamID>Author</steamID></profile>")
    with patch("backend.workshop.urllib.request.urlopen", side_effect=[transient, success]) as request, \
         patch("backend.workshop.time.sleep") as sleep:
        self.assertEqual(_fetch_author_profile("765")["name"], "Author")
    self.assertEqual(request.call_count, 2)
    sleep.assert_called_once_with(0.5)

    permanent = urllib.error.HTTPError("https://example", 404, "missing", {}, None)
    with patch("backend.workshop.urllib.request.urlopen", side_effect=permanent) as request:
        with self.assertRaises(AuthorProfileError) as raised:
            _fetch_author_profile("765")
    self.assertEqual(raised.exception.code, "http_404")
    request.assert_called_once()
```

- [x] **Step 2: Run Workshop tests and verify RED**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_workshop.WorkshopMetadataTests.test_steam_friends_success_avoids_http tests.test_workshop.WorkshopMetadataTests.test_failed_refresh_preserves_cached_name_and_logs_counts -v`

Expected: Steam Friends is not called and cache fields/logs are absent.

- [x] **Step 3: Implement classified HTTP retries**

```python
class AuthorProfileError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable

def _fetch_author_profile(steam_id: str, deadline: float | None = None):
    for attempt in range(AUTHOR_HTTP_MAX_ATTEMPTS):
        try:
            return _fetch_author_profile_once(steam_id)
        except AuthorProfileError as exc:
            if not exc.retryable or attempt + 1 >= AUTHOR_HTTP_MAX_ATTEMPTS:
                raise
            if deadline is not None and time.monotonic() >= deadline:
                raise AuthorProfileError("deadline", f"Author refresh deadline reached: {steam_id}")
            time.sleep(AUTHOR_HTTP_BACKOFF_SECONDS[attempt])
```

Map `HTTPError`, `URLError`, socket timeout, `ET.ParseError`, and missing names to the exact codes in the specification. Clamp sleeps to the remaining deadline.

- [x] **Step 4: Implement Steam-first merge, cache preservation, and aggregate logging**

```python
steam_result = query_steam_persona_names(pending)
for steam_id, name in steam_result.names.items():
    cached = authors.get(steam_id, {})
    authors[steam_id] = _successful_author_record(steam_id, name, cached.get("avatar", ""), now)
unresolved = list(steam_result.unresolved)
with ThreadPoolExecutor(max_workers=min(AUTHOR_HTTP_MAX_WORKERS, len(unresolved))) as executor:
    futures = {
        executor.submit(_fetch_author_profile, steam_id, deadline): steam_id
        for steam_id in unresolved
    }
    for future in as_completed(futures):
        steam_id = futures[future]
        try:
            profile = future.result()
        except AuthorProfileError as exc:
            failures[steam_id] = exc
        else:
            authors[steam_id] = _successful_author_record(
                steam_id, profile["name"], profile.get("avatar", ""), now
            )
```

When both paths fail, copy the cached record, retain non-empty `name` and `avatar`, and set only failure metadata. Treat old schema-6 empty records' `fetched_at` as their last error time for the 30-minute retry cooldown. Log `total`, `cached`, `pending`, `steam_success`, `http_success`, `retained`, `failed`, and sorted error counts.

- [x] **Step 5: Run Workshop regressions and inspect the diff**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_steam_friends tests.test_workshop -v`

Expected: all pass. Run `git diff --check`; do not commit.

### Task 6: Browser and Steam-client Workshop context actions

**Files:**
- Modify: `backend/api.py:125-180,1216-1231,1694-1704`
- Modify: `tests/test_storage_and_api.py`
- Modify: `frontend/src/store.js:1214-1222`
- Modify: `frontend/src/App.vue:296-300`
- Modify: `frontend/src/components/ModContextMenu.vue:124-159`
- Modify: `frontend/src/components/__tests__/ModContextMenu.test.js`
- Modify: `frontend/src/languages.js:188-190`

**Interfaces:**
- Existing `open_workshop_page(mod_id)` remains the browser action.
- New `open_workshop_client(mod_id)` dispatches `steam://url/CommunityFilePage/<id>`.
- Frontend actions are `open-workshop-browser` and `open-workshop-client`.

- [x] **Step 1: Write failing backend and component tests**

```python
def test_open_workshop_client_uses_official_steam_uri(self):
    with patch.object(api, "_open_uri") as opener:
        result = api.call("open_workshop_client", [mod_id])
    self.assertTrue(result["ok"])
    opener.assert_called_once_with("steam://url/CommunityFilePage/123")
```

```javascript
it('shows adjacent top-level browser and client Workshop actions', async () => {
  const wrapper = mount(ModContextMenu, { props: { open: true, mod, types } })
  const topLevel = wrapper.find('nav').element.children
  const browser = buttonByText(wrapper, '跳转到创意工坊（浏览器）')
  const client = buttonByText(wrapper, '跳转到创意工坊（客户端）')
  expect(browser.element.parentElement).toBe(wrapper.get('nav').element)
  expect(client.element.previousElementSibling).toBe(browser.element)
  await client.trigger('click')
  expect(wrapper.emitted('action')[0][0].action).toBe('open-workshop-client')
})
```

- [x] **Step 2: Run focused menu tests and verify RED**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_storage_and_api -v`

Run: `pnpm --dir frontend test -- src/components/__tests__/ModContextMenu.test.js`

Expected: missing RPC, labels, and action.

- [x] **Step 3: Add backend Steam URI dispatch**

```python
def _open_workshop_client(self, mod_id: str) -> dict[str, bool]:
    asset = self._require_asset(mod_id)
    if not asset.workshop_id:
        raise ValueError("该 MOD 不是 Workshop 项目")
    self._open_uri(f"steam://url/CommunityFilePage/{asset.workshop_id}")
    return {"opened": True}

@staticmethod
def _open_uri(uri: str) -> None:
    if urlparse(uri).scheme != "steam":
        raise ValueError("只允许打开有效的 Steam 链接")
    if os.name == "nt":
        os.startfile(uri)
    elif os.name == "posix":
        subprocess.Popen(["open" if os.uname().sysname == "Darwin" else "xdg-open", uri])
    else:
        raise ValueError("当前系统不支持打开 Steam 链接")
```

Register the RPC without changing the HTTPS browser RPC.

- [x] **Step 4: Move and rename frontend actions in all five languages**

```vue
<button v-if="hasWorkshop" type="button" class="context-menu-item" @click="run('open-workshop-browser')">
  <span class="context-menu-icon">↗</span><span>{{ batchLabel(t('context.openWorkshopBrowser')) }}</span>
</button>
<button v-if="hasWorkshop" type="button" class="context-menu-item" @click="run('open-workshop-client')">
  <span class="context-menu-icon steam-icon">S</span><span>{{ batchLabel(t('context.openWorkshopClient')) }}</span>
</button>
```

Place both buttons immediately before `context-steam-menu`, remove the nested old browser button, add five-language labels, add `store.openWorkshopClient`, and route browser/client action IDs separately in `App.vue` while retaining batch filtering.

- [x] **Step 5: Run menu and API regressions and inspect the diff**

Run: `.\.venv-build\Scripts\python.exe -m unittest tests.test_storage_and_api -v`

Run: `pnpm --dir frontend test -- src/components/__tests__/ModContextMenu.test.js`

Expected: all pass. Run `git diff --check`; do not commit.

### Task 7: Documentation consistency and complete verification

**Files:**
- Modify only if current UI/behavior documentation still instructs manual generation: `README.md`, `README.en.md`, and relevant current docs.
- Verify all files changed by Tasks 1-6.

**Interfaces:**
- No new runtime interface; this task proves the approved specification is fully covered.

- [x] **Step 1: Search for stale active documentation and UI strings**

Run: `rg -n "Generate patch|生成补丁|重新生成补丁|generate_game_data_patch|context.visitWorkshop|访问创意工坊" README.md README.en.md backend frontend/src tests docs`

Expected: only historical 0.6.0 changelog/design references may remain; active UI, tests, and current README text use launch-time generation and the two new destinations.

- [x] **Step 2: Run the complete backend suite**

Run: `.\.venv-build\Scripts\python.exe -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [x] **Step 3: Run the complete frontend suite**

Run: `pnpm --dir frontend test`

Expected: all test files and tests pass.

- [x] **Step 4: Build the frontend production bundle**

Run: `pnpm --dir frontend build`

Expected: Vite exits 0 and writes only the repository build output.

- [x] **Step 5: Run static and repository checks**

Run: `.\.venv-build\Scripts\python.exe -m compileall -q backend main.py`

Run: `git diff --check`

Run: `git status --short`

Expected: compilation and diff checks exit 0; status lists only the approved source, test, and documentation changes. Do not package, commit, tag, or publish.
