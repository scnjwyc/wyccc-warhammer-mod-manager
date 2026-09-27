"""Read launch evidence without executing or changing game/mod files.

The v20 build's modified.log comparison is useful, but the first missing Pack
is only a suspect. Dependency reordering and Movie Packs make positional
comparisons invalid; script-log timestamps do not prove arrival at the menu.
"""
from __future__ import annotations

import os
import re
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .scanner import read_pack_type

_MOD_LINE = re.compile(r'^\s*mod\s+"([^"\r\n]+)"\s*;', re.I | re.M)
_DIRECTORY_LINE = re.compile(r'^\s*add_working_directory\s+"([^"\r\n]+)"\s*;', re.I | re.M)
_LOADED_LINE = re.compile(r"^\s*Mod:\s*(.+?)\s*$", re.I | re.M)
_DUMP_TIME = re.compile(r"^D(\d{4}-\d{2}-\d{2})_T(\d{2}-\d{2}-\d{2})$")
_READ_LIMIT = 4 * 1024 * 1024


def game_user_directory(name: str) -> Path:
    root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return root / "The Creative Assembly" / name


def file_signature(path: Path) -> list[int]:
    try:
        stat = path.stat()
        return [stat.st_mtime_ns, stat.st_size]
    except OSError:
        return []


def read_text(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(_READ_LIMIT + 1)
    if len(raw) > _READ_LIMIT:
        raise ValueError(f"Diagnostic input exceeds {_READ_LIMIT} bytes: {path.name}")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw and raw[1::2].count(0) * 4 >= len(raw):
        return raw.decode("utf-16le", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def pack_basename(value: str) -> str:
    return value.strip().replace("\\", "/").rsplit("/", 1)[-1]


def parse_launch_list(path: Path) -> tuple[list[str], list[str]]:
    content = read_text(path)
    return _DIRECTORY_LINE.findall(content), _MOD_LINE.findall(content)


def read_dump_exception(path: Path) -> dict[str, Any]:
    """Bounded reads of the minidump directory and exception stream."""
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(32)
            if len(header) != 32 or header[:4] != b"MDMP":
                return {}
            count, directory = struct.unpack_from("<II", header, 8)
            if count > 4096 or directory + count * 12 > size:
                return {}
            stream.seek(directory)
            entries = stream.read(count * 12)
            for index in range(count):
                kind, length, offset = struct.unpack_from("<III", entries, index * 12)
                if kind != 6 or length < 168 or offset + 168 > size:
                    continue
                stream.seek(offset)
                payload = stream.read(168)
                code = struct.unpack_from("<I", payload, 8)[0]
                address = struct.unpack_from("<Q", payload, 24)[0]
                parameter_count = min(struct.unpack_from("<I", payload, 32)[0], 15)
                return {
                    "code": f"0x{code:08X}", "address": f"0x{address:X}",
                    "parameters": list(struct.unpack_from(f"<{parameter_count}Q", payload, 40)),
                }
    except (OSError, ValueError, struct.error):
        pass
    return {}


def dump_snapshot(directory: Path) -> dict[str, list[int]]:
    try:
        return {str(path): file_signature(path) for path in directory.glob("*.mdmp")}
    except OSError:
        return {}


def collect_crash_dumps(
    directory: Path, since: float, before: dict[str, list[int]] | None = None,
) -> list[dict[str, Any]]:
    result = []
    for name, signature in dump_snapshot(directory).items():
        if not signature or (before is not None and before.get(name) == signature):
            continue
        path = Path(name)
        stamp = signature[0] / 1_000_000_000
        match = _DUMP_TIME.fullmatch(path.stem)
        if match:
            try:
                stamp = datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H-%M-%S").timestamp()
            except ValueError:
                pass
        if stamp < since - 2 or stamp > time.time() + 5:
            continue
        try:
            stack = read_text(path.with_suffix(".stack.txt")).splitlines()[:32]
        except (OSError, ValueError):
            stack = []
        result.append({"name": path.name, "path": name, "at": stamp,
                       "exception": read_dump_exception(path), "stack": stack})
    return sorted(result, key=lambda row: row["at"], reverse=True)[:5]


def capture_evidence(user_dir: Path) -> dict[str, Any]:
    logs = user_dir / "logs"
    return {
        "log_signature": file_signature(logs / "modified.log"),
        "unclean_signature": file_signature(logs / "no_clean_exit"),
        "dumps_before": dump_snapshot(user_dir / "crash_report"),
    }


def launch_record(
    game_id: str, game_path: str, user_dir: Path, plan: dict[str, Any],
    started_at: float, before: dict[str, Any],
) -> dict[str, Any]:
    directories = [Path(value) for value in plan.get("working_directories", [])]
    directories.append(Path(game_path) / "data")
    packs = []
    for name in plan.get("pack_names", []):
        # The launch plan is already validated; never interpret a log as a path.
        basename = pack_basename(name)
        path = next((root / basename for root in directories if (root / basename).is_file()), None)
        packs.append({"pack_name": basename, "path": str(path or ""),
                      "pack_type": read_pack_type(path) if path else "missing"})
    return {"game_id": game_id, "game_path": game_path, "user_dir": str(user_dir),
            "list_path": plan.get("target_path", ""), "packs": packs,
            "started_at": started_at, "acknowledged": False, **before}


def diagnose_launch(record: dict[str, Any], *, running: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "running" if running else "no_run", "crashed": False,
        "expected_count": 0, "loaded_count": 0, "pending": [], "ghosts": [],
        "dumps": [], "loaded": [], "no_clean_exit": False, "should_notify": False,
        "log_path": "", "list_path": record.get("list_path", ""), "report": "",
    }
    if not record or running:
        return result
    log = Path(record["user_dir"]) / "logs" / "modified.log"
    result["log_path"] = str(log)
    expected = [row for row in record.get("packs", []) if row["pack_type"] != "movie"]
    result["expected_count"] = len(expected)
    result["ghosts"] = [row for row in expected if not row["path"] or not Path(row["path"]).is_file()]
    signature = file_signature(log)
    started_at = float(record["started_at"])
    result["dumps"] = collect_crash_dumps(
        log.parent.parent / "crash_report", started_at, record.get("dumps_before", {}),
    )
    result["crashed"] = bool(result["dumps"])
    unclean = file_signature(log.parent / "no_clean_exit")
    result["no_clean_exit"] = bool(unclean and unclean != record.get("unclean_signature"))
    if (not signature or signature == record.get("log_signature")
            or signature[0] / 1_000_000_000 < started_at - 2):
        result["status"] = "not_started"
    else:
        try:
            loaded = list(dict.fromkeys(pack_basename(name) for name in _LOADED_LINE.findall(read_text(log))))
            loaded_keys = {name.casefold() for name in loaded}
            result["loaded"] = loaded
            result["pending"] = [row for row in expected if row["pack_name"].casefold() not in loaded_keys]
            result["loaded_count"] = len(expected) - len(result["pending"])
            result["status"] = (
                "no_mods_loaded" if expected and not loaded
                else "interrupted" if result["pending"] else "loaded_all"
            )
        except (OSError, ValueError) as exc:
            result.update(status="unreadable", detail=str(exc))
    result["should_notify"] = result["crashed"] and not record.get("acknowledged", False)
    result["report"] = "\n".join([
        "Wyccc launch diagnostics", f"Game: {record.get('game_id', '')}",
        f"Status: {result['status']}", f"Launch list: {result['list_path']}",
        f"Log: {log}", f"Loaded: {result['loaded_count']}/{result['expected_count']}",
        "Unloaded Packs are suspects, not confirmed causes.",
        *[f"Pending: {row['pack_name']}" for row in result["pending"]],
        *[f"Dump: {row['name']} {row['exception']}" for row in result["dumps"]],
    ])
    return result
