from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.steamworks_bridge import (
    RESULT_PREFIX,
    SteamworksBridgeError,
    find_node_executable,
    perform_workshop_operation,
    publish_workshop_item,
    query_workshop_dependencies,
    query_workshop_languages,
)


class SteamworksBridgeTests(unittest.TestCase):
    def test_packaged_node_runtime_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root / "steam_runtime" / "node.exe"
            node.parent.mkdir(parents=True)
            node.write_bytes(b"node fixture")

            with patch("backend.steamworks_bridge._node_is_supported", return_value=True):
                self.assertEqual(find_node_executable(root), node.resolve())

    def test_query_parses_prefixed_json_and_preserves_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "steam_runtime" / "workshop_bridge.js"
            script.parent.mkdir(parents=True)
            script.write_text("// fixture", encoding="utf-8")
            node = root / "node.exe"
            node.write_bytes(b"node fixture")
            payload = {
                "ok": True,
                "languages": {
                    "schinese": {
                        "123": {
                            "title": "中文标题",
                            "description": "中文描述",
                        }
                    }
                },
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"native log\n{RESULT_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n",
                stderr="",
            )

            with (
                patch("backend.steamworks_bridge.find_node_executable", return_value=node),
                patch("backend.steamworks_bridge.subprocess.run", return_value=completed) as run,
            ):
                result = query_workshop_languages(
                    ["123", "123", "not-an-id"],
                    ["schinese"],
                    root=root,
                )

        self.assertEqual(result["schinese"]["123"]["title"], "中文标题")
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["operation"], "query")
        self.assertEqual(request["ids"], ["123"])
        self.assertEqual(request["languages"], ["schinese"])

    def test_query_reports_missing_bridge_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "steam_runtime" / "workshop_bridge.js"
            script.parent.mkdir(parents=True)
            script.write_text("// fixture", encoding="utf-8")
            node = root / "node.exe"
            node.write_bytes(b"node fixture")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="native output only",
                stderr="Steam initialization failed",
            )

            with (
                patch("backend.steamworks_bridge.find_node_executable", return_value=node),
                patch("backend.steamworks_bridge.subprocess.run", return_value=completed),
            ):
                with self.assertRaisesRegex(SteamworksBridgeError, "Steam initialization failed"):
                    query_workshop_languages(["123"], ["schinese"], root=root)

    def test_dependency_query_parses_required_item_titles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "steam_runtime" / "workshop_bridge.js"
            script.parent.mkdir(parents=True)
            script.write_text("// fixture", encoding="utf-8")
            node = root / "node.exe"
            node.write_bytes(b"node fixture")
            payload = {
                "ok": True,
                "dependencies": {
                    "123": [{"workshop_id": "456", "title": "依赖 MOD"}],
                },
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{RESULT_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n",
                stderr="",
            )
            with (
                patch("backend.steamworks_bridge.find_node_executable", return_value=node),
                patch("backend.steamworks_bridge.subprocess.run", return_value=completed) as run,
            ):
                result = query_workshop_dependencies(
                    ["123", "invalid"],
                    "schinese",
                    root=root,
                )

        self.assertEqual(result["123"][0]["title"], "依赖 MOD")
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["operation"], "query_dependencies")
        self.assertEqual(request["ids"], ["123"])
        self.assertEqual(request["language"], "schinese")

    def test_workshop_operation_sends_force_update_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "steam_runtime" / "workshop_bridge.js"
            script.parent.mkdir(parents=True)
            script.write_text("// fixture", encoding="utf-8")
            node = root / "node.exe"
            node.write_bytes(b"node fixture")
            payload = {
                "ok": True,
                "result": {
                    "operation": "force_update",
                    "workshop_id": "123",
                    "accepted": True,
                },
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{RESULT_PREFIX}{json.dumps(payload)}\n",
                stderr="",
            )

            with (
                patch("backend.steamworks_bridge.find_node_executable", return_value=node),
                patch("backend.steamworks_bridge.subprocess.run", return_value=completed) as run,
            ):
                result = perform_workshop_operation("force_update", "123", root=root)

        self.assertTrue(result["accepted"])
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["operation"], "force_update")
        self.assertEqual(request["id"], "123")

    def test_publish_item_sends_content_metadata_and_existing_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "steam_runtime" / "workshop_bridge.js"
            script.parent.mkdir(parents=True)
            script.write_text("// fixture", encoding="utf-8")
            node = root / "node.exe"
            node.write_bytes(b"node fixture")
            content = root / "content"
            content.mkdir()
            preview = root / "preview.png"
            preview.write_bytes(b"preview")
            payload = {
                "ok": True,
                "result": {
                    "operation": "update",
                    "workshop_id": "123",
                    "created": False,
                    "owner_id": "76561198000000000",
                    "owner_name": "Wyccc",
                    "needs_to_accept_agreement": False,
                },
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{RESULT_PREFIX}{json.dumps(payload)}\n",
                stderr="",
            )

            with (
                patch("backend.steamworks_bridge.find_node_executable", return_value=node),
                patch("backend.steamworks_bridge.subprocess.run", return_value=completed) as run,
            ):
                result = publish_workshop_item(
                    content_path=content,
                    preview_path=preview,
                    title="中文标题",
                    description="中文描述",
                    change_note="更新说明",
                    tags=["mod", "ui"],
                    visibility=3,
                    workshop_id="123",
                    app_id=1142710,
                    root=root,
                )

        self.assertEqual(result["owner_name"], "Wyccc")
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["operation"], "publish_item")
        self.assertEqual(request["id"], "123")
        self.assertEqual(request["title"], "中文标题")
        self.assertEqual(request["description"], "中文描述")
        self.assertEqual(request["changeNote"], "更新说明")
        self.assertEqual(request["tags"], ["mod", "ui"])
        self.assertEqual(request["visibility"], 3)


if __name__ == "__main__":
    unittest.main()
