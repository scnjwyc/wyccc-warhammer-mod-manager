from __future__ import annotations

import os
import struct
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.api import API
from backend.crash_diagnostics import (
    capture_evidence, collect_crash_dumps, diagnose_launch, launch_record,
    parse_launch_list, read_dump_exception,
)
from backend.mod_diagnostics import DiagnosticSession, GameProbe, TrialStopped, dependency_groups
from backend.models import GamePaths
from backend.load_order import file_token
from tests.helpers import make_asset, write_pack


def record_fixture(root):
    game = root / "game"
    data = game / "data"
    data.mkdir(parents=True)
    user = root / "user"
    (user / "logs").mkdir(parents=True)
    write_pack(data / "a.pack", byte_mask=3)
    write_pack(data / "b.pack", byte_mask=3)
    write_pack(data / "movie.pack", byte_mask=4)
    before = capture_evidence(user)
    plan = {"target_path": str(game / "used_mods.txt"), "pack_names": ["a.pack", "b.pack", "movie.pack"]}
    return launch_record("warhammer3", str(game), user, plan, time.time(), before), user


def test_reordered_case_insensitive_loading_and_movie_exclusion(tmp_path):
    record, user = record_fixture(tmp_path)
    (user / "logs" / "modified.log").write_text("Mod: B.PACK\nMod: a.pack\nMod: a.pack\n")
    result = diagnose_launch(record)
    assert result["status"] == "loaded_all"
    assert result["expected_count"] == result["loaded_count"] == 2
    assert result["pending"] == []
    assert not result["crashed"]


def test_pending_pack_is_a_suspect_not_a_proven_crash(tmp_path):
    record, user = record_fixture(tmp_path)
    (user / "logs" / "modified.log").write_text("Mod: b.pack\n")
    result = diagnose_launch(record)
    assert result["status"] == "interrupted"
    assert [row["pack_name"] for row in result["pending"]] == ["a.pack"]
    assert not result["crashed"] and not result["should_notify"]


def test_old_log_and_old_dump_cannot_be_assigned_to_new_launch(tmp_path):
    record, user = record_fixture(tmp_path)
    log = user / "logs" / "modified.log"
    log.write_text("Mod: a.pack\n")
    os.utime(log, (record["started_at"] - 60, record["started_at"] - 60))
    dump = user / "crash_report" / "D2020-01-01_T00-00-00.mdmp"
    dump.parent.mkdir()
    dump.write_bytes(b"old copied dump")
    result = diagnose_launch(record)
    assert result["status"] == "not_started"
    assert result["dumps"] == []
    assert not result["crashed"]


def test_fresh_dump_notifies_once_and_does_not_need_a_loading_log(tmp_path):
    record, user = record_fixture(tmp_path)
    dump = user / "crash_report" / "current.mdmp"
    dump.parent.mkdir()
    dump.write_bytes(b"new dump")
    result = diagnose_launch(record)
    assert result["crashed"] and result["should_notify"]
    record["acknowledged"] = True
    assert not diagnose_launch(record)["should_notify"]
    assert not diagnose_launch(record, running=True)["should_notify"]
    assert collect_crash_dumps(dump.parent, time.time(), {str(dump): [dump.stat().st_mtime_ns, dump.stat().st_size]}) == []


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16le"])
def test_launch_lists_support_game_encodings_and_non_ascii_directories(tmp_path, encoding):
    path = tmp_path / "list.txt"
    path.write_bytes('add_working_directory "C:\\模组";\r\nmod "test.pack";\r\n'.encode(encoding))
    assert parse_launch_list(path) == (["C:\\模组"], ["test.pack"])


def test_dump_exception_reads_stream_beyond_first_header_page(tmp_path):
    payload = bytearray(5000)
    payload[:4] = b"MDMP"
    struct.pack_into("<II", payload, 8, 1, 32)
    struct.pack_into("<III", payload, 32, 6, 168, 4500)
    struct.pack_into("<I", payload, 4508, 0xC0000005)
    struct.pack_into("<Q", payload, 4524, 0x12345678)
    struct.pack_into("<I", payload, 4532, 2)
    struct.pack_into("<QQ", payload, 4540, 0, 123)
    path = tmp_path / "test.mdmp"
    path.write_bytes(payload)
    assert read_dump_exception(path) == {"code": "0xC0000005", "address": "0x12345678", "parameters": [0, 123]}
    struct.pack_into("<II", payload, 8, 999999, 32)
    path.write_bytes(payload)
    assert read_dump_exception(path) == {}


def run_session(root, failure, mode="bisect", *, groups=None):
    groups = groups or [[name] for name in "abcd"]
    ids = [item for group in groups for item in group]
    session = DiagnosticSession(root / "sessions.json")
    session.start({"game_id": "warhammer3", "mode": mode, "original_ids": ids}, groups,
                  lambda selected, *_args: {"verdict": "crash" if failure(set(selected)) else "ok"})
    session._thread.join(timeout=5)
    assert not session.running
    return session


def test_bisect_checks_failure_and_working_complement(tmp_path):
    session = run_session(tmp_path, lambda ids: "c" in ids)
    result = session.status()
    assert result["status"] == "isolated" and result["can_apply"]
    assert result["suspect_ids"] == result["excluded_ids"] == ["c"]
    assert result["result_ids"] == ["a", "b", "d"]
    assert result["rounds"][-3]["kind"] == "complement"
    assert [row["kind"] for row in result["rounds"][-2:]] == ["final", "final"]
    assert result["rounds"][-1]["kind"] == "final"
    assert DiagnosticSession(tmp_path / "sessions.json").history("warhammer3")[0]["result_ids"] == ["a", "b", "d"]
    assert session.history("three_kingdoms") == []


def test_combination_failure_is_returned_as_a_group(tmp_path):
    result = run_session(tmp_path, lambda ids: {"b", "d"} <= ids).status()
    assert result["status"] == "isolated"
    assert set(result["suspect_ids"]) == {"b", "d"}
    assert not any(key in result for key in ("known_bad", "culprit"))


def test_multiple_failures_are_not_called_fixed_by_one_exclusion(tmp_path):
    result = run_session(tmp_path, lambda ids: bool({"b", "d"} & ids)).status()
    assert result["status"] == "multiple"
    assert not result["can_apply"]


def test_repeated_exclusion_validates_the_final_combination(tmp_path):
    result = run_session(tmp_path, lambda ids: bool({"b", "d"} & ids), mode="maxload").status()
    assert result["status"] == "success" and result["can_apply"]
    assert set(result["excluded_ids"]) == {"b", "d"}
    assert result["result_ids"] == ["a", "c"]
    assert result["rounds"][-1]["verdict"] == "ok"


@pytest.mark.parametrize("failure,status", [(lambda _ids: False, "no_repro"), (lambda _ids: True, "background_failure")])
def test_baselines_prevent_false_culprits(tmp_path, failure, status):
    result = run_session(tmp_path, failure).status()
    assert result["status"] == status
    assert not result["can_apply"]


def test_missing_start_evidence_stops_the_search(tmp_path):
    session = DiagnosticSession(tmp_path / "session.json")
    session.start({"game_id": "warhammer3", "mode": "bisect", "original_ids": ["a"]}, [["a"]],
                  lambda *_args: {"verdict": "inconclusive"})
    session._thread.join(5)
    assert session.status()["status"] == "inconclusive"
    assert len(session.status()["rounds"]) == 1


def test_dependencies_stay_together_in_every_trial(tmp_path):
    assets = {name: make_asset(write_pack(tmp_path / f"{name}.pack", byte_mask=3), name, "data") for name in "abcd"}
    assets["b"].dependency_packs = ["A.pack"]
    assets["c"].required_workshop_items = [{"workshop_id": "123"}]
    assets["d"].workshop_id = "123"
    groups = dependency_groups(assets, list("abcd"))
    assert groups == [["a", "b"], ["c", "d"]]
    result = run_session(tmp_path, lambda ids: "b" in ids, groups=groups).status()
    for row in result["rounds"]:
        assert ("a" in row["mod_ids"]) == ("b" in row["mod_ids"])


def test_disabled_duplicate_pack_cannot_hide_the_enabled_dependency(tmp_path):
    a = make_asset(write_pack(tmp_path / "a.pack", byte_mask=3), "a", "data")
    b = make_asset(write_pack(tmp_path / "b.pack", byte_mask=3), "b", "data")
    duplicate = make_asset(write_pack(tmp_path / "other" / "a.pack", byte_mask=3), "other-a", "data")
    b.dependency_packs = ["A.pack"]
    assert dependency_groups({"a": a, "b": b, "other-a": duplicate}, ["a", "b"]) == [["a", "b"]]


def test_cancel_and_stale_confirmation_cannot_advance_another_round(tmp_path):
    session = DiagnosticSession(tmp_path / "session.json")
    ready = threading.Event()

    def trial(_ids, cancel, _manual, progress, _kind):
        progress("confirm_menu")
        ready.set()
        cancel.wait(2)
        raise TrialStopped("cancelled")

    session.start({"game_id": "warhammer3", "mode": "bisect", "original_ids": ["a"]}, [["a"]], trial)
    assert ready.wait(2)
    state = session.status()
    with pytest.raises(ValueError, match="staleTrial"):
        session.confirm(state["id"], 999, "ok")
    session.confirm(state["id"], 1, "ok")
    with pytest.raises(ValueError, match="staleTrial"):
        session.confirm(state["id"], 1, "crash")
    session.cancel()
    session._thread.join(5)
    assert session.status()["status"] == "cancelled"


def test_restart_marks_incomplete_run_interrupted(tmp_path):
    session = DiagnosticSession(tmp_path / "session.json")
    session._store.save({"session": {"running": True, "game_id": "warhammer3"}, "history": []})
    result = DiagnosticSession(tmp_path / "session.json").status()
    assert result["status"] == "interrupted" and not result["running"]


@pytest.mark.parametrize("manual,verdict", [("", "inconclusive"), ("ok", "ok"), ("crash", "crash")])
def test_process_survival_is_not_a_success_verdict(tmp_path, manual, verdict):
    paths = GamePaths(game_path=str(tmp_path))
    probe = GameProbe(paths, tmp_path / "user", timeout=0.02, poll=0.001)
    with patch("backend.mod_diagnostics.launcher.is_game_running", return_value=False), \
            patch("backend.mod_diagnostics.launcher.launch_game", return_value={"pid": 12}), \
            patch("backend.mod_diagnostics.launcher._matching_game_process_ids", return_value=[12]), \
            patch("backend.mod_diagnostics.launcher.terminate_game_processes") as terminate, \
            patch("backend.mod_diagnostics.find_crash_dialog", return_value=None):
        result = probe.run("trial.txt", threading.Event(), lambda: manual, lambda _phase: None)
    assert result["verdict"] == verdict
    assert terminate.call_args.args[0] == {12}


def test_preexisting_game_is_never_terminated(tmp_path):
    probe = GameProbe(GamePaths(game_path=str(tmp_path)), tmp_path)
    with patch("backend.mod_diagnostics.launcher.is_game_running", return_value=True), \
            patch("backend.mod_diagnostics.launcher.launch_game") as launch, \
            patch("backend.mod_diagnostics.launcher.terminate_game_processes") as terminate:
        assert probe.run("trial", threading.Event(), lambda: "", lambda _: None)["evidence"] == "already_running"
        launch.assert_not_called()
        terminate.assert_not_called()


@pytest.fixture
def diagnostic_api(tmp_path):
    game = tmp_path / "game"
    data = game / "data"
    data.mkdir(parents=True)
    (game / "Warhammer3.exe").write_bytes(b"fixture")
    api = API(tmp_path / "state")
    paths = GamePaths(game_path=str(game), data_path=str(data))
    assets = {name: make_asset(write_pack(data / f"{name}.pack", byte_mask=3), name, "data") for name in "abc"}
    api._assets = assets
    api.state_repository.update_current_playset(list("abc"), "warhammer3")
    (game / "used_mods.txt").write_bytes(b'original list\r\n')
    api._last_order_token = file_token(game / "used_mods.txt")
    with patch.object(api.settings_service, "resolve_game_paths", return_value=paths), \
            patch.object(api, "detect_game_running", return_value=False):
        yield api, game
    api.close()


@pytest.mark.parametrize("mode", ["bisect", "maxload"])
@pytest.mark.parametrize("kind", ["pack", "workshop"])
@pytest.mark.parametrize("availability", ["missing", "disabled"])
def test_api_diagnostics_respects_ignored_dependencies(diagnostic_api, mode, kind, availability):
    api, _game = diagnostic_api
    asset = api._assets["a"]
    if kind == "pack":
        dependency_id = "missing.pack" if availability == "missing" else "b.pack"
        asset.dependency_packs = [dependency_id]
    else:
        api._assets["b"].workshop_id = "102"
        dependency_id = "999" if availability == "missing" else "102"
        asset.required_workshop_items = [{"workshop_id": dependency_id, "title": "Dependency"}]
    if availability == "missing":
        asset.missing_dependencies = [{"kind": kind, "id": dependency_id, "name": "Dependency"}]
    selected = ["a", "c"]
    api.state_repository.update_current_playset(selected, "warhammer3")
    seen = []

    def run(_self, path, *_args):
        seen.append(parse_launch_list(Path(path))[1])
        return {"verdict": "ok"}

    with patch("backend.diagnostics_api.GameProbe.run", autospec=True, side_effect=run) as probe:
        blocked = api.call("start_mod_diagnostics", [selected, mode])
        assert not blocked["ok"] and blocked["error"]["message"] == "diagnostics.dependenciesMissing"
        probe.assert_not_called()

        ignored = api.call("set_mod_warning_ignored", [asset.id, "missing_dependency", True])
        assert ignored["ok"], ignored
        response = api.call("start_mod_diagnostics", [selected, mode])
        assert response["ok"], response
        api.diagnostics.session._thread.join(5)
        assert api.diagnostics.session.status()["status"] == "no_repro"
        assert seen == [["a.pack", "c.pack"], ["a.pack", "c.pack"]]
        assert api.state_repository.get_current_playset()["mod_ids"] == selected

        restored = api.call("set_mod_warning_ignored", [asset.id, "missing_dependency", False])
        assert restored["ok"], restored
        blocked = api.call("start_mod_diagnostics", [selected, mode])
        assert not blocked["ok"] and blocked["error"]["message"] == "diagnostics.dependenciesMissing"
        assert probe.call_count == 2


@pytest.mark.parametrize("ignored_mod,warning_code", [("a", "outdated_mod"), ("c", "missing_dependency")])
def test_api_diagnostics_ignore_only_applies_to_the_selected_mod_warning(
    diagnostic_api, ignored_mod, warning_code,
):
    api, _game = diagnostic_api
    api._assets["a"].missing_dependencies = [{"kind": "pack", "id": "missing.pack", "name": "Missing"}]
    ignored = api.call("set_mod_warning_ignored", [ignored_mod, warning_code, True])
    assert ignored["ok"], ignored
    with patch("backend.diagnostics_api.GameProbe.run") as probe:
        blocked = api.call("start_mod_diagnostics", [list("abc")])
        assert not blocked["ok"] and blocked["error"]["message"] == "diagnostics.dependenciesMissing"
        probe.assert_not_called()


def test_api_trials_preserve_playset_and_disk_order_then_apply_and_restore(diagnostic_api):
    api, game = diagnostic_api
    seen = []

    def run(_self, path, *_args):
        raw = Path(path).read_bytes()
        assert b"\r\n" in raw
        seen.append(parse_launch_list(Path(path))[1])
        return {"verdict": "crash" if "b.pack" in seen[-1] else "ok"}

    original = api.state_repository.get_current_playset()["mod_ids"]
    with patch("backend.diagnostics_api.GameProbe.run", autospec=True, side_effect=run):
        response = api.call("start_mod_diagnostics", [list("abc"), "bisect"])
        assert response["ok"], response
        api.diagnostics.session._thread.join(5)
    state = api.diagnostics.session.status()
    assert state["status"] == "isolated", state
    assert api.state_repository.get_current_playset()["mod_ids"] == original
    assert (game / "used_mods.txt").read_bytes() == b"original list\r\n"
    assert not list(game.glob("wyccc_diagnostics_*.txt"))
    response = api.call("apply_diagnostics_result", [state["id"]])
    assert response["ok"], response
    assert response["data"]["ordered_mod_ids"] == ["a", "c"]
    assert response["data"]["order_token"] == file_token(game / "used_mods.txt")
    assert parse_launch_list(game / "used_mods.txt")[1] == ["a.pack", "c.pack"]
    assert api.state_repository.get_current_playset()["mod_ids"] == ["a", "c"]
    assert api.call("apply_diagnostics_result", [state["id"], True])["ok"]
    assert api.state_repository.get_current_playset()["mod_ids"] == original
    assert parse_launch_list(game / "used_mods.txt")[1] == ["a.pack", "b.pack", "c.pack"]
    Path(api._assets["b"].path).write_bytes(b"updated pack")
    response = api.call("apply_diagnostics_result", [state["id"]])
    assert not response["ok"] and response["error"]["message"] == "diagnostics.contextChanged"


def test_rpc_mutations_are_blocked_while_cancel_is_available(diagnostic_api):
    api, _game = diagnostic_api
    ready = threading.Event()

    def probe(_self, _path, cancel, _manual, progress):
        progress("confirm_menu")
        ready.set()
        cancel.wait(2)
        raise TrialStopped("cancelled")

    with patch("backend.diagnostics_api.GameProbe.run", autospec=True, side_effect=probe):
        assert api.call("start_mod_diagnostics", [list("abc")])["ok"]
        assert ready.wait(2)
        assert not api.low_consumption_enabled()
        for method, args in [("save_settings", [{"selected_game": "three_kingdoms"}]),
                             ("switch_playset", ["x"]), ("launch_game", [[]]), ("scan_mods", [])]:
            response = api.call(method, args)
            assert not response["ok"] and response["error"]["message"] == "diagnostics.running"
        assert api.call("cancel_mod_diagnostics")["ok"]
        api.diagnostics.session._thread.join(5)
    assert api.diagnostics.session.status()["status"] == "cancelled"
