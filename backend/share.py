from __future__ import annotations

import base64
import json
import urllib.parse
import zlib
from typing import Any

from .models import ModAsset

PREFIX = "WMM1"
LEGACY_PREFIXES = ("WWM1", "WWMM1")
PENDING_WORKSHOP_PREFIX = "pending:steam:"


def export_share(mods: list[ModAsset]) -> str:
    payload = {
        "schema_version": 1,
        "game": "wh3",
        "mods": [
            {
                "id": mod.id,
                "workshop_id": mod.workshop_id,
                "pack_name": mod.pack_name,
                "source": mod.source,
            }
            for mod in mods
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    checksum = zlib.crc32(compressed) & 0xFFFFFFFF
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    return f"{PREFIX}-{checksum:08X}-{encoded}"


def parse_share(value: str) -> list[dict[str, Any]]:
    text = value.strip()
    matched_prefix = next(
        (
            candidate
            for candidate in (PREFIX, *LEGACY_PREFIXES)
            if text.startswith(f"{candidate}-")
        ),
        "",
    )
    if matched_prefix:
        parts = text.split("-", 2)
        if len(parts) != 3:
            raise ValueError("分享码格式错误")
        _, checksum_text, encoded = parts
        padding = "=" * (-len(encoded) % 4)
        try:
            compressed = base64.urlsafe_b64decode(encoded + padding)
            expected = int(checksum_text, 16)
            if zlib.crc32(compressed) & 0xFFFFFFFF != expected:
                raise ValueError("分享码校验失败")
            payload = json.loads(zlib.decompress(compressed).decode("utf-8"))
        except (ValueError, TypeError, json.JSONDecodeError, zlib.error) as exc:
            raise ValueError(f"无法解析分享码：{exc}") from exc
        if payload.get("game") != "wh3" or payload.get("schema_version") != 1:
            raise ValueError("不支持的分享码版本或游戏")
        mods = payload.get("mods", [])
        if not isinstance(mods, list):
            raise ValueError("分享码内容无效")
        return [item for item in mods if isinstance(item, dict)]

    # Compatibility with WH3-Mod-Manager's workshopId[;loadOrder]|... format.
    result = []
    for index, token in enumerate(part.strip() for part in text.split("|")):
        if not token:
            continue
        workshop_id, _, load_order = token.partition(";")
        result.append(
            {
                "workshop_id": workshop_id.strip(),
                "position": int(load_order) if load_order.strip().isdigit() else index,
                "legacy_workshop_project": True,
            }
        )
    if not result:
        raise ValueError("未识别到可导入的 MOD")
    return sorted(result, key=lambda item: item.get("position", 0))


def resolve_share(
    references: list[dict[str, Any]],
    assets: dict[str, ModAsset],
) -> tuple[list[str], list[dict[str, Any]]]:
    ordered_ids: list[str] = []
    missing: list[dict[str, Any]] = []
    for reference in references:
        candidates = _resolve_reference(reference, assets)
        if not candidates:
            missing.append(reference)
            continue
        for candidate in candidates:
            if candidate.id not in ordered_ids:
                ordered_ids.append(candidate.id)
    return ordered_ids, missing


def resolve_share_with_pending(
    references: list[dict[str, Any]],
    assets: dict[str, ModAsset],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Resolve installed items while preserving downloadable Workshop entries in order."""
    ordered_ids: list[str] = []
    missing: list[dict[str, Any]] = []
    for reference in references:
        candidates = _resolve_reference(reference, assets)
        if candidates:
            resolved_ids = [candidate.id for candidate in candidates]
        else:
            missing.append(reference)
            pending_id = pending_workshop_mod_id(reference)
            resolved_ids = [pending_id] if pending_id else []
        for mod_id in resolved_ids:
            if mod_id and mod_id not in ordered_ids:
                ordered_ids.append(mod_id)
    return ordered_ids, missing


def pending_workshop_mod_id(reference: dict[str, Any]) -> str:
    workshop_id = str(reference.get("workshop_id") or "").strip()
    if not workshop_id.isdigit():
        return ""
    pack_name = urllib.parse.quote(
        str(reference.get("pack_name") or "").strip().casefold(),
        safe="",
    )
    return f"{PENDING_WORKSHOP_PREFIX}{workshop_id}:{pack_name}"


def parse_pending_workshop_mod_id(value: str) -> tuple[str, str] | None:
    normalized = str(value or "")
    if not normalized.startswith(PENDING_WORKSHOP_PREFIX):
        return None
    payload = normalized[len(PENDING_WORKSHOP_PREFIX) :]
    workshop_id, separator, encoded_pack_name = payload.partition(":")
    if not separator or not workshop_id.isdigit():
        return None
    return workshop_id, urllib.parse.unquote(encoded_pack_name).casefold()


def _resolve_reference(
    reference: dict[str, Any],
    assets: dict[str, ModAsset],
) -> list[ModAsset]:
    if reference.get("legacy_workshop_project"):
        workshop_id = str(reference.get("workshop_id") or "")
        return sorted(
            (
                asset
                for asset in assets.values()
                if workshop_id and asset.workshop_id == workshop_id
            ),
            key=lambda item: (item.pack_name.casefold(), item.id),
        )

    selected = assets.get(str(reference.get("id") or ""))
    if selected:
        return [selected]
    workshop_id = str(reference.get("workshop_id") or "")
    pack_name = str(reference.get("pack_name") or "").casefold()
    source = str(reference.get("source") or "")
    candidates = [
        asset
        for asset in assets.values()
        if (not workshop_id or asset.workshop_id == workshop_id)
        and (not pack_name or asset.pack_name.casefold() == pack_name)
        and (not source or asset.source == source)
    ]
    selected = sorted(candidates, key=lambda item: item.id)[0] if candidates else None
    return [selected] if selected else []
