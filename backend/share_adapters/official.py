from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .base import ShareCodeContext, ShareCodeParseResult, ShareMod, normalize_share_text

SCHEME = "mod_lookup_key://"
OFFICIAL_FORMAT_ID = "official-mod-lookup-key"

# Single source of truth for official launcher profile lines: the .twmods
# importer and the paste adapter both parse through this expression.
_LOOKUP_LINE_RE = re.compile(
    r"^mod_lookup_key://(?P<hash>.*?)@steam_workshop:(?P<app_id>\d+)/"
    r"(?P<workshop_id>\d+)@(?P<timestamp>[^/]+)/(?P<pack_path>.+\.pack)$",
    re.IGNORECASE,
)


METADATA_HASH = "hash"
METADATA_TIMESTAMP = "timestamp"
METADATA_PACK_PATH = "pack_path"


@dataclass(frozen=True)
class OfficialLookupEntry:
    hash: str
    workshop_id: str
    timestamp: str
    path_segment: str
    pack_name: str


@dataclass(frozen=True)
class OfficialLookupParse:
    entries: list[OfficialLookupEntry] = field(default_factory=list)
    unrecognized_lines: list[str] = field(default_factory=list)
    foreign_app_ids: list[str] = field(default_factory=list)
    scheme_line_count: int = 0


def parse_lookup_lines(text: str, app_id: str) -> OfficialLookupParse:
    """Parse official launcher lines for one App ID, preserving order and de-duplicating."""
    expected_app_id = str(app_id or "").strip()
    entries: list[OfficialLookupEntry] = []
    unrecognized_lines: list[str] = []
    foreign_app_ids: list[str] = []
    seen: set[tuple[str, str]] = set()
    scheme_line_count = 0
    for raw_line in normalize_share_text(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        if not line.casefold().startswith(SCHEME):
            unrecognized_lines.append(line)
            continue
        scheme_line_count += 1
        matched = _LOOKUP_LINE_RE.match(line)
        if not matched:
            unrecognized_lines.append(line)
            continue
        if matched.group("app_id") != expected_app_id:
            if matched.group("app_id") not in foreign_app_ids:
                foreign_app_ids.append(matched.group("app_id"))
            unrecognized_lines.append(line)
            continue
        pack_path = matched.group("pack_path")
        decoded_name = Path(
            urllib.parse.unquote(pack_path).replace("\\", "/")
        ).name.strip()
        if not decoded_name.casefold().endswith(".pack"):
            unrecognized_lines.append(line)
            continue
        key = (matched.group("workshop_id"), decoded_name.casefold())
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            OfficialLookupEntry(
                hash=matched.group("hash"),
                workshop_id=matched.group("workshop_id"),
                timestamp=matched.group("timestamp"),
                path_segment=pack_path,
                pack_name=decoded_name,
            )
        )
    return OfficialLookupParse(
        entries=entries,
        unrecognized_lines=unrecognized_lines,
        foreign_app_ids=foreign_app_ids,
        scheme_line_count=scheme_line_count,
    )


class OfficialModLookupKeyAdapter:
    """Official launcher ``mod_lookup_key://`` lines, as pasted from the game launcher."""

    format_id = OFFICIAL_FORMAT_ID
    can_serialize = True

    def can_handle(self, value: str) -> bool:
        return any(
            line.strip().casefold().startswith(SCHEME)
            for line in normalize_share_text(value).splitlines()
        )

    def deserialize(self, value: str, context: ShareCodeContext) -> ShareCodeParseResult:
        parsed = parse_lookup_lines(value, context.app_id)
        if not parsed.entries:
            if parsed.foreign_app_ids:
                raise ValueError(
                    "官方启动器分享码属于其他游戏（App ID "
                    f"{'、'.join(parsed.foreign_app_ids)}），请切换游戏后导入"
                )
            if parsed.scheme_line_count:
                raise ValueError(
                    "官方启动器分享码中没有有效的 MOD 行，需要以 .pack 结尾且 App ID 匹配"
                )
            raise ValueError("未识别到可导入的 MOD")
        mods = [
            ShareMod(
                workshop_id=entry.workshop_id,
                pack_name=entry.pack_name,
                position=position,
                metadata={
                    METADATA_HASH: entry.hash,
                    METADATA_TIMESTAMP: entry.timestamp,
                    METADATA_PACK_PATH: entry.path_segment,
                },
            )
            for position, entry in enumerate(parsed.entries)
        ]
        return ShareCodeParseResult(
            format_id=self.format_id,
            mods=mods,
            warnings=list(parsed.unrecognized_lines),
        )

    def serialize(self, mods: Sequence[ShareMod], context: ShareCodeContext) -> str:
        if not mods:
            raise ValueError("官方启动器分享码不能包含空 MOD 列表")
        lines: list[str] = []
        for mod in sorted(mods, key=lambda item: item.position):
            workshop_id = str(mod.workshop_id or "").strip()
            if not workshop_id.isdigit():
                raise ValueError("官方启动器分享码需要数字 Workshop ID，本地 MOD 无法导出")
            hash_value = str(mod.metadata.get(METADATA_HASH) or "").strip()
            timestamp = str(mod.metadata.get(METADATA_TIMESTAMP) or "").strip()
            path_segment = str(mod.metadata.get(METADATA_PACK_PATH) or "").strip()
            if not hash_value or not timestamp or not path_segment:
                raise ValueError(
                    "该 MOD 缺少官方启动器分享码所需的 hash、时间戳或路径，无法导出"
                )
            lines.append(
                f"{SCHEME}{hash_value}@steam_workshop:{context.app_id}/"
                f"{workshop_id}@{timestamp}/{path_segment}"
            )
        return "\n".join(lines)
