from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.constants import SOURCE_DATA, SOURCE_WORKSHOP
from backend.share import PREFIX, export_share, parse_share, resolve_share
from tests.helpers import make_asset, write_pack


class ShareCodeTests(unittest.TestCase):
    def test_round_trip_and_resolve_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = make_asset(
                write_pack(root / "123" / "first.pack"),
                "old-first",
                SOURCE_WORKSHOP,
                "123",
            )
            second = make_asset(
                write_pack(root / "data" / "second.pack"),
                "old-second",
                SOURCE_DATA,
            )
            code = export_share([first, second])
            self.assertTrue(code.startswith(f"{PREFIX}-"))
            references = parse_share(code)

            installed = {
                "new-first": make_asset(
                    Path(first.path), "new-first", SOURCE_WORKSHOP, "123"
                ),
                "new-second": make_asset(
                    Path(second.path), "new-second", SOURCE_DATA
                ),
            }
            ordered_ids, missing = resolve_share(references, installed)

            self.assertEqual(ordered_ids, ["new-first", "new-second"])
            self.assertEqual(missing, [])

    def test_accepts_legacy_branded_share_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = write_pack(Path(temporary) / "mod.pack")
            code = export_share([make_asset(path, "mod", SOURCE_DATA)])

            for legacy_prefix in ("WWM1", "WWMM1"):
                with self.subTest(legacy_prefix=legacy_prefix):
                    references = parse_share(
                        code.replace("WMM1-", f"{legacy_prefix}-", 1)
                    )
                    self.assertEqual(references[0]["pack_name"], "mod.pack")

    def test_rejects_bad_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = write_pack(Path(temporary) / "mod.pack")
            code = export_share([make_asset(path, "mod", SOURCE_DATA)])
            prefix, checksum, payload = code.split("-", 2)
            bad_checksum = "FFFFFFFF" if checksum != "FFFFFFFF" else "00000000"
            with self.assertRaisesRegex(ValueError, "校验"):
                parse_share(f"{prefix}-{bad_checksum}-{payload}")

    def test_imports_legacy_wh3_manager_order(self) -> None:
        references = parse_share("222;1|111;0|333")
        self.assertEqual(
            [item["workshop_id"] for item in references],
            ["111", "222", "333"],
        )

    def test_legacy_project_enables_every_pack_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = {
                "z": make_asset(
                    write_pack(root / "123" / "zeta.pack"),
                    "z",
                    SOURCE_WORKSHOP,
                    "123",
                ),
                "a": make_asset(
                    write_pack(root / "123" / "alpha.pack"),
                    "a",
                    SOURCE_WORKSHOP,
                    "123",
                ),
            }

            ordered_ids, missing = resolve_share(parse_share("123"), assets)

            self.assertEqual(ordered_ids, ["a", "z"])
            self.assertEqual(missing, [])

    def test_source_prevents_same_named_local_pack_from_matching_wrong_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exported = make_asset(
                write_pack(root / "old-data" / "same.pack"),
                "old-id",
                SOURCE_DATA,
            )
            references = parse_share(export_share([exported]))
            installed = {
                "workshop-copy": make_asset(
                    write_pack(root / "workshop" / "same.pack"),
                    "workshop-copy",
                    SOURCE_WORKSHOP,
                    "987",
                ),
                "new-data-copy": make_asset(
                    write_pack(root / "new-data" / "same.pack"),
                    "new-data-copy",
                    SOURCE_DATA,
                ),
            }

            ordered_ids, missing = resolve_share(references, installed)

            self.assertEqual(ordered_ids, ["new-data-copy"])
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
