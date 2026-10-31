from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .constants import INTERNAL_RUNTIME_PACK_NAMES, VOICE_COMPATIBILITY_PATCH_NAME, WH3_APP_ID
from .game_data import DbSource, GameDataEntry
from .json_store import AtomicJsonStore
from .models import ModAsset
from .pack_reader import read_pack_index
from .steam_paths import parse_vdf
from .start_options import PackEntry, read_pack_entries, resolve_game_data_source_specs, write_pfh5_pack
from .voice_compatibility import (
    VOICE_RUNTIME_MARKER,
    VOICE_SETTING_KEY,
    bank_scope,
    build_voice_compatibility_entries,
    normalized_name,
)

BUILDER_VERSION = 7
MANIFEST_NAME = "!!!!wyccc_voice_compatibility.json"
_LANGUAGE_PACKS = {
    "english(uk)": "audio_en_bnk.pack", "chinese": "audio_cn_bnk.pack",
    "french(france)": "audio_fr_bnk.pack", "german": "audio_ge_bnk.pack",
    "italian": "audio_it_bnk.pack", "polish": "audio_pl_bnk.pack",
    "russian": "audio_ru_bnk.pack", "spanish(spain)": "audio_sp_bnk.pack",
}
_CORE_BANKS = {
    f"{name}__core.bnk" for name in (
        "battle_vo_orders", "battle_vo_conversational", "campaign_vo",
        "campaign_vo_conversational", "frontend_vo",
    )
}
_VOICE_LANGUAGE_CODES = {
    code: scope for scope, codes in {
        "english(uk)": ("en", "english"), "chinese": ("cn", "zh", "schinese", "tchinese", "chinese"),
        "french(france)": ("fr", "french"), "german": ("de", "german"), "italian": ("it", "italian"),
        "polish": ("pl", "polish"), "russian": ("ru", "russian"), "spanish(spain)": ("es", "spanish"),
    }.items() for code in codes
}


def _voice_language(data_path: str | Path) -> str:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        preferences = Path(appdata) / "The Creative Assembly" / "Warhammer3" / "scripts" / "preferences.script.txt"
        try:
            raw = preferences.read_bytes()
            text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig", errors="replace")
            match = re.search(r'^\s*language_audio\s+"([^"]*)"\s*;', text, re.MULTILINE)
            if match and match[1].strip():
                return _VOICE_LANGUAGE_CODES.get(match[1].strip().casefold(), "")
        except OSError:
            pass
    steamapps = Path(data_path).parent.parent.parent
    try:
        parsed = parse_vdf((steamapps / f"appmanifest_{WH3_APP_ID}.acf")
                           .read_text(encoding="utf-8-sig", errors="replace"))
        state = parsed.get("AppState", parsed.get("appstate", {}))
        config = state.get("UserConfig", {}) if isinstance(state, dict) else {}
        language = config.get("language", "") if isinstance(config, dict) else ""
        return _VOICE_LANGUAGE_CODES.get(str(language).strip().casefold(), "")
    except (OSError, ValueError):
        return ""


def voice_compatibility_requested(settings: Mapping[str, Any]) -> bool:
    value = settings.get(VOICE_SETTING_KEY, False)
    return value.strip().casefold() in {"1", "true", "yes", "on"} if isinstance(value, str) else bool(value)


def _read_source(path: Path, *, vanilla: bool = False) -> tuple[DbSource | None, dict]:
    before = path.stat()
    index = read_pack_index(path)
    if any(normalized_name(entry.name) == VOICE_RUNTIME_MARKER for entry in index):
        return None, {}
    names = [entry.name for entry in index if (
        normalized_name(entry.name).startswith("audio\\wwise\\")
        and normalized_name(entry.name).endswith(".bnk")
        and (not vanilla or normalized_name(entry.name).rpartition("\\")[2] in _CORE_BANKS)
    )]
    # An empty prefix list means "read everything" to the shared Pack reader.
    entries = read_pack_entries(path, names) if names else []
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"语音兼容：{path.name} 在读取期间发生变化，请等待 MOD 更新完成后重试")
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(normalized_name(entry.name).encode("utf-8") + b"\0")
        digest.update(len(entry.payload).to_bytes(8, "little"))
        digest.update(entry.payload)
    record = {"path": str(path.resolve()), "size": after.st_size,
              "mtime_ns": after.st_mtime_ns, "bank_sha256": digest.hexdigest(), "vanilla": vanilla}
    return DbSource(path.name, tuple(GameDataEntry(e.name, e.payload) for e in entries),
                    role="vanilla" if vanilla else "mod"), record


def _snapshot(data_path, assets, active_ids, language_scope=""):
    sources, records = [], []
    for spec in resolve_game_data_source_specs(data_path, assets, active_ids):
        if spec.role == "vanilla" or spec.path.name.casefold() in INTERNAL_RUNTIME_PACK_NAMES:
            continue
        if spec.asset is not None and spec.asset.is_launcher_runtime_pack:
            continue
        try:
            source, record = _read_source(spec.path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"语音兼容无法读取 {spec.path.name}：{exc}") from exc
        if source is not None:
            if spec.asset is not None:
                asset = spec.asset
                label = asset.effective_name
                if label != spec.path.name:
                    label += f" [{spec.path.name}]"
                if asset.workshop_id:
                    label += f" (Workshop {asset.workshop_id})"
                source = replace(source, name=label)
            sources.append(source)
            records.append(record)
    scopes = {bank_scope(entry.name) for source in sources for entry in source.entries}
    data_root = Path(data_path)
    vanilla_paths = {data_root / _LANGUAGE_PACKS[scope] for scope in scopes
                     if scope in _LANGUAGE_PACKS and (data_root / _LANGUAGE_PACKS[scope]).is_file()}
    if scopes and language_scope in _LANGUAGE_PACKS:
        preferred = data_root / _LANGUAGE_PACKS[language_scope]
        if preferred.is_file():
            vanilla_paths.add(preferred)
    if scopes and ("" in scopes or len(vanilla_paths) < len(scopes)):
        fallback = next((data_root / name for name in _LANGUAGE_PACKS.values()
                         if (data_root / name).is_file()), None)
        if fallback is not None:
            vanilla_paths.add(fallback)
    # Older installations can also keep dialogue definitions in the base bank.
    if scopes and (data_root / "audio_base_bnk.pack").is_file():
        vanilla_paths.add(data_root / "audio_base_bnk.pack")
    for path in sorted(vanilla_paths):
        source, record = _read_source(path, vanilla=True)
        if source is not None:
            sources.append(source)
            records.append(record)
    return sources, records


def _fingerprint(inputs: Mapping) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ensure_voice_compatibility_patch(
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
    patch_path = output_dir / VOICE_COMPATIBILITY_PATCH_NAME
    store = AtomicJsonStore(output_dir / MANIFEST_NAME, lambda: {})
    if not subscribed or not voice_compatibility_requested(settings):
        patch_path.unlink(missing_ok=True)
        store.save({})
        return {"status": "zero_modification", "reason": "disabled" if subscribed else "patch_not_subscribed", "path": "",
                "fingerprint": "", "entry_count": 0, "stats": {}, "source_diagnostics": {}}

    for attempt in range(2):
        language_scope = _voice_language(data_path)
        sources, records = _snapshot(data_path, assets, active_ids, language_scope)
        inputs = {"builder_version": BUILDER_VERSION, "playset_id": str(playset_id),
                  "voice_language": language_scope, "active_ids": list(active_ids), "sources": records}
        fingerprint = _fingerprint(inputs)
        previous = store.load()
        if previous.get("fingerprint") == fingerprint:
            result = previous.get("result", {})
            output_hash = previous.get("output_sha256")
            if isinstance(result, dict) and (
                (output_hash and patch_path.is_file() and _file_hash(patch_path) == output_hash)
                or (not output_hash and not patch_path.exists())
            ):
                return {**result, "status": "reused" if output_hash else "zero_modification"}

        entries, stats = build_voice_compatibility_entries(sources, language_scope=language_scope)
        if entries and not any(source.entries for source in sources if source.role == "vanilla"):
            raise ValueError("语音兼容未找到原版对话事件库，无法保留原版语音分支")
        verified_language = _voice_language(data_path)
        _, verified = _snapshot(data_path, assets, active_ids, verified_language)
        if records == verified and language_scope == verified_language:
            break
        if attempt:
            raise ValueError("语音兼容的数据源在生成期间连续变化，请等待 MOD 更新完成后重试")

    diagnostics = {"source_pack_names": [source.name for source in sources if source.role != "vanilla"],
                   "vanilla_pack_names": [source.name for source in sources if source.role == "vanilla"],
                   "voice_language": language_scope}
    if entries:
        marker = json.dumps({"builder_version": BUILDER_VERSION, "stats": stats},
                            sort_keys=True).encode("utf-8")
        packed = [PackEntry(entry.name, entry.payload) for entry in entries]
        packed.append(PackEntry(VOICE_RUNTIME_MARKER, marker))
        write_pfh5_pack(patch_path, packed)
        if read_pack_entries(patch_path) != packed:
            patch_path.unlink(missing_ok=True)
            raise ValueError("动态语音兼容补丁的 Pack 回读失败")
    else:
        patch_path.unlink(missing_ok=True)
    result = {
        "status": "generated" if entries else "zero_modification",
        "reason": "" if entries else "no_conflicting_dialogue_events",
        "path": str(patch_path.resolve()) if entries else "", "fingerprint": fingerprint,
        "entry_count": len(entries) + 1 if entries else 0,
        "stats": stats, "source_diagnostics": diagnostics,
    }
    store.save({"inputs": inputs, "fingerprint": fingerprint, "result": result,
                "output_sha256": _file_hash(patch_path) if entries else None})
    return result
