from __future__ import annotations

import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.start_options import (
    EMPTY_MOVIE,
    INTRO_MOVIES,
    PERMISSIONS_ENTRY,
    PERMISSIONS_GUID,
    PERMISSIONS_VERSION,
    PackEntry,
    _decompress_payload,
    build_runtime_options_pack,
    read_pack_entries,
    write_pfh5_pack,
)


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
            self.assertEqual(result["entry_count"], 8)
            self.assertEqual(entries["script\\enable_console_logging"], b"\0")
            for movie in INTRO_MOVIES:
                self.assertEqual(entries[movie], EMPTY_MOVIE)
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
