from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.mod_profiles import parse_mod_profile
from backend.share_adapters import OfficialModLookupKeyAdapter
from backend.share_code import share_context
from tests.helpers import make_asset, write_pack


class OfficialModProfileTests(unittest.TestCase):
    def test_profile_files_and_pasted_text_share_one_parser(self) -> None:
        content = "\n".join(
            [
                "# TW Mod Profile",
                "mod_lookup_key://abc@steam_workshop:1142710/123@10/folder/My%20Mod.pack",
                "mod_lookup_key://def@steam_workshop:594570/456@20/other_game.pack",
                "unsupported line",
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "Shared.twmods"
            profile.write_text(content, encoding="utf-8")
            parsed = parse_mod_profile(profile)

        pasted = OfficialModLookupKeyAdapter().deserialize(
            content, share_context("warhammer3")
        )
        self.assertEqual(
            parsed["references"],
            [
                {"workshop_id": mod.workshop_id, "pack_name": mod.pack_name}
                for mod in pasted.mods
            ],
        )
        self.assertEqual(parsed["references"], [{"workshop_id": "123", "pack_name": "My Mod.pack"}])
        self.assertEqual(parsed["unrecognized_lines"], pasted.warnings)

    def test_parses_twmods_in_file_order_and_deduplicates_exact_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "My Profile.twmods"
            profile.write_text(
                "\n".join(
                    [
                        "# TW Mod Profile",
                        "mod_lookup_key://abc@steam_workshop:1142710/123@10/First.pack",
                        "mod_lookup_key://def@steam_workshop:1142710/456@20/folder/second.pack",
                        "mod_lookup_key://duplicate@steam_workshop:1142710/123@30/FIRST.PACK",
                        "unsupported line",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = parse_mod_profile(profile)

        self.assertEqual(parsed["name"], "My Profile")
        self.assertEqual(
            [(item["workshop_id"], item["pack_name"]) for item in parsed["references"]],
            [("123", "First.pack"), ("456", "second.pack")],
        )
        self.assertEqual(parsed["unrecognized_lines"], ["unsupported line"])

    def test_preview_and_import_support_new_or_replace_with_pending_items(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "Official.twmods"
            profile.write_text(
                "\n".join(
                    [
                        "mod_lookup_key://abc@steam_workshop:1142710/123@10/installed.pack",
                        "mod_lookup_key://def@steam_workshop:1142710/456@20/missing.pack",
                    ]
                ),
                encoding="utf-8",
            )
            api = API(root / "state")
            installed_path = root / "workshop" / "123" / "installed.pack"
            installed_path.parent.mkdir(parents=True)
            installed_path.write_bytes(b"PFH5")
            installed = make_asset(
                installed_path,
                "steam:123:installed.pack",
                "workshop",
                "123",
            )
            api._assets = {installed.id: installed}
            with patch(
                "backend.api.query_workshop_subscription_status",
                return_value=[
                    {"workshop_id": "123", "title": "Installed", "subscribed": True},
                    {"workshop_id": "456", "title": "Missing", "subscribed": False},
                ],
            ):
                preview = api.call("preview_mod_profile", [str(profile)])

            self.assertTrue(preview["ok"])
            self.assertEqual(preview["data"]["ordered_mod_ids"], [installed.id])
            self.assertEqual(preview["data"]["unsubscribed"][0]["workshop_id"], "456")

            created = api.call("import_mod_profile", [str(profile), "new"])
            self.assertTrue(created["ok"])
            self.assertEqual(created["data"]["current_playset"]["name"], "Official")
            self.assertEqual(created["data"]["ordered_mod_ids"], [installed.id])
            self.assertEqual(created["data"]["pending_workshop_ids"], ["456"])
            self.assertTrue(created["data"]["missing_mod_ids"][0].startswith("pending:steam:456:"))

            replaced = api.call("import_mod_profile", [str(profile), "replace"])
            self.assertTrue(replaced["ok"])
            self.assertEqual(replaced["data"]["current_playset"]["name"], "Official")


class _RecordingService:
    """Wraps the real service to prove .twmods import goes through an adapter."""

    def __init__(self) -> None:
        from backend.share_code import default_share_code_service

        self.inner = default_share_code_service()
        self.calls: list[str] = []

    def deserialize(self, value, context):
        self.calls.append("deserialize")
        return self.inner.deserialize(value, context)

    def serialize(self, mods, context, format_id=None):
        self.calls.append("serialize")
        return self.inner.serialize(mods, context, format_id=format_id)


class OfficialModProfileAdapterTests(unittest.TestCase):
    def _profile(self, root: Path, content: str, name: str = "Bom.twmods") -> Path:
        path = root / name
        # Write the exact bytes the launcher produces: UTF-8 BOM + CRLF.
        path.write_bytes(b"\xef\xbb\xbf" + content.replace("\n", "\r\n").encode("utf-8"))
        return path

    def test_profile_file_import_goes_through_the_adapter_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(
                root,
                "# TW Mod Profile\n"
                "mod_lookup_key://abc@steam_workshop:1142710/123@10/installed.pack",
            )
            api = API(root / "state")
            installed = make_asset(
                write_pack(root / "workshop" / "123" / "installed.pack"),
                "installed-id",
                "workshop",
                "123",
            )
            api._assets = {installed.id: installed}
            recorded = _RecordingService()
            api.share_codes = recorded

            with patch("backend.api.query_workshop_subscription_status", return_value=[]):
                preview = api.call("preview_mod_profile", [str(profile)])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["ordered_mod_ids"], ["installed-id"])
            self.assertEqual(preview["data"]["unrecognized_lines"], [])

            imported = api.call("import_mod_profile", [str(profile), "new"])
            self.assertTrue(imported["ok"], imported)

            self.assertEqual(recorded.calls, ["deserialize", "deserialize"])

    def test_profile_without_official_lines_is_not_parsed_as_legacy(self) -> None:
        # "123;0" is valid legacy share-code text, but a .twmods file that has no
        # mod_lookup_key:// line must be rejected instead of imported as a legacy code.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(root, "# TW Mod Profile\n123;0|456;1", "Legacy.twmods")
            with self.assertRaisesRegex(ValueError, "配置中未识别到 Warhammer III 工坊 MOD"):
                parse_mod_profile(profile)

    def test_profile_comment_and_blank_lines_are_not_mods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = self._profile(
                root,
                "# TW Mod Profile\n\n"
                "mod_lookup_key://abc@steam_workshop:1142710/123@10/one.pack\n"
                "unsupported line\n",
            )
            parsed = parse_mod_profile(profile)
        self.assertEqual(parsed["references"], [{"workshop_id": "123", "pack_name": "one.pack"}])
        self.assertEqual(parsed["unrecognized_lines"], ["unsupported line"])


if __name__ == "__main__":
    unittest.main()
