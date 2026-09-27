"""The small subset of game localisation needed by the read-only unit panels."""
from __future__ import annotations

import re
import struct
from functools import lru_cache
from pathlib import Path

from .start_options import read_pack_entries
from .unit_data import _LocValue, _has_loc_priority, _language_loc_packs

PREFIXES = (
    "land_units_onscreen_name_", "cultures_name_", "factions_screen_name_",
    "unit_description_short_texts_text_", "unit_description_historical_texts_text_",
    "ui_unit_groupings_onscreen_", "unit_attributes_bullet_text_",
    "unit_attributes_imued_effect_text_", "unit_abilities_onscreen_name_", "unit_abilities_tooltip_text_",
    "ui_text_replacements_localised_text_",
)


def clean_game_text(value: str) -> str:
    # Render game markup as text, never as HTML from a MOD.
    text = str(value or "").replace("\\n", "\n").replace("||", "\n")
    text = re.sub(r"\[\[.*?\]\]", "", text)
    return re.sub(r"\{\{.*?\}\}", "", text).strip()


def parse_catalogue_loc(payload: bytes) -> dict[str, str]:
    if len(payload) < 14 or payload[:6] != b"\xff\xfeLOC\0":
        return {}
    count = struct.unpack_from("<i", payload, 10)[0]
    if not 0 <= count <= 2_000_000:
        return {}
    cursor = 14
    result = {}
    for _ in range(count):
        values = []
        for limit in (1024, 32768):
            if cursor + 2 > len(payload):
                raise ValueError("Truncated catalogue localisation")
            length = struct.unpack_from("<H", payload, cursor)[0]
            cursor += 2
            if length > limit or cursor + length * 2 > len(payload):
                raise ValueError("Invalid catalogue localisation string")
            values.append(payload[cursor:cursor + length * 2].decode("utf-16le", errors="replace"))
            cursor += length * 2
        if cursor >= len(payload):
            raise ValueError("Missing catalogue localisation language byte")
        cursor += 1
        if values[0].startswith(PREFIXES):
            result[values[0]] = clean_game_text(values[1])
    return result


@lru_cache(maxsize=64)
def _load(path: str, size: int, mtime: int) -> dict[str, _LocValue]:
    result = {}
    for rank, entry in enumerate(read_pack_entries(Path(path), "text/")):
        if not entry.name.casefold().endswith(".loc"):
            continue
        internal_name = entry.name.replace("/", "\\").split("\\", 1)[-1]
        for key, value in parse_catalogue_loc(entry.payload).items():
            candidate = _LocValue(value, internal_name, rank)
            if key not in result or _has_loc_priority(candidate, 0, result[key], 0):
                result[key] = candidate
    return result


def collect_catalogue_loc(data_path: Path, mod_paths: list[Path], language: str) -> dict[str, str]:
    def read(path: Path):
        stat = path.stat()
        return _load(str(path), stat.st_size, stat.st_mtime_ns)

    result = {}
    for name in _language_loc_packs(language):
        path = data_path / name
        if path.is_file():
            result.update({key: value.text for key, value in read(path).items()})
    mods = {}
    for rank, path in enumerate(mod_paths):
        for key, candidate in read(path).items():
            existing = mods.get(key)
            if existing is None or _has_loc_priority(candidate, rank, *existing):
                mods[key] = (candidate, rank)
    result.update({key: value.text for key, (value, _) in mods.items()})
    return result
