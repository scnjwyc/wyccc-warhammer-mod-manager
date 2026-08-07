from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .json_store import AtomicJsonStore
from .models import ModAsset
from .start_options import (
    UNIT_DATA_PATCH_NAME,
    build_unit_data_patch,
    collect_game_data_source_snapshot,
)
from .unit_data import _sanitize_edits


UNIT_DATA_PATCH_MANIFEST_NAME = "!!!!wyccc_unit_data_patch.json"
UNIT_DATA_EDITS_NAME = "unit_data_edits.json"
FINGERPRINT_SCHEMA_VERSION = 1
UNIT_DATA_BUILDER_VERSION = 1


def _edits_store(output_dir: Path) -> AtomicJsonStore:
    return AtomicJsonStore(
        Path(output_dir) / UNIT_DATA_EDITS_NAME,
        lambda: {},
    )


def _manifest_store(output_dir: Path) -> AtomicJsonStore:
    return AtomicJsonStore(
        Path(output_dir) / UNIT_DATA_PATCH_MANIFEST_NAME,
        lambda: {},
    )


def load_unit_data_edits(output_dir: str | Path) -> dict[str, dict[str, Any]]:
    stored = _edits_store(Path(output_dir)).load()
    return _sanitize_edits(stored if isinstance(stored, Mapping) else {})


def save_unit_data_edits(
    output_dir: str | Path,
    edits: Mapping[str, Any],
) -> dict[str, Any]:
    sanitized = _sanitize_edits(edits)
    _edits_store(Path(output_dir)).save(
        {key: dict(fields) for key, fields in sorted(sanitized.items())}
    )
    return {
        "edited_units": len(sanitized),
        "disabled_units": sum(
            1
            for fields in sanitized.values()
            if str(fields.get("enabled")).strip().casefold() in {"0", "false", "off"}
        ),
    }


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


def build_unit_data_inputs(
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
    edits: Mapping[str, Any],
    source_snapshot: Any | None = None,
) -> dict[str, Any]:
    snapshot = source_snapshot
    if snapshot is None:
        snapshot = collect_game_data_source_snapshot(data_path, assets, active_ids)
    sources = [
        {
            "role": entry.spec.role,
            "pack_name": entry.spec.path.name,
            "source": (
                str(entry.spec.asset.source)
                if entry.spec.asset is not None
                else entry.spec.role
            ),
            "workshop_id": (
                str(entry.spec.asset.workshop_id)
                if entry.spec.asset is not None
                else ""
            ),
            "file": {
                "path": str(entry.spec.path),
                "size": entry.size,
                "mtime_ns": entry.mtime_ns,
                "target_db_sha256": entry.content_sha256,
            },
        }
        for entry in snapshot.entries
    ]
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "builder_version": UNIT_DATA_BUILDER_VERSION,
        "playset_id": str(playset_id),
        "active_ids": [str(mod_id) for mod_id in active_ids],
        "settings": {
            "unit_model_multiplier": int(
                float(settings.get("unit_model_multiplier", 1) or 1)
            ),
            "single_entity_unit_mode": str(
                settings.get("single_entity_unit_mode", "scale") or "scale"
            ),
            "artillery_unit_mode": str(
                settings.get("artillery_unit_mode", "full") or "full"
            ),
            "war_machine_unit_mode": str(
                settings.get("war_machine_unit_mode", "full") or "full"
            ),
            "scale_lord_hero_health": bool(settings.get("scale_lord_hero_health")),
        },
        "edits": {
            str(unit_key): dict(fields)
            for unit_key, fields in sorted(_sanitize_edits(edits).items())
        },
        "sources": sources,
    }


def fingerprint_unit_data_inputs(inputs: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        inputs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _output_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": UNIT_DATA_PATCH_NAME,
        "size": stat.st_size,
        "sha256": _sha256_file(path),
    }


def _manifest_output_is_valid(manifest: Mapping[str, Any], output_dir: Path) -> bool:
    patch_path = Path(output_dir) / UNIT_DATA_PATCH_NAME
    if manifest.get("build_status") == "zero_modification":
        return not patch_path.exists() and manifest.get("output") is None
    if manifest.get("build_status") != "generated":
        return False
    output = manifest.get("output")
    if not isinstance(output, Mapping) or output.get("name") != UNIT_DATA_PATCH_NAME:
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
) -> dict[str, Any]:
    stored_result = manifest.get("result")
    result = stored_result if isinstance(stored_result, Mapping) else {}
    path = ""
    if manifest.get("build_status") == "generated":
        path = str((Path(output_dir) / UNIT_DATA_PATCH_NAME).resolve(strict=False))
    return {
        "status": status,
        "path": path,
        "fingerprint": str(manifest.get("fingerprint", "")),
        "entry_count": int(result.get("entry_count", 0)),
        "stats": dict(result),
    }


def ensure_unit_data_patch(
    output_dir: str | Path,
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the unit-data patch when edits exist; reuse a valid cached result."""
    output_dir = Path(output_dir)
    edits = load_unit_data_edits(output_dir)
    snapshot = (
        collect_game_data_source_snapshot(data_path, assets, active_ids)
        if edits
        else None
    )
    inputs = build_unit_data_inputs(
        data_path,
        assets,
        active_ids,
        playset_id,
        settings,
        edits,
        snapshot,
    )
    fingerprint = fingerprint_unit_data_inputs(inputs)
    store = _manifest_store(output_dir)
    previous = store.load()
    if previous.get("fingerprint") == fingerprint and _manifest_output_is_valid(
        previous, output_dir
    ):
        terminal_status = (
            "zero_modification"
            if previous.get("build_status") == "zero_modification"
            else "reused"
        )
        return _result_from_manifest(previous, output_dir, terminal_status)

    patch_path = Path(output_dir) / UNIT_DATA_PATCH_NAME
    if not edits:
        patch_path.unlink(missing_ok=True)
        build_status = "zero_modification"
        output = None
        result_payload: dict[str, Any] = {
            "edited_unit_count": 0,
            "disabled_unit_count": 0,
            "entry_count": 0,
        }
    else:
        built = build_unit_data_patch(
            output_dir,
            str(data_path),
            dict(assets),
            list(active_ids),
            dict(settings),
            edits,
            source_snapshot=snapshot,
        )
        if built.get("path") and Path(str(built["path"])).is_file():
            build_status = "generated"
            output = _output_record(patch_path)
            result_payload = dict(built.get("stats", {}))
        else:
            patch_path.unlink(missing_ok=True)
            build_status = "zero_modification"
            output = None
            result_payload = dict(built.get("stats", {})) or {
                "edited_unit_count": 0,
                "disabled_unit_count": 0,
                "entry_count": 0,
            }

    manifest = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "builder_version": UNIT_DATA_BUILDER_VERSION,
        "fingerprint": fingerprint,
        "inputs": inputs,
        "generated_at_ns": time.time_ns(),
        "build_status": build_status,
        "output": output,
        "result": result_payload,
    }
    store.save(manifest)
    return _result_from_manifest(manifest, output_dir, build_status)
