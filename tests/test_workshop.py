from __future__ import annotations

import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from backend.steam_friends import SteamFriendsError, SteamPersonaResult
from backend.steamworks_bridge import SteamworksBridgeError
from backend.workshop import (
    AUTHOR_FAILURE_RETRY_MS,
    AUTHOR_HTTP_MAX_WORKERS,
    AuthorProfileError,
    CACHE_SCHEMA_VERSION,
    DEPENDENCY_CACHE_WARNING,
    DETAILS_ENDPOINT,
    WorkshopMetadataService,
)


class FakeResponse:
    def __init__(self, payload: dict | bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


class WorkshopMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch(
            "backend.workshop.query_workshop_dependencies",
            return_value={"123": []},
        )
        self.query_dependencies = patcher.start()
        self.addCleanup(patcher.stop)
        friends_patcher = patch(
            "backend.workshop.query_steam_persona_names",
            side_effect=lambda steam_ids: SteamPersonaResult({}, tuple(steam_ids)),
        )
        self.query_friends = friends_patcher.start()
        self.addCleanup(friends_patcher.stop)

    def test_refresh_caches_creator_and_published_time(self) -> None:
        response = FakeResponse(
            {
                "response": {
                    "publishedfiledetails": [
                        {
                            "publishedfileid": "123",
                            "title": "Example Mod",
                            "description": "English description",
                            "creator": "76561198000000000",
                            "time_created": 1_690_000_000,
                            "time_updated": 1_700_000_000,
                            "result": 1,
                        }
                    ]
                }
            }
        )
        profile_response = FakeResponse(
            b'<?xml version="1.0"?><profile><steamID64>76561198000000000</steamID64>'
            b'<steamID><![CDATA[Example Author]]></steamID>'
            b'<avatarFull><![CDATA[https://example.invalid/avatar.jpg]]></avatarFull></profile>'
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            with patch(
                "backend.workshop.urllib.request.urlopen",
                side_effect=[response, profile_response],
            ):
                item = service.refresh(["123"])["123"]

        self.assertEqual(item["creator_id"], "76561198000000000")
        self.assertEqual(item["author"], "Example Author")
        self.assertEqual(item["created_at"], 1_690_000_000_000)
        self.assertEqual(item["updated_at"], 1_700_000_000_000)

    def test_steam_friends_success_avoids_profile_http_and_logs_counts(self) -> None:
        steam_id = "76561198000000000"
        self.query_friends.side_effect = None
        self.query_friends.return_value = SteamPersonaResult(
            {steam_id: "Steam Author"},
            (),
        )
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            authors: dict[str, dict] = {}
            with (
                self.assertLogs("backend.workshop", level="INFO") as logs,
                patch.object(service, "_fetch_author_profile") as http_profile,
            ):
                service._refresh_author_profiles(authors, [steam_id])

        self.assertEqual(authors[steam_id]["name"], "Steam Author")
        self.assertEqual(authors[steam_id]["last_error_code"], "")
        self.assertGreater(authors[steam_id]["last_attempt_at"], 0)
        http_profile.assert_not_called()
        self.assertIn("success=1", "\n".join(logs.output))
        self.assertIn("failed=0", "\n".join(logs.output))

    def test_empty_steam_friends_name_falls_back_to_profile_http(self) -> None:
        steam_id = "76561198000000000"
        self.query_friends.side_effect = None
        self.query_friends.return_value = SteamPersonaResult(
            {steam_id: ""},
            (steam_id,),
        )
        profile = {
            "steam_id": steam_id,
            "name": "HTTP Author",
            "profile_url": f"https://steamcommunity.com/profiles/{steam_id}/",
            "avatar": "",
            "fetched_at": 2_000_000_000_000,
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            authors: dict[str, dict] = {}
            with patch.object(
                service,
                "_fetch_author_profile",
                return_value=profile,
            ) as http_profile:
                service._refresh_author_profiles(authors, [steam_id])

        http_profile.assert_called_once()
        self.assertEqual(authors[steam_id]["name"], "HTTP Author")

    def test_failed_refresh_preserves_cached_name_avatar_and_logs_error_code(self) -> None:
        steam_id = "76561198000000001"
        now = 2_000_000_000_000
        old_fetched_at = now - 8 * 24 * 60 * 60 * 1000
        authors = {
            steam_id: {
                "steam_id": steam_id,
                "name": "Cached Author",
                "avatar": "https://example.invalid/cached.jpg",
                "profile_url": f"https://steamcommunity.com/profiles/{steam_id}/",
                "fetched_at": old_fetched_at,
            }
        }
        self.query_friends.side_effect = SteamFriendsError("steam_unavailable", "offline")
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            with (
                self.assertLogs("backend.workshop", level="WARNING") as logs,
                patch("backend.workshop.time.time", return_value=now / 1000),
                patch("backend.workshop.time.monotonic", return_value=10.0),
                patch.object(
                    service,
                    "_fetch_author_profile",
                    side_effect=AuthorProfileError("timeout", "timed out", retryable=True),
                ),
            ):
                service._refresh_author_profiles(authors, [steam_id])

        self.assertEqual(authors[steam_id]["name"], "Cached Author")
        self.assertEqual(authors[steam_id]["avatar"], "https://example.invalid/cached.jpg")
        self.assertEqual(authors[steam_id]["fetched_at"], old_fetched_at)
        self.assertEqual(authors[steam_id]["last_error_code"], "timeout")
        self.assertEqual(authors[steam_id]["last_error_at"], now)
        self.assertIn("retained=1", "\n".join(logs.output))
        self.assertIn("failed=1", "\n".join(logs.output))
        self.assertIn("timeout=1", "\n".join(logs.output))

    def test_transient_http_error_retries_but_permanent_404_does_not(self) -> None:
        service = WorkshopMetadataService(Path("unused-cache.json"))
        transient = urllib.error.URLError(socket.timeout("timed out"))
        success = FakeResponse(b"<profile><steamID>Retry Author</steamID></profile>")
        with (
            patch(
                "backend.workshop.urllib.request.urlopen",
                side_effect=[transient, success],
            ) as request,
            patch("backend.workshop.time.sleep") as sleep,
        ):
            profile = service._fetch_author_profile("76561198000000002")

        self.assertEqual(profile["name"], "Retry Author")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.5)

        permanent = urllib.error.HTTPError(
            "https://example.invalid",
            404,
            "missing",
            {},
            None,
        )
        with patch(
            "backend.workshop.urllib.request.urlopen",
            side_effect=permanent,
        ) as request:
            with self.assertRaises(AuthorProfileError) as raised:
                service._fetch_author_profile("76561198000000002")
        self.assertEqual(raised.exception.code, "http_404")
        self.assertFalse(raised.exception.retryable)
        request.assert_called_once()

    def test_author_failure_cooldown_uses_legacy_empty_record_timestamp(self) -> None:
        steam_id = "76561198000000003"
        now = 2_000_000_000_000
        authors = {
            steam_id: {
                "steam_id": steam_id,
                "name": "",
                "avatar": "",
                "fetched_at": now - AUTHOR_FAILURE_RETRY_MS + 1,
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            with patch("backend.workshop.time.time", return_value=now / 1000):
                service._refresh_author_profiles(authors, [steam_id])

        self.query_friends.assert_not_called()

    def test_author_http_concurrency_is_limited_to_two_workers(self) -> None:
        self.assertEqual(AUTHOR_HTTP_MAX_WORKERS, 2)

    def test_selected_language_uses_localized_title_and_falls_back_per_field(self) -> None:
        details_response = FakeResponse(
            {
                "response": {
                    "publishedfiledetails": [
                        {
                            "publishedfileid": "123",
                            "title": "English title",
                            "description": "English description",
                            "creator": "76561198000000000",
                            "time_created": 1_690_000_000,
                            "time_updated": 1_700_000_000,
                            "result": 1,
                        }
                    ]
                }
            }
        )
        profile_response = FakeResponse(
            b'<?xml version="1.0"?><profile><steamID64>76561198000000000</steamID64>'
            b'<steamID><![CDATA[Example Author]]></steamID></profile>'
        )

        def fake_urlopen(request, timeout=0):
            if request.full_url == DETAILS_ENDPOINT:
                return details_response
            if "steamcommunity.com/profiles" in request.full_url:
                return profile_response
            raise AssertionError(request.full_url)

        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            with (
                patch("backend.workshop.urllib.request.urlopen", side_effect=fake_urlopen),
                patch(
                    "backend.workshop.query_workshop_languages",
                    return_value={
                        "schinese": {
                            "123": {
                                "title": "中文标题",
                                "description": "",
                                "creator_id": "76561198000000000",
                                "updated_at": 1_700_000_000_000,
                            }
                        }
                    },
                ) as query_languages,
            ):
                localized = service.refresh(["123"], "zh-CN")["123"]
            english = service.get_many(["123"], "en-US")["123"]

        self.assertEqual(localized["title"], "中文标题")
        self.assertEqual(localized["description"], "English description")
        self.assertEqual(localized["title_language"], "schinese")
        self.assertEqual(localized["description_language"], "english")
        self.assertEqual(english["title"], "English title")
        self.assertEqual(english["description"], "English description")
        query_languages.assert_called_once_with(["123"], ["schinese"])

    def test_schema_three_page_failure_is_immediately_replaced_by_steamworks(self) -> None:
        now = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "title": "English title",
                                "description": "English description",
                                "updated_at": 1_700_000_000_000,
                                "localized": {
                                    "english": {
                                        "title": "English title",
                                        "description": "English description",
                                    },
                                    "schinese": {
                                        "title": "",
                                        "description": "",
                                        "failed": True,
                                        "last_error_at": now,
                                    },
                                },
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            with (
                patch.object(service, "_refresh_english_details"),
                patch(
                    "backend.workshop.query_workshop_languages",
                    return_value={
                        "schinese": {
                            "123": {
                                "title": "新的中文标题",
                                "description": "新的中文描述",
                                "updated_at": 1_700_000_000_000,
                            }
                        }
                    },
                ) as query_languages,
            ):
                item = service.refresh(["123"], "zh-CN")["123"]

        self.assertEqual(item["title"], "新的中文标题")
        self.assertEqual(item["description"], "新的中文描述")
        query_languages.assert_called_once_with(["123"], ["schinese"])

    def test_steamworks_failure_keeps_english_fallback_and_exposes_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "title": "English title",
                                "description": "English description",
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            with (
                patch.object(service, "_refresh_english_details"),
                patch(
                    "backend.workshop.query_workshop_languages",
                    side_effect=SteamworksBridgeError("Steam is unavailable"),
                ),
            ):
                item = service.refresh(["123"], "zh-CN")["123"]

        self.assertEqual(item["title"], "English title")
        self.assertEqual(item["description"], "English description")
        self.assertIn("Steamworks", service.last_refresh_warning)

    def test_schema_two_cache_is_treated_as_english_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "title": "Legacy English title",
                                "description": "Legacy English description",
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            item = WorkshopMetadataService(cache_path).get_many(["123"], "ru-RU")["123"]

        self.assertEqual(item["title"], "Legacy English title")
        self.assertEqual(item["description"], "Legacy English description")
        self.assertEqual(item["title_language"], "english")
        self.assertEqual(item["description_language"], "english")

    def test_each_supported_interface_language_selects_its_workshop_variant(self) -> None:
        language_pairs = {
            "zh-CN": "schinese",
            "en-US": "english",
            "ko-KR": "koreana",
            "ru-RU": "russian",
            "ja-JP": "japanese",
            "es-ES": "spanish",
        }
        localized = {
            steam_language: {
                "title": f"title-{steam_language}",
                "description": f"description-{steam_language}",
                "fetched_at": 1,
                "source_updated_at": 1,
                "failed": False,
            }
            for steam_language in language_pairs.values()
        }

        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "title": "title-english",
                                "description": "description-english",
                                "localized": localized,
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            for interface_language, steam_language in language_pairs.items():
                with self.subTest(interface_language=interface_language):
                    item = service.get_many(["123"], interface_language)["123"]
                    self.assertEqual(item["title"], f"title-{steam_language}")
                    self.assertEqual(item["description"], f"description-{steam_language}")
                    self.assertEqual(item["requested_language"], steam_language)

    def test_publish_copy_refresh_fetches_only_english_and_the_requested_language(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "title": "English title",
                                "description": "English description",
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            with (
                patch.object(service, "_refresh_english_details") as refresh_english,
                patch(
                    "backend.workshop.query_workshop_languages",
                    return_value={
                        "russian": {
                            "123": {
                                "title": "Русский заголовок",
                                "description": "Русское описание",
                            }
                        }
                    },
                ) as query_languages,
            ):
                item = service.refresh_localized(["123"], "ru-RU")["123"]

        refresh_english.assert_called_once()
        query_languages.assert_called_once_with(["123"], ["russian"])
        self.assertEqual(item["title"], "Русский заголовок")
        self.assertEqual(item["description"], "Русское описание")
        self.assertEqual(item["description_language"], "russian")

    def test_steam_english_fallback_is_not_mislabeled_as_a_translation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "title": "English title",
                                "description": "English description",
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            with (
                patch.object(service, "_refresh_english_details"),
                patch(
                    "backend.workshop.query_workshop_languages",
                    return_value={
                        "schinese": {
                            "123": {
                                "title": "English title",
                                "description": "English description",
                            }
                        }
                    },
                ),
            ):
                item = service.refresh_localized(["123"], "zh-CN")["123"]

        self.assertEqual(item["title"], "English title")
        self.assertEqual(item["description"], "English description")
        self.assertEqual(item["title_language"], "english")
        self.assertEqual(item["description_language"], "english")

    def test_dependency_refresh_failure_explains_the_cached_fallback(self) -> None:
        self.query_dependencies.side_effect = SteamworksBridgeError("Steam is unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            item = service.ensure_dependencies(["123"], "zh-CN")["123"]

        self.assertEqual(service.last_refresh_warning, DEPENDENCY_CACHE_WARNING)
        self.assertEqual(item["required_workshop_items"], [])

    def test_dependency_refresh_caches_required_items_with_titles(self) -> None:
        self.query_dependencies.return_value = {
            "123": [
                {"workshop_id": "456", "title": "Required Mod"},
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            service = WorkshopMetadataService(Path(temporary) / "workshop_cache.json")
            item = service.ensure_dependencies(["123"], "zh-CN")["123"]
            cached = service.get_many(["123"], "zh-CN")["123"]

        self.assertEqual(
            item["required_workshop_items"],
            [{"workshop_id": "456", "title": "Required Mod"}],
        )
        self.assertEqual(cached["required_workshop_items"], item["required_workshop_items"])
        self.query_dependencies.assert_called_once_with(["123"], "schinese")

    def test_dependency_refresh_preserves_only_the_failed_items_cache(self) -> None:
        self.query_dependencies.return_value = {
            "123": [{"workshop_id": "456", "title": "Fresh dependency"}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 5,
                        "items": {
                            "789": {
                                "workshop_id": "789",
                                "required_workshop_items": [
                                    {"workshop_id": "999", "title": "Cached dependency"}
                                ],
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            result = service.ensure_dependencies(["123", "789"], "zh-CN")

        self.assertEqual(
            result["123"]["required_workshop_items"],
            [{"workshop_id": "456", "title": "Fresh dependency"}],
        )
        self.assertEqual(
            result["789"]["required_workshop_items"],
            [{"workshop_id": "999", "title": "Cached dependency"}],
        )
        self.assertEqual(service.last_refresh_warning, DEPENDENCY_CACHE_WARNING)

    def test_schema_five_failure_retries_immediately_with_the_fixed_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "workshop_cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 5,
                        "items": {
                            "123": {
                                "workshop_id": "123",
                                "dependencies_last_error_at": 9_999_999_999_999,
                                "required_workshop_items": [
                                    {"workshop_id": "456", "title": "Old cache"}
                                ],
                            }
                        },
                        "authors": {},
                    }
                ),
                encoding="utf-8",
            )
            service = WorkshopMetadataService(cache_path)
            with (
                patch.object(service, "_refresh_english_details"),
                patch.object(service, "_refresh_author_profiles"),
            ):
                item = service.refresh(["123"], "en-US")["123"]
            persisted = json.loads(cache_path.read_text(encoding="utf-8"))

        self.query_dependencies.assert_called_once_with(["123"], "english")
        self.assertEqual(item["required_workshop_items"], [])
        self.assertEqual(item["dependencies_last_error_at"], 0)
        self.assertEqual(persisted["schema_version"], CACHE_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
