from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .game_data_settings import (
    normalize_single_entity_unit_mode,
    normalize_unit_scale_multiplier,
)
from .json_store import AtomicJsonStore
from .models import ModAsset
from .start_options import (
    GAME_DATA_PATCH_NAME,
    build_game_data_patch,
)


GAME_DATA_PATCH_MANIFEST_NAME = "!!!!wyccc_game_data_patch.json"
FINGERPRINT_SCHEMA_VERSION = 1
GAME_DATA_BUILDER_VERSION = 5


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalized_settings(settings: Mapping[str, Any]) -> dict[str, int | bool | str]:
    return {
        "unit_model_multiplier": normalize_unit_scale_multiplier(
            settings.get("unit_model_multiplier", 1)
        ),
        "single_entity_unit_mode": normalize_single_entity_unit_mode(
            settings.get("single_entity_unit_mode", "scale")
        ),
        "scale_lord_hero_health": _coerce_bool(
            settings.get("scale_lord_hero_health", False)
        ),
        "disable_unit_friendly_fire": _coerce_bool(
            settings.get("disable_unit_friendly_fire", False)
        ),
        "disable_spell_friendly_fire": _coerce_bool(
            settings.get("disable_spell_friendly_fire", False)
        ),
    }


def game_data_settings_requested(settings: Mapping[str, Any]) -> bool:
    normalized = _normalized_settings(settings)
    return (
        not math.isclose(
            float(normalized["unit_model_multiplier"]),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or bool(normalized["disable_unit_friendly_fire"])
        or bool(normalized["disable_spell_friendly_fire"])
    )


def _file_signature(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=False)
    signature: dict[str, Any] = {"path": str(resolved)}
    try:
        stat = resolved.stat()
    except OSError:
        signature["missing"] = True
        return signature
    if not resolved.is_file():
        signature["missing"] = True
        return signature
    signature.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return signature


def build_game_data_inputs(
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
    subscription_state: Mapping[str, bool],
) -> dict[str, Any]:
    ordered_ids = [str(mod_id) for mod_id in active_ids]
    sources: list[dict[str, Any]] = []
    for mod_id in ordered_ids:
        asset = assets.get(mod_id)
        if asset is None:
            sources.append({"id": mod_id, "missing_asset": True})
            continue
        sources.append(
            {
                "id": mod_id,
                "pack_name": str(asset.pack_name),
                "source": str(asset.source),
                "workshop_id": str(asset.workshop_id),
                "file": _file_signature(Path(asset.path)),
            }
        )
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "builder_version": GAME_DATA_BUILDER_VERSION,
        "playset_id": str(playset_id),
        "active_ids": ordered_ids,
        "settings": _normalized_settings(settings),
        "subscription_state": {
            str(workshop_id): bool(subscribed)
            for workshop_id, subscribed in sorted(
                subscription_state.items(),
                key=lambda item: str(item[0]),
            )
        },
        "sources": sources,
        "db_pack": _file_signature(Path(data_path) / "db.pack"),
    }


def fingerprint_game_data_inputs(inputs: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        inputs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def classify_input_changes(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
) -> list[str]:
    if not previous:
        return ["initial"]
    groups = (
        ("schema", "fingerprint_schema_version"),
        ("builder", "builder_version"),
        ("settings", "settings"),
        ("playset", "playset_id"),
        ("order", "active_ids"),
        ("subscription", "subscription_state"),
        ("sources", "sources"),
        ("db_pack", "db_pack"),
    )
    return [label for label, key in groups if previous.get(key) != current.get(key)]


def _manifest_store(output_dir: Path) -> AtomicJsonStore:
    return AtomicJsonStore(
        Path(output_dir) / GAME_DATA_PATCH_MANIFEST_NAME,
        lambda: {},
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _output_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": GAME_DATA_PATCH_NAME,
        "size": stat.st_size,
        "sha256": _sha256_file(path),
    }


def _manifest_output_is_valid(manifest: Mapping[str, Any], output_dir: Path) -> bool:
    patch_path = Path(output_dir) / GAME_DATA_PATCH_NAME
    if manifest.get("build_status") == "zero_modification":
        return not patch_path.exists() and manifest.get("output") is None
    if manifest.get("build_status") != "generated":
        return False
    output = manifest.get("output")
    if not isinstance(output, Mapping) or output.get("name") != GAME_DATA_PATCH_NAME:
        return False
    try:
        stat = patch_path.stat()
        if not patch_path.is_file() or stat.st_size != int(output.get("size", -1)):
            return False
        return _sha256_file(patch_path) == str(output.get("sha256", ""))
    except (OSError, TypeError, ValueError):
        return False


def _result_from_manifest(
    manifest: Mapping[str, Any],
    output_dir: Path,
    status: str,
    changed_inputs: Sequence[str] = (),
) -> dict[str, Any]:
    stored_result = manifest.get("result")
    result = stored_result if isinstance(stored_result, Mapping) else {}
    path = ""
    if manifest.get("build_status") == "generated":
        path = str((Path(output_dir) / GAME_DATA_PATCH_NAME).resolve(strict=False))
    game_data = result.get("game_data")
    return {
        "status": status,
        "path": path,
        "fingerprint": str(manifest.get("fingerprint", "")),
        "changed_inputs": list(changed_inputs),
        "entry_count": int(result.get("entry_count", 0)),
        "options": list(result.get("options", [])),
        "game_data": dict(game_data) if isinstance(game_data, Mapping) else {},
    }


def load_manifest_subscription_state(output_dir: Path) -> dict[str, bool] | None:
    manifest = _manifest_store(Path(output_dir)).load()
    inputs = manifest.get("inputs")
    if not isinstance(inputs, Mapping):
        return None
    state = inputs.get("subscription_state")
    if not isinstance(state, Mapping):
        return None
    return {str(workshop_id): bool(value) for workshop_id, value in state.items()}


def ensure_game_data_patch(
    output_dir: Path,
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
    subscription_state: Mapping[str, bool],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    inputs = build_game_data_inputs(
        data_path,
        assets,
        active_ids,
        playset_id,
        settings,
        subscription_state,
    )
    fingerprint = fingerprint_game_data_inputs(inputs)
    store = _manifest_store(output_dir)
    previous = store.load()
    changed_inputs = classify_input_changes(
        previous.get("inputs", {}) if isinstance(previous.get("inputs"), Mapping) else {},
        inputs,
    )

    if previous.get("fingerprint") == fingerprint:
        if _manifest_output_is_valid(previous, output_dir):
            terminal_status = (
                "zero_modification"
                if previous.get("build_status") == "zero_modification"
                else "reused"
            )
            return _result_from_manifest(previous, output_dir, terminal_status)
        if "output" not in changed_inputs:
            changed_inputs.append("output")

    patch_path = output_dir / GAME_DATA_PATCH_NAME
    if game_data_settings_requested(settings):
        built = build_game_data_patch(
            output_dir,
            str(data_path),
            dict(assets),
            list(active_ids),
            dict(settings),
            subscribed_workshop_ids=[
                workshop_id
                for workshop_id, subscribed in subscription_state.items()
                if subscribed
            ],
        )
    else:
        patch_path.unlink(missing_ok=True)
        built = {"path": "", "options": [], "entry_count": 0, "game_data": {}}

    entry_count = int(built.get("entry_count", 0))
    generated = bool(built.get("path")) and entry_count > 0
    if generated:
        returned_path = Path(str(built["path"])).resolve(strict=False)
        if returned_path != patch_path.resolve(strict=False) or not patch_path.is_file():
            raise ValueError("游戏数据修改补丁生成结果无效")
        build_status = "generated"
        output = _output_record(patch_path)
    else:
        patch_path.unlink(missing_ok=True)
        build_status = "zero_modification"
        output = None

    game_data = built.get("game_data")
    result_payload = {
        "entry_count": entry_count if generated else 0,
        "options": list(built.get("options", [])),
        "game_data": dict(game_data) if isinstance(game_data, Mapping) else {},
    }
    manifest = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "builder_version": GAME_DATA_BUILDER_VERSION,
        "fingerprint": fingerprint,
        "inputs": inputs,
        "generated_at_ns": time.time_ns(),
        "build_status": build_status,
        "output": output,
        "result": result_payload,
    }
    store.save(manifest)
    return _result_from_manifest(
        manifest,
        output_dir,
        build_status,
        changed_inputs,
    )
