from __future__ import annotations

import io
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.steam_friends import (
    SteamFriendsError,
    SteamPersonaResult,
    query_steam_persona_names,
    query_steam_persona_names_isolated,
    run_steam_friends_worker,
)


class FakeFunction:
    def __init__(self, implementation):
        self.implementation = implementation
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.implementation(*args)


class FakeSteamDll:
    def __init__(self, names_after_callbacks=None, init_success=True, friends=1234):
        self.names_after_callbacks = names_after_callbacks or {}
        self.callback_count = 0
        self.requested: list[tuple[int, bool]] = []
        self.shutdown_count = 0
        self.SteamAPI_InitSafe = FakeFunction(lambda: init_success)
        self.SteamAPI_SteamFriends_v017 = FakeFunction(lambda: friends)
        self.SteamAPI_ISteamFriends_RequestUserInformation = FakeFunction(self._request)
        self.SteamAPI_ISteamFriends_GetFriendPersonaName = FakeFunction(self._get_name)
        self.SteamAPI_RunCallbacks = FakeFunction(self._run_callbacks)
        self.SteamAPI_Shutdown = FakeFunction(self._shutdown)

    def _request(self, _friends, steam_id, name_only):
        self.requested.append((int(steam_id), bool(name_only)))
        return True

    def _run_callbacks(self):
        self.callback_count += 1

    def _get_name(self, _friends, steam_id):
        required_callbacks, name = self.names_after_callbacks.get(
            str(int(steam_id)),
            (10_000, "[unknown]"),
        )
        if self.callback_count < required_callbacks:
            return b"[unknown]"
        return name.encode("utf-8")

    def _shutdown(self):
        self.shutdown_count += 1


class SteamFriendsTests(unittest.TestCase):
    def test_worker_uses_utf8_transport_on_a_gbk_system(self) -> None:
        request_payload = json.dumps(
            {
                "steam_ids": ["76561198000000008"],
                "app_id": 1_142_710,
                "root": r"C:\游戏",
                "timeout_seconds": 0.25,
                "poll_interval": 0.01,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        source = io.TextIOWrapper(io.BytesIO(request_payload), encoding="gbk")
        destination_buffer = io.BytesIO()
        destination = io.TextIOWrapper(destination_buffer, encoding="gbk")
        dll = FakeSteamDll(
            names_after_callbacks={"76561198000000008": (1, "☼")}
        )

        with (
            patch("backend.steam_friends.sys.stdin", source),
            patch("backend.steam_friends.sys.stdout", destination),
            patch("backend.steam_friends._load_library", return_value=dll) as loader,
        ):
            try:
                exit_code = run_steam_friends_worker()
            except UnicodeError as exc:
                self.fail(f"worker leaked UTF-8 text through the GBK transport: {exc}")

        destination.flush()
        payload = json.loads(
            destination_buffer.getvalue().decode("utf-8").split("=", 1)[1]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["names"], {"76561198000000008": "☼"})
        self.assertEqual(loader.call_args.args[0], Path(r"C:\游戏"))

    def test_worker_serializes_the_in_process_steam_result(self) -> None:
        request = io.StringIO(
            json.dumps(
                {
                    "steam_ids": ["76561198000000007"],
                    "app_id": 1_142_710,
                    "root": "",
                    "timeout_seconds": 0.25,
                    "poll_interval": 0.01,
                }
            )
        )
        response = io.StringIO()
        dll = FakeSteamDll(
            names_after_callbacks={"76561198000000007": (1, "Worker Author")}
        )

        with patch("backend.steam_friends._load_library", return_value=dll):
            exit_code = run_steam_friends_worker(request, response)

        self.assertEqual(exit_code, 0)
        result_line = response.getvalue().strip()
        self.assertTrue(result_line.startswith("WMM_STEAM_FRIENDS_RESULT="))
        payload = json.loads(result_line.split("=", 1)[1])
        self.assertEqual(
            payload,
            {
                "ok": True,
                "names": {"76561198000000007": "Worker Author"},
                "unresolved": [],
            },
        )

    def test_isolated_query_returns_worker_result_without_loading_steam_in_parent(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                'WMM_STEAM_FRIENDS_RESULT={"ok":true,'
                '"names":{"76561198000000001":"Worker Author"},'
                '"unresolved":[]}\n'
            ),
            stderr="native Steam diagnostic",
        )

        with (
            patch("subprocess.run", return_value=completed) as run,
            patch("backend.steam_friends._load_library") as loader,
        ):
            result = query_steam_persona_names_isolated(
                ["76561198000000001"],
                timeout_seconds=0.25,
            )

        self.assertEqual(
            result,
            SteamPersonaResult({"76561198000000001": "Worker Author"}, ()),
        )
        loader.assert_not_called()
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn("--steam-friends-worker", command)
        self.assertTrue(Path(command[1]).is_absolute())
        self.assertEqual(Path(command[1]).name, "main.py")
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["steam_ids"], ["76561198000000001"])
        self.assertEqual(request["timeout_seconds"], 0.25)

    def test_isolated_query_classifies_a_worker_exit_without_killing_parent(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="Steam worker stopped",
        )

        with patch("subprocess.run", return_value=completed):
            with self.assertRaises(SteamFriendsError) as raised:
                query_steam_persona_names_isolated(["76561198000000002"])

        self.assertEqual(raised.exception.code, "steam_unavailable")
        self.assertIn("exit 1", str(raised.exception))

    def test_empty_query_returns_without_loading_steam(self) -> None:
        with patch("backend.steam_friends._load_library") as loader:
            result = query_steam_persona_names([])

        self.assertEqual(result, SteamPersonaResult({}, ()))
        loader.assert_not_called()

    def test_requests_users_and_pumps_callbacks_until_names_arrive(self) -> None:
        dll = FakeSteamDll(
            names_after_callbacks={
                "76561198000000001": (1, "Author One"),
                "76561198000000002": (2, "作者二"),
            }
        )
        with (
            patch("backend.steam_friends._load_library", return_value=dll),
            patch("backend.steam_friends.time.sleep"),
        ):
            result = query_steam_persona_names(
                ["76561198000000001", "invalid", "76561198000000002", "76561198000000001"],
                timeout_seconds=1,
            )

        self.assertEqual(
            result.names,
            {
                "76561198000000001": "Author One",
                "76561198000000002": "作者二",
            },
        )
        self.assertEqual(result.unresolved, ())
        self.assertEqual(
            dll.requested,
            [
                (76561198000000001, True),
                (76561198000000002, True),
            ],
        )
        self.assertGreaterEqual(dll.callback_count, 2)
        self.assertEqual(dll.shutdown_count, 1)

    def test_timeout_returns_unresolved_ids_and_shuts_down(self) -> None:
        dll = FakeSteamDll()
        monotonic_values = iter((10.0, 10.0, 10.1))
        with (
            patch("backend.steam_friends._load_library", return_value=dll),
            patch("backend.steam_friends.time.monotonic", side_effect=monotonic_values),
            patch("backend.steam_friends.time.sleep"),
        ):
            result = query_steam_persona_names(
                ["76561198000000003"],
                timeout_seconds=0.1,
            )

        self.assertEqual(result.names, {})
        self.assertEqual(result.unresolved, ("76561198000000003",))
        self.assertEqual(dll.shutdown_count, 1)

    def test_init_failure_has_classified_error_and_does_not_shutdown(self) -> None:
        dll = FakeSteamDll(init_success=False)
        with patch("backend.steam_friends._load_library", return_value=dll):
            with self.assertRaisesRegex(
                SteamFriendsError,
                "Steam API initialization failed",
            ) as raised:
                query_steam_persona_names(["76561198000000004"])

        self.assertEqual(raised.exception.code, "steam_unavailable")
        self.assertEqual(dll.shutdown_count, 0)

    def test_missing_friends_interface_is_classified_and_shuts_down(self) -> None:
        dll = FakeSteamDll(friends=0)
        with patch("backend.steam_friends._load_library", return_value=dll):
            with self.assertRaises(SteamFriendsError) as raised:
                query_steam_persona_names(["76561198000000005"])

        self.assertEqual(raised.exception.code, "steam_unavailable")
        self.assertEqual(dll.shutdown_count, 1)

    def test_app_environment_is_restored_after_query(self) -> None:
        dll = FakeSteamDll(names_after_callbacks={"76561198000000006": (1, "Author")})
        original_app_id = os.environ.get("SteamAppId")
        original_game_id = os.environ.get("SteamGameId")
        os.environ["SteamAppId"] = "old-app"
        os.environ.pop("SteamGameId", None)
        try:
            with patch("backend.steam_friends._load_library", return_value=dll):
                query_steam_persona_names(["76561198000000006"])
            self.assertEqual(os.environ.get("SteamAppId"), "old-app")
            self.assertNotIn("SteamGameId", os.environ)
        finally:
            if original_app_id is None:
                os.environ.pop("SteamAppId", None)
            else:
                os.environ["SteamAppId"] = original_app_id
            if original_game_id is None:
                os.environ.pop("SteamGameId", None)
            else:
                os.environ["SteamGameId"] = original_game_id


if __name__ == "__main__":
    unittest.main()
