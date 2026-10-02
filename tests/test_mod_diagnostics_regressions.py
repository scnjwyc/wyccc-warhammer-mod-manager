"""Regression coverage for the October diagnostics audit, isolated from real games."""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.crash_diagnostics import (
    capture_evidence, diagnose_launch, dump_belongs_to_launch, launch_record,
    freeze_launch, parse_launch_list, read_dump_exception, read_dump_process,
)
from backend.load_order import file_token
from backend.mod_diagnostics import DiagnosticSession, GameProbe
from backend.models import GamePaths
from backend.scanner import ModScanner
from tests.helpers import make_asset, write_minidump, write_pack
from tests import test_mod_diagnostics

diagnostic_api = test_mod_diagnostics.diagnostic_api


def verified_run(api):
    def trial(_probe, path, *_args):
        return {"verdict": "crash" if "b.pack" in parse_launch_list(Path(path))[1] else "ok"}

    with patch("backend.diagnostics_api.GameProbe.run", autospec=True, side_effect=trial):
        assert api.call("start_mod_diagnostics", [list("abc"), "bisect"])["ok"]
        api.diagnostics.session._thread.join(5)
    state = api.diagnostics.session.status()
    assert state["can_apply"] and state["result_ids"] == ["a", "c"]
    return state


@pytest.mark.parametrize("failure_at", ["file", "database"])
def test_apply_failure_preserves_playset_and_both_order_files(diagnostic_api, failure_at):
    api, game = diagnostic_api
    state = verified_run(api)
    old_order = (game / "used_mods.txt").read_bytes()
    old_token = file_token(game / "used_mods.txt")
    old_playset = api.state_repository.get_current_playset()["mod_ids"]
    target = api.load_order if failure_at == "file" else api.state_repository
    method = "_atomic_write" if failure_at == "file" else "add_backup"
    with patch.object(target, method, side_effect=OSError("injected save failure")):
        result = api.call("apply_diagnostics_result", [state["id"], False, old_token])
    assert not result["ok"]
    assert api.state_repository.get_current_playset()["mod_ids"] == old_playset
    assert (game / "used_mods.txt").read_bytes() == old_order
    assert file_token(game / "used_mods.txt") == old_token
    assert not (game / "my_mods.txt").exists()
    assert api._last_order_token == old_token
    assert api.call("apply_diagnostics_result", [state["id"], False, old_token])["ok"]


def test_apply_rejects_external_order_change_before_modifying_playset(diagnostic_api):
    api, game = diagnostic_api
    state = verified_run(api)
    old_token = file_token(game / "used_mods.txt")
    (game / "used_mods.txt").write_bytes(b"changed by another manager")
    result = api.call("apply_diagnostics_result", [state["id"], False, old_token])
    assert not result["ok"]
    assert api.state_repository.get_current_playset()["mod_ids"] == list("abc")
    assert (game / "used_mods.txt").read_bytes() == b"changed by another manager"


def test_ended_launch_keeps_evidence_when_shared_files_change(tmp_path):
    game = tmp_path / "game"
    user = tmp_path / "user"
    (game / "data").mkdir(parents=True)
    (user / "logs").mkdir(parents=True)
    write_pack(game / "data" / "a.pack", byte_mask=3)
    record = launch_record("warhammer3", str(game), user, {"pack_names": ["a.pack"]},
                           time.time(), capture_evidence(user))
    log = user / "logs" / "modified.log"
    log.write_text("Mod: a.pack\n")
    first = diagnose_launch(record)
    assert first["status"] == "loaded_all" and not first["crashed"]
    log.write_text("Mod: another.pack\n")
    dump = user / "crash_report" / "later.mdmp"
    dump.parent.mkdir()
    dump.write_bytes(b"a later trial")
    assert diagnose_launch(record) == first


def test_owned_delayed_dump_is_retained_until_the_next_launch_seals_evidence(tmp_path):
    user = tmp_path / "user"
    (user / "logs").mkdir(parents=True)
    record = launch_record("warhammer3", str(tmp_path), user, {"pack_names": []},
                           time.time(), capture_evidence(user))
    record["process_ids"] = [12]
    (user / "logs" / "modified.log").write_text("finished loading\n")
    assert not diagnose_launch(record)["crashed"]
    write_minidump(user / "crash_report" / "delayed.mdmp", 12, created_at=int(record["started_at"]))
    assert diagnose_launch(record)["crashed"]
    freeze_launch(record)
    sealed = diagnose_launch(record)
    write_minidump(user / "crash_report" / "another.mdmp", 12, created_at=int(record["started_at"]))
    assert diagnose_launch(record) == sealed


@pytest.mark.parametrize("first,second", [("ok", "crash"), ("crash", "ok")])
def test_inconsistent_baseline_never_produces_verified_result(tmp_path, first, second):
    session = DiagnosticSession(tmp_path / "sessions.json")
    verdicts = iter([first, second])
    session.start({"game_id": "warhammer3", "mode": "bisect", "original_ids": ["a"]}, [["a"]],
                  lambda *_args: {"verdict": next(verdicts)})
    session._thread.join(5)
    state = session.status()
    assert state["status"] == "unstable" and not state["can_apply"]
    assert len(state["rounds"]) == 2


def test_unselected_movie_keeps_transitive_dependencies(diagnostic_api):
    api, game = diagnostic_api
    movie = make_asset(write_pack(game / "data" / "movie.pack", byte_mask=4,
                                 dependencies=["b.pack"]), "movie", "data")
    movie.dependency_packs = ["b.pack"]
    api._assets["movie"] = movie
    api._assets["b"].dependency_packs = ["c.pack"]
    seen = []

    def trial(_probe, path, *_args):
        names = parse_launch_list(Path(path))[1]
        seen.append(names)
        return {"verdict": "crash" if "a.pack" in names or not {"b.pack", "c.pack"} <= set(names) else "ok"}

    with patch("backend.diagnostics_api.GameProbe.run", autospec=True, side_effect=trial):
        assert api.call("start_mod_diagnostics", [list("abc"), "bisect"])["ok"]
        api.diagnostics.session._thread.join(5)
    state = api.diagnostics.session.status()
    assert state["can_apply"] and state["result_ids"] == ["b", "c"]
    assert state["fixed_ids"] == ["b", "c"]
    assert all({"b.pack", "c.pack"} <= set(names) for names in seen)


@pytest.mark.parametrize("identical", [True, False])
def test_rescan_resolves_alias_and_checks_its_actual_content(diagnostic_api, identical):
    api, game = diagnostic_api
    workshop = game.parent / "workshop" / "a.pack"
    workshop.parent.mkdir(exist_ok=True)
    shutil.move(api._assets["a"].path, workshop)
    api._assets["a"] = make_asset(workshop, "a", "workshop", workshop_id="101")
    state = verified_run(api)
    copied = game / "data" / "a.pack"
    shutil.copy2(workshop, copied)
    if not identical:
        write_pack(copied, byte_mask=3, entries=[("different", b"payload")])
    api._assets["data-a"] = make_asset(copied, "data-a", "data")
    ModScanner._merge_data_workshop_duplicates(api._assets)
    api._asset_aliases = {alias: asset.id for asset in api._assets.values() for alias in asset.alternate_ids}
    result = api.call("apply_diagnostics_result", [state["id"]])
    assert result["ok"] == identical
    if identical:
        assert result["data"]["ordered_mod_ids"] == ["data-a", "c"]
        assert parse_launch_list(game / "used_mods.txt")[1] == ["a.pack", "c.pack"]
    else:
        assert result["error"]["message"] == "diagnostics.contextChanged"


@pytest.mark.parametrize("exit_code", [0, 1])
@pytest.mark.parametrize("verdict", ["ok", "crash"])
def test_exit_before_first_scan_allows_manual_verdict(tmp_path, exit_code, verdict):
    probe = GameProbe(GamePaths(game_path=str(tmp_path)), tmp_path / "user", timeout=0.1, poll=0.001)
    phases = []
    with (
        patch("backend.mod_diagnostics.launcher.is_game_running", return_value=False),
        patch("backend.mod_diagnostics.launcher.launch_game", return_value={"pid": 12}),
        patch("backend.mod_diagnostics.launcher._matching_game_process_ids", return_value=[]),
        patch("backend.mod_diagnostics.launcher.launched_game_exit_code", return_value=exit_code),
        patch("backend.mod_diagnostics.launcher.terminate_game_processes"),
        patch("backend.mod_diagnostics.find_crash_dialog", return_value=None),
    ):
        result = probe.run("trial.txt", threading.Event(), lambda: verdict, phases.append)
    assert phases == ["confirm_exit"]
    assert result["verdict"] == verdict and result["evidence"] == "user"


@pytest.mark.parametrize("pid,time_delta,flags,expected", [
    (12, 0, 3, "crash"), (11, 0, 3, "ok"), (12, -120, 3, "ok"), (12, 0, 0, "ok"),
])
def test_dump_must_belong_to_current_process_before_it_overrides_confirmation(
    tmp_path, pid, time_delta, flags, expected,
):
    user = tmp_path / "user"
    probe = GameProbe(GamePaths(game_path=str(tmp_path)), user, timeout=0.1, poll=0.001)

    def launch(*_args, **_kwargs):
        write_minidump(user / "crash_report" / "delayed.mdmp", pid,
                      created_at=int(time.time()) + time_delta, flags=flags)
        return {"pid": 12}

    with (
        patch("backend.mod_diagnostics.launcher.is_game_running", return_value=False),
        patch("backend.mod_diagnostics.launcher.launch_game", side_effect=launch),
        patch("backend.mod_diagnostics.launcher._matching_game_process_ids", return_value=[12]),
        patch("backend.mod_diagnostics.launcher.launched_game_exit_code", return_value=None),
        patch("backend.mod_diagnostics.launcher.terminate_game_processes"),
        patch("backend.mod_diagnostics.find_crash_dialog", return_value=None),
    ):
        result = probe.run("trial.txt", threading.Event(), lambda: "ok", lambda _phase: None)
    assert result["verdict"] == expected
    assert result["evidence"] == ("dump" if expected == "crash" else "user")


def test_unknown_dump_requires_manual_confirmation(tmp_path):
    user = tmp_path / "user"
    probe = GameProbe(GamePaths(game_path=str(tmp_path)), user, timeout=0.1, poll=0.001)
    phases = []

    def launch(*_args, **_kwargs):
        write_minidump(user / "crash_report" / "unknown.mdmp", 12, flags=0)
        return {"pid": 12}

    with (
        patch("backend.mod_diagnostics.launcher.is_game_running", return_value=False),
        patch("backend.mod_diagnostics.launcher.launch_game", side_effect=launch),
        patch("backend.mod_diagnostics.launcher._matching_game_process_ids", return_value=[]),
        patch("backend.mod_diagnostics.launcher.launched_game_exit_code", return_value=None),
        patch("backend.mod_diagnostics.launcher.terminate_game_processes"),
        patch("backend.mod_diagnostics.find_crash_dialog", return_value=None),
    ):
        result = probe.run("trial.txt", threading.Event(), lambda: "crash", phases.append)
    assert phases == ["confirm_dump"]
    assert result["verdict"] == "crash" and result["evidence"] == "user"
    assert len(result["uncertain_dumps"]) == 1


def test_misc_info_flags_control_process_identity_and_invalid_streams_are_ignored(tmp_path):
    dump = tmp_path / "fixture.mdmp"
    write_minidump(dump, 12, created_at=100, flags=3)
    assert read_dump_process(dump) == {"pid": 12, "created_at": 100}
    assert dump_belongs_to_launch({"process": read_dump_process(dump)}, {12}, 100.9)
    assert not dump_belongs_to_launch({"process": read_dump_process(dump)}, {12}, 101)
    write_minidump(dump, 12, created_at=100, flags=1)
    assert read_dump_process(dump) == {"pid": 12}
    write_minidump(dump, 12, flags=2)
    assert read_dump_process(dump) == {}
    dump.write_bytes(b"invalid header")
    assert read_dump_process(dump) == {} and read_dump_exception(dump) == {}


def test_start_freezes_unqueried_normal_launch_before_trials_overwrite_its_log(diagnostic_api):
    api, game = diagnostic_api
    user = game.parent / "user"
    (user / "logs").mkdir(parents=True)
    record = launch_record("warhammer3", str(game), user, {"pack_names": ["a.pack"]},
                           time.time(), capture_evidence(user))
    (user / "logs" / "modified.log").write_text("Mod: a.pack\n")
    api.diagnostics.launches.save({"version": 1, "games": {"warhammer3": record}})

    def trial(*_args):
        (user / "logs" / "modified.log").write_text("Mod: b.pack\n")
        return {"verdict": "ok"}

    with patch("backend.diagnostics_api.GameProbe.run", side_effect=trial):
        assert api.call("start_mod_diagnostics", [list("abc")])["ok"]
        api.diagnostics.session._thread.join(5)
    stored = api.diagnostics.launches.load()["games"]["warhammer3"]
    assert stored["ended_at"] >= stored["started_at"]
    assert stored["final_diagnosis"]["loaded"] == ["a.pack"]
    assert api.diagnostics.diagnosis()["loaded"] == ["a.pack"]


def test_delayed_normal_crash_is_persisted_and_running_launch_is_not_sealed(diagnostic_api):
    api, game = diagnostic_api
    user = game.parent / "user"
    (user / "logs").mkdir(parents=True)
    record = launch_record("warhammer3", str(game), user, {"pack_names": []},
                           time.time(), capture_evidence(user))
    record["process_ids"] = [12]
    api.diagnostics.launches.save({"version": 1, "games": {"warhammer3": record}})
    (user / "logs" / "modified.log").write_text("finished loading\n")
    assert not api.diagnostics.diagnosis()["crashed"]
    write_minidump(user / "crash_report" / "delayed.mdmp", 12, created_at=int(record["started_at"]))
    assert api.diagnostics.diagnosis()["crashed"]
    stored = api.diagnostics.launches.load()["games"]["warhammer3"]
    assert stored["final_diagnosis"]["crashed"]
    with patch.object(api, "detect_game_running", return_value=True):
        api.diagnostics.before_launch()
    assert not api.diagnostics.launches.load()["games"]["warhammer3"].get("evidence_sealed")


def test_inconsistent_final_retest_never_allows_apply(tmp_path):
    session = DiagnosticSession(tmp_path / "sessions.json")
    final_count = 0

    def trial(ids, _cancel, _manual, _progress, kind):
        nonlocal final_count
        if kind == "final":
            final_count += 1
            return {"verdict": "ok" if final_count == 1 else "crash"}
        return {"verdict": "crash" if "b" in ids else "ok"}

    session.start({"game_id": "warhammer3", "mode": "bisect", "original_ids": list("abc")},
                  [[item] for item in "abc"], trial)
    session._thread.join(5)
    state = session.status()
    assert final_count == 2 and state["status"] == "unstable" and not state["can_apply"]
