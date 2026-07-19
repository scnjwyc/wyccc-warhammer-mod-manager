from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .constants import APP_VERSION


COLLECTION_DETAILS_ENDPOINT = (
    "https://api.steampowered.com/ISteamRemoteStorage/"
    "GetCollectionDetails/v1/"
)
MAX_COLLECTION_ITEMS = 1_000


def parse_workshop_collection_id(value: str) -> str:
    text = str(value or "").strip()
    if text.isdigit():
        return text
    parsed = urllib.parse.urlparse(text)
    query_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
    if str(query_id).isdigit():
        return str(query_id)
    path_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if parsed.scheme == "steam" and path_id.isdigit():
        return path_id
    raise ValueError("请输入有效的 Steam 创意工坊合集链接或合集 ID")


def fetch_workshop_collection(value: str, *, app_id: int | str) -> dict[str, Any]:
    collection_id = parse_workshop_collection_id(value)
    # Steam returns collection membership (and its explicit sort order) through
    # GetCollectionDetails.  Published-file details do not reliably include
    # children for public collection links.
    del app_id
    payload = urllib.parse.urlencode(
        [("collectioncount", "1"), ("publishedfileids[0]", collection_id)]
    ).encode("ascii")
    request = urllib.request.Request(
        COLLECTION_DETAILS_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"WycccModManager/{APP_VERSION}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Steam 创意工坊合集：{exc}") from exc

    details = result.get("response", {}).get("collectiondetails", [])
    detail = details[0] if isinstance(details, list) and details else {}
    if not isinstance(detail, dict) or int(detail.get("result") or 0) != 1:
        raise ValueError("未找到该 Steam 创意工坊合集，或该合集暂不可访问")

    raw_children = detail.get("children")
    if not isinstance(raw_children, list):
        raw_children = []
    indexed_children: list[tuple[int, int, str]] = []
    for index, child in enumerate(raw_children):
        if not isinstance(child, dict):
            continue
        workshop_id = str(child.get("publishedfileid") or "").strip()
        if not workshop_id.isdigit():
            continue
        try:
            sort_order = int(child.get("sortorder"))
        except (TypeError, ValueError):
            sort_order = index
        indexed_children.append((sort_order, index, workshop_id))
    indexed_children.sort()

    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _sort_order, _index, workshop_id in indexed_children:
        if workshop_id in seen:
            continue
        seen.add(workshop_id)
        references.append(
            {"workshop_id": workshop_id, "legacy_workshop_project": True}
        )
        if len(references) > MAX_COLLECTION_ITEMS:
            raise ValueError(f"创意工坊合集最多支持 {MAX_COLLECTION_ITEMS} 个 MOD")
    if not references:
        raise ValueError("该创意工坊合集不包含可导入的 MOD")

    return {
        "collection_id": collection_id,
        "title": str(detail.get("title") or "").strip(),
        "references": references,
    }
