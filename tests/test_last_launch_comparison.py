from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.api import API
from backend.start_options import RUNTIME_PACK_NAME
from backend.games import get_game_definition
from backend.crash_diagnostics import parse_launch_list
from backend.storage import StateRepository
from tests.helpers import make_asset, write_pack


@pytest.fixture
def manager(tmp_path):
    api = API(tmp_path / "state")
    with patch.object(api, "detect_game_running", return_value=False):
        yield api
    api.close()


def select_game(api, root, game_id="warhammer3", suffix=""):
    game = root / (game_id + suffix)
    (game / "data").mkdir(parents=True, exist_ok=True)
    (game / get_game_definition(game_id).executable_name).touch()
    workshop = root / (game_id + suffix + "_workshop")
    workshop.mkdir(exist_ok=True)
    response = api.call("save_settings", [{
        "selected_game": game_id, "game_path": str(game), "workshop_path": str(workshop),
        "live_mod_detection": False, "fetch_workshop_metadata": False,
    }])
    assert response["ok"], response
    return game


def test_empty_baseline_is_distinct_from_no_launch(manager, tmp_path):
    select_game(manager, tmp_path)
    assert manager.call("get_last_launch_mods")["data"]["available"] is False
    with patch("backend.api.launch_game", return_value={"pid": 123}):
        response = manager.call("launch_game", [[]])
    assert response["ok"], response
    snapshot = manager.call("get_last_launch_mods")["data"]
    assert snapshot["available"] is True
    assert snapshot["mods"] == []
    assert snapshot["started_at"] > 0


def test_real_launch_order_persists_across_saves_failure_and_restart(manager, tmp_path):
    game = select_game(manager, tmp_path)
    assets = [make_asset(write_pack(game / "data" / f"{name}.pack"), name, "data") for name in ("a", "b")]
    manager._assets = {asset.id: asset for asset in assets}
    with patch("backend.api.launch_game", return_value={"pid": 123}):
        response = manager.call("launch_game", [["b", "a"]])
    assert response["ok"], response
    snapshot = manager.call("get_last_launch_mods")["data"]
    assert [row["pack_name"] for row in snapshot["mods"]] == ["b.pack", "a.pack"]
    assert snapshot["mods"][0]["effective_name"] == "b"
    saved = manager.call("save_load_order", [["a"]])
    assert saved["ok"], saved
    assert manager.call("get_last_launch_mods")["data"] == snapshot
    with patch("backend.api.launch_game", side_effect=OSError("cannot launch")):
        assert manager.call("launch_game", [["a"]])["ok"] is False
    assert manager.call("get_last_launch_mods")["data"] == snapshot
    # Reopening the manager, even after the MOD is gone, keeps historical names.
    reopened = API(tmp_path / "state")
    try:
        assert reopened.call("get_last_launch_mods")["data"] == snapshot
    finally:
        reopened.close()
    with patch("backend.api.launch_game", return_value={"pid": 124}):
        assert manager.call("launch_game", [["a"]])["ok"]
    assert [row["pack_name"] for row in manager.call("get_last_launch_mods")["data"]["mods"]] == ["a.pack"]


def test_launch_from_save_and_continue_update_the_same_baseline(manager, tmp_path):
    game = select_game(manager, tmp_path)
    asset = make_asset(write_pack(game / "data" / "a.pack"), "a", "data")
    manager._assets = {"a": asset}
    manager.save_games.save_directory = tmp_path / "saves"
    manager.save_games.save_directory.mkdir()
    (manager.save_games.save_directory / "campaign.save").write_bytes(b"fixture")
    with patch("backend.api.launch_game", return_value={"pid": 123}):
        response = manager.call("launch_game", [["a"], "", "campaign.save"])
    assert response["ok"], response
    assert manager.call("get_last_launch_mods")["data"]["mods"][0]["pack_name"] == "a.pack"
    with patch("backend.api.launch_game", return_value={"pid": 124}):
        response = manager.call("continue_game", [[]])
    assert response["ok"], response
    assert manager.call("get_last_launch_mods")["data"]["mods"] == []
    history = manager.call("list_launch_history")["data"]["items"]
    assert [record["mod_count"] for record in history] == [0, 1]
    assert [record["save_name"] for record in history] == ["campaign.save", "campaign.save"]


def test_old_records_are_available_without_generated_packs_and_isolated_by_game(manager, tmp_path):
    game = select_game(manager, tmp_path)
    manager.diagnostics.launches.save({"games": {"warhammer3": {
        "game_path": str(game), "started_at": 123,
        "packs": [{"pack_name": "old.pack"}, {"pack_name": RUNTIME_PACK_NAME}],
    }}})
    assert manager.call("get_last_launch_mods")["data"]["mods"] == [
        {"pack_name": "old.pack", "effective_name": ""},
    ]
    select_game(manager, tmp_path, "three_kingdoms")
    assert manager.call("get_last_launch_mods")["data"]["available"] is False
    select_game(manager, tmp_path, suffix="_other")
    assert manager.call("get_last_launch_mods")["data"]["available"] is False
    select_game(manager, tmp_path)
    assert manager.call("get_last_launch_mods")["data"]["available"] is True


def launch_record(manager, ids):
    with patch("backend.api.launch_game", return_value={"pid": 123}):
        response = manager.call("launch_game", [ids])
    assert response["ok"], response
    return manager.call("list_launch_history")["data"]["items"][0]


def setup_named_mods(manager, tmp_path):
    game = select_game(manager, tmp_path)
    manager._assets = {
        name: make_asset(write_pack(game / "data" / f"{name}.pack", byte_mask=3), name, "data")
        for name in ("a", "b", "c")
    }
    for name, title in zip(("a", "b", "c"), ("龙裔扩展", "江湖英雄", "建筑调整")):
        manager._assets[name].display_name = title
    return game


def test_records_every_launch_including_identical_and_empty_lists(manager, tmp_path):
    setup_named_mods(manager, tmp_path)
    first = launch_record(manager, ["b", "a"])
    second = launch_record(manager, ["b", "a"])
    empty = launch_record(manager, [])
    assert len({first["id"], second["id"], empty["id"]}) == 3
    records = manager.call("list_launch_history")["data"]["items"]
    assert [row["mod_count"] for row in records] == [0, 2, 2]
    with patch("backend.api.launch_game", side_effect=OSError("cannot launch")):
        assert not manager.call("launch_game", [["a"]])["ok"]
    assert manager.call("list_launch_history")["data"]["items"] == records
    reopened = API(tmp_path / "state")
    try:
        assert reopened.call("list_launch_history")["data"]["items"] == records
    finally:
        reopened.close()


def test_record_names_and_order_are_immutable_and_restoration_persists(manager, tmp_path):
    game = setup_named_mods(manager, tmp_path)
    record = launch_record(manager, ["b", "a"])
    launch_record(manager, ["c"])
    manager._assets["b"].alias = "Changed alias"
    snapshot = manager.call("get_launch_record", [record["id"]])["data"]
    assert [mod["effective_name"] for mod in snapshot["mods"]] == ["江湖英雄", "龙裔扩展"]
    result = manager.call("load_launch_record", [record["id"], manager._last_order_token])
    assert result["ok"], result
    assert result["data"]["ordered_mod_ids"] == ["b", "a"]
    repository = StateRepository(manager.state_repository.database_path)
    assert repository.get_current_playset()["mod_ids"] == ["b", "a"]
    assert parse_launch_list(game / "used_mods.txt")[1] == ["b.pack", "a.pack"]
    assert len(manager.call("list_launch_history")["data"]["items"]) == 2


def test_loading_empty_record_clears_previous_missing_entries(manager, tmp_path):
    setup_named_mods(manager, tmp_path)
    empty = launch_record(manager, [])
    launch_record(manager, ["a"])
    manager.state_repository.update_current_playset(["a", "old-missing"])
    result = manager.call("load_launch_record", [empty["id"], manager._last_order_token])
    assert result["ok"], result
    assert result["data"]["ordered_mod_ids"] == []
    assert result["data"]["current_playset"]["mod_ids"] == []
    assert result["data"]["missing_mod_ids"] == []


def test_load_preserves_missing_names_and_intent_and_resolves_source_alias(manager, tmp_path):
    setup_named_mods(manager, tmp_path)
    record = launch_record(manager, ["a", "b"])
    manager._assets["a"].path = str(tmp_path / "gone.pack")
    moved = manager._assets.pop("b")
    moved.id = "workshop:b"
    manager._assets[moved.id] = moved
    manager._asset_aliases["b"] = moved.id
    snapshot = manager.call("get_launch_record", [record["id"]])["data"]
    assert snapshot["mods"][0]["effective_name"] == "龙裔扩展"
    assert snapshot["mods"][0]["missing"]
    response = manager.call("load_launch_record", [record["id"], manager._last_order_token])
    assert response["ok"], response
    result = response["data"]
    assert result["ordered_mod_ids"] == ["workshop:b"]
    assert result["missing_mod_ids"] == ["a"]
    assert result["current_playset"]["mod_ids"] == ["a", "workshop:b"]
    assert result["missing_mods"][0]["effective_name"] == "龙裔扩展"


def test_load_rejects_other_game_and_running_game_without_mutation(manager, tmp_path):
    setup_named_mods(manager, tmp_path)
    record = launch_record(manager, ["a"])
    with patch.object(manager, "detect_game_running", return_value=True):
        assert not manager.call("load_launch_record", [record["id"]])["ok"]
    assert manager.state_repository.get_current_playset()["mod_ids"] == ["a"]
    select_game(manager, tmp_path, "three_kingdoms")
    assert not manager.call("get_launch_record", [record["id"]])["ok"]
    assert not manager.call("load_launch_record", [record["id"]])["ok"]
    assert manager.state_repository.get_current_playset("three_kingdoms")["mod_ids"] == []


def test_load_does_not_substitute_a_different_workshop_mod_with_the_same_filename(manager, tmp_path):
    game = setup_named_mods(manager, tmp_path)
    manager._assets["a"].workshop_id = "123"
    record = launch_record(manager, ["a"])
    manager._assets.pop("a")
    other = make_asset(write_pack(game / "data" / "a.pack", byte_mask=3), "other", "data")
    other.workshop_id = "456"
    manager._assets[other.id] = other
    snapshot = manager.call("get_launch_record", [record["id"]])["data"]
    assert snapshot["mods"][0]["missing"]
    response = manager.call("load_launch_record", [record["id"], manager._last_order_token])
    assert response["ok"], response
    assert response["data"]["ordered_mod_ids"] == []
    assert response["data"]["missing_mod_ids"] == ["a"]


def test_history_is_isolated_by_installation_and_ambiguous_sources_stay_missing(manager, tmp_path):
    setup_named_mods(manager, tmp_path)
    record = launch_record(manager, ["a"])
    manager._assets.pop("a")
    for mod_id in ("other1", "other2"):
        manager._assets[mod_id] = make_asset(write_pack(tmp_path / mod_id / "a.pack", byte_mask=3), mod_id, "data")
    snapshot = manager.call("get_launch_record", [record["id"]])["data"]
    assert snapshot["mods"][0]["missing"]
    select_game(manager, tmp_path, suffix="_other")
    assert manager.call("list_launch_history")["data"]["items"] == []
    assert not manager.call("load_launch_record", [record["id"]])["ok"]


def test_load_rolls_back_files_database_and_token_on_save_failure(manager, tmp_path):
    game = setup_named_mods(manager, tmp_path)
    record = launch_record(manager, ["a", "b"])
    launch_record(manager, ["c"])
    before = (game / "used_mods.txt").read_bytes()
    token = manager._last_order_token
    with patch.object(manager.state_repository, "update_current_playset", side_effect=OSError("disk failure")):
        assert not manager.call("load_launch_record", [record["id"], token])["ok"]
    assert (game / "used_mods.txt").read_bytes() == before
    assert manager.state_repository.get_current_playset()["mod_ids"] == ["c"]
    assert manager._last_order_token == token
    (game / "used_mods.txt").write_text("externally changed", encoding="utf-8")
    assert not manager.call("load_launch_record", [record["id"], token])["ok"]
    assert (game / "used_mods.txt").read_text(encoding="utf-8") == "externally changed"
    assert manager.state_repository.get_current_playset()["mod_ids"] == ["c"]


def test_migrates_the_previous_single_record_once(manager, tmp_path):
    game = setup_named_mods(manager, tmp_path)
    manager.diagnostics.launches.save({"games": {"warhammer3": {
        "game_path": str(game), "started_at": 123, "evidence_sealed": True,
        "packs": [{"pack_name": "a.pack"}, {"pack_name": RUNTIME_PACK_NAME}],
    }}})
    records = manager.call("list_launch_history")["data"]["items"]
    assert len(records) == 1
    snapshot = manager.call("get_launch_record", [records[0]["id"]])["data"]
    assert snapshot["mods"][0]["effective_name"] == "龙裔扩展"
    assert manager.call("list_launch_history")["data"]["items"] == records
    launch_record(manager, ["b"])
    assert len(manager.call("list_launch_history")["data"]["items"]) == 2
