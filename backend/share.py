from __future__ import annotations

import hashlib
import struct
import urllib.parse
from pathlib import Path
from typing import Any

from .models import ModAsset
from .games import DEFAULT_GAME_ID, game_definitions
from .mod_profiles import parse_mod_profile_text
from .steam_paths import parse_vdf

PENDING_WORKSHOP_PREFIX = "pending:steam:"


def quick_checksum(path: str | Path) -> str:
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.md5(struct.pack("<Q", size))
    with path.open("rb") as stream:
        digest.update(stream.read(min(size, 1024 * 1024)))
        if size > 1024 * 1024:
            stream.seek(size - 1024 * 1024)
            digest.update(stream.read(1024 * 1024))
    return digest.hexdigest()


def export_share(
    mods: list[ModAsset], game_id: str = DEFAULT_GAME_ID, game_path: str | Path = "",
) -> str:
    game = next((game for game in game_definitions() if game.id == game_id), None)
    if not game or game.mod_format != "pack":
        raise ValueError("share.unsupportedGame")
    lines = ["# TW Mod Profile", "", ""]
    workshop_updates: dict[str, Any] = {}
    workshop_manifest_loaded = False
    for mod in mods:
        path = Path(mod.path)
        try:
            checksum = quick_checksum(path)
        except OSError as exc:
            raise ValueError(f"share.unreadablePack: {mod.pack_name}") from exc
        if mod.source == "workshop" and mod.workshop_id.isdigit():
            updated_at = max(0, int(mod.workshop_updated_at)) // 1000
            if not updated_at and not workshop_manifest_loaded:
                workshop_manifest_loaded = True
                for parent in path.parents:
                    manifest = parent / f"appworkshop_{game.app_id}.acf"
                    if manifest.is_file():
                        try:
                            workshop_updates = parse_vdf(manifest.read_text("utf-8-sig"))["AppWorkshop"].get("WorkshopItemsInstalled", {})
                        except (OSError, ValueError, KeyError):
                            workshop_updates = {}
                        break
            if not updated_at:
                updated_at = int(workshop_updates.get(mod.workshop_id, {}).get("timeupdated") or 0)
            location = f"steam_workshop:{game.app_id}/{mod.workshop_id}@{updated_at}/{mod.pack_name}"
        else:
            try:
                if not game_path:
                    raise ValueError("No game directory")
                relative = path.resolve().relative_to(Path(game_path).resolve()).as_posix()
            except ValueError as exc:
                raise ValueError(f"share.outsideGame: {mod.pack_name}") from exc
            location = f"game_dir:{relative}"
        if not mod.pack_name.casefold().endswith(".pack") or any(c in location for c in "\r\n"):
            raise ValueError("share.invalidOfficial")
        lines.append(f"mod_lookup_key://{checksum}@{location}")
    return "\n".join(lines) + "\n"


def parse_share(value: str, game_id: str = DEFAULT_GAME_ID) -> list[dict[str, Any]]:
    return parse_mod_profile_text(value, game_id)["references"]


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
        and (not reference.get("relative_path") or asset.path.replace("\\", "/").casefold().endswith(
            "/" + str(reference["relative_path"]).casefold()
        ))
    ]
    selected = sorted(candidates, key=lambda item: item.id)[0] if candidates else None
    return [selected] if selected else []
