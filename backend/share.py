from __future__ import annotations

import urllib.parse
from typing import Any

from .games import DEFAULT_GAME_ID
from .models import ModAsset
from .share_adapters import LEGACY_PREFIXES, PREFIX
from .share_code import (
    DEFAULT_EXPORT_FORMAT_ID,
    default_share_code_service,
    share_context,
    share_mods_from_assets,
)

PENDING_WORKSHOP_PREFIX = "pending:steam:"

__all__ = [
    "LEGACY_PREFIXES",
    "PENDING_WORKSHOP_PREFIX",
    "PREFIX",
    "export_share",
    "parse_pending_workshop_mod_id",
    "parse_share",
    "pending_workshop_mod_id",
    "resolve_share",
    "resolve_share_with_pending",
]


def export_share(mods: list[ModAsset], game_id: str = DEFAULT_GAME_ID) -> str:
    """Compatibility wrapper: serialize through the default WMM1 adapter."""
    return default_share_code_service().serialize(
        share_mods_from_assets(mods),
        share_context(game_id),
        format_id=DEFAULT_EXPORT_FORMAT_ID,
    )


def parse_share(value: str, game_id: str = DEFAULT_GAME_ID) -> list[dict[str, Any]]:
    """Compatibility wrapper: deserialize through the adapter chain."""
    return default_share_code_service().references(value, share_context(game_id))


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
