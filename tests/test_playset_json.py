from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from backend.playset_json import (
    DESCRIPTION_LIMIT,
    MAX_FILE_BYTES,
    build_export_payload,
    compact_description,
    parse_import_payload,
    read_import_file,
    safe_export_name,
    write_export_file,
)
from backend.share import pending_workshop_mod_id
from tests.helpers import make_asset, write_pack


class PlaysetJsonTests(unittest.TestCase):
    def _assets(self, root: Path) -> dict:
        first = replace(
            make_asset(write_pack(root / "a.pack"), "a", "data", "111"),
            description="Workshop description A",
        )
        second = make_asset(write_pack(root / "b.pack"), "b", "workshop", "222")
        return {first.id: first, second.id: second}

    def test_build_and_parse_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = self._assets(Path(temporary))
            payload = build_export_payload(
                game_id="warhammer3",
                playset_name="My playset",
                ordered_ids=["b", "a"],
                assets=assets,
                include_descriptions=True,
            )
            self.assertEqual([mod["id"] for mod in payload["mods"]], ["b", "a"])
            self.assertEqual([mod["load_order"] for mod in payload["mods"]], [1, 2])
            self.assertEqual(payload["mods"][0]["workshop_url"], "https://steamcommunity.com/sharedfiles/filedetails/?id=222")
            self.assertEqual(payload["mods"][1]["description"], "Workshop description A")
            self.assertEqual(payload["description_mode"], "compact")
            self.assertEqual(payload["description_limit"], DESCRIPTION_LIMIT)

            parsed = parse_import_payload(json.dumps(payload))
            self.assertEqual(parsed["game"], "warhammer3")
            self.assertEqual(parsed["playset_name"], "My playset")
            self.assertEqual([mod["id"] for mod in parsed["mods"]], ["b", "a"])

    def test_missing_asset_is_preserved_as_a_reference(self) -> None:
        payload = build_export_payload(
            game_id="warhammer3",
            playset_name="x",
            ordered_ids=["missing"],
            assets={},
        )
        self.assertEqual(payload["mods"][0]["id"], "missing")
        self.assertEqual(payload["mods"][0]["load_order"], 1)

    def test_missing_pending_workshop_mod_keeps_its_link(self) -> None:
        pending = pending_workshop_mod_id(
            {"workshop_id": "333", "pack_name": "C.PACK"}
        )
        payload = build_export_payload(
            game_id="warhammer3",
            playset_name="x",
            ordered_ids=[pending],
            assets={},
        )
        item = payload["mods"][0]
        self.assertEqual(item["load_order"], 1)
        self.assertEqual(item["workshop_id"], "333")
        self.assertEqual(item["pack_name"], "c.pack")
        self.assertEqual(
            item["workshop_url"],
            "https://steamcommunity.com/sharedfiles/filedetails/?id=333",
        )

    def test_descriptions_are_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            assets = self._assets(Path(temporary))
            payload = build_export_payload(
                game_id="warhammer3",
                playset_name="x",
                ordered_ids=["a"],
                assets=assets,
                include_descriptions=False,
            )
            self.assertNotIn("description", payload["mods"][0])
            self.assertNotIn("description_mode", payload)
            self.assertNotIn("description_limit", payload)

    def test_compact_description_strips_images_links_and_markup(self) -> None:
        compacted, truncated = compact_description(
            "[b]Hello[/b] [img]https://example.com/a.png[/img] "
            "[url=https://example.com]Link[/url] [list][*]A[*]B[/list] "
            "<br>https://example.com/bare"
        )
        self.assertFalse(truncated)
        self.assertEqual(compacted, "Hello Link A B")

    def test_compact_description_limits_length(self) -> None:
        compacted, truncated = compact_description("x" * (DESCRIPTION_LIMIT + 50))
        self.assertTrue(truncated)
        self.assertEqual(len(compacted), DESCRIPTION_LIMIT + 1)
        self.assertTrue(compacted.endswith("…"))

    def test_export_compacts_long_descriptions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = replace(
                make_asset(
                    write_pack(Path(temporary) / "a.pack"), "a", "data", "111"
                ),
                description=(
                    "[img]https://example.com/a.png[/img] "
                    + ("x" * (DESCRIPTION_LIMIT + 10))
                ),
            )
            payload = build_export_payload(
                game_id="warhammer3",
                playset_name="x",
                ordered_ids=[asset.id],
                assets={asset.id: asset},
                include_descriptions=True,
            )
            item = payload["mods"][0]
            self.assertTrue(item["description_truncated"])
            self.assertLessEqual(len(item["description"]), DESCRIPTION_LIMIT + 1)
            self.assertNotIn("[img]", item["description"])

    def test_rejects_wrong_type_schema_and_empty_mods(self) -> None:
        valid = {
            "schema_version": 1,
            "type": "wyccc-mod-manager-playset",
            "game": "warhammer3",
            "playset_name": "x",
            "mods": [{"id": "a"}],
        }
        for mutation in (
            {**valid, "type": "other"},
            {**valid, "schema_version": 99},
            {**valid, "mods": []},
            {**valid, "mods": "not a list"},
            {**valid, "mods": [{"unknown": 1}]},
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse_import_payload(json.dumps(mutation))

    def test_accepts_edited_payloads_from_other_tools(self) -> None:
        # A bare list, a list of ids, or a payload without optional metadata is
        # still useful when another AI rewrites the export.
        parsed = parse_import_payload(json.dumps([{"id": "a"}, "b"]))
        self.assertEqual([mod["id"] for mod in parsed["mods"]], ["a", "b"])
        self.assertEqual(parsed["game"], "")
        self.assertEqual(parsed["playset_name"], "")

        parsed = parse_import_payload(
            json.dumps({"mods": [{"id": "a"}, {"id": "b"}]})
        )
        self.assertEqual([mod["id"] for mod in parsed["mods"]], ["a", "b"])

        parsed = parse_import_payload(
            json.dumps({"mods": [{"id": "a", "source": "steam"}]})
        )
        self.assertEqual(parsed["mods"][0]["source"], "")

    def test_import_uses_array_order_not_load_order(self) -> None:
        parsed = parse_import_payload(
            json.dumps(
                {
                    "mods": [
                        {"id": "b", "load_order": 9},
                        {"id": "a", "load_order": 1},
                    ]
                }
            )
        )
        self.assertEqual([mod["id"] for mod in parsed["mods"]], ["b", "a"])

    def test_derives_workshop_id_from_url(self) -> None:
        parsed = parse_import_payload(
            json.dumps(
                {
                    "mods": [
                        {
                            "name": "x",
                            "workshop_url": (
                                "https://steamcommunity.com/sharedfiles/"
                                "filedetails/?id=444&searchtext=x"
                            ),
                        }
                    ]
                }
            )
        )
        self.assertEqual(parsed["mods"][0]["workshop_id"], "444")

    def test_accepts_bare_workshop_links_and_ids(self) -> None:
        parsed = parse_import_payload(
            json.dumps(
                [
                    "https://steamcommunity.com/sharedfiles/filedetails/?id=555",
                    "666",
                ]
            )
        )
        self.assertEqual(
            [mod["workshop_id"] for mod in parsed["mods"]], ["555", "666"]
        )

    def test_rejects_oversized_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "过大"):
            parse_import_payload("x" * (MAX_FILE_BYTES + 1))

    def test_rejects_deeply_nested_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "格式无效"):
            parse_import_payload("[" * 10_000 + "]" * 10_000)

    def test_write_and_read_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = build_export_payload(
                game_id="warhammer3",
                playset_name="x",
                ordered_ids=["a"],
                assets={},
            )
            target = write_export_file(root / "export", payload)
            self.assertEqual(target.suffix, ".json")
            self.assertEqual(read_import_file(target)["game"], "warhammer3")

    def test_read_file_accepts_bom_and_falls_back_to_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "my-playset.json"
            path.write_bytes(
                b"\xef\xbb\xbf"
                + json.dumps({"game": "warhammer3", "mods": [{"id": "a"}]}).encode(
                    "utf-8"
                )
            )
            parsed = read_import_file(path)
            self.assertEqual(parsed["playset_name"], "my-playset")
            self.assertEqual(parsed["game"], "warhammer3")

    def test_read_file_rejects_non_utf8_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            path.write_bytes(b"\xff\xfe\x00\x00")
            with self.assertRaisesRegex(ValueError, "格式无效"):
                read_import_file(path)

    def test_safe_export_name(self) -> None:
        self.assertEqual(safe_export_name('a/b:c*?'), "a_b_c__")
        self.assertEqual(safe_export_name("   "), "playset")
        self.assertEqual(safe_export_name("CON"), "_CON")
        self.assertEqual(safe_export_name("CON.txt"), "_CON.txt")


if __name__ == "__main__":
    unittest.main()
