from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.api import API
from tests.helpers import write_pack


def _prepare(root: Path) -> tuple[API, dict[str, str]]:
    game = root / "Total War WARHAMMER III"
    data = game / "data"
    data.mkdir(parents=True)
    (game / "Warhammer3.exe").write_bytes(b"")
    (data / "manifest.txt").write_text("data.pack\t0\ndb.pack\t0\n", encoding="utf-8")
    write_pack(data / "data.pack")
    write_pack(data / "db.pack")
    write_pack(data / "a.pack")
    write_pack(data / "b.pack")
    api = API(root / "state")
    saved = api.call(
        "save_settings",
        [{"game_path": str(game), "workshop_path": "", "fetch_workshop_metadata": False}],
    )
    if not saved["ok"]:
        raise AssertionError(saved)
    scan = api.call("scan_mods", [False])
    if not scan["ok"]:
        raise AssertionError(scan)
    by_pack = {mod["pack_name"]: mod["id"] for mod in scan["data"]["mods"]}
    return api, by_pack


class PlaysetJsonApiTests(unittest.TestCase):
    def test_export_preview_and_import_new_playset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, by_pack = _prepare(root)
            a_id, b_id = by_pack["a.pack"], by_pack["b.pack"]
            api._assets[a_id].description = "Description A"
            created = api.call("create_playset", ["Original", [a_id, b_id]])
            self.assertTrue(created["ok"], created)

            target = root / "export.json"
            exported = api.call("export_playset_json", [True, str(target)])
            self.assertTrue(exported["ok"], exported)
            self.assertTrue(exported["data"]["exported"])
            self.assertGreater(exported["data"]["bytes"], 0)
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual([mod["id"] for mod in payload["mods"]], [a_id, b_id])
            self.assertEqual([mod["load_order"] for mod in payload["mods"]], [1, 2])
            self.assertEqual(payload["mods"][0]["description"], "Description A")
            self.assertEqual(payload["description_mode"], "compact")
            self.assertEqual(payload["playset_name"], "Original")

            preview = api.call("preview_import_playset_json", [str(target)])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["resolved_mod_ids"], [a_id, b_id])
            self.assertEqual(preview["data"]["missing"], [])

            imported = api.call("import_playset_json", [str(target), "new"])
            self.assertTrue(imported["ok"], imported)
            self.assertEqual(imported["data"]["current_playset"]["mod_ids"], [a_id, b_id])
            self.assertEqual(imported["data"]["imported_count"], 2)

    def test_import_reports_missing_mods_without_subscribing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, by_pack = _prepare(root)
            a_id = by_pack["a.pack"]
            payload = {
                "schema_version": 1,
                "type": "wyccc-mod-manager-playset",
                "game": "warhammer3",
                "playset_name": "With missing",
                "mods": [
                    {"id": a_id},
                    {"workshop_id": "999999", "pack_name": "missing.pack"},
                ],
            }
            path = root / "import.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            preview = api.call("preview_import_playset_json", [str(path)])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["resolved_mod_ids"], [a_id])
            self.assertEqual(len(preview["data"]["missing"]), 1)

            imported = api.call("import_playset_json", [str(path), "current"])
            self.assertTrue(imported["ok"], imported)
            self.assertEqual(imported["data"]["current_playset"]["mod_ids"], [a_id])
            self.assertEqual(len(imported["data"]["missing"]), 1)

    def test_import_accepts_an_edited_payload_without_game_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, by_pack = _prepare(root)
            a_id, b_id = by_pack["a.pack"], by_pack["b.pack"]
            path = root / "ai-sorted.json"
            path.write_text(json.dumps([b_id, a_id]), encoding="utf-8")

            preview = api.call("preview_import_playset_json", [str(path)])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["game"], "warhammer3")
            self.assertEqual(preview["data"]["resolved_mod_ids"], [b_id, a_id])

            imported = api.call("import_playset_json", [str(path), "new"])
            self.assertTrue(imported["ok"], imported)
            self.assertEqual(imported["data"]["current_playset"]["name"], "ai-sorted")
            self.assertEqual(
                imported["data"]["current_playset"]["mod_ids"], [b_id, a_id]
            )

    def test_accepts_game_id_with_different_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, by_pack = _prepare(root)
            a_id = by_pack["a.pack"]
            path = root / "case.json"
            path.write_text(
                json.dumps({"game": "WARHAMMER3", "mods": [{"id": a_id}]}),
                encoding="utf-8",
            )
            preview = api.call("preview_import_playset_json", [str(path)])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["game"], "warhammer3")
            self.assertEqual(preview["data"]["resolved_mod_ids"], [a_id])

    def test_rejects_a_json_for_another_game(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api, _by_pack = _prepare(root)
            payload = {
                "schema_version": 1,
                "type": "wyccc-mod-manager-playset",
                "game": "three_kingdoms",
                "playset_name": "Wrong game",
                "mods": [{"id": "a"}],
            }
            path = root / "wrong.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = api.call("preview_import_playset_json", [str(path)])
            self.assertFalse(result["ok"])
            self.assertIn("游戏", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
