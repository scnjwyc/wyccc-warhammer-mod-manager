from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import zstandard

from backend.api import API
from backend.pack_reader import read_pack_index, read_pack_layout
from backend.pack_rewrite import pack_digest, replace_pack_entries
from backend.schema_update import (
    GUID_MARKER,
    VERSION_MARKER,
    decode_table,
    installed_definitions,
    migrate_table,
    table_header,
    update_mod_schema,
)
from backend.start_options import read_pack_entries
from backend.table_schema import load_latest_schema, parse_schema
from tests.helpers import make_asset, write_pack


def field(name, kind, default=None):
    return {"name": name, "type": kind, "default": default}


OLD = {"version": 1, "fields": [field("key", "StringU8"), field("count", "I32"), field("removed", "Boolean")]}
NEW = {
    "version": 2,
    "fields": [field("count", "I64"), field("added", "Boolean", "true"), field("key", "StringU8")],
}
GUID = GUID_MARKER + struct.pack("<H", 4) + "guid".encode("utf-16le")
BODY = struct.pack("<H", 3) + b"abc" + struct.pack("<iB", 123, 1)
OLD_DATA = GUID + VERSION_MARKER + struct.pack("<iBI", 1, 1, 1) + BODY
NEW_DATA = (
    GUID
    + VERSION_MARKER
    + struct.pack("<iBI", 2, 1, 1)
    + struct.pack("<qB", 123, 1)
    + struct.pack("<H", 3)
    + b"abc"
)
SCHEMAS = {"example_tables": [NEW, OLD]}
TARGETS = {"example_tables": NEW}
RON = """(version:5,definitions:{"example_tables":[(version:2,fields:[
  (name:"key",field_type:StringU8,default_value:Some("x")),
  (name:"nested",field_type:SequenceU32((version:0,fields:[(name:"number",field_type:I32)])))
])]},patches:{"example_tables":{"key":{"default_value":"patched"}}})"""


class TableMigrationTests(unittest.TestCase):
    def test_reorder_remove_add_convert_and_preserve_guid(self):
        result, stats = migrate_table(OLD_DATA, [NEW, OLD], NEW)
        self.assertEqual(result, NEW_DATA)
        self.assertEqual(stats, {"from_version": 1, "to_version": 2, "rows": 1, "reset_values": 0})

    def test_current_and_newer_table_bytes_are_unchanged(self):
        self.assertEqual(migrate_table(NEW_DATA, [NEW, OLD], NEW)[0], NEW_DATA)
        newer = NEW_DATA.replace(
            VERSION_MARKER + struct.pack("<i", 2), VERSION_MARKER + struct.pack("<i", 99)
        )
        self.assertEqual(migrate_table(newer, [NEW, OLD], NEW)[0], newer)

    def test_failed_numeric_conversion_uses_target_default_and_reports_it(self):
        old = {"version": 1, "fields": [field("number", "StringU8")]}
        new = {"version": 2, "fields": [field("number", "I32", "7")]}
        payload = VERSION_MARKER + struct.pack("<iBIH", 1, 1, 1, 3) + b"bad"
        migrated, stats = migrate_table(payload, [old], new)
        self.assertEqual(decode_table(migrated, [new])[1][0][0][0], 7)
        self.assertEqual(stats["reset_values"], 1)
        self.assertTrue(migrated.startswith(GUID_MARKER))

    def test_optional_integers_and_strings_use_the_correct_binary_widths(self):
        old = {"version": 1, "fields": [field("n", "OptionalI32"), field("s", "OptionalStringU16")]}
        new = {"version": 2, "fields": [*old["fields"], field("next", "OptionalI64", "9")]}
        raw = b"\0" + struct.pack("<i", -4) + b"\0"
        payload = VERSION_MARKER + struct.pack("<iBI", 1, 1, 1) + raw
        migrated, _ = migrate_table(payload, [old], new)
        self.assertTrue(migrated.endswith(raw + b"\1" + struct.pack("<q", 9)))
        self.assertEqual([item[0] for item in decode_table(migrated, [new])[1][0]], [-4, "", 9])

    def test_utf16_non_bmp_string_conversion_uses_code_unit_length(self):
        old = {"version": 1, "fields": [field("key", "StringU8")]}
        new = {"version": 2, "fields": [field("key", "OptionalStringU16")]}
        text = "中文😀"
        raw = text.encode("utf-8")
        payload = VERSION_MARKER + struct.pack("<iBIH", 1, 1, 1, len(raw)) + raw
        migrated, _ = migrate_table(payload, [old], new)
        self.assertTrue(migrated.endswith(b"\1" + struct.pack("<H", 4) + text.encode("utf-16le")))
        self.assertEqual(decode_table(migrated, [new])[1][0][0][0], text)

    def test_versionless_historical_definitions_require_full_consumption(self):
        small = {"version": -1, "fields": [field("n", "I16")]}
        large = {"version": 0, "fields": [field("n", "I32")]}
        payload = struct.pack("<BIh", 1, 1, 12)
        self.assertEqual(decode_table(payload, [large, small])[0], small)
        migrated, _ = migrate_table(payload, [large, small], large)
        self.assertNotIn(VERSION_MARKER, migrated)
        self.assertTrue(migrated.endswith(struct.pack("<BIi", 1, 1, 12)))

    def test_unchanged_nested_sequence_is_preserved_and_changed_layout_is_rejected(self):
        nested = {"kind": "SequenceU32", "definition": {"version": 0, "fields": [field("n", "I16")]}}
        old = {"version": 1, "fields": [field("sequence", nested)]}
        new = {"version": 2, "fields": [field("added", "Boolean"), *old["fields"]]}
        raw = struct.pack("<Ihh", 2, 3, 4)
        payload = VERSION_MARKER + struct.pack("<iBI", 1, 1, 1) + raw
        migrated, _ = migrate_table(payload, [old], new)
        self.assertTrue(migrated.endswith(b"\0" + raw))
        changed = {
            "version": 3,
            "fields": [field("sequence", {"kind": "SequenceU16", "definition": nested["definition"]})],
        }
        with self.assertRaisesRegex(ValueError, "semanticChange"):
            migrate_table(payload, [old], changed)

    def test_changed_colour_groups_are_rejected_before_data_loss(self):
        new = {"version": 2, "fields": [{**OLD["fields"][0], "colour": ["red", 1]}, *OLD["fields"][1:]]}
        with self.assertRaisesRegex(ValueError, "semanticChange"):
            migrate_table(OLD_DATA, [OLD], new)

    def test_truncation_trailing_bytes_unknown_version_and_bad_count_are_rejected(self):
        for data in (
            OLD_DATA[:-1],
            OLD_DATA + b"extra",
            VERSION_MARKER + struct.pack("<iBI", 1, 1, 0xFFFFFFFF),
        ):
            with self.subTest(data=data), self.assertRaisesRegex(ValueError, "decodeFailed"):
                migrate_table(data, [OLD], NEW)
        with self.assertRaisesRegex(ValueError, "unknownVersion"):
            migrate_table(OLD_DATA, [NEW], NEW)

    def test_raw_strings_float_bits_and_empty_tables_are_preserved(self):
        old = {"version": 1, "fields": [field("key", "StringU8"), field("n", "F32")]}
        new = {"version": 2, "fields": [*old["fields"], field("added", "ColourRGB", "0504FF")]}
        raw = struct.pack("<H", 1) + b"\xff" + b"\x01\0\xc0\x7f"
        payload = VERSION_MARKER + struct.pack("<iBI", 1, 1, 1) + raw
        migrated, _ = migrate_table(payload, [old], new)
        self.assertTrue(migrated.endswith(raw + struct.pack("<I", 0x0504FF)))
        empty = VERSION_MARKER + struct.pack("<iBI", 1, 0, 0)
        self.assertEqual(table_header(migrate_table(empty, [old], new)[0])[3], 0)


class PackMigrationTests(unittest.TestCase):
    def test_all_container_formats_keep_metadata_dependencies_assets_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for magic in (b"PFH2", b"PFH3", b"PFH4", b"PFH5", b"PFH6"):
                with self.subTest(magic=magic):
                    path = write_pack(
                        root / f"{magic.decode()}.pack",
                        byte_mask=3 | 0x40 | 0x100,
                        dependencies=["dependency.pack"],
                        magic=magic,
                        fake_workshop_preamble=True,
                        entries=[
                            ("db\\example_tables\\mod", OLD_DATA),
                            ("script\\x.lua", b"script"),
                            ("text\\x.loc", b"loc"),
                        ],
                    )
                    original = path.read_bytes() + b"trailer"
                    path.write_bytes(original)
                    layout = read_pack_layout(path)
                    result = update_mod_schema(path, SCHEMAS, TARGETS, root / "backups")
                    self.assertEqual(Path(result["backup_path"]).read_bytes(), original)
                    self.assertEqual(
                        path.read_bytes()[: layout.header_size + layout.dependency_size],
                        original[: layout.header_size + layout.dependency_size],
                    )
                    self.assertTrue(path.read_bytes().endswith(b"trailer"))
                    self.assertEqual(
                        [(e.name, e.payload) for e in read_pack_entries(path)],
                        [
                            ("db\\example_tables\\mod", NEW_DATA),
                            ("script\\x.lua", b"script"),
                            ("text\\x.loc", b"loc"),
                        ],
                    )

    def test_compressed_updated_entry_becomes_readable_uncompressed_others_stay_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compressed = struct.pack("<I", len(OLD_DATA)) + zstandard.ZstdCompressor().compress(OLD_DATA)
            path = write_pack(
                root / "mod.pack",
                3,
                entries=[("db\\example_tables\\x", compressed), ("untouched", compressed)],
            )
            data = bytearray(path.read_bytes())
            layout = read_pack_layout(path)
            index_cursor = layout.header_size
            data[index_cursor + 4] = 1
            index_cursor += 5 + len("db\\example_tables\\x") + 1
            data[index_cursor + 4] = 1
            path.write_bytes(data)
            update_mod_schema(path, SCHEMAS, TARGETS, root / "backups")
            entries = read_pack_index(path)
            self.assertFalse(entries[0].compressed)
            self.assertTrue(entries[1].compressed)
            self.assertEqual(
                path.read_bytes()[entries[1].offset : entries[1].offset + entries[1].size], compressed
            )
            self.assertEqual(read_pack_entries(path)[0].payload, NEW_DATA)

    def test_one_bad_table_prevents_any_write_and_unknown_tables_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_pack(
                root / "bad.pack",
                3,
                entries=[("db/example_tables/a", OLD_DATA), ("db/example_tables/b", OLD_DATA[:-1])],
            )
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                update_mod_schema(path, SCHEMAS, TARGETS, root / "backups")
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((root / "backups").exists())
            path = write_pack(
                root / "partial.pack",
                3,
                entries=[("db/example_tables/a", OLD_DATA), ("db/custom_tables/b", b"custom")],
            )
            result = update_mod_schema(path, SCHEMAS, TARGETS, root / "backups")
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["skipped"][0]["reason"], "schemaUpdate.unknownTable")
            self.assertEqual(read_pack_entries(path)[1].payload, b"custom")

    def test_unchanged_does_not_touch_mtime_or_create_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_pack(root / "current.pack", 3, entries=[("db/example_tables/x", NEW_DATA)])
            before = path.stat().st_mtime_ns
            self.assertEqual(
                update_mod_schema(path, SCHEMAS, TARGETS, root / "backups")["status"], "unchanged"
            )
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertFalse((root / "backups").exists())

    def test_atomic_replacement_failure_keeps_original_and_backup_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_pack(root / "mod.pack", 3, entries=[("db/example_tables/x", OLD_DATA)])
            original = path.read_bytes()
            with (
                patch("backend.pack_rewrite.os.replace", side_effect=OSError("locked")),
                self.assertRaises(OSError),
            ):
                replace_pack_entries(
                    path, {"db/example_tables/x": NEW_DATA}, root / "backups", pack_digest(path)
                )
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(next((root / "backups").glob("*.bak")).read_bytes(), original)
            self.assertFalse(list(root.glob("*.tmp")))

    def test_changed_file_and_duplicate_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_pack(root / "mod.pack", 3, entries=[("x", b"old")])
            with self.assertRaisesRegex(ValueError, "fileChanged"):
                replace_pack_entries(path, {"x": b"new"}, root / "backups", "stale")
            path = write_pack(path, 3, entries=[("x", b"old"), ("x", b"old")])
            with self.assertRaisesRegex(ValueError, "duplicateEntries"):
                replace_pack_entries(path, {"x": b"new"}, root / "backups", pack_digest(path))

    def test_target_is_installed_vanilla_version_and_ignores_mods_and_movies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_pack(root / "db.pack", 1, entries=[("db/example_tables/a", OLD_DATA)])
            write_pack(root / "fake.pack", 3, entries=[("db/example_tables/a", NEW_DATA)])
            write_pack(root / "movie.pack", 4, entries=[("db/example_tables/a", NEW_DATA)])
            self.assertEqual(
                installed_definitions(root, {"example_tables"}, SCHEMAS), {"example_tables": OLD}
            )
            write_pack(root / "patch.pack", 2, entries=[("db/example_tables/a", NEW_DATA)])
            self.assertEqual(installed_definitions(root, {"example_tables"}, SCHEMAS), TARGETS)

    def test_versionless_vanilla_targets_choose_latest_decoded_definition(self):
        small = {"version": -2, "fields": [field("n", "I16")]}
        large = {"version": -1, "fields": [field("n", "I32")]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_pack(root / "a.pack", 1, entries=[("db/example_tables/a", struct.pack("<BIi", 1, 1, 8))])
            write_pack(root / "z.pack", 2, entries=[("db/example_tables/a", struct.pack("<BIh", 1, 1, 8))])
            self.assertEqual(
                installed_definitions(root, {"example_tables"}, {"example_tables": [large, small]}),
                {"example_tables": large},
            )


class SchemaLoaderTests(unittest.TestCase):
    def test_ron_options_nested_sequences_patches_and_comments(self):
        result = parse_schema("// comment\n" + RON)
        self.assertEqual(result["example_tables"][0]["fields"][0]["default"], "patched")
        self.assertEqual(result["example_tables"][0]["fields"][1]["type"]["kind"], "SequenceU32")
        for invalid in ("(version:6,definitions:{})", "bad", RON + "unexpected"):
            with self.assertRaises(ValueError):
                parse_schema(invalid)

    def test_http_etag_cache_revalidation_and_explicit_offline_fallback(self):
        from io import BytesIO

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            response = BytesIO(RON.encode())
            response.headers = {"ETag": '"one"'}
            with patch("backend.table_schema.urlopen", return_value=response) as fetch:
                schemas, info = load_latest_schema("warhammer3", root)
            self.assertFalse(info["cached"])
            self.assertIn("schema_wh3.ron", fetch.call_args.args[0].full_url)
            with patch(
                "backend.table_schema.urlopen", side_effect=HTTPError("url", 304, "", {}, None)
            ) as fetch:
                self.assertEqual(load_latest_schema("warhammer3", root)[0], schemas)
                self.assertEqual(fetch.call_args.args[0].get_header("If-none-match"), '"one"')
                self.assertFalse(load_latest_schema("warhammer3", root)[1]["cached"])
            with patch("backend.table_schema.urlopen", side_effect=URLError("offline")):
                self.assertTrue(load_latest_schema("warhammer3", root)[1]["cached"])
                with self.assertRaisesRegex(ValueError, "downloadFailed"):
                    load_latest_schema("warhammer2", root)


class BatchApiTests(unittest.TestCase):
    def test_batch_continues_after_a_failure_deduplicates_paths_and_preserves_playset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data = game / "data"
            data.mkdir(parents=True)
            (game / "Warhammer3.exe").write_bytes(b"")
            write_pack(data / "db.pack", 1, entries=[("db/example_tables/a", NEW_DATA)])
            good = write_pack(data / "good.pack", 3, entries=[("db/example_tables/a", OLD_DATA)])
            bad = write_pack(data / "bad.pack", 3, entries=[("db/example_tables/a", OLD_DATA[:-1])])
            empty = write_pack(data / "empty.pack", 3, entries=[("script/a.lua", b"script")])
            api = API(root / "state")
            api.settings_service.save({"game_path": str(game), "fetch_workshop_metadata": False})
            api._assets = {
                name: make_asset(path, name, "data")
                for name, path in (("good", good), ("alias", good), ("bad", bad), ("empty", empty))
            }
            api.state_repository.update_current_playset(["bad", "good"], "warhammer3")
            before = api.state_repository.get_current_playset("warhammer3")
            with (
                patch("backend.api.is_game_running", return_value=False),
                patch("backend.api.load_latest_schema", return_value=(SCHEMAS, {"cached": False})),
                patch.object(api, "_scan_mods", return_value={"mods": []}),
            ):
                result = api.call(
                    "update_mod_table_schemas", [["bad", "good", "alias", "empty", "good"], "warhammer3"]
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                (
                    result["data"]["updated_count"],
                    result["data"]["failed_count"],
                    result["data"]["unchanged_count"],
                ),
                (1, 1, 1),
            )
            self.assertEqual(len(result["data"]["results"]), 3)
            self.assertEqual([row["mod_id"] for row in result["data"]["results"]], ["bad", "good", "empty"])
            self.assertEqual(api.state_repository.get_current_playset("warhammer3"), before)
            self.assertEqual(read_pack_entries(good)[0].payload, NEW_DATA)

    def test_running_game_and_stale_context_block_before_loading_or_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            with (
                patch("backend.api.is_game_running", return_value=True),
                patch("backend.api.load_latest_schema") as loader,
            ):
                self.assertFalse(api.call("update_mod_table_schemas", [["a"]])["ok"])
                loader.assert_not_called()
            with patch("backend.api.is_game_running", return_value=False):
                response = api.call("update_mod_table_schemas", [["a"], "three_kingdoms"])
                self.assertEqual(response["error"]["message"], "schemaUpdate.contextChanged")


if __name__ == "__main__":
    unittest.main()
