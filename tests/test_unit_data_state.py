from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.game_data import TABLE_SCHEMAS, GameDataEntry, DbSource
from backend.start_options import UNIT_DATA_PATCH_NAME
from backend.unit_data_state import (
    ensure_unit_data_patch,
    fingerprint_unit_data_inputs,
    load_unit_data_edits,
    save_unit_data_edits,
)


def _encode_value(field_type: str, value: Any) -> bytes:
    if field_type == "Boolean":
        return bytes([1 if value else 0])
    if field_type in {"I32", "ColourRGB"}:
        return struct.pack("<i", int(value or 0))
    if field_type == "I16":
        return struct.pack("<h", int(value or 0))
    if field_type == "I64":
        return struct.pack("<q", int(value or 0))
    if field_type == "F32":
        return struct.pack("<f", float(value or 0))
    if field_type == "F64":
        return struct.pack("<d", float(value or 0))
    if field_type == "StringU8":
        raw = str(value or "").encode("ascii")
        return struct.pack("<H", len(raw)) + raw
    if field_type == "OptionalStringU8":
        if value in {None, ""}:
            return b"\0"
        raw = str(value).encode("ascii")
        return b"\1" + struct.pack("<H", len(raw)) + raw
    if field_type == "StringU16":
        text = str(value or "")
        return struct.pack("<H", len(text)) + text.encode("utf-16le")
    raise AssertionError(f"unsupported fixture type: {field_type}")


def _table_payload(table_name: str, version: int, rows: list[dict[str, Any]]) -> bytes:
    schema = TABLE_SCHEMAS[table_name][version]
    encoded_rows = []
    for row in rows:
        encoded_rows.append(
            b"".join(_encode_value(field_type, row.get(name)) for name, field_type in schema)
        )
    return b"".join(
        (
            b"\xfc\xfd\xfe\xff",
            struct.pack("<i", version),
            b"\1",
            struct.pack("<i", len(encoded_rows)),
            *encoded_rows,
        )
    )


class _TempGame(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="wmm_unit_state_")
        self.root = Path(self._temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        (self.data / "db.pack").write_bytes(
            b"PFH5"
            + struct.pack("<6i", 0, 0, 0, 0, 0, 0)
        )
        source = DbSource(
            "db.pack",
            (
                GameDataEntry(
                    "db\\main_units_tables\\data__",
                    _table_payload(
                        "main_units_tables",
                        7,
                        [
                            {
                                "unit": "inf_swordsmen",
                                "caste": "infantry",
                                "land_unit": "land_inf_swordsmen",
                                "num_men": 90,
                                "campaign_cap": 4,
                                "recruitment_cost": 400,
                                "upkeep_cost": 100,
                            }
                        ],
                    ),
                ),
                GameDataEntry(
                    "db\\land_units_tables\\data__",
                    _table_payload(
                        "land_units_tables",
                        54,
                        [
                            {
                                "key": "land_inf_swordsmen",
                                "man_entity": "man_swordsmen",
                                "armour": "wh2_main_body_10",
                                "charge_bonus": 15,
                                "num_mounts": 0,
                                "num_engines": 0,
                                "rank_depth": 3,
                                "category": "infantry",
                                "spacing": "infantry",
                            }
                        ],
                    ),
                ),
            ),
        )
        self._sources_pack = source
        self.assets: dict[str, Any] = {}

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _build_db_pack(self) -> None:
        from backend.start_options import write_pfh5_pack, PackEntry

        write_pfh5_pack(
            self.data / "db.pack",
            [PackEntry(entry.name, entry.payload) for entry in self._sources_pack.entries],
        )


class UnitDataStateTests(_TempGame):
    def test_edit_store_roundtrip_and_cleanup(self) -> None:
        self._build_db_pack()
        saved = save_unit_data_edits(
            self.runtime,
            {"inf_swordsmen": {"campaign_cap": 9, "unknown": 1}},
        )
        self.assertEqual(saved["edited_units"], 1)
        self.assertEqual(
            load_unit_data_edits(self.runtime),
            {"inf_swordsmen": {"campaign_cap": 9}},
        )

    def test_patch_generated_reused_and_cleared(self) -> None:
        self._build_db_pack()
        save_unit_data_edits(self.runtime, {"inf_swordsmen": {"campaign_cap": 9}})
        first = ensure_unit_data_patch(
            self.runtime,
            self.data,
            self.assets,
            [],
            "default",
            {"unit_model_multiplier": 1},
        )
        self.assertEqual(first["status"], "generated")
        self.assertTrue((self.runtime / UNIT_DATA_PATCH_NAME).is_file())

        second = ensure_unit_data_patch(
            self.runtime,
            self.data,
            self.assets,
            [],
            "default",
            {"unit_model_multiplier": 1},
        )
        self.assertEqual(second["status"], "reused")

        save_unit_data_edits(self.runtime, {})
        cleared = ensure_unit_data_patch(
            self.runtime,
            self.data,
            self.assets,
            [],
            "default",
            {"unit_model_multiplier": 1},
        )
        self.assertEqual(cleared["status"], "zero_modification")
        self.assertFalse((self.runtime / UNIT_DATA_PATCH_NAME).exists())

    def test_fingerprint_changes_with_edits_and_sources(self) -> None:
        self._build_db_pack()
        base = {
            "playset_id": "default",
            "active_ids": [],
            "settings": {"unit_model_multiplier": 1},
            "edits": {},
            "sources": [],
        }
        first = fingerprint_unit_data_inputs(base)
        changed_edits = fingerprint_unit_data_inputs(
            {**base, "edits": {"inf_swordsmen": {"campaign_cap": 9}}}
        )
        self.assertNotEqual(first, changed_edits)


if __name__ == "__main__":
    unittest.main()
