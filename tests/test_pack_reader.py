from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from backend.scanner import read_pack_entry_names
from backend.start_options import read_pack_entries
from tests.helpers import write_pack


class PackReaderTests(unittest.TestCase):
    def test_scan_and_payload_readers_agree_for_all_supported_layouts(self):
        entries = [("textures/a", b"not-selected"), ("db\\main_units_tables\\fixture", b"first-row"),
                   ("db\\land_units_tables\\fixture", b"second-row")]
        with tempfile.TemporaryDirectory() as directory:
            for magic in (b"PFH2", b"PFH3", b"PFH4", b"PFH5", b"PFH6"):
                for flags in (0, 0x40, 0x100, 0x140):
                    for preamble in (False, True):
                        with self.subTest(magic=magic, flags=flags, preamble=preamble):
                            path = write_pack(Path(directory) / "test.pack", magic=magic, byte_mask=flags,
                                              fake_workshop_preamble=preamble, dependencies=["base.pack"], entries=entries)
                            self.assertEqual(read_pack_entry_names(path), [name for name, _ in entries])
                            self.assertEqual([(e.name, e.payload) for e in read_pack_entries(path, "db/")], entries[1:])

    def test_encrypted_and_truncated_indexes_do_not_produce_partial_results(self):
        with tempfile.TemporaryDirectory() as directory:
            for variant in ("encrypted", "truncated", "oversized"):
                with self.subTest(variant=variant):
                    path = write_pack(Path(directory) / "test.pack", byte_mask=0x80 if variant == "encrypted" else 0,
                                      entries=[("db\\fixture", b"payload")])
                    if variant == "truncated":
                        path.write_bytes(path.read_bytes()[:-3])
                    if variant == "oversized":
                        data = bytearray(path.read_bytes())
                        struct.pack_into("<I", data, 20, 0x7fffffff)
                        path.write_bytes(data)
                    self.assertEqual(read_pack_entry_names(path), [])
                    with self.assertRaisesRegex(ValueError, "Pack"):
                        read_pack_entries(path)
