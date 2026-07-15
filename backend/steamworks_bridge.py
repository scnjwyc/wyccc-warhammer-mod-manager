from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


RESULT_PREFIX = "WMM_WORKSHOP_RESULT="


class SteamworksBridgeError(RuntimeError):
    pass


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _node_is_supported(candidate: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(candidate), "-p", "process.versions.node.split('.')[0]"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0 and int(completed.stdout.strip()) >= 22
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def find_node_executable(root: Path | None = None) -> Path | None:
    base = Path(root or runtime_root())
    candidates: list[Path] = [base / "steam_runtime" / "node.exe"]

    for environment_name in (
        "WMM_STEAMWORKS_NODE",
        "WMM_NODE",
        "WWM_STEAMWORKS_NODE",
        "WWM_NODE",
        "WWMM_STEAMWORKS_NODE",
        "WWMM_NODE",
    ):
        value = os.environ.get(environment_name, "").strip()
        if value:
            candidates.append(Path(value).expanduser())

    path_node = shutil.which("node.exe") or shutil.which("node")
    if path_node:
        candidates.append(Path(path_node))

    program_files = os.environ.get("ProgramFiles", "").strip()
    if program_files:
        candidates.append(Path(program_files) / "nodejs" / "node.exe")
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "nodejs" / "node.exe")
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        candidates.append(
            Path(user_profile)
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        )

    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve(strict=False)).casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.is_file() and _node_is_supported(candidate):
            return candidate.resolve(strict=False)
    return None


def query_workshop_languages(
    workshop_ids: list[str],
    languages: list[str],
    *,
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: int = 120,
) -> dict[str, dict[str, dict[str, Any]]]:
    ids = list(dict.fromkeys(value for value in workshop_ids if str(value).isdigit()))
    requested_languages = list(
        dict.fromkeys(str(value).strip() for value in languages if str(value).strip())
    )
    if not ids or not requested_languages:
        return {}

    request = {
        "operation": "query",
        "appId": int(app_id),
        "ids": ids,
        "languages": requested_languages,
    }
    payload = _run_bridge_request(request, root=root, timeout_seconds=timeout_seconds)
    source = payload.get("languages")
    if not isinstance(source, dict):
        raise SteamworksBridgeError("Steamworks bridge result has no language data")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for language in requested_languages:
        language_items = source.get(language)
        if not isinstance(language_items, dict):
            result[language] = {}
            continue
        result[language] = {
            str(workshop_id): dict(item)
            for workshop_id, item in language_items.items()
            if str(workshop_id).isdigit() and isinstance(item, dict)
        }
    return result


def query_workshop_dependencies(
    workshop_ids: list[str],
    language: str = "english",
    *,
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: int = 120,
) -> dict[str, list[dict[str, str]]]:
    ids = list(dict.fromkeys(str(value) for value in workshop_ids if str(value).isdigit()))
    if not ids:
        return {}
    payload = _run_bridge_request(
        {
            "operation": "query_dependencies",
            "appId": int(app_id),
            "ids": ids,
            "language": str(language or "english").strip() or "english",
        },
        root=root,
        timeout_seconds=timeout_seconds,
    )
    source = payload.get("dependencies")
    if not isinstance(source, dict):
        raise SteamworksBridgeError("Steamworks bridge result has no dependency data")
    failures = payload.get("dependency_failures")
    if isinstance(failures, list) and failures:
        failed_ids = ", ".join(str(value) for value in failures[:10])
        raise SteamworksBridgeError(
            f"Steamworks could not read dependencies for Workshop items: {failed_ids}"
        )
    result: dict[str, list[dict[str, str]]] = {}
    for workshop_id in ids:
        required_items = source.get(workshop_id, [])
        if not isinstance(required_items, list):
            required_items = []
        result[workshop_id] = [
            {
                "workshop_id": str(item.get("workshop_id") or ""),
                "title": str(item.get("title") or ""),
            }
            for item in required_items
            if isinstance(item, dict) and str(item.get("workshop_id") or "").isdigit()
        ]
    return result


def query_workshop_subscription_status(
    workshop_ids: list[str],
    language: str = "english",
    *,
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: int = 120,
) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(str(value) for value in workshop_ids if str(value).isdigit()))
    if not ids:
        return []
    payload = _run_bridge_request(
        {
            "operation": "query_subscriptions",
            "appId": int(app_id),
            "ids": ids,
            "language": str(language or "english").strip() or "english",
        },
        root=root,
        timeout_seconds=timeout_seconds,
    )
    source = payload.get("subscriptions")
    if not isinstance(source, dict):
        raise SteamworksBridgeError("Steamworks bridge result has no subscription data")
    return [
        {
            "workshop_id": workshop_id,
            "title": str(source.get(workshop_id, {}).get("title") or ""),
            "subscribed": bool(source.get(workshop_id, {}).get("subscribed")),
        }
        for workshop_id in ids
    ]


def subscribe_workshop_items(
    workshop_ids: list[str],
    *,
    app_id: int = 1_142_710,
    root: Path | None = None,
    timeout_seconds: int = 180,
) -> dict[str, Any]:
    ids = list(dict.fromkeys(str(value) for value in workshop_ids if str(value).isdigit()))
    if not ids:
        return {"operation": "subscribe_many", "subscribed": [], "already_subscribed": []}
    payload = _run_bridge_request(
        {
            "operation": "subscribe_many",
            "appId": int(app_id),
            "ids": ids,
        },
        root=root,
        timeout_seconds=timeout_seconds,
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SteamworksBridgeError("Steamworks bridge result has no subscription operation data")
    return dict(result)


def perform_workshop_operation(
    operation: str,
    workshop_id: str,
    *,
    app_id: int | str = 1_142_710,
    root: Path | None = None,
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    normalized_operation = str(operation or "").strip()
    if normalized_operation not in {"subscribe", "unsubscribe", "force_update"}:
        raise ValueError("Unsupported Steamworks operation")
    normalized_id = str(workshop_id or "").strip()
    if not normalized_id.isdigit():
        raise ValueError("Invalid Workshop ID")
    payload = _run_bridge_request(
        {
            "operation": normalized_operation,
            "appId": int(app_id),
            "id": normalized_id,
        },
        root=root,
        timeout_seconds=timeout_seconds,
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SteamworksBridgeError("Steamworks bridge result has no operation data")
    return dict(result)


def publish_workshop_item(
    *,
    content_path: str | Path,
    preview_path: str | Path,
    title: str,
    description: str = "",
    change_note: str = "",
    tags: list[str] | None = None,
    visibility: int = 0,
    workshop_id: str = "",
    language: str = "english",
    app_id: int | str = 1_142_710,
    root: Path | None = None,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    normalized_id = str(workshop_id or "").strip()
    if normalized_id and not normalized_id.isdigit():
        raise ValueError("Invalid Workshop ID")
    payload = _run_bridge_request(
        {
            "operation": "publish_item",
            "appId": int(app_id),
            "id": normalized_id,
            "contentPath": str(Path(content_path).resolve(strict=False)),
            "previewPath": str(Path(preview_path).resolve(strict=False)),
            "title": str(title),
            "description": str(description),
            "changeNote": str(change_note),
            "tags": list(dict.fromkeys(str(item) for item in (tags or []) if str(item))),
            "visibility": int(visibility),
            "language": str(language or "english").strip() or "english",
        },
        root=root,
        timeout_seconds=timeout_seconds,
    )
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SteamworksBridgeError("Steamworks bridge result has no publishing data")
    return dict(result)


def _run_bridge_request(
    request: dict[str, Any],
    *,
    root: Path | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    base = Path(root or runtime_root())
    script = base / "steam_runtime" / "workshop_bridge.js"
    if not script.is_file():
        raise SteamworksBridgeError(f"Steamworks bridge script is missing: {script}")
    node = find_node_executable(base)
    if node is None:
        raise SteamworksBridgeError(
            "Node.js runtime is unavailable; use the one-click launcher or rebuild the release package."
        )

    app_id = int(request.get("appId") or 0)
    environment = os.environ.copy()
    environment.setdefault("SteamAppId", str(app_id))
    try:
        completed = subprocess.run(
            [str(node), str(script)],
            cwd=script.parent,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(10, int(timeout_seconds)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SteamworksBridgeError(f"Steamworks bridge could not run: {exc}") from exc

    result_line = next(
        (
            line[len(RESULT_PREFIX) :]
            for line in reversed(completed.stdout.splitlines())
            if line.startswith(RESULT_PREFIX)
        ),
        "",
    )
    if not result_line:
        detail = (completed.stderr or completed.stdout).strip()[-800:]
        raise SteamworksBridgeError(
            f"Steamworks bridge returned no result (exit {completed.returncode}): {detail}"
        )
    try:
        payload = json.loads(result_line)
    except json.JSONDecodeError as exc:
        raise SteamworksBridgeError("Steamworks bridge returned invalid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        message = str(payload.get("error") or "Steamworks query failed") if isinstance(payload, dict) else ""
        raise SteamworksBridgeError(message or "Steamworks query failed")

    return payload
