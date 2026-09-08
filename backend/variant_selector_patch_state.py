from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .json_store import AtomicJsonStore
from .models import ModAsset
from .variant_selector_compatibility import (
    VARIANT_SELECTOR_FRAMEWORK_SCRIPT,
    VARIANT_SELECTOR_SOURCE_PREFIXES,
)
from .start_options import (
    VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME,
    GameDataSourceSnapshot,
    build_variant_selector_compatibility_patch,
    collect_game_data_source_snapshot,
)


VARIANT_SELECTOR_COMPATIBILITY_MANIFEST_NAME = (
    "!!!!wyccc_variant_selector_patch.json"
)
FINGERPRINT_SCHEMA_VERSION = 1
VARIANT_SELECTOR_COMPATIBILITY_BUILDER_VERSION = 1
SETTING_KEY = "variant_selector_compatibility_patch_enabled"


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return bool(value)


def variant_selector_compatibility_requested(settings: Mapping[str, Any]) -> bool:
    return _coerce_bool(settings.get(SETTING_KEY, True))


def _source_snapshot(
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
) -> GameDataSourceSnapshot:
    return collect_game_data_source_snapshot(
        data_path, assets, active_ids, prefixes=VARIANT_SELECTOR_SOURCE_PREFIXES,
    )


def _file_signature(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=False)
    result: dict[str, Any] = {"path": str(resolved)}
    try:
        stat = resolved.stat()
    except OSError:
        result["missing"] = True
        return result
    if not resolved.is_file():
        result["missing"] = True
        return result
    result.update({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return result


def build_variant_selector_compatibility_inputs(
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
    source_snapshot: GameDataSourceSnapshot | None = None,
) -> dict[str, Any]:
    enabled = variant_selector_compatibility_requested(settings)
    ordered_ids = [str(mod_id) for mod_id in active_ids]
    snapshot = source_snapshot
    if enabled and snapshot is None:
        snapshot = _source_snapshot(data_path, assets, active_ids)
    if snapshot is not None:
        sources = [entry.input_record() for entry in snapshot.entries]
    else:
        sources = []
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
        sources.append(
            {
                "role": "vanilla",
                "pack_name": "db.pack",
                "file": _file_signature(Path(data_path) / "db.pack"),
            }
        )
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "builder_version": VARIANT_SELECTOR_COMPATIBILITY_BUILDER_VERSION,
        "playset_id": str(playset_id),
        "active_ids": ordered_ids,
        "enabled": enabled,
        "sources": sources,
    }


def fingerprint_variant_selector_compatibility_inputs(
    inputs: Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        inputs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _manifest_store(output_dir: Path) -> AtomicJsonStore:
    return AtomicJsonStore(
        output_dir / VARIANT_SELECTOR_COMPATIBILITY_MANIFEST_NAME,
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
        "name": VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME,
        "size": stat.st_size,
        "sha256": _sha256_file(path),
    }


def _manifest_output_is_valid(manifest: Mapping[str, Any], output_dir: Path) -> bool:
    patch_path = output_dir / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME
    if manifest.get("build_status") == "zero_modification":
        return not patch_path.exists() and manifest.get("output") is None
    if manifest.get("build_status") != "generated":
        return False
    output = manifest.get("output")
    if not isinstance(output, Mapping):
        return False
    if output.get("name") != VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME:
        return False
    try:
        stat = patch_path.stat()
        return (
            patch_path.is_file()
            and stat.st_size == int(output.get("size", -1))
            and _sha256_file(patch_path) == str(output.get("sha256", ""))
        )
    except (OSError, TypeError, ValueError):
        return False


def _result_from_manifest(
    manifest: Mapping[str, Any],
    output_dir: Path,
    status: str,
) -> dict[str, Any]:
    stored = manifest.get("result")
    result = stored if isinstance(stored, Mapping) else {}
    path = ""
    if manifest.get("build_status") == "generated":
        path = str(
            (output_dir / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME).resolve(
                strict=False
            )
        )
    stats = result.get("stats")
    diagnostics = result.get("source_diagnostics")
    return {
        "status": status,
        "reason": str(result.get("reason") or ""),
        "path": path,
        "fingerprint": str(manifest.get("fingerprint") or ""),
        "entry_count": int(result.get("entry_count", 0)),
        "stats": dict(stats) if isinstance(stats, Mapping) else {},
        "source_diagnostics": (
            dict(diagnostics) if isinstance(diagnostics, Mapping) else {}
        ),
    }


def ensure_variant_selector_compatibility_patch(
    output_dir: str | Path,
    data_path: str | Path,
    assets: Mapping[str, ModAsset],
    active_ids: Sequence[str],
    playset_id: str,
    settings: Mapping[str, Any],
    *,
    subscribed: bool = False,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    enabled = subscribed and variant_selector_compatibility_requested(settings)
    reason = "" if enabled else ("disabled" if subscribed else "patch_not_subscribed")
    snapshot = (
        _source_snapshot(data_path, assets, active_ids)
        if enabled
        else None
    )
    if snapshot is not None and not any(
        entry.name.replace("/", "\\").casefold() == VARIANT_SELECTOR_FRAMEWORK_SCRIPT
        for source in snapshot.sources for entry in source.entries
    ):
        enabled = False
        reason = "variant_selector_not_enabled"
    settings = {**settings, SETTING_KEY: enabled}
    inputs = build_variant_selector_compatibility_inputs(
        data_path,
        assets,
        active_ids,
        playset_id,
        settings,
        snapshot,
    )
    inputs["availability"] = reason
    fingerprint = fingerprint_variant_selector_compatibility_inputs(inputs)
    store = _manifest_store(output_dir)
    previous = store.load()
    if previous.get("fingerprint") == fingerprint and _manifest_output_is_valid(
        previous, output_dir
    ):
        status = (
            "zero_modification"
            if previous.get("build_status") == "zero_modification"
            else "reused"
        )
        return _result_from_manifest(previous, output_dir, status)

    patch_path = output_dir / VARIANT_SELECTOR_COMPATIBILITY_PATCH_NAME
    if not enabled:
        patch_path.unlink(missing_ok=True)
        built: dict[str, Any] = {
            "path": "",
            "entry_count": 0,
            "stats": {
                "art_set_rows": 0,
                "valid_art_set_rows": 0,
                "invalid_art_set_rows": 0,
                "candidate_subtype_count": 0,
                "candidate_art_set_count": 0,
            },
        }
    else:
        if snapshot is None:
            raise ValueError("Variant Selector 兼容补丁数据源快照无效")
        for attempt in range(2):
            built = build_variant_selector_compatibility_patch(
                output_dir,
                str(data_path),
                dict(assets),
                list(active_ids),
                True,
                source_snapshot=snapshot,
            )
            verified_snapshot = _source_snapshot(
                data_path, assets, active_ids
            )
            verified_inputs = build_variant_selector_compatibility_inputs(
                data_path,
                assets,
                active_ids,
                playset_id,
                settings,
                verified_snapshot,
            )
            verified_inputs["availability"] = reason
            verified_fingerprint = fingerprint_variant_selector_compatibility_inputs(
                verified_inputs
            )
            if verified_fingerprint == fingerprint:
                break
            patch_path.unlink(missing_ok=True)
            if attempt:
                raise ValueError(
                    "Variant Selector 兼容补丁的数据源在生成期间连续变化，请等待 MOD 更新完成后重试"
                )
            snapshot = verified_snapshot
            inputs = verified_inputs
            fingerprint = verified_fingerprint
        else:  # pragma: no cover
            raise ValueError("Variant Selector 兼容补丁生成未完成")

    entry_count = int(built.get("entry_count", 0))
    generated = bool(built.get("path")) and entry_count > 0
    if generated:
        returned = Path(str(built["path"])).resolve(strict=False)
        if returned != patch_path.resolve(strict=False) or not patch_path.is_file():
            raise ValueError("Variant Selector 兼容补丁生成结果无效")
        build_status = "generated"
        output: dict[str, Any] | None = _output_record(patch_path)
    else:
        patch_path.unlink(missing_ok=True)
        build_status = "zero_modification"
        output = None
    result_payload = {
        "reason": reason,
        "entry_count": entry_count if generated else 0,
        "stats": dict(built.get("stats", {})),
        "source_diagnostics": dict(built.get("source_diagnostics", {})),
    }
    manifest = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "builder_version": VARIANT_SELECTOR_COMPATIBILITY_BUILDER_VERSION,
        "fingerprint": fingerprint,
        "inputs": inputs,
        "generated_at_ns": time.time_ns(),
        "build_status": build_status,
        "output": output,
        "result": result_payload,
    }
    store.save(manifest)
    return _result_from_manifest(manifest, output_dir, build_status)
