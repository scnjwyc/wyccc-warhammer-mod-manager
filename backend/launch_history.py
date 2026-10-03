"""Immutable launch lists, with transactional restoration of the current playset."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any


class LaunchHistoryService:
    def __init__(self, api):
        self.api = api
        self.repository = api.state_repository

    def _import_previous(self, paths) -> None:
        if self.repository.list_launch_records(paths.game_id, paths.game_path):
            return
        snapshot = self.api.diagnostics.last_launch_mods()
        if not snapshot.get("available") or snapshot.get("game_id") != paths.game_id:
            return
        with self.repository.transaction():
            if self.repository.list_launch_records(paths.game_id, paths.game_path):
                return
            record_id = uuid.uuid5(uuid.NAMESPACE_URL, f"wmm:{paths.game_id}:{paths.game_path}:{snapshot['started_at']}")
            self.repository.add_launch_record({
                "id": record_id.hex, "game_id": paths.game_id, "game_path": paths.game_path,
                "started_at": snapshot["started_at"], "mods": snapshot["mods"],
            })

    def remember(self, result: dict, before: dict) -> None:
        paths = before["paths"]
        if not paths.game_definition.uses_mod_list:
            return
        # Import the former single record before diagnostics replaces it.
        self._import_previous(paths)
        self.repository.add_launch_record({
            "game_id": paths.game_id, "game_path": paths.game_path, "started_at": before["at"],
            "mods": result["mod_snapshot"], "save_name": str((result.get("save") or {}).get("name") or ""),
            "playset_name": result.get("launch_playset_name", ""),
        })

    def list(self) -> dict[str, Any]:
        with self.api._context_lock:
            paths = self.api.settings_service.resolve_game_paths()
            self._import_previous(paths)
            return {"game_id": paths.game_id,
                    "items": self.repository.list_launch_records(paths.game_id, paths.game_path)}

    def _require(self, record_id: str, paths) -> dict[str, Any]:
        record = self.repository.get_launch_record(record_id, paths.game_id, paths.game_path)
        if not record:
            raise ValueError("launchHistory.notFound")
        return record

    def _resolve(self, reference: dict):
        assets = self.api._assets
        mod_id = str(reference.get("id") or "")
        selected = assets.get(self.api._asset_aliases.get(mod_id, mod_id))
        pack_name = str(reference.get("pack_name") or "").casefold()
        if selected and selected.pack_name.casefold() == pack_name:
            candidates = [selected]
        else:
            candidates = [asset for asset in assets.values() if asset.pack_name.casefold() == pack_name]
            workshop_id = reference.get("workshop_id")
            if workshop_id:
                candidates = [asset for asset in candidates if asset.workshop_id == workshop_id]
            source = reference.get("source")
            preferred = [asset for asset in candidates
                         if not source or source in (asset.sources or [asset.source])]
            if preferred:
                candidates = preferred
        candidates = [asset for asset in candidates if Path(asset.path).is_file()]
        return candidates[0] if len(candidates) == 1 else None

    def get(self, record_id: str) -> dict[str, Any]:
        with self.api._context_lock:
            paths = self.api.settings_service.resolve_game_paths()
            record = self._require(record_id, paths)
            for mod in record["mods"]:
                asset = self._resolve(mod)
                mod["effective_name"] = mod.get("effective_name") or (asset.effective_name if asset else "")
                mod["missing"] = asset is None
            return {**record, "available": True}

    def load(self, record_id: str, expected_token: str = "") -> dict[str, Any]:
        with self.api._file_operation_lock, self.api._context_lock, self.api._order_lock:
            self.api.diagnostics.require_idle()
            if self.api.detect_game_running():
                raise ValueError("diagnostics.exitGame")
            paths = self.api.settings_service.resolve_game_paths()
            record = self._require(record_id, paths)
            present, intent, missing = [], [], []
            for index, mod in enumerate(record["mods"]):
                asset = self._resolve(mod)
                if asset:
                    present.append(asset.id)
                    intent.append(asset.id)
                else:
                    missing.append(mod)
                    intent.append(mod.get("id") or f"history-missing:{record_id}:{index}")
            previous_token = self.api._last_order_token
            try:
                with self.api.load_order.rollback_on_error(paths.game_path), self.repository.transaction():
                    saved = self.api._save_load_order_locked(present, expected_token)
                    # Replace exactly, including zero-MOD records and historical missing items.
                    self.repository.update_current_playset(intent, paths.game_id)
                    return {**self.api._current_playset_payload(), **saved, "game_id": paths.game_id,
                            "ordered_mod_ids": present, "missing_mod_ids": [item for item in intent if item not in present],
                            "record_id": record_id, "missing_mods": missing}
            except Exception:
                self.api._last_order_token = previous_token
                raise
