from pathlib import Path
from unittest.mock import patch

import pytest

from backend.api import API
from backend.load_order import LoadOrderService
from backend.models import GamePaths
from backend.scanner import ModScanner
from backend.steamworks_bridge import SteamworksBridgeError
from tests.helpers import write_pack
from tests.test_scanner import OfflineWorkshopMetadata


def test_scanner_excludes_family_workshop_items_not_subscribed_by_current_user(tmp_path: Path) -> None:
    steam = tmp_path / "Steam"
    workshop = tmp_path / "SteamLibrary" / "steamapps" / "workshop" / "content" / "1142710"
    write_pack(workshop / "101" / "own.pack")
    write_pack(workshop / "102" / "family.pack")
    (steam / "config").mkdir(parents=True)
    (steam / "config" / "loginusers.vdf").write_text(
        '"users" { "76561197960265729" { "MostRecent" "1" "Timestamp" "1800000000" } }',
        encoding="utf-8",
    )
    subscriptions = steam / "userdata" / "1" / "ugc" / "1142710_subscriptions.vdf"
    subscriptions.parent.mkdir(parents=True)
    subscriptions.write_text(
        '"subscribedfiles" { "appid" "1142710" "0" '
        '{ "publishedfileid" "101" "time_subscribed" "1700000000" } }',
        encoding="utf-8",
    )
    metadata = OfflineWorkshopMetadata()
    with patch("backend.steam_paths.candidate_steam_roots", return_value=[]):
        result = ModScanner(metadata).scan(
            GamePaths(steam_root=str(steam), workshop_path=str(workshop)),
            {"check_outdated_mods": False},
        )

    assert [mod.workshop_id for mod in result.mods] == ["101"]
    assert metadata.requested_ids == ["101"]


@pytest.fixture
def steam_library(tmp_path: Path):
    steam = tmp_path / "Steam"
    workshop = tmp_path / "Library" / "steamapps" / "workshop" / "content" / "1142710"
    (steam / "config").mkdir(parents=True)
    (steam / "config" / "loginusers.vdf").write_text(
        '"users" { '
        '"76561197960265729" { "AutoLogin" "0" "MostRecent" "1" "Timestamp" "1" } '
        '"76561197960265730" { "AutoLogin" "1" "MostRecent" "0" "Timestamp" "2" } }',
        encoding="utf-8",
    )
    write_pack(workshop / "101" / "own.pack")
    write_pack(workshop / "102" / "family.pack", byte_mask=4)
    data = tmp_path / "game" / "data"
    write_pack(data / "local.pack")
    (data / "manifest.txt").write_text('', encoding="utf-8")
    paths = GamePaths(steam_root=str(steam), workshop_path=str(workshop),
                      game_path=str(data.parent), data_path=str(data))
    with patch("backend.steam_paths.candidate_steam_roots", return_value=[]):
        yield paths


def write_subscriptions(paths: GamePaths, account: str, ids: list[str], *, time: str = "1700000000"):
    target = Path(paths.steam_root) / "userdata" / account / "ugc" / f"{paths.game_definition.app_id}_subscriptions.vdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    entries = ' '.join(
        f'"{index}" {{ "publishedfileid" "{item}" "time_subscribed" "{time}" }}'
        for index, item in enumerate(ids)
    )
    target.write_text(f'"subscribedfiles" {{ "appid" "{paths.game_definition.app_id}" {entries} }}',
                      encoding="utf-8-sig")
    return target


def scan(paths: GamePaths):
    return ModScanner(OfflineWorkshopMetadata()).scan(paths, {"check_outdated_mods": False})


def test_empty_current_subscriptions_do_not_use_another_accounts_list(steam_library: GamePaths):
    write_subscriptions(steam_library, "1", [])
    write_subscriptions(steam_library, "2", ["102"])
    with patch("backend.scanner.get_subscribed_workshop_items") as native:
        result = scan(steam_library)
    assert [mod.pack_name for mod in result.mods] == ["local.pack"]
    native.assert_not_called()


def test_local_copy_of_unsubscribed_item_is_kept_without_workshop_alias(steam_library: GamePaths):
    write_subscriptions(steam_library, "1", ["101"])
    write_pack(Path(steam_library.data_path) / "family.pack", byte_mask=4)
    result = scan(steam_library)
    local_copy = next(mod for mod in result.mods if mod.pack_name == "family.pack")
    assert local_copy.sources == ["data"]
    assert local_copy.workshop_id == ""
    assert local_copy.alternate_paths == []
    assert {mod.workshop_id for mod in result.mods} == {"", "101"}


@pytest.mark.parametrize("time", ["0", "", "invalid"])
def test_subscription_membership_does_not_require_a_valid_timestamp(steam_library: GamePaths, time: str):
    write_subscriptions(steam_library, "1", ["101"], time=time)
    result = scan(steam_library)
    assert {mod.workshop_id for mod in result.mods} == {"", "101"}
    assert next(mod for mod in result.mods if mod.workshop_id).subscribed_at == 0


@pytest.mark.parametrize("content", [None, '"subscribedfiles" { "appid" "779340" }',
                                    '"subscribedfiles" { "appid" "1142710"',
                                    '"subscribedfiles" { "appid" "1142710" "0" {} }'])
def test_missing_or_invalid_current_file_uses_native_subscriptions_not_family(
    steam_library: GamePaths, content: str | None,
):
    write_subscriptions(steam_library, "2", ["102"])
    if content is not None:
        target = write_subscriptions(steam_library, "1", [])
        target.write_text(content, encoding="utf-8")
    with patch("backend.scanner.get_subscribed_workshop_items", return_value=["101"]) as native:
        result = scan(steam_library)
    assert {mod.workshop_id for mod in result.mods} == {"", "101"}
    native.assert_called_once_with(app_id=1142710)


def test_unavailable_current_subscriptions_skip_workshop_and_report_warning(steam_library: GamePaths):
    write_subscriptions(steam_library, "2", ["102"])
    with patch("backend.scanner.get_subscribed_workshop_items", side_effect=SteamworksBridgeError("offline")):
        result = scan(steam_library)
    assert [mod.pack_name for mod in result.mods] == ["local.pack"]
    assert [warning["code"] for warning in result.warnings] == ["workshop_subscriptions_unavailable"]


def test_running_account_takes_precedence_over_cached_login_account(steam_library: GamePaths):
    write_subscriptions(steam_library, "1", ["101"])
    write_subscriptions(steam_library, "2", ["102"])
    with patch("backend.scanner.active_steam_account_id", return_value="2"):
        result = scan(steam_library)
    assert {mod.workshop_id for mod in result.mods} == {"", "102"}


def test_manual_path_in_secondary_library_is_filtered(steam_library: GamePaths):
    write_subscriptions(steam_library, "1", ["101"])
    root = Path(steam_library.steam_root)
    (root / "steamapps").mkdir()
    library = Path(steam_library.workshop_path).parents[3]
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders" {{ "0" {{ "path" "{library.as_posix()}" }} }}', encoding="utf-8",
    )
    manual = GamePaths(workshop_path=steam_library.workshop_path, data_path=steam_library.data_path)
    with patch("backend.steam_paths.candidate_steam_roots", return_value=[root]):
        result = scan(manual)
    assert {mod.workshop_id for mod in result.mods} == {"", "101"}


def test_manually_managed_directory_does_not_use_unrelated_steam_subscriptions(steam_library: GamePaths):
    write_subscriptions(steam_library, "1", [])
    custom = GamePaths(workshop_path=steam_library.workshop_path)
    with patch("backend.steam_paths.candidate_steam_roots", return_value=[Path(steam_library.steam_root)]):
        result = scan(custom)
    assert {mod.workshop_id for mod in result.mods} == {"101", "102"}


def test_refresh_after_account_switch_replaces_previous_workshop_items(steam_library: GamePaths):
    write_subscriptions(steam_library, "1", ["101"])
    write_subscriptions(steam_library, "2", ["102"])
    scanner = ModScanner(OfflineWorkshopMetadata())
    with patch("backend.scanner.active_steam_account_id", return_value="1"):
        first = scanner.scan(steam_library, {})
    with patch("backend.scanner.active_steam_account_id", return_value="2"):
        second = scanner.scan(steam_library, {})
    assert {mod.workshop_id for mod in first.mods} == {"", "101"}
    assert {mod.workshop_id for mod in second.mods} == {"", "102"}


def test_disk_order_import_and_launch_plan_exclude_unsubscribed_family_item(steam_library: GamePaths, tmp_path: Path):
    write_subscriptions(steam_library, "1", ["101"])
    order_path = Path(steam_library.game_path) / "used_mods.txt"
    order_path.write_text('mod "family.pack";\nmod "own.pack";', encoding="utf-8")
    result = scan(steam_library)
    service = LoadOrderService(tmp_path / "backups")
    imported = service.import_disk_order(steam_library.game_path, result.mods)
    plan = service.build_plan(steam_library.game_path, steam_library.data_path,
                              {mod.id: mod for mod in result.mods}, imported)
    assert plan.pack_names == ["own.pack"]
    assert "102" not in plan.content
    assert "family.pack" not in plan.content


def test_api_refresh_filters_existing_playset_and_loaded_assets(steam_library: GamePaths, tmp_path: Path):
    write_subscriptions(steam_library, "1", ["101"])
    (Path(steam_library.game_path) / "Warhammer3.exe").write_bytes(b"")
    api = API(tmp_path / "state")
    try:
        api.settings_service.save({"game_path": steam_library.game_path,
            "workshop_path": steam_library.workshop_path, "live_mod_detection": False,
            "fetch_workshop_metadata": False, "check_outdated_mods": False})
        api.scanner = ModScanner(OfflineWorkshopMetadata())
        api.state_repository.update_current_playset(["steam:102:family.pack", "steam:101:own.pack"])
        api.state_repository.mark_playsets_initialized("warhammer3")
        with patch.object(api.settings_service, "resolve_game_paths", return_value=steam_library):
            response = api.call("scan_mods", [False])
        assert response["ok"], response
        assert {mod["workshop_id"] for mod in response["data"]["mods"]} == {"", "101"}
        assert response["data"]["enabled_order"] == ["steam:101:own.pack"]
        assert response["data"]["missing_enabled_ids"] == ["steam:102:family.pack"]
        assert "steam:102:family.pack" not in api._assets
    finally:
        api.close()


@pytest.mark.parametrize("game_id,app_id", [("three_kingdoms", "779340"), ("rome_remastered", "885970")])
def test_subscription_filter_uses_selected_games_manifest(
    steam_library: GamePaths, game_id: str, app_id: str,
):
    paths = GamePaths(game_id=game_id, steam_root=steam_library.steam_root,
                      workshop_path=str(Path(steam_library.workshop_path).with_name(app_id)))
    root = Path(paths.workshop_path)
    if game_id == "rome_remastered":
        from tests.test_scanner import ScannerTests
        ScannerTests._write_rome_directory_mod(root, "101")
        ScannerTests._write_rome_directory_mod(root, "102")
    else:
        write_pack(root / "101" / "own.pack")
        write_pack(root / "102" / "family.pack")
    write_subscriptions(paths, "1", ["101"])
    write_subscriptions(steam_library, "1", ["102"])
    result = scan(paths)
    assert [mod.workshop_id for mod in result.mods] == ["101"]
