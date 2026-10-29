"""Import and export a playset as a portable JSON file.

The export is intentionally human-readable and keeps the load order in the
``mods`` array, with a 1-based ``load_order`` on every entry. Workshop URLs are
always included when known; Workshop descriptions are optional and are
compacted (images/links removed, length limited) so a long description cannot
make the file too large for another AI to read. The import side is deliberately
tolerant of files edited by another AI: a bare list, a list of MOD ids, or a
payload without the optional metadata is still accepted as long as it contains
importable MOD references.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .constants import APP_VERSION, SOURCE_DATA, SOURCE_LOCAL, SOURCE_WORKSHOP
from .models import ModAsset
from .share import parse_pending_workshop_mod_id

SCHEMA_VERSION = 1
PAYLOAD_TYPE = "wyccc-mod-manager-playset"
MAX_FILE_BYTES = 20 * 1024 * 1024
DESCRIPTION_LIMIT = 2000
KNOWN_SOURCES = {SOURCE_DATA, SOURCE_WORKSHOP, SOURCE_LOCAL}
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WORKSHOP_ID_IN_URL = re.compile(r"[?&]id=(\d+)")
_IMAGE_TAG = re.compile(r"\[img\].*?\[/img\]", re.IGNORECASE | re.DOTALL)
_URL_TAG = re.compile(r"\[url=[^\]]*\](.*?)\[/url\]", re.IGNORECASE | re.DOTALL)
_BBCODE_TAG = re.compile(r"\[/?[a-zA-Z][^\]]*\]")
_LIST_ITEM = re.compile(r"\[\*\]")
_HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_BARE_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_RESERVED_FILENAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def safe_export_name(name: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", str(name or "")).strip().strip(".")
    if cleaned.split(".", 1)[0].casefold() in _RESERVED_FILENAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:80] or "playset"


def _workshop_url(workshop_id: str) -> str:
    return (
        f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}"
        if workshop_id
        else ""
    )


def _text(item: Mapping[str, Any], key: str) -> str:
    value = item.get(key)
    return "" if value is None else str(value).strip()


def compact_description(
    text: str, limit: int = DESCRIPTION_LIMIT
) -> tuple[str, bool]:
    """Strip image/link markup and bound a Workshop description.

    Workshop descriptions often contain large BBCode image galleries. Keeping
    those verbatim can make the exported file too large for another AI's
    single-file upload limit, so only the readable text is kept.
    """
    value = str(text or "")
    if not value:
        return "", False
    value = _IMAGE_TAG.sub(" ", value)
    value = _URL_TAG.sub(r"\1", value)
    value = _LIST_ITEM.sub(" ", value)
    value = _BBCODE_TAG.sub(" ", value)
    value = _HTML_TAG.sub(" ", value)
    value = _BARE_URL.sub(" ", value)
    value = _WHITESPACE.sub(" ", value).strip()
    if len(value) > limit:
        return f"{value[:limit].rstrip()}…", True
    return value, False


def build_export_payload(
    *,
    game_id: str,
    playset_name: str,
    ordered_ids: list[str],
    assets: Mapping[str, ModAsset],
    include_descriptions: bool = False,
) -> dict[str, Any]:
    mods: list[dict[str, Any]] = []
    for index, mod_id in enumerate(ordered_ids):
        raw_id = str(mod_id)
        asset = assets.get(raw_id)
        if asset is None:
            # A pending Workshop reference still carries enough identity to be
            # useful after the mod is installed on another machine.
            pending = parse_pending_workshop_mod_id(raw_id)
            workshop_id = pending[0] if pending else ""
            mods.append(
                {
                    "load_order": index + 1,
                    "id": raw_id,
                    "pack_name": pending[1] if pending else "",
                    "name": "",
                    "source": "",
                    "workshop_id": workshop_id,
                    "workshop_url": _workshop_url(workshop_id),
                }
            )
            continue
        workshop_id = asset.workshop_id
        item: dict[str, Any] = {
            "load_order": index + 1,
            "id": asset.id,
            "pack_name": asset.pack_name,
            "name": asset.effective_name,
            "source": asset.source,
            "workshop_id": workshop_id,
            "workshop_url": asset.workshop_url or _workshop_url(workshop_id),
        }
        if include_descriptions:
            description, truncated = compact_description(asset.description or "")
            item["description"] = description
            if truncated:
                item["description_truncated"] = True
        mods.append(item)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "type": PAYLOAD_TYPE,
        "app_version": APP_VERSION,
        "game": game_id,
        "playset_name": str(playset_name or "").strip()[:120],
        "exported_at": int(time.time() * 1000),
        "include_descriptions": bool(include_descriptions),
    }
    if include_descriptions:
        payload["description_mode"] = "compact"
        payload["description_limit"] = DESCRIPTION_LIMIT
    payload["mods"] = mods
    return payload


def parse_import_payload(text: str) -> dict[str, Any]:
    normalized_text = str(text or "").lstrip("\ufeff")
    encoded = normalized_text.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError("播放集 JSON 文件过大")
    try:
        payload = json.loads(normalized_text)
    except (TypeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("播放集 JSON 格式无效") from exc
    if isinstance(payload, list):
        payload = {"mods": payload}
    if not isinstance(payload, dict):
        raise ValueError("播放集 JSON 内容无效")
    payload_type = str(payload.get("type") or "").strip()
    if payload_type not in ("", PAYLOAD_TYPE):
        raise ValueError("不是 Wyccc's Mod Manager 播放集 JSON")
    schema_version = payload.get("schema_version")
    if schema_version is not None and str(schema_version) != str(SCHEMA_VERSION):
        raise ValueError("不支持的播放集 JSON 版本")
    game = str(payload.get("game") or "").strip()
    name = str(payload.get("playset_name") or "").strip()[:120]
    raw_mods = payload.get("mods")
    if not isinstance(raw_mods, list):
        raise ValueError("播放集 JSON 缺少 MOD 列表")
    mods: list[dict[str, Any]] = []
    for item in raw_mods:
        if isinstance(item, str):
            text = item.strip()
            url_match = _WORKSHOP_ID_IN_URL.search(text)
            if url_match:
                item = {"workshop_id": url_match.group(1), "workshop_url": text}
            elif text.isdigit():
                item = {"workshop_id": text}
            else:
                item = {"id": text}
        if not isinstance(item, dict):
            continue
        workshop_id = _text(item, "workshop_id")
        if not workshop_id:
            match = _WORKSHOP_ID_IN_URL.search(_text(item, "workshop_url"))
            workshop_id = match.group(1) if match else ""
        source = _text(item, "source")
        if source not in KNOWN_SOURCES:
            source = ""
        normalized = {
            "id": _text(item, "id"),
            "pack_name": _text(item, "pack_name"),
            "workshop_id": workshop_id,
            "source": source,
            "name": _text(item, "name"),
            "workshop_url": _text(item, "workshop_url"),
            "description": _text(item, "description"),
        }
        if not any(
            normalized.get(key) for key in ("id", "workshop_id", "pack_name")
        ):
            continue
        mods.append(normalized)
    if not mods:
        raise ValueError("播放集 JSON 中没有可导入的 MOD")
    return {
        "schema_version": SCHEMA_VERSION,
        "type": PAYLOAD_TYPE,
        "game": game,
        "playset_name": name,
        "mods": mods,
    }


def read_import_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError("播放集 JSON 文件不存在")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("播放集 JSON 文件过大")
    try:
        text = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("播放集 JSON 格式无效") from exc
    payload = parse_import_payload(text)
    if not payload["playset_name"]:
        payload["playset_name"] = source.stem.strip()[:120] or "Imported playset"
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def write_export_file(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    if target.suffix.casefold() != ".json":
        target = target.with_suffix(".json")
    _write_json(target, payload)
    return target
