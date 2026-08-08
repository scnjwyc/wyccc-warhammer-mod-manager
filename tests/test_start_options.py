from __future__ import annotations

import inspect
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.start_options as start_options
from backend.game_data import GameDataBuildResult, GameDataEntry
from backend.start_options import (
    INTRO_MOVIES,
    PERMISSIONS_ENTRY,
    PERMISSIONS_GUID,
    PERMISSIONS_VERSION,
    PackEntry,
    _decompress_payload,
    build_runtime_options_pack,
    collect_game_data_source_snapshot,
    read_pack_entries,
    write_pfh5_pack,
)
from tests.helpers import make_asset

UNIT_SIZE_FEATURE_WORKSHOP_ID = "3765783838"
FRIENDLY_FIRE_FEATURE_WORKSHOP_ID = "3765783977"
UNIT_CAP_FEATURE_WORKSHOP_ID = start_options.GAME_DATA_FEATURE_WORKSHOP_ITEMS["unit_cap"]["workshop_id"]
REFERENCE_INTRO_MOVIES = {
    *(
        f"movies\\epilepsy_warning\\epilepsy_warning_{language}.ca_vp8"
        for language in (
            "br",
            "cn",
            "cz",
            "de",
            "en",
            "es",
            "fr",
            "it",
            "kr",
            "pl",
            "ru",
            "tr",
            "zh",
        )
    ),
    "movies\\gam_int.ca_vp8",
    *(f"movies\\startup_movie_{index:02d}.ca_vp8" for index in range(1, 9)),
}


def _string_u8(value: str) -> bytes:
    raw = value.encode("ascii")
    return struct.pack("<H", len(raw)) + raw


def _permission_row(faction: str, unit: str, general: int) -> bytes:
    return b"".join(
        (
            _string_u8(faction),
            bytes([general]),
            _string_u8(unit),
            b"\x01\x01",
            b"\x00\x00\x00",
            b"\x00",
            b"\x00",
            b"\x00",
        )
    )


def _permission_table(rows: list[bytes]) -> bytes:
    return b"".join(
        (
            b"\xfd\xfe\xfc\xff",
            struct.pack("<H", len(PERMISSIONS_GUID)),
            PERMISSIONS_GUID.encode("utf-16le"),
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", PERMISSIONS_VERSION),
            b"\x01",
            struct.pack("<i", len(rows)),
            b"".join(rows),
        )
    )


class StartOptionsPackTests(unittest.TestCase):
    def test_game_data_generation_has_a_dedicated_builder(self) -> None:
        self.assertNotIn(
            "subscribed_workshop_ids",
            inspect.signature(build_runtime_options_pack).parameters,
        )
        self.assertTrue(callable(getattr(start_options, "build_game_data_patch", None)))
        self.assertEqual(
            getattr(start_options, "GAME_DATA_PATCH_NAME", ""),
            "!!!!wyccc_game_data_patch.pack",
        )

    def test_runtime_builder_does_not_generate_game_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()

            with patch("backend.start_options.build_game_data_entries") as builder:
                result = build_runtime_options_pack(
                    root / "runtime",
                    str(root / "data"),
                    {},
                    [],
                    {
                        "unit_model_multiplier": 2.0,
                        "scale_lord_hero_health": True,
                        "disable_unit_friendly_fire": True,
                        "disable_spell_friendly_fire": True,
                    },
                )

            builder.assert_not_called()
            self.assertEqual(result["path"], "")
            self.assertEqual(result["options"], [])

    def test_disabled_game_data_settings_remove_the_existing_patch(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "runtime"
            output_dir.mkdir()
            output_path = output_dir / "!!!!wyccc_game_data_patch.pack"
            output_path.write_bytes(b"old patch")

            with patch("backend.start_options.build_game_data_entries") as builder:
                result = build_game_data_patch(
                    output_dir,
                    str(root / "data"),
                    {},
                    [],
                    {
                        "unit_model_multiplier": 1.0,
                        "scale_lord_hero_health": False,
                        "disable_unit_friendly_fire": False,
                        "disable_spell_friendly_fire": False,
                    },
                )

            builder.assert_not_called()
            self.assertEqual(result["path"], "")
            self.assertFalse(output_path.exists())

    def test_each_subscription_unlocks_only_its_own_game_data_settings(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"source-table")],
            )
            built = GameDataBuildResult(
                (GameDataEntry("db\\main_units_tables\\!!!!wyccc_game_data_v0007", b"patched"),),
                {"unit_model_multiplier": 2.0},
            )

            for workshop_id, expected in (
                (
                    UNIT_SIZE_FEATURE_WORKSHOP_ID,
                    {
                        "unit_model_multiplier": 2.0,
                        "unit_recruitment_capacity_multiplier": 1,
                        "single_entity_unit_mode": "health",
                        "artillery_unit_mode": "half",
                        "war_machine_unit_mode": "health",
                        "scale_lord_hero_health": True,
                        "disable_unit_friendly_fire": False,
                        "disable_spell_friendly_fire": False,
                    },
                ),
                (
                    FRIENDLY_FIRE_FEATURE_WORKSHOP_ID,
                    {
                        "unit_model_multiplier": 1.0,
                        "unit_recruitment_capacity_multiplier": 1,
                        "single_entity_unit_mode": "scale",
                        "artillery_unit_mode": "full",
                        "war_machine_unit_mode": "full",
                        "scale_lord_hero_health": False,
                        "disable_unit_friendly_fire": True,
                        "disable_spell_friendly_fire": True,
                    },
                ),
                (
                    UNIT_CAP_FEATURE_WORKSHOP_ID,
                    {
                        "unit_model_multiplier": 1.0,
                        "single_entity_unit_mode": "scale",
                        "artillery_unit_mode": "full",
                        "war_machine_unit_mode": "full",
                        "scale_lord_hero_health": False,
                        "unit_recruitment_capacity_multiplier": 4,
                        "disable_unit_friendly_fire": False,
                        "disable_spell_friendly_fire": False,
                    },
                ),
            ):
                with self.subTest(workshop_id=workshop_id):
                    with patch("backend.start_options.build_game_data_entries", return_value=built) as builder:
                        result = build_game_data_patch(
                            root / f"runtime-{workshop_id}",
                            str(data),
                            {},
                            [],
                            {
                                "unit_model_multiplier": 2.0,
                                "single_entity_unit_mode": "health",
                                "artillery_unit_mode": "half",
                                "war_machine_unit_mode": "health",
                                "scale_lord_hero_health": True,
                                "unit_recruitment_capacity_multiplier": 4,
                                "disable_unit_friendly_fire": True,
                                "disable_spell_friendly_fire": True,
                            },
                            subscribed_workshop_ids=(workshop_id,),
                        )

                    self.assertTrue(builder.called)
                    self.assertEqual(builder.call_args.args[1], expected)
                    expected_options = [
                        key
                        for key, value in expected.items()
                        if (key == "unit_model_multiplier" and value != 1.0)
                        or (key == "unit_recruitment_capacity_multiplier" and value != 1)
                        or (key == "single_entity_unit_mode" and value == "health")
                        or (
                            key in {"artillery_unit_mode", "war_machine_unit_mode"}
                            and value != "full"
                        )
                        or (
                            key not in {
                                "unit_model_multiplier",
                                "unit_recruitment_capacity_multiplier",
                                "single_entity_unit_mode",
                                "artillery_unit_mode",
                                "war_machine_unit_mode",
                            }
                            and value
                        )
                    ]
                    self.assertEqual(result["options"], expected_options)

    def test_game_data_entries_are_read_from_db_pack_and_composed_into_runtime_pack(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"source-table")],
            )
            built = GameDataBuildResult(
                (GameDataEntry("db\\main_units_tables\\!!!!wyccc_game_data_v0007", b"patched-table"),),
                {"unit_rows_scaled": 1, "unit_model_multiplier": 2.0},
            )

            with patch("backend.start_options.build_game_data_entries", return_value=built) as builder:
                result = build_game_data_patch(
                    root / "runtime",
                    str(data),
                    {},
                    [],
                    {"unit_model_multiplier": 2.0},
                    subscribed_workshop_ids=(UNIT_SIZE_FEATURE_WORKSHOP_ID,),
                )

            self.assertTrue(builder.called)
            self.assertEqual(Path(result["path"]).name, "!!!!wyccc_game_data_patch.pack")
            sources = builder.call_args.args[0]
            self.assertEqual([source.name for source in sources], ["原版数据库 db.pack"])
            self.assertEqual([entry.name for entry in sources[0].entries], ["db\\main_units_tables\\data__"])
            output = {entry.name: entry.payload for entry in read_pack_entries(Path(result["path"]))}
            self.assertEqual(
                output["db\\main_units_tables\\!!!!wyccc_game_data_v0007"],
                b"patched-table",
            )
            self.assertIn("unit_model_multiplier", result["options"])
            self.assertEqual(result["game_data"]["unit_rows_scaled"], 1)

    def test_game_data_sources_follow_enabled_order_before_vanilla(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            workshop = root / "workshop"
            data.mkdir()
            workshop.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"vanilla")],
            )
            high_path = write_pfh5_pack(
                workshop / "high.pack",
                [PackEntry("db\\main_units_tables\\z_high", b"high")],
            )
            low_path = write_pfh5_pack(
                workshop / "low.pack",
                [PackEntry("db\\main_units_tables\\!low", b"low")],
            )
            assets = {
                "high": make_asset(high_path, "high", "workshop"),
                "low": make_asset(low_path, "low", "workshop"),
            }
            built = GameDataBuildResult(
                (
                    GameDataEntry(
                        "db\\main_units_tables\\!!!!wyccc_game_data_v0007",
                        b"patched",
                    ),
                ),
                {"unit_rows_scaled": 1},
            )

            with patch(
                "backend.start_options.build_game_data_entries",
                return_value=built,
            ) as builder:
                build_game_data_patch(
                    root / "runtime",
                    str(data),
                    assets,
                    ["high", "low"],
                    {"unit_model_multiplier": 2.0},
                    subscribed_workshop_ids=(UNIT_SIZE_FEATURE_WORKSHOP_ID,),
                )

            self.assertEqual(
                [source.name for source in builder.call_args.args[0]],
                [
                    'MOD "high" [pack: high.pack, source: Workshop]',
                    'MOD "low" [pack: low.pack, source: Workshop]',
                    "原版数据库 db.pack",
                ],
            )

    def test_game_data_snapshot_includes_implicit_movie_packs_from_game_search_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            workshop = root / "workshop"
            data.mkdir()
            workshop.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"vanilla")],
            )
            write_pfh5_pack(
                data / "data_movie.pack",
                [PackEntry("db\\main_units_tables\\data_movie", b"movie")],
                pack_header_mask=4,
            )
            active_path = write_pfh5_pack(
                workshop / "enabled.pack",
                [PackEntry("db\\main_units_tables\\enabled", b"enabled")],
            )
            write_pfh5_pack(
                workshop / "sibling_movie.pack",
                [PackEntry("db\\main_units_tables\\sibling_movie", b"movie")],
                pack_header_mask=4,
            )
            assets = {"enabled": make_asset(active_path, "enabled", "workshop")}

            snapshot = collect_game_data_source_snapshot(data, assets, ["enabled"])

            self.assertEqual(
                [entry.spec.role for entry in snapshot.entries],
                ["auto_movie", "auto_movie", "explicit", "vanilla"],
            )
            self.assertEqual(
                [entry.spec.path.name for entry in snapshot.entries],
                ["data_movie.pack", "sibling_movie.pack", "enabled.pack", "db.pack"],
            )
            self.assertEqual(
                snapshot.diagnostics()["auto_movie_pack_names"],
                ["data_movie.pack", "sibling_movie.pack"],
            )

    def test_three_kingdoms_uses_database_pack_as_vanilla_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "database.pack",
                [PackEntry("db\\main_units_tables\\data__", b"three-kingdoms")],
            )

            snapshot = collect_game_data_source_snapshot(
                data,
                {},
                [],
                game_id="three_kingdoms",
            )

            self.assertEqual(len(snapshot.entries), 1)
            self.assertEqual(snapshot.entries[0].spec.role, "vanilla")
            self.assertEqual(snapshot.entries[0].spec.path.name, "database.pack")
            self.assertEqual(snapshot.entries[0].source.entries[0].payload, b"three-kingdoms")

    def test_game_data_snapshot_rejects_a_pack_changed_while_reading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"vanilla")],
            )
            source_path = write_pfh5_pack(
                root / "enabled.pack",
                [PackEntry("db\\main_units_tables\\enabled", b"enabled")],
            )
            assets = {"enabled": make_asset(source_path, "enabled", "workshop")}
            original_reader = start_options.read_pack_entries

            def read_then_change(path, prefix=""):
                entries = original_reader(path, prefix)
                if Path(path).resolve(strict=False) == source_path.resolve(strict=False):
                    with source_path.open("ab") as stream:
                        stream.write(b"changed")
                return entries

            with patch(
                "backend.start_options.read_pack_entries",
                side_effect=read_then_change,
            ), self.assertRaisesRegex(ValueError, "读取期间发生变化"):
                collect_game_data_source_snapshot(data, assets, ["enabled"])

    def test_custom_battle_permission_pack_uses_the_same_implicit_movie_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            workshop = root / "workshop"
            data.mkdir()
            workshop.mkdir()
            db_pack = write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\units_custom_battle_permissions_tables\\data__", b"db")],
            )
            data_movie = write_pfh5_pack(
                data / "data_movie.pack",
                [PackEntry("db\\units_custom_battle_permissions_tables\\movie", b"movie")],
                pack_header_mask=4,
            )
            active_path = write_pfh5_pack(
                workshop / "enabled.pack",
                [PackEntry("db\\units_custom_battle_permissions_tables\\enabled", b"enabled")],
            )
            sibling_movie = write_pfh5_pack(
                workshop / "sibling_movie.pack",
                [PackEntry("db\\units_custom_battle_permissions_tables\\sibling", b"movie")],
                pack_header_mask=4,
            )
            assets = {"enabled": make_asset(active_path, "enabled", "workshop")}

            with patch(
                "backend.start_options._build_permission_table",
                return_value=b"permissions",
            ) as permission_builder:
                build_runtime_options_pack(
                    root / "runtime",
                    str(data),
                    assets,
                    ["enabled"],
                    {"custom_battle_all_units_as_lords": True},
                )

            self.assertEqual(
                [path.name for path in permission_builder.call_args.args[0]],
                [
                    data_movie.name,
                    sibling_movie.name,
                    active_path.name,
                    db_pack.name,
                ],
            )

    def test_game_data_source_errors_identify_the_exact_mod(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            workshop = root / "workshop"
            data.mkdir()
            workshop.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"vanilla")],
            )
            broken_path = write_pfh5_pack(
                workshop / "wyd.pack",
                [PackEntry("db\\battle_entities_tables\\wyd_date", b"broken")],
            )
            assets = {
                "wyd": make_asset(broken_path, "wyd", "workshop"),
            }

            def fake_read_pack_entries(path: Path, prefix: str | tuple[str, ...] = "") -> list[PackEntry]:
                if path.resolve(strict=False) == broken_path.resolve(strict=False):
                    raise ValueError(
                        "无法解压 Pack 条目 db\\battle_entities_tables\\wyd_date："
                        "Error 3 while decompressing data: unknown compression method"
                    )
                return []

            with patch(
                "backend.start_options.read_pack_entries",
                side_effect=fake_read_pack_entries,
            ), self.assertRaisesRegex(
                ValueError,
                r'游戏数据来源 MOD "wyd" \[pack: wyd\.pack, source: Workshop\] 读取失败',
            ) as exc:
                build_game_data_patch(
                    root / "runtime",
                    str(data),
                    assets,
                    ["wyd"],
                    {"unit_model_multiplier": 2.0},
                    subscribed_workshop_ids=(UNIT_SIZE_FEATURE_WORKSHOP_ID,),
                )

            self.assertIn("db\\battle_entities_tables\\wyd_date", str(exc.exception))

    def test_kv_rule_only_game_data_change_writes_a_patch(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\_kv_rules_tables\\data__", b"source-table")],
            )
            built = GameDataBuildResult(
                (
                    GameDataEntry(
                        "db\\_kv_rules_tables\\!!!!wyccc_game_data_v0000",
                        b"patched-kv-rules",
                    ),
                ),
                {"unit_friendly_fire_kv_rules_changed": 4},
            )

            with patch("backend.start_options.build_game_data_entries", return_value=built):
                result = build_game_data_patch(
                    root / "runtime",
                    str(data),
                    {},
                    [],
                    {
                        "unit_model_multiplier": 1.0,
                        "disable_unit_friendly_fire": True,
                        "disable_spell_friendly_fire": False,
                    },
                    subscribed_workshop_ids=(FRIENDLY_FIRE_FEATURE_WORKSHOP_ID,),
                )

            self.assertTrue(result["path"])
            self.assertEqual(result["entry_count"], 1)
            output = {entry.name: entry.payload for entry in read_pack_entries(Path(result["path"]))}
            self.assertEqual(
                output["db\\_kv_rules_tables\\!!!!wyccc_game_data_v0000"],
                b"patched-kv-rules",
            )

    def test_game_data_builder_reports_zero_modification_without_writing_a_pack(self) -> None:
        build_game_data_patch = getattr(start_options, "build_game_data_patch", None)
        self.assertTrue(callable(build_game_data_patch))
        if not callable(build_game_data_patch):
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [PackEntry("db\\main_units_tables\\data__", b"source-table")],
            )
            unchanged = GameDataBuildResult(
                (GameDataEntry("db\\main_units_tables\\!!!!wyccc_game_data_v0007", b"unchanged"),),
                {
                    "unit_model_multiplier": 2.0,
                    "unit_rows_scaled": 0,
                    "land_rows_scaled": 0,
                    "unit_friendly_fire_rows_changed": 0,
                    "spell_friendly_fire_rows_changed": 0,
                },
            )

            with patch("backend.start_options.build_game_data_entries", return_value=unchanged):
                result = build_game_data_patch(
                    root / "runtime",
                    str(data),
                    {},
                    [],
                    {"unit_model_multiplier": 2.0},
                    subscribed_workshop_ids=(UNIT_SIZE_FEATURE_WORKSHOP_ID,),
                )

            self.assertEqual(result["path"], "")
            self.assertEqual(result["entry_count"], 0)
            self.assertEqual(result["game_data"], unchanged.stats)
            self.assertFalse((root / "runtime" / "!!!!wyccc_game_data_patch.pack").exists())

    def test_ca_zstandard_payload_uses_prefixed_output_size(self) -> None:
        calls: list[tuple[bytes, int]] = []

        class FakeZstdError(Exception):
            pass

        class FakeDecompressor:
            def decompress(self, payload: bytes, max_output_size: int = 0) -> bytes:
                calls.append((payload, max_output_size))
                if payload.startswith(b"\x28\xb5\x2f\xfd"):
                    return b"decoded"
                raise FakeZstdError("not a zstandard frame")

        fake_module = types.ModuleType("zstandard")
        fake_module.ZstdError = FakeZstdError
        fake_module.ZstdDecompressor = FakeDecompressor
        raw = struct.pack("<I", 355_678) + b"\x28\xb5\x2f\xfdcompressed"
        with patch.dict(sys.modules, {"zstandard": fake_module}):
            result = _decompress_payload(raw, "permissions")

        self.assertEqual(result, b"decoded")
        self.assertEqual(calls, [(raw[4:], 355_678)])

    def test_unflagged_zstandard_pack_entry_is_decompressed_from_its_frame_signature(self) -> None:
        calls: list[tuple[bytes, int]] = []

        class FakeZstdError(Exception):
            pass

        class FakeDecompressor:
            def decompress(self, payload: bytes, max_output_size: int = 0) -> bytes:
                calls.append((payload, max_output_size))
                if payload.startswith(b"\x28\xb5\x2f\xfd"):
                    return b"decoded-table"
                raise FakeZstdError("not a zstandard frame")

        fake_module = types.ModuleType("zstandard")
        fake_module.ZstdError = FakeZstdError
        fake_module.ZstdDecompressor = FakeDecompressor
        raw = struct.pack("<I", 13) + b"\x28\xb5\x2f\xfdcompressed"
        with tempfile.TemporaryDirectory() as temporary:
            pack = write_pfh5_pack(
                Path(temporary) / "unflagged-zstd.pack",
                [PackEntry("db\\_kv_rules_tables\\battle_animations_synckills__", raw)],
            )
            with patch.dict(sys.modules, {"zstandard": fake_module}):
                entries = read_pack_entries(pack, "db\\_kv_rules_tables\\")

        self.assertEqual(
            entries,
            [PackEntry("db\\_kv_rules_tables\\battle_animations_synckills__", b"decoded-table")],
        )
        self.assertEqual(calls, [(raw[4:], 13)])

    def test_unflagged_non_compressed_pack_entry_is_left_unchanged(self) -> None:
        payload = b"plain db table payload"
        with tempfile.TemporaryDirectory() as temporary:
            pack = write_pfh5_pack(
                Path(temporary) / "plain.pack",
                [PackEntry("db\\_kv_rules_tables\\plain", payload)],
            )
            with patch("backend.start_options._decompress_payload") as decompress:
                entries = read_pack_entries(pack, "db\\_kv_rules_tables\\")

        self.assertEqual(entries, [PackEntry("db\\_kv_rules_tables\\plain", payload)])
        decompress.assert_not_called()

    def test_runtime_pack_contains_all_three_reference_features(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            write_pfh5_pack(
                data / "db.pack",
                [
                    PackEntry(
                        "db\\units_custom_battle_permissions_tables\\vanilla",
                        _permission_table(
                            [
                                _permission_row("faction_a", "unit_a", 0),
                                _permission_row("faction_a", "lord_a", 1),
                            ]
                        ),
                    )
                ],
            )

            result = build_runtime_options_pack(
                root / "runtime",
                str(data),
                {},
                [],
                {
                    "custom_battle_all_units_as_lords": True,
                    "enable_script_logging": True,
                    "skip_intro_movies": True,
                },
            )

            entries = {entry.name: entry.payload for entry in read_pack_entries(Path(result["path"]))}
            self.assertEqual(set(INTRO_MOVIES), REFERENCE_INTRO_MOVIES)
            self.assertEqual(result["entry_count"], 24)
            self.assertEqual(entries["script\\enable_console_logging"], b"\0")
            for movie in REFERENCE_INTRO_MOVIES:
                self.assertEqual(entries[movie], b"")
            permissions = entries[PERMISSIONS_ENTRY]
            row_count_offset = 4 + 2 + len(PERMISSIONS_GUID) * 2 + 4 + 4 + 1
            self.assertEqual(struct.unpack_from("<i", permissions, row_count_offset)[0], 3)

    def test_all_units_option_fails_clearly_without_a_permissions_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data").mkdir()
            with self.assertRaisesRegex(ValueError, "权限表"):
                build_runtime_options_pack(
                    root / "runtime",
                    str(root / "data"),
                    {},
                    [],
                    {"custom_battle_all_units_as_lords": True},
                )


if __name__ == "__main__":
    unittest.main()
