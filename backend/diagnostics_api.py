"""Bind diagnostics to the existing manager without using its playset-saving launch path."""
from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .constants import INTERNAL_RUNTIME_PACK_NAMES
from .crash_diagnostics import (
    capture_evidence, diagnose_launch, file_signature, game_user_directory, launch_record,
)
from .json_store import AtomicJsonStore
from .mod_diagnostics import DiagnosticSession, GameProbe, TrialStopped, dependency_groups
from .scanner import read_pack_type


class ModDiagnosticsService:
    def __init__(self, api):
        self.api = api
        self.operation_lock = threading.RLock()
        self._busy_operations = 0
        self.session = DiagnosticSession(api.data_dir / "diagnostics" / "sessions.json")
        self.launches = AtomicJsonStore(
            api.data_dir / "diagnostics" / "launches.json", lambda: {"version": 1, "games": {}},
        )

    @property
    def running(self) -> bool:
        return self.session.running

    def require_idle(self) -> None:
        if self.running:
            raise ValueError("diagnostics.running")

    @contextmanager
    def rpc_scope(self, method: str):
        reads = {
            "get_mod_diagnostics", "confirm_diagnostic_trial", "cancel_mod_diagnostics",
            "get_crash_diagnosis", "dismiss_crash_diagnosis", "get_diagnostics_history",
            "get_runtime_status", "get_mod_thumbnails", "get_mod_preview", "exit_app",
        }
        counted = method not in reads and method != "start_mod_diagnostics"
        with self.operation_lock:
            if method not in reads:
                self.require_idle()
            if counted:
                self._busy_operations += 1
        try:
            yield
        finally:
            if counted:
                with self.operation_lock:
                    self._busy_operations -= 1

    def before_launch(self) -> dict[str, Any]:
        paths = self.api.settings_service.resolve_game_paths()
        directory = game_user_directory(paths.game_definition.save_directory_name)
        return {"paths": paths, "directory": directory, "at": time.time(),
                "evidence": capture_evidence(directory)}

    def remember_launch(self, result: dict, before: dict) -> None:
        paths = before["paths"]
        if not paths.game_definition.uses_mod_list:
            return
        record = launch_record(paths.game_id, paths.game_path, before["directory"],
                               result["launch_plan"], before["at"], before["evidence"])
        with self.operation_lock:
            payload = self.launches.load()
            payload.setdefault("games", {})[paths.game_id] = record
            self.launches.save(payload)

    def diagnosis(self) -> dict[str, Any]:
        paths = self.api.settings_service.resolve_game_paths()
        record = self.launches.load().get("games", {}).get(paths.game_id, {})
        if record.get("game_path") != paths.game_path:
            record = {}
        result = diagnose_launch(record, running=self.api.detect_game_running() or self.running)
        by_pack = {asset.pack_name.casefold(): asset for asset in self.api._assets.values()}
        for row in result["pending"]:
            asset = by_pack.get(row["pack_name"].casefold())
            if asset:
                row.update(mod_id=asset.id, name=asset.effective_name)
        return result

    def dismiss(self) -> dict[str, bool]:
        with self.operation_lock:
            payload = self.launches.load()
            record = payload.get("games", {}).get(self.api._active_game().id)
            if record:
                record["acknowledged"] = True
                self.launches.save(payload)
        return {"dismissed": True}

    @staticmethod
    def _movie_snapshot(directories: list[str]) -> dict[str, list[int]]:
        movies = {}
        for directory in directories:
            for path in Path(directory).glob("*.pack"):
                if read_pack_type(path) == "movie":
                    movies[str(path)] = file_signature(path)
        return movies

    def _unchanged(self, context: dict[str, Any]) -> bool:
        paths = self.api.settings_service.resolve_game_paths()
        return (
            paths.game_id == context["game_id"] and paths.game_path == context["game_path"]
            and self.api.state_repository.get_current_playset_id(paths.game_id) == context["playset_id"]
            and all(file_signature(Path(path)) == signature for path, signature in context["files"].items())
            and self._movie_snapshot(context["search_directories"]) == context["movies"]
        )

    def start(self, ordered_ids: list[str], mode: str = "bisect") -> dict[str, Any]:
        with self.api._file_operation_lock, self.operation_lock:
            self.require_idle()
            if self._busy_operations:
                raise ValueError("diagnostics.busy")
            if mode not in {"bisect", "maxload"}:
                raise ValueError("diagnostics.invalidMode")
            self.api._require_pack_mod_format("MOD diagnostics")
            paths = self.api.settings_service.resolve_game_paths()
            if not Path(paths.executable_path).is_file() or self.api.detect_game_running():
                raise ValueError("diagnostics.exitGame")
            ids = self.api._canonicalize_mod_ids(ordered_ids)
            assets = deepcopy(self.api._assets)
            if not ids or any(mod_id not in assets or not Path(assets[mod_id].path).is_file() for mod_id in ids):
                raise ValueError("diagnostics.missingMods")
            if any(assets[mod_id].pack_name.casefold() in INTERNAL_RUNTIME_PACK_NAMES for mod_id in ids):
                raise ValueError("diagnostics.runtimePack")
            names = [assets[mod_id].pack_name.casefold() for mod_id in ids]
            if len(names) != len(set(names)):
                raise ValueError("diagnostics.duplicatePacks")
            self.api.scanner.refresh_missing_dependency_warnings(assets.values(), ids)
            # Ignoring a warning leaves its raw dependency metadata intact.
            if any(assets[mod_id].missing_dependencies or any(
                warning.get("code") == "missing_dependency" for warning in assets[mod_id].warnings
            ) for mod_id in ids if "missing_dependency" not in assets[mod_id].ignored_warning_codes):
                raise ValueError("diagnostics.dependenciesMissing")
            mapping = self.api.launch_path_aliases.prepare(paths.game_path, paths.workshop_path)
            list_name = f"wyccc_diagnostics_{uuid.uuid4().hex}.txt"
            full_plan = self.api.load_order.build_plan(
                paths.game_path, paths.data_path, assets, ids,
                target_name=list_name, path_mapper=mapping.map_path,
            )
            search_directories = list(dict.fromkeys([
                paths.data_path, *[assets[mod_id].directory for mod_id in ids],
            ]))
            movies = self._movie_snapshot(search_directories)
            fixed_ids = set(mod_id for mod_id in ids if read_pack_type(Path(assets[mod_id].path)) == "movie")
            groups = []
            for group in dependency_groups(assets, ids):
                if fixed_ids.intersection(group):
                    fixed_ids.update(group)
                else:
                    groups.append(group)
            if not groups:
                raise ValueError("diagnostics.noCandidates")
            files = {assets[mod_id].path: file_signature(Path(assets[mod_id].path)) for mod_id in ids}
            for path in [Path(paths.executable_path), Path(paths.data_path) / "db.pack",
                         Path(paths.data_path) / "database.pack", Path(paths.data_path) / "manifest.txt"]:
                files[str(path)] = file_signature(path)
            context = {
                "game_id": paths.game_id, "game_path": paths.game_path,
                "playset_id": self.api.state_repository.get_current_playset_id(paths.game_id),
                "mode": mode, "original_ids": ids, "fixed_ids": [item for item in ids if item in fixed_ids],
                "files": files, "movies": movies, "search_directories": search_directories,
                "list_path": full_plan.target_path,
                "mods": {mod_id: {"name": assets[mod_id].effective_name, "pack_name": assets[mod_id].pack_name}
                         for mod_id in ids},
            }
            probe = GameProbe(paths, game_user_directory(paths.game_definition.save_directory_name),
                              launch_root=mapping.map_path(paths.game_path))

            def trial(selected_ids, cancel, manual, progress, kind):
                if not self._unchanged(context):
                    raise TrialStopped("context_changed")
                if cancel.is_set():
                    raise TrialStopped("cancelled")
                plan = self.api.load_order.build_plan(
                    paths.game_path, paths.data_path, assets, selected_ids,
                    target_name=list_name, path_mapper=mapping.map_path,
                )
                # Keep every original search directory: auto-loaded Movie Packs must
                # be the same in the baseline, subsets, and the empty background trial.
                directories = plan.working_directories if kind == "final" else full_plan.working_directories
                lines = [f'add_working_directory "{directory}";' for directory in directories]
                lines.extend(f'mod "{name}";' for name in plan.pack_names)
                content = "\r\n".join(lines) + "\r\n"
                self.api.load_order._atomic_write(Path(plan.target_path), content,
                                                  encoding=paths.game_definition.mod_list_encoding)
                result = probe.run(plan.target_path, cancel, manual, progress)
                if not self._unchanged(context):
                    raise TrialStopped("context_changed")
                return result

            return self.session.start(
                context, groups, trial,
                cleanup=lambda: Path(full_plan.target_path).unlink(missing_ok=True),
            )

    def status(self) -> dict[str, Any]:
        state = self.session.status()
        if state.get("game_id") not in {None, self.api._active_game().id}:
            return {"status": "idle", "running": False}
        return state

    def history(self) -> list[dict[str, Any]]:
        return self.session.history(self.api._active_game().id)

    def apply(self, run_id: str, restore_original: bool = False) -> dict[str, Any]:
        with self.api._file_operation_lock, self.operation_lock:
            self.require_idle()
            if self._busy_operations > 1:
                raise ValueError("diagnostics.busy")
            if self.api.detect_game_running():
                raise ValueError("diagnostics.exitGame")
            run = next((row for row in self.history() if row["id"] == run_id), None)
            if not run or (not restore_original and not run.get("can_apply")):
                raise ValueError("diagnostics.noVerifiedResult")
            if not self._unchanged(run):
                raise ValueError("diagnostics.contextChanged")
            selected = run["original_ids"] if restore_original else run["result_ids"]
            if any(mod_id not in self.api._assets for mod_id in selected):
                raise ValueError("diagnostics.missingMods")
            return self.api._update_playset(run["playset_id"], selected)
