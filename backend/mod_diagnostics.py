"""Isolated launch trials, dependency-aware reduction, and scoped run history."""
from __future__ import annotations

import ctypes
import os
import re
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from . import launcher
from .crash_diagnostics import capture_evidence, collect_crash_dumps, dump_belongs_to_launch, file_signature, pack_basename
from .json_store import AtomicJsonStore
from .models import ModAsset


class TrialStopped(Exception):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


def dependency_groups(assets: dict[str, ModAsset], ordered_ids: list[str]) -> list[list[str]]:
    """Keep dependencies together so reduction cannot manufacture missing-dependency crashes."""
    by_pack = {assets[mod_id].pack_name.casefold(): mod_id for mod_id in ordered_ids}
    by_workshop: dict[str, list[str]] = {}
    for mod_id in ordered_ids:
        asset = assets[mod_id]
        if asset.workshop_id:
            by_workshop.setdefault(asset.workshop_id, []).append(mod_id)
    parents = dict.fromkeys(ordered_ids)

    def root(mod_id: str) -> str:
        while parents[mod_id] is not None:
            mod_id = parents[mod_id]
        return mod_id

    for mod_id in ordered_ids:
        asset = assets[mod_id]
        dependencies = [by_pack.get(pack_basename(name).casefold()) for name in asset.dependency_packs]
        for item in asset.required_workshop_items:
            dependencies.extend(by_workshop.get(str(item.get("workshop_id") or ""), []))
        for dependency in dependencies:
            if dependency in parents and root(mod_id) != root(dependency):
                parents[root(mod_id)] = root(dependency)
    groups: dict[str, list[str]] = {}
    for mod_id in ordered_ids:
        groups.setdefault(root(mod_id), []).append(mod_id)
    return list(groups.values())


def fixed_movie_dependencies(
    assets: dict[str, ModAsset], ordered_ids: list[str], movies: list[ModAsset],
) -> set[str]:
    """Keep the dependency closure of every actually loaded Movie in the background."""
    by_pack = {assets[item].pack_name.casefold(): assets[item] for item in ordered_ids}
    by_pack.update({movie.pack_name.casefold(): movie for movie in movies})
    by_workshop: dict[str, list[ModAsset]] = {}
    for asset in [*[assets[item] for item in ordered_ids], *movies]:
        if asset.workshop_id:
            by_workshop.setdefault(asset.workshop_id, []).append(asset)
    selected = set(ordered_ids)
    fixed: set[str] = set()
    pending = list(movies)
    visited: set[str] = set()
    while pending:
        asset = pending.pop()
        key = str(Path(asset.path).resolve(strict=False)).casefold()
        if key in visited:
            continue
        visited.add(key)
        if asset.id in selected:
            fixed.add(asset.id)
        dependencies = [by_pack.get(pack_basename(name).casefold()) for name in asset.dependency_packs]
        for item in asset.required_workshop_items:
            dependencies.extend(by_workshop.get(str(item.get("workshop_id") or ""), [None]))
        for dependency in dependencies:
            if dependency is None:
                if "missing_dependency" not in asset.ignored_warning_codes:
                    raise ValueError("diagnostics.dependenciesMissing")
                continue
            if dependency.id in selected:
                fixed.add(dependency.id)
            pending.append(dependency)
    return fixed


def reduce_failure(candidates: list[int], test: Callable[[list[int], str], str]) -> list[int]:
    """Delta debugging checks both subsets and complements, including combination failures."""
    current = list(candidates)
    partitions = 2
    while len(current) > 1:
        chunks = [current[index::partitions] for index in range(partitions)]
        attempts = chunks + [[item for item in current if item not in chunk] for chunk in chunks]
        seen: set[tuple[int, ...]] = set()
        for subset in attempts:
            key = tuple(subset)
            if not subset or key in seen or len(subset) == len(current):
                continue
            seen.add(key)
            if test(subset, "reduce") == "crash":
                current = subset
                partitions = max(2, partitions - 1)
                break
        else:
            if partitions >= len(current):
                break
            partitions = min(len(current), partitions * 2)
    return current


def find_crash_dialog(process_ids: set[int]) -> dict[str, Any] | None:
    """Only inspect windows owned by this trial's game processes."""
    if os.name != "nt" or not process_ids:
        return None
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)
    found = None

    def window_text(hwnd: int) -> str:
        length = min(user32.GetWindowTextLengthW(hwnd), 16_384)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    @callback_type
    def visit(hwnd: int, _parameter: int) -> bool:
        nonlocal found
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in process_ids or not user32.IsWindowVisible(hwnd):
            return True
        title = window_text(hwnd)
        if not re.search(r"crash report|fatal error|application error|崩溃|应用程序错误", title, re.I):
            return True
        parts = []

        @callback_type
        def child_text(child: int, _value: int) -> bool:
            text = window_text(child)
            if text and len(parts) < 64:
                parts.append(text)
            return True

        user32.EnumChildWindows(hwnd, child_text, 0)
        found = {"title": title, "body": "\n".join(parts), "pid": pid.value}
        return False

    user32.EnumWindows(visit, 0)
    return found


class GameProbe:
    """A fresh dump/dialog proves a failed trial; menu arrival is confirmed by the user.

    Process survival, unrelated log timestamps, and timeouts are never success.
    Only processes observed after this probe's launch are eligible for cleanup.
    """

    def __init__(self, paths, user_dir: Path, *, launch_root: str = "", timeout: float = 600, poll: float = 0.5):
        self.paths = paths
        self.launch_root = launch_root or paths.game_path
        self.user_dir = user_dir
        self.timeout = timeout
        self.poll = poll

    def run(
        self, list_path: str, cancel: threading.Event,
        manual: Callable[[], str], progress: Callable[[str], None],
    ) -> dict[str, Any]:
        game = self.paths.game_definition
        executable = self.paths.executable_path
        if launcher.is_game_running(executable, process_name=game.process_name):
            return {"verdict": "inconclusive", "evidence": "already_running"}
        if cancel.is_set():
            raise TrialStopped("cancelled")
        before = capture_evidence(self.user_dir)
        started_at = time.time()
        started = time.monotonic()
        owned: set[int] = set()
        seen_process = False
        last_progress = ""
        result = {"verdict": "inconclusive", "evidence": "timeout"}
        launched_pid = None
        try:
            launched = launcher.launch_game(
                self.launch_root, list_path, executable_name=game.executable_name,
                process_name=game.process_name, app_id=game.app_id,
            )
            launched_pid = int(launched["pid"])
            owned.add(launched_pid)
            while time.monotonic() - started < self.timeout:
                if cancel.is_set():
                    raise TrialStopped("cancelled")
                pids = set(launcher._matching_game_process_ids(executable, process_name=game.process_name))
                owned.update(pids)
                seen_process |= bool(pids)
                dumps = collect_crash_dumps(
                    self.user_dir / "crash_report", started_at, before["dumps_before"],
                )
                uncertain_dumps = [dump for dump in dumps if not dump.get("process", {}).get("pid")]
                dumps = [dump for dump in dumps if dump_belongs_to_launch(dump, owned, started_at)]
                dialog = find_crash_dialog(pids)
                if dumps or dialog:
                    result = {"verdict": "crash", "evidence": "dump" if dumps else "dialog",
                              "dumps": dumps, "dialog": dialog}
                    break
                signature = file_signature(self.user_dir / "logs" / "modified.log")
                advanced = bool(signature and signature != before["log_signature"])
                exited = launcher.launched_game_exit_code(launched_pid) is not None
                can_confirm = seen_process or exited or bool(uncertain_dumps)
                if (seen_process or exited) and not pids:
                    # A player closing the game is indistinguishable from a silent crash.
                    phase = "confirm_exit"
                elif uncertain_dumps:
                    phase = "confirm_dump"
                elif pids:
                    phase = "confirm_menu"
                else:
                    phase = "starting"
                if phase != last_progress:
                    progress(phase)
                    last_progress = phase
                verdict = manual()
                if verdict in {"ok", "crash"} and can_confirm:
                    result = {"verdict": verdict, "evidence": "user", "log_advanced": advanced,
                              "uncertain_dumps": uncertain_dumps}
                    break
                if not can_confirm and time.monotonic() - started >= 75:
                    result = {"verdict": "inconclusive", "evidence": "not_started"}
                    break
                cancel.wait(self.poll)
        finally:
            try:
                launcher.terminate_game_processes(owned, executable, process_name=game.process_name)
            finally:
                if launched_pid is not None:
                    launcher.forget_launched_game(launched_pid)
        result["seconds"] = round(time.monotonic() - started, 1)
        return result


class DiagnosticSession:
    """One worker owns the experiment; persisted snapshots never silently change playsets."""

    def __init__(self, path: Path):
        self._store = AtomicJsonStore(path, lambda: {"version": 1, "session": {}, "history": []})
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._manual = ""
        self._thread: threading.Thread | None = None
        self._data = self._store.load()
        if self._data.get("session", {}).get("running"):
            self._data["session"].update(running=False, status="interrupted", phase="finished", can_apply=False)
            if self._data["session"].get("id"):
                self._data.setdefault("history", []).insert(0, deepcopy(self._data["session"]))
                self._data["history"] = self._data["history"][:30]
            self._store.save(self._data)

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._data.get("session", {}).get("running"))

    def status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._data.get("session") or {"status": "idle", "running": False})

    def history(self, game_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy([run for run in self._data.get("history", []) if run["game_id"] == game_id])

    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._data["session"].update(changes)
            self._store.save(self._data)

    def start(
        self, context: dict[str, Any], groups: list[list[str]],
        trial: Callable[[list[str], threading.Event, Callable, Callable, str], dict],
        cleanup: Callable[[], None] = lambda: None,
    ) -> dict[str, Any]:
        with self._lock:
            if self.running:
                raise ValueError("diagnostics.running")
            self._cancel.clear()
            self._manual = ""
            self._data["session"] = {
                **deepcopy(context), "id": uuid.uuid4().hex, "started_at": time.time(),
                "running": True, "status": "running", "phase": "starting",
                "rounds": [], "excluded_ids": [], "suspect_ids": [], "result_ids": [],
                "can_apply": False, "group_count": len(groups),
            }
            self._store.save(self._data)
            self._thread = threading.Thread(
                target=self._work, args=(groups, trial, cleanup), name="mod-diagnostics", daemon=True,
            )
            self._thread.start()
            return self.status()

    def confirm(self, session_id: str, round_number: int, verdict: str) -> dict[str, Any]:
        with self._lock:
            state = self._data["session"]
            if (not self.running or state["id"] != session_id
                    or state.get("round_number") != round_number
                    or state.get("phase") not in {"confirm_menu", "confirm_exit", "confirm_dump"}
                    or verdict not in {"ok", "crash"} or self._manual):
                raise ValueError("diagnostics.staleTrial")
            self._manual = verdict
            state["phase"] = "finishing_trial"
            return self.status()

    def _take_manual(self) -> str:
        with self._lock:
            return self._manual

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        return self.status()

    def close(self) -> None:
        self._cancel.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=8)

    def _work(self, groups: list[list[str]], trial: Callable, cleanup: Callable) -> None:
        state = self.status()
        fixed = state.get("fixed_ids", [])
        original = state["original_ids"]
        observed: dict[tuple, str] = {}

        def test(indices: list[int], kind: str) -> str:
            if self._cancel.is_set():
                raise TrialStopped("cancelled")
            current = self.status()
            if len(current["rounds"]) >= 128:
                raise TrialStopped("round_limit")
            selected = set(fixed)
            selected.update(item for index in indices for item in groups[index])
            ids = [item for item in original if item in selected]
            with self._lock:
                self._manual = ""
                self._update(phase="preparing", current_ids=ids, test_kind=kind,
                             round_number=len(current["rounds"]) + 1)
            result = trial(ids, self._cancel, self._take_manual, lambda phase: self._update(phase=phase), kind)
            if self._cancel.is_set():
                raise TrialStopped("cancelled")
            rounds = self.status()["rounds"]
            rounds.append({"kind": kind, "mod_ids": ids, **result})
            self._update(rounds=rounds)
            verdict = result.get("verdict")
            if verdict not in {"ok", "crash"}:
                raise TrialStopped("inconclusive")
            # Final trials use the result's actual search directories; all other
            # trials retain the original Movie environment.
            key = (tuple(ids), "final" if kind == "final" else "original")
            if key in observed and observed[key] != verdict:
                raise TrialStopped("unstable")
            observed[key] = verdict
            return verdict

        try:
            remaining = list(range(len(groups)))
            baseline = test(remaining, "baseline")
            test(remaining, "baseline")
            if baseline == "ok":
                self._update(status="no_repro")
                return
            if test([], "background") != "ok":
                self._update(status="background_failure")
                return
            excluded: list[int] = []
            while remaining:
                minimal = reduce_failure(remaining, test)
                suspects = [item for index in minimal for item in groups[index]]
                self._update(suspect_ids=suspects)
                if test(minimal, "verify") != "crash":
                    self._update(status="unstable")
                    return
                rest = [index for index in remaining if index not in minimal]
                rest_ok = test(rest, "complement") == "ok"
                if state["mode"] == "bisect" and not rest_ok:
                    self._update(status="multiple")
                    return
                excluded.extend(minimal)
                excluded_ids = [item for index in excluded for item in groups[index]]
                self._update(excluded_ids=excluded_ids)
                if rest_ok:
                    # Validate the exact normal-launch search directories as well:
                    # removing the last MOD in an external directory can remove its
                    # automatically loaded Movie Packs from the final environment.
                    if test(rest, "final") != "ok" or test(rest, "final") != "ok":
                        self._update(status="unstable", can_apply=False)
                        return
                    self._update(
                        status="isolated" if state["mode"] == "bisect" else "success",
                        result_ids=[item for item in original if item not in set(excluded_ids)],
                        can_apply=True,
                    )
                    return
                remaining = rest
            self._update(status="background_failure")
        except TrialStopped as exc:
            self._update(status=exc.status, can_apply=False)
        except Exception as exc:
            self._update(status="error", detail=str(exc), can_apply=False)
        finally:
            try:
                cleanup()
            except Exception as exc:
                self._update(status="cleanup_failed", detail=str(exc), can_apply=False)
            with self._lock:
                self._update(running=False, phase="finished", finished_at=time.time())
                self._data.setdefault("history", []).insert(0, self.status())
                self._data["history"] = self._data["history"][:30]
                self._store.save(self._data)
