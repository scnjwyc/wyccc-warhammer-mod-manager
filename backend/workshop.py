from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .json_store import AtomicJsonStore
from .steam_friends import (
    SteamFriendsError,
    query_steam_persona_names,
)
from .steamworks_bridge import (
    SteamworksBridgeError,
    query_workshop_dependencies,
    query_workshop_languages,
)


logger = logging.getLogger(__name__)

DETAILS_ENDPOINT = (
    "https://api.steampowered.com/ISteamRemoteStorage/"
    "GetPublishedFileDetails/v1/"
)
PROFILE_ENDPOINT = "https://steamcommunity.com/profiles/{steam_id}?xml=1"

CACHE_SCHEMA_VERSION = 7
ENGLISH_STEAM_LANGUAGE = "english"
STEAM_LANGUAGE_BY_INTERFACE = {
    "zh-CN": "schinese",
    "en-US": ENGLISH_STEAM_LANGUAGE,
    "ko-KR": "koreana",
    "ru-RU": "russian",
    "ja-JP": "japanese",
}
INTERFACE_LANGUAGE_BY_STEAM = {
    steam_language: interface_language
    for interface_language, steam_language in STEAM_LANGUAGE_BY_INTERFACE.items()
}

AUTHOR_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000
AUTHOR_FAILURE_RETRY_MS = 30 * 60 * 1000
AUTHOR_HTTP_MAX_WORKERS = 2
AUTHOR_HTTP_TIMEOUT_SECONDS = 5.0
AUTHOR_HTTP_MAX_ATTEMPTS = 3
AUTHOR_HTTP_BACKOFF_SECONDS = (0.5, 1.0)
AUTHOR_HTTP_DEADLINE_SECONDS = 90.0
LOCALIZED_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000
LOCALIZED_FAILURE_RETRY_MS = 6 * 60 * 60 * 1000
DEPENDENCY_CACHE_WARNING = (
    "Steam 暂时无法读取部分工坊依赖，已使用已有缓存；缺失依赖结果可能不是最新状态"
)


class AuthorProfileError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _default_cache() -> dict[str, Any]:
    return {"schema_version": CACHE_SCHEMA_VERSION, "items": {}, "authors": {}}


def _steam_language(interface_language: str) -> str:
    return STEAM_LANGUAGE_BY_INTERFACE.get(
        str(interface_language or "").strip(),
        ENGLISH_STEAM_LANGUAGE,
    )


def steam_language_for_interface(interface_language: str) -> str:
    return _steam_language(interface_language)


def interface_language_for_steam(steam_language: str) -> str:
    return INTERFACE_LANGUAGE_BY_STEAM.get(
        str(steam_language or "").strip(),
        "en-US",
    )


class WorkshopMetadataService:
    def __init__(self, cache_path: Path):
        self.store = AtomicJsonStore(cache_path, _default_cache)
        self.last_refresh_warning = ""

    @staticmethod
    def _upgrade_item(source: Any, workshop_id: str) -> dict[str, Any]:
        record = dict(source) if isinstance(source, dict) else {}
        localized_source = record.get("localized")
        localized: dict[str, dict[str, Any]] = {}
        if isinstance(localized_source, dict):
            localized = {
                str(language): dict(value)
                for language, value in localized_source.items()
                if isinstance(value, dict)
            }
        if ENGLISH_STEAM_LANGUAGE not in localized:
            localized[ENGLISH_STEAM_LANGUAGE] = {
                "title": str(record.get("title") or ""),
                "description": str(record.get("description") or ""),
                "fetched_at": int(record.get("fetched_at") or 0),
                "source_updated_at": int(record.get("updated_at") or 0),
                "failed": False,
                "source": "legacy-cache",
            }
        record["workshop_id"] = workshop_id
        record["localized"] = localized
        required_items = record.get("required_workshop_items")
        if not isinstance(required_items, list):
            record["required_workshop_items"] = []
        return record

    def get_many(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict[str, Any]]:
        cache = self.store.load()
        items = cache.get("items", {})
        authors = cache.get("authors", {})
        if not isinstance(items, dict):
            return {}
        if not isinstance(authors, dict):
            authors = {}

        requested_language = _steam_language(interface_language)
        result: dict[str, dict[str, Any]] = {}
        for workshop_id in workshop_ids:
            source = items.get(workshop_id)
            if not isinstance(source, dict):
                continue
            record = self._upgrade_item(source, workshop_id)
            localized = record.get("localized", {})
            english = localized.get(ENGLISH_STEAM_LANGUAGE, {})
            requested = localized.get(requested_language, {})

            item = {key: value for key, value in record.items() if key != "localized"}
            requested_title = str(requested.get("title") or "").strip()
            requested_description = str(requested.get("description") or "").strip()
            english_title = str(english.get("title") or item.get("title") or "").strip()
            english_description = str(
                english.get("description") or item.get("description") or ""
            ).strip()
            item["title"] = requested_title or english_title
            item["description"] = requested_description or english_description
            item["requested_language"] = requested_language
            item["title_language"] = (
                requested_language if requested_title else ENGLISH_STEAM_LANGUAGE
            )
            item["description_language"] = (
                requested_language if requested_description else ENGLISH_STEAM_LANGUAGE
            )

            creator_id = str(item.get("creator_id") or "")
            profile = authors.get(creator_id)
            if isinstance(profile, dict):
                item["author"] = str(profile.get("name") or "")
                item["author_profile_url"] = str(profile.get("profile_url") or "")
                item["author_fetched_at"] = int(profile.get("fetched_at") or 0)
            result[workshop_id] = item
        return result

    def refresh(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict[str, Any]]:
        self.last_refresh_warning = ""
        ids = list(dict.fromkeys(item for item in workshop_ids if item.isdigit()))
        if not ids:
            return {}
        cache = self.store.load()
        try:
            previous_schema = int(cache.get("schema_version") or 0)
        except (TypeError, ValueError):
            previous_schema = 0
        items = cache.setdefault("items", {})
        authors = cache.setdefault("authors", {})
        if not isinstance(items, dict):
            items = {}
            cache["items"] = items
        if not isinstance(authors, dict):
            authors = {}
            cache["authors"] = authors

        try:
            self._refresh_english_details(items, ids)
        except Exception as exc:
            logger.warning("Steam English Workshop metadata refresh failed: %s", exc)

        requested_language = _steam_language(interface_language)
        if requested_language != ENGLISH_STEAM_LANGUAGE:
            self._refresh_localized_steamworks(
                items,
                ids,
                requested_language,
                force=previous_schema < CACHE_SCHEMA_VERSION,
            )

        self._refresh_dependencies(
            items,
            ids,
            requested_language,
            force=previous_schema < CACHE_SCHEMA_VERSION,
        )

        creator_ids = [
            str(items[workshop_id].get("creator_id") or "")
            for workshop_id in ids
            if isinstance(items.get(workshop_id), dict)
        ]
        self._refresh_author_profiles(authors, creator_ids)
        cache["schema_version"] = CACHE_SCHEMA_VERSION
        self.store.save(cache)
        return self.get_many(ids, interface_language)

    def refresh_localized(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict[str, Any]]:
        """Refresh only the localized publishing copy for the requested items."""
        self.last_refresh_warning = ""
        ids = list(dict.fromkeys(item for item in workshop_ids if item.isdigit()))
        if not ids:
            return {}
        cache = self.store.load()
        items = cache.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            cache["items"] = items

        try:
            self._refresh_english_details(items, ids)
        except Exception as exc:
            logger.warning("Steam English Workshop publishing copy refresh failed: %s", exc)
            self.last_refresh_warning = f"英文工坊信息刷新失败，已保留缓存内容：{exc}"

        requested_language = _steam_language(interface_language)
        if requested_language != ENGLISH_STEAM_LANGUAGE:
            self._refresh_localized_steamworks(
                items,
                ids,
                requested_language,
                force=True,
            )

        cache["schema_version"] = CACHE_SCHEMA_VERSION
        self.store.save(cache)
        return self.get_many(ids, interface_language)

    def ensure_dependencies(
        self,
        workshop_ids: list[str],
        interface_language: str = "en-US",
    ) -> dict[str, dict[str, Any]]:
        self.last_refresh_warning = ""
        ids = list(dict.fromkeys(item for item in workshop_ids if item.isdigit()))
        if not ids:
            return {}
        cache = self.store.load()
        items = cache.setdefault("items", {})
        if not isinstance(items, dict):
            items = {}
            cache["items"] = items
        self._refresh_dependencies(items, ids, _steam_language(interface_language))
        cache["schema_version"] = CACHE_SCHEMA_VERSION
        self.store.save(cache)
        return self.get_many(ids, interface_language)

    def _refresh_dependencies(
        self,
        items: dict[str, Any],
        workshop_ids: list[str],
        steam_language: str,
        *,
        force: bool = False,
    ) -> None:
        now = int(time.time() * 1000)
        pending: list[str] = []
        retry_blocked = False
        for workshop_id in workshop_ids:
            record = self._upgrade_item(items.get(workshop_id), workshop_id)
            items[workshop_id] = record
            fetched_at = int(record.get("dependencies_fetched_at") or 0)
            last_error_at = int(record.get("dependencies_last_error_at") or 0)
            cached_language = str(record.get("dependencies_language") or "")
            if not force and fetched_at > 0 and cached_language == steam_language:
                if now - fetched_at <= LOCALIZED_CACHE_MAX_AGE_MS:
                    continue
            if not force and last_error_at > 0 and now - last_error_at <= LOCALIZED_FAILURE_RETRY_MS:
                retry_blocked = True
                continue
            pending.append(workshop_id)
        if retry_blocked:
            self.last_refresh_warning = DEPENDENCY_CACHE_WARNING
        if not pending:
            return

        try:
            dependencies = query_workshop_dependencies(pending, steam_language)
        except SteamworksBridgeError as exc:
            logger.warning("Steamworks Workshop dependency refresh failed: %s", exc)
            self.last_refresh_warning = DEPENDENCY_CACHE_WARNING
            for workshop_id in pending:
                items[workshop_id]["dependencies_last_error_at"] = now
            return

        failed_ids = [workshop_id for workshop_id in pending if workshop_id not in dependencies]
        if failed_ids:
            self.last_refresh_warning = DEPENDENCY_CACHE_WARNING
            logger.warning(
                "Workshop dependency refresh retained cache for %s item(s): %s",
                len(failed_ids),
                ", ".join(failed_ids[:10]),
            )
            for workshop_id in failed_ids:
                items[workshop_id]["dependencies_last_error_at"] = now

        for workshop_id in pending:
            if workshop_id not in dependencies:
                continue
            record = items[workshop_id]
            record["required_workshop_items"] = dependencies.get(workshop_id, [])
            record["dependencies_fetched_at"] = now
            record["dependencies_last_error_at"] = 0
            record["dependencies_language"] = steam_language

    def _refresh_english_details(
        self,
        items: dict[str, Any],
        workshop_ids: list[str],
    ) -> None:
        for start in range(0, len(workshop_ids), 100):
            chunk = workshop_ids[start : start + 100]
            payload: list[tuple[str, str]] = [("itemcount", str(len(chunk)))]
            payload.extend(
                (f"publishedfileids[{index}]", value)
                for index, value in enumerate(chunk)
            )
            encoded = urllib.parse.urlencode(payload).encode("ascii")
            request = urllib.request.Request(
                DETAILS_ENDPOINT,
                data=encoded,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "WycccModManager/0.1",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
            details = result.get("response", {}).get("publishedfiledetails", [])
            fetched_at = int(time.time() * 1000)
            for detail in details:
                workshop_id = str(detail.get("publishedfileid") or "")
                if not workshop_id:
                    continue
                updated_at = int(detail.get("time_updated") or 0) * 1000
                record = self._upgrade_item(items.get(workshop_id), workshop_id)
                record.update(
                    {
                        "workshop_id": workshop_id,
                        "title": str(detail.get("title") or ""),
                        "description": str(detail.get("description") or ""),
                        "creator_id": str(detail.get("creator") or ""),
                        "preview_url": str(detail.get("preview_url") or ""),
                        "created_at": int(detail.get("time_created") or 0) * 1000,
                        "updated_at": updated_at,
                        "result": int(detail.get("result") or 0),
                        "fetched_at": fetched_at,
                    }
                )
                record["localized"][ENGLISH_STEAM_LANGUAGE] = {
                    "title": record["title"],
                    "description": record["description"],
                    "fetched_at": fetched_at,
                    "source_updated_at": updated_at,
                    "failed": False,
                    "last_error_at": 0,
                    "source": "steam-remote-storage",
                }
                items[workshop_id] = record

    def _refresh_localized_steamworks(
        self,
        items: dict[str, Any],
        workshop_ids: list[str],
        steam_language: str,
        *,
        force: bool = False,
    ) -> None:
        now = int(time.time() * 1000)
        pending: list[str] = []
        for workshop_id in workshop_ids:
            record = self._upgrade_item(items.get(workshop_id), workshop_id)
            items[workshop_id] = record
            variant = record["localized"].get(steam_language)
            if not force and isinstance(variant, dict):
                fetched_at = int(variant.get("fetched_at") or 0)
                last_error_at = int(variant.get("last_error_at") or 0)
                source_updated_at = int(variant.get("source_updated_at") or 0)
                current_updated_at = int(record.get("updated_at") or 0)
                if (
                    variant.get("source") == "steamworks"
                    and not variant.get("failed")
                    and fetched_at > 0
                    and now - fetched_at <= LOCALIZED_CACHE_MAX_AGE_MS
                    and source_updated_at >= current_updated_at
                ):
                    continue
                if last_error_at > 0 and now - last_error_at <= LOCALIZED_FAILURE_RETRY_MS:
                    continue
            pending.append(workshop_id)
        if not pending:
            return

        try:
            response = query_workshop_languages(pending, [steam_language])
            language_items = response.get(steam_language, {})
        except SteamworksBridgeError as exc:
            logger.warning("Steamworks localized Workshop refresh failed: %s", exc)
            self.last_refresh_warning = (
                f"Steamworks 多语言工坊信息刷新失败，已回退英文或缓存内容：{exc}"
            )
            self._record_localized_failure(items, pending, steam_language, now)
            return

        for workshop_id in pending:
            record = items[workshop_id]
            detail = language_items.get(workshop_id)
            if not isinstance(detail, dict):
                self._record_localized_failure(
                    items,
                    [workshop_id],
                    steam_language,
                    now,
                )
                continue

            title = str(detail.get("title") or "").strip()
            description = str(detail.get("description") or "").strip()
            english_variant = record["localized"].get(ENGLISH_STEAM_LANGUAGE, {})
            english_title = str(english_variant.get("title") or "").strip()
            english_description = str(
                english_variant.get("description") or ""
            ).strip()
            localized_title = "" if title and title == english_title else title
            localized_description = (
                ""
                if description and description == english_description
                else description
            )
            updated_at = int(detail.get("updated_at") or record.get("updated_at") or 0)
            record["localized"][steam_language] = {
                "title": localized_title,
                "description": localized_description,
                "fetched_at": now,
                "source_updated_at": updated_at,
                "failed": not bool(localized_title or localized_description),
                "last_error_at": 0,
                "source": "steamworks",
            }
            for key in ("creator_id", "preview_url", "created_at", "updated_at"):
                value = detail.get(key)
                if value:
                    record[key] = value

    @staticmethod
    def _record_localized_failure(
        items: dict[str, Any],
        workshop_ids: list[str],
        steam_language: str,
        failed_at: int,
    ) -> None:
        for workshop_id in workshop_ids:
            record = items[workshop_id]
            localized = record["localized"]
            existing = localized.get(steam_language)
            if isinstance(existing, dict) and (
                existing.get("title") or existing.get("description")
            ):
                existing["last_error_at"] = failed_at
                continue
            localized[steam_language] = {
                "title": "",
                "description": "",
                "fetched_at": failed_at,
                "source_updated_at": int(record.get("updated_at") or 0),
                "failed": True,
                "last_error_at": failed_at,
                "source": "steamworks-error",
            }

    @staticmethod
    def _classify_author_profile_error(exc: Exception, steam_id: str) -> AuthorProfileError:
        if isinstance(exc, AuthorProfileError):
            return exc
        if isinstance(exc, urllib.error.HTTPError):
            code = int(exc.code)
            if code == 429:
                return AuthorProfileError(
                    "rate_limited",
                    f"Steam profile request was rate limited: {steam_id}",
                    retryable=True,
                )
            if 500 <= code <= 599:
                return AuthorProfileError(
                    "http_5xx",
                    f"Steam profile service returned HTTP {code}: {steam_id}",
                    retryable=True,
                )
            return AuthorProfileError(
                f"http_{code}",
                f"Steam profile request returned HTTP {code}: {steam_id}",
            )
        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                return AuthorProfileError(
                    "timeout",
                    f"Steam profile request timed out: {steam_id}",
                    retryable=True,
                )
            return AuthorProfileError(
                "network",
                f"Steam profile network request failed: {steam_id}: {reason}",
                retryable=True,
            )
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return AuthorProfileError(
                "timeout",
                f"Steam profile request timed out: {steam_id}",
                retryable=True,
            )
        if isinstance(exc, ET.ParseError):
            return AuthorProfileError(
                "invalid_xml",
                f"Steam profile returned invalid XML: {steam_id}",
            )
        if isinstance(exc, OSError):
            return AuthorProfileError(
                "network",
                f"Steam profile request failed: {steam_id}: {exc}",
                retryable=True,
            )
        return AuthorProfileError(
            "unexpected",
            f"Steam profile request failed unexpectedly: {steam_id}: {exc}",
        )

    @classmethod
    def _fetch_author_profile(
        cls,
        steam_id: str,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            PROFILE_ENDPOINT.format(steam_id=urllib.parse.quote(steam_id)),
            headers={"User-Agent": "WycccModManager/0.1"},
        )
        for attempt in range(AUTHOR_HTTP_MAX_ATTEMPTS):
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AuthorProfileError(
                        "deadline",
                        f"Author refresh deadline reached: {steam_id}",
                    )
                timeout = min(AUTHOR_HTTP_TIMEOUT_SECONDS, max(0.1, remaining))
            else:
                timeout = AUTHOR_HTTP_TIMEOUT_SECONDS
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    root = ET.fromstring(response.read())
                name = str(root.findtext("steamID") or "").strip()
                if not name:
                    raise AuthorProfileError(
                        "missing_name",
                        f"Steam profile did not expose a persona name: {steam_id}",
                    )
                return {
                    "steam_id": steam_id,
                    "name": name,
                    "profile_url": f"https://steamcommunity.com/profiles/{steam_id}/",
                    "avatar": str(root.findtext("avatarFull") or "").strip(),
                    "fetched_at": int(time.time() * 1000),
                }
            except Exception as exc:
                classified = cls._classify_author_profile_error(exc, steam_id)
                if not classified.retryable or attempt + 1 >= AUTHOR_HTTP_MAX_ATTEMPTS:
                    raise classified from exc
                delay = AUTHOR_HTTP_BACKOFF_SECONDS[attempt]
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AuthorProfileError(
                            "deadline",
                            f"Author refresh deadline reached: {steam_id}",
                        ) from exc
                    delay = min(delay, remaining)
                time.sleep(delay)
        raise AuthorProfileError("unexpected", f"Author refresh failed: {steam_id}")

    @staticmethod
    def _successful_author_record(
        steam_id: str,
        name: str,
        avatar: str,
        now: int,
        cached: Any,
    ) -> dict[str, Any]:
        existing = dict(cached) if isinstance(cached, dict) else {}
        return {
            **existing,
            "steam_id": steam_id,
            "name": str(name).strip(),
            "profile_url": f"https://steamcommunity.com/profiles/{steam_id}/",
            "avatar": str(avatar or existing.get("avatar") or "").strip(),
            "fetched_at": now,
            "last_attempt_at": now,
            "last_error_at": 0,
            "last_error_code": "",
        }

    @staticmethod
    def _failed_author_record(
        steam_id: str,
        cached: Any,
        now: int,
        error: AuthorProfileError,
    ) -> dict[str, Any]:
        existing = dict(cached) if isinstance(cached, dict) else {}
        return {
            **existing,
            "steam_id": steam_id,
            "name": str(existing.get("name") or ""),
            "profile_url": str(
                existing.get("profile_url")
                or f"https://steamcommunity.com/profiles/{steam_id}/"
            ),
            "avatar": str(existing.get("avatar") or ""),
            "fetched_at": int(existing.get("fetched_at") or 0),
            "last_attempt_at": now,
            "last_error_at": now,
            "last_error_code": error.code,
        }

    def _refresh_author_profiles(
        self,
        authors: dict[str, Any],
        creator_ids: list[str],
    ) -> None:
        now = int(time.time() * 1000)
        normalized_ids = list(dict.fromkeys(item for item in creator_ids if item.isdigit()))
        pending: list[str] = []
        cached_count = 0
        for steam_id in normalized_ids:
            cached = authors.get(steam_id)
            if isinstance(cached, dict):
                fetched_at = int(cached.get("fetched_at") or 0)
                last_error_at = int(cached.get("last_error_at") or 0)
                last_attempt_at = int(cached.get("last_attempt_at") or 0)
                if not cached.get("name") and not last_error_at and not last_attempt_at:
                    last_error_at = fetched_at
                if (
                    cached.get("name")
                    and fetched_at > 0
                    and now - fetched_at <= AUTHOR_CACHE_MAX_AGE_MS
                ):
                    cached_count += 1
                    continue
                failure_at = max(last_error_at, last_attempt_at)
                if failure_at > 0 and now - failure_at <= AUTHOR_FAILURE_RETRY_MS:
                    cached_count += 1
                    continue
            pending.append(steam_id)
        if not pending:
            logger.info(
                "Workshop author refresh total=%s cached=%s pending=0 success=0 failed=0 steam_success=0 http_success=0 retained=0 errors=none",
                len(normalized_ids),
                cached_count,
            )
            return

        steam_success = 0
        http_success = 0
        retained = 0
        failures: dict[str, AuthorProfileError] = {}
        try:
            steam_result = query_steam_persona_names(pending)
        except SteamFriendsError as exc:
            logger.warning(
                "Steam Friends author refresh failed code=%s detail=%s",
                exc.code,
                exc,
            )
            unresolved = list(pending)
        else:
            for steam_id in pending:
                name = str(steam_result.names.get(steam_id) or "").strip()
                if not name:
                    continue
                cached = authors.get(steam_id)
                authors[steam_id] = self._successful_author_record(
                    steam_id,
                    name,
                    str(cached.get("avatar") or "") if isinstance(cached, dict) else "",
                    now,
                    cached,
                )
                steam_success += 1
            unresolved = [
                steam_id
                for steam_id in pending
                if not str(steam_result.names.get(steam_id) or "").strip()
            ]

        if unresolved:
            deadline = time.monotonic() + AUTHOR_HTTP_DEADLINE_SECONDS
            workers = min(AUTHOR_HTTP_MAX_WORKERS, len(unresolved))
            with ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="steam-author",
            ) as executor:
                futures = {
                    executor.submit(self._fetch_author_profile, steam_id, deadline): steam_id
                    for steam_id in unresolved
                }
                for future in as_completed(futures):
                    steam_id = futures[future]
                    try:
                        profile = future.result()
                    except AuthorProfileError as exc:
                        failures[steam_id] = exc
                    except Exception as exc:
                        failures[steam_id] = AuthorProfileError(
                            "unexpected",
                            f"Author refresh failed unexpectedly: {steam_id}: {exc}",
                        )
                    else:
                        authors[steam_id] = self._successful_author_record(
                            steam_id,
                            str(profile.get("name") or ""),
                            str(profile.get("avatar") or ""),
                            int(profile.get("fetched_at") or now),
                            authors.get(steam_id),
                        )
                        http_success += 1

        error_counts: Counter[str] = Counter()
        for steam_id, error in failures.items():
            cached = authors.get(steam_id)
            if isinstance(cached, dict) and (cached.get("name") or cached.get("avatar")):
                retained += 1
            authors[steam_id] = self._failed_author_record(steam_id, cached, now, error)
            error_counts[error.code] += 1

        failed = len(failures)
        success = steam_success + http_success
        error_summary = ",".join(
            f"{code}={count}" for code, count in sorted(error_counts.items())
        ) or "none"
        log_method = logger.warning if failed else logger.info
        log_method(
            "Workshop author refresh total=%s cached=%s pending=%s success=%s failed=%s steam_success=%s http_success=%s retained=%s errors=%s",
            len(normalized_ids),
            cached_count,
            len(pending),
            success,
            failed,
            steam_success,
            http_success,
            retained,
            error_summary,
        )
