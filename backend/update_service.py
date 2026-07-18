from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib import parse, request

from .app_settings import SettingsService
from .constants import (
    APP_NAME,
    APP_SLUG,
    APP_VERSION,
    GITEE_UPDATE_MANIFEST_URL,
    GITHUB_UPDATE_MANIFEST_URL,
)


UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_UPDATE_BYTES = 1024 * 1024 * 1024
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){0,3})(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _version_key(value: str) -> tuple[tuple[int, int, int, int], int, tuple[tuple[int, Any], ...]]:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError(f"无效版本号：{value}")
    numbers = [int(part) for part in match.group(1).split(".")]
    numbers.extend([0] * (4 - len(numbers)))
    prerelease = match.group(2)
    if prerelease is None:
        return (tuple(numbers), 1, ())
    tokens: list[tuple[int, Any]] = []
    for token in prerelease.split("."):
        tokens.append((0, int(token)) if token.isdigit() else (1, token.casefold()))
    return (tuple(numbers), 0, tuple(tokens))


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    return _version_key(candidate) > _version_key(current)


def _validate_url(value: str, *, allow_file: bool = False) -> str:
    url = str(value or "").strip()
    parsed = parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return url
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return url
    if allow_file and parsed.scheme == "file":
        return url
    raise ValueError("更新地址必须使用 HTTPS；仅本机测试可使用 localhost 或 file 地址")


def _normalize_entries(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = raw.get("entries", raw.get("changes", []))
    if isinstance(raw, str):
        lines = [line.strip(" -\t") for line in raw.splitlines() if line.strip(" -\t")]
        return [{"title": "本次更新", "changes": [{"type": "change", "text": line} for line in lines]}]
    if not isinstance(raw, list):
        return []

    entries: list[dict[str, Any]] = []
    loose_changes: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            loose_changes.append({"type": "change", "text": item.strip()})
            continue
        if not isinstance(item, dict):
            continue
        if "changes" in item:
            changes: list[dict[str, str]] = []
            for change in item.get("changes") or []:
                if isinstance(change, str) and change.strip():
                    changes.append({"type": "change", "text": change.strip()})
                elif isinstance(change, dict) and str(change.get("text") or "").strip():
                    changes.append(
                        {
                            "type": str(change.get("type") or "change").strip(),
                            "text": str(change.get("text") or "").strip(),
                        }
                    )
            if changes:
                entries.append({"title": str(item.get("title") or "本次更新").strip(), "changes": changes})
        elif str(item.get("text") or "").strip():
            loose_changes.append(
                {
                    "type": str(item.get("type") or "change").strip(),
                    "text": str(item.get("text") or "").strip(),
                }
            )
    if loose_changes:
        entries.insert(0, {"title": "本次更新", "changes": loose_changes})
    return entries


class UpdateService:
    """Manifest-driven updater for the single-file Windows release."""

    def __init__(self, data_dir: Path, settings_service: SettingsService):
        self.data_dir = Path(data_dir)
        self.settings_service = settings_service
        self.update_dir = self.data_dir / "updates"
        self._lock = threading.RLock()
        self._last_info: dict[str, Any] | None = None

    @staticmethod
    def should_check_automatically(settings: dict[str, Any], now: int | None = None) -> bool:
        if not settings.get("check_updates_automatically"):
            return False
        current_time = int(now if now is not None else time.time())
        last_check = int(settings.get("last_update_check_at") or 0)
        return current_time - last_check >= UPDATE_CHECK_INTERVAL_SECONDS

    @staticmethod
    def preferred_repository_sources(language: str) -> tuple[tuple[str, str], ...]:
        github = ("github", GITHUB_UPDATE_MANIFEST_URL)
        gitee = ("gitee", GITEE_UPDATE_MANIFEST_URL)
        if str(language or "").strip().casefold().startswith("zh"):
            return (gitee, github)
        return (github, gitee)

    def check(self, *, manual: bool = True) -> dict[str, Any]:
        with self._lock:
            settings = self.settings_service.get()
            sources = self.preferred_repository_sources(
                str(settings.get("language") or "")
            )

            candidates: list[dict[str, Any]] = []
            failures: list[tuple[str, Exception]] = []
            for source, source_url in sources:
                try:
                    validated_url = _validate_url(source_url, allow_file=True)
                    payload, final_manifest_url = self._read_json(validated_url)
                    candidate = self._parse_manifest(payload, final_manifest_url)
                    candidate["source"] = source
                    candidates.append(candidate)
                except Exception as exc:
                    failures.append((source, exc))

            if not candidates:
                if len(sources) == 1 and failures:
                    raise failures[0][1]
                source_labels = {"gitee": "Gitee", "github": "GitHub"}
                failed_names = (
                    "、".join(source_labels.get(source, source) for source, _ in failures)
                    or "Gitee、GitHub"
                )
                cause = failures[0][1] if failures else None
                raise ValueError(f"无法从更新源检查新版本：{failed_names}") from cause

            # Sources are already in language-preference order. Only replace the
            # selected candidate when another repository has a strictly newer
            # version, so equal versions keep the preferred regional host.
            info = candidates[0]
            for candidate in candidates[1:]:
                if _version_key(candidate["version"]) > _version_key(info["version"]):
                    info = candidate

            checked_at = int(time.time())
            self.settings_service.save({"last_update_check_at": checked_at})

            newer = is_newer_version(info["version"], APP_VERSION)
            ignored = str(settings.get("ignored_update_version") or "") == info["version"]
            info.update(
                {
                    "configured": True,
                    "checked_at": checked_at,
                    "current_version": APP_VERSION,
                    "has_update": bool(newer and (manual or not ignored)),
                    "update_available": bool(newer),
                    "ignored": bool(newer and ignored),
                    "status": "remote" if newer else "current",
                    "sources_checked": [source for source, _ in sources],
                }
            )
            if newer and self._cached_update_is_valid(info):
                info["status"] = "ready"
                info["local_path"] = str(self._update_path(info["version"]))
            self._last_info = info
            return self._public_info(info)

    def download(self, version: str = "") -> dict[str, Any]:
        with self._lock:
            info = self._last_info
            if not info or not info.get("update_available"):
                info = self.check(manual=True)
                info = self._last_info
            if not info or not info.get("update_available"):
                raise ValueError("当前没有可下载的新版本")
            if version and str(version) != info["version"]:
                raise ValueError("更新版本已经变化，请重新检查")
            if self._cached_update_is_valid(info):
                info["status"] = "ready"
                info["local_path"] = str(self._update_path(info["version"]))
                return self._public_info(info)

            self.update_dir.mkdir(parents=True, exist_ok=True)
            target = self._update_path(info["version"])
            partial = target.with_suffix(".exe.part")
            digest = hashlib.sha256()
            total = 0
            try:
                http_request = request.Request(
                    info["download_url"],
                    headers={"User-Agent": f"{APP_SLUG}/{APP_VERSION}"},
                )
                with request.urlopen(http_request, timeout=120) as response, partial.open("wb") as stream:
                    final_url = str(response.geturl() or info["download_url"])
                    _validate_url(final_url, allow_file=parse.urlparse(info["download_url"]).scheme == "file")
                    content_length = int(response.headers.get("Content-Length") or 0)
                    if content_length > MAX_UPDATE_BYTES:
                        raise ValueError("更新文件超过允许的最大大小")
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_UPDATE_BYTES:
                            raise ValueError("更新文件超过允许的最大大小")
                        digest.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                expected_size = int(info.get("size") or 0)
                if expected_size and total != expected_size:
                    raise ValueError(f"更新文件大小校验失败：期望 {expected_size}，实际 {total}")
                if digest.hexdigest().casefold() != info["sha256"].casefold():
                    raise ValueError("更新文件 SHA-256 校验失败，已取消安装")
                with partial.open("rb") as stream:
                    if stream.read(2) != b"MZ":
                        raise ValueError("更新文件不是有效的 Windows 可执行文件")
                os.replace(partial, target)
                self._write_cached_metadata(info, target)
            except Exception:
                partial.unlink(missing_ok=True)
                raise

            info["status"] = "ready"
            info["local_path"] = str(target)
            info["downloaded_size"] = total
            return self._public_info(info)

    def ignore(self, version: str) -> dict[str, Any]:
        normalized = str(version or "").strip()
        _version_key(normalized)
        settings = self.settings_service.save({"ignored_update_version": normalized})
        if self._last_info and self._last_info.get("version") == normalized:
            self._last_info["ignored"] = True
            self._last_info["has_update"] = False
        return {"ignored_update_version": settings["ignored_update_version"]}

    def install_and_restart(self, version: str = "") -> dict[str, Any]:
        with self._lock:
            if os.name != "nt" or not getattr(sys, "frozen", False):
                raise ValueError("自动安装仅支持打包后的 Windows 版本；源码模式可检查和下载更新")
            info = self._last_info
            if not info or info.get("status") != "ready":
                raise ValueError("请先下载并校验更新")
            if version and str(version) != info["version"]:
                raise ValueError("更新版本已经变化，请重新检查")
            downloaded = Path(str(info.get("local_path") or self._update_path(info["version"])))
            if not downloaded.is_file() or not self._cached_update_is_valid(info):
                raise ValueError("已下载的更新文件不存在或校验失败，请重新下载")
            current_executable = Path(sys.executable).resolve(strict=False)
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if not powershell:
                raise ValueError("未找到 Windows PowerShell，无法执行安全替换")
            script = self._write_installer_script(current_executable, downloaded)
            subprocess.Popen(
                [
                    powershell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=str(current_executable.parent),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            exit_timer = threading.Timer(0.6, os._exit, args=(0,))
            exit_timer.daemon = True
            exit_timer.start()
            return {"restarting": True, "version": info["version"]}

    def consume_install_error(self) -> str:
        """Return one rollback error to the UI, then clear the handoff file."""
        log_path = self.update_dir / "install-error.log"
        if not log_path.is_file():
            return ""
        try:
            message = log_path.read_text(encoding="utf-8-sig", errors="replace").strip()
            log_path.unlink(missing_ok=True)
            return message[-2000:]
        except OSError:
            return ""

    def _read_json(self, url: str) -> tuple[dict[str, Any], str]:
        http_request = request.Request(url, headers={"User-Agent": f"{APP_SLUG}/{APP_VERSION}"})
        with request.urlopen(http_request, timeout=20) as response:
            final_url = str(response.geturl() or url)
            _validate_url(final_url, allow_file=parse.urlparse(url).scheme == "file")
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > MAX_MANIFEST_BYTES:
                raise ValueError("更新清单过大")
            raw = response.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("更新清单过大")
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("更新清单不是有效的 UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("更新清单根节点必须是对象")
        return payload, final_url

    @staticmethod
    def _parse_manifest(payload: dict[str, Any], manifest_url: str) -> dict[str, Any]:
        schema_version = int(payload.get("schema_version") or 1)
        if schema_version != 1:
            raise ValueError(f"不支持的更新清单版本：{schema_version}")
        declared_app = str(payload.get("app") or "").strip()
        if declared_app and declared_app != APP_NAME:
            raise ValueError("更新清单属于其他应用，已拒绝使用")
        version = str(payload.get("version") or "").strip().lstrip("v")
        _version_key(version)
        download = payload.get("download") if isinstance(payload.get("download"), dict) else {}
        raw_url = str(download.get("url") or payload.get("download_url") or "").strip()
        if not raw_url:
            raise ValueError("更新清单缺少下载地址")
        download_url = parse.urljoin(manifest_url, raw_url)
        allow_file = parse.urlparse(manifest_url).scheme == "file"
        _validate_url(download_url, allow_file=allow_file)
        sha256 = str(download.get("sha256") or payload.get("sha256") or "").strip()
        if not _SHA256_RE.fullmatch(sha256):
            raise ValueError("更新清单必须提供 64 位 SHA-256")
        try:
            size = int(download.get("size") or payload.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("更新文件大小必须是整数") from exc
        if size <= 0 or size > MAX_UPDATE_BYTES:
            raise ValueError("更新清单必须提供有效的更新文件字节数")
        return {
            "version": version,
            "published_at": str(payload.get("published_at") or payload.get("date") or "").strip(),
            "entries": _normalize_entries(payload.get("changelog", payload.get("entries", []))),
            "download_url": download_url,
            "sha256": sha256.casefold(),
            "size": size,
            "manifest_url": manifest_url,
        }

    def _cached_update_is_valid(self, info: dict[str, Any]) -> bool:
        path = self._update_path(str(info["version"]))
        if not path.is_file():
            return False
        expected_size = int(info.get("size") or 0)
        try:
            if expected_size and path.stat().st_size != expected_size:
                return False
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest().casefold() == str(info["sha256"]).casefold()
        except OSError:
            return False

    def _update_path(self, version: str) -> Path:
        safe_version = re.sub(r"[^0-9A-Za-z._-]", "_", version)
        return self.update_dir / f"{APP_SLUG}-{safe_version}.exe"

    def _write_cached_metadata(self, info: dict[str, Any], target: Path) -> None:
        metadata = {
            "version": info["version"],
            "sha256": info["sha256"],
            "size": target.stat().st_size,
            "download_url": info["download_url"],
            "downloaded_at": int(time.time()),
        }
        metadata_path = target.with_suffix(".json")
        temporary = metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, metadata_path)

    def _write_installer_script(self, current: Path, downloaded: Path) -> Path:
        self.update_dir.mkdir(parents=True, exist_ok=True)
        script = self.update_dir / f"install-{int(time.time())}-{os.getpid()}.ps1"
        backup = current.with_name(f"{current.name}.update-backup")
        log_path = self.update_dir / "install-error.log"
        log_path.unlink(missing_ok=True)
        arguments = subprocess.list2cmdline([str(argument) for argument in sys.argv[1:]])
        content = f"""$ErrorActionPreference = 'Stop'
$parentPid = {os.getpid()}
$current = {self._ps_quote(str(current))}
$downloaded = {self._ps_quote(str(downloaded))}
$backup = {self._ps_quote(str(backup))}
$workingDirectory = {self._ps_quote(str(current.parent))}
$logPath = {self._ps_quote(str(log_path))}
$arguments = {self._ps_quote(arguments)}
$deadline = [DateTime]::UtcNow.AddSeconds(45)

try {{
    while (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) {{
        if ([DateTime]::UtcNow -ge $deadline) {{ throw '等待旧版本退出超时' }}
        Start-Sleep -Milliseconds 250
    }}
    if (Test-Path -LiteralPath $backup) {{ Remove-Item -LiteralPath $backup -Force }}
    Move-Item -LiteralPath $current -Destination $backup -Force
    try {{
        Copy-Item -LiteralPath $downloaded -Destination $current -Force
        $startParameters = @{{
            FilePath = $current
            WorkingDirectory = $workingDirectory
            PassThru = $true
        }}
        if (-not [string]::IsNullOrWhiteSpace($arguments)) {{
            $startParameters['ArgumentList'] = $arguments
        }}
        $started = Start-Process @startParameters
        Start-Sleep -Milliseconds 1500
        if ($started.HasExited) {{ throw '新版本启动后立即退出' }}
        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $downloaded -Force -ErrorAction SilentlyContinue
    }} catch {{
        if (Test-Path -LiteralPath $current) {{ Remove-Item -LiteralPath $current -Force }}
        if (Test-Path -LiteralPath $backup) {{ Move-Item -LiteralPath $backup -Destination $current -Force }}
        throw
    }}
}} catch {{
    "$(Get-Date -Format o) $($_.Exception.Message)" | Out-File -LiteralPath $logPath -Encoding utf8 -Append
    if (Test-Path -LiteralPath $current) {{
        $restartParameters = @{{
            FilePath = $current
            WorkingDirectory = $workingDirectory
        }}
        if (-not [string]::IsNullOrWhiteSpace($arguments)) {{
            $restartParameters['ArgumentList'] = $arguments
        }}
        Start-Process @restartParameters
    }}
    exit 1
}}

Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
        script.write_text(content, encoding="utf-8-sig", newline="\r\n")
        return script

    @staticmethod
    def _ps_quote(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    @staticmethod
    def _public_info(info: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "configured",
            "checked_at",
            "current_version",
            "has_update",
            "update_available",
            "ignored",
            "status",
            "version",
            "published_at",
            "entries",
            "size",
            "local_path",
            "downloaded_size",
            "source",
            "sources_checked",
        }
        return {key: value for key, value in info.items() if key in allowed}
