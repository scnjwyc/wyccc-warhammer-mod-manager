from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.mod_profiles import parse_mod_profile
from tests.helpers import make_asset


class OfficialModProfileTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
