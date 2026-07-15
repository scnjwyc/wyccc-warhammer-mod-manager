from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.constants import SOURCE_DATA, SOURCE_WORKSHOP
from backend.load_order import LoadOrderService, current_order_path, file_token
from tests.helpers import make_asset, write_pack


class LoadOrderTests(unittest.TestCase):
    def test_build_write_and_import_used_mods(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data = game / "data"
            workshop_item = root / "workshop" / "123"
            backup_dir = root / "backups"
            game.mkdir()

            data_pack = write_pack(data / "local.pack")
            first_pack = write_pack(workshop_item / "first.pack")
            second_pack = write_pack(workshop_item / "second.pack")
            assets = {
                "workshop-first": make_asset(
                    first_pack, "workshop-first", SOURCE_WORKSHOP, "123"
                ),
                "local": make_asset(data_pack, "local", SOURCE_DATA),
                "workshop-second": make_asset(
                    second_pack, "workshop-second", SOURCE_WORKSHOP, "123"
                ),
            }

            old_order = game / "used_mods.txt"
            old_order.write_text('mod "old.pack";\r\n', encoding="utf-8", newline="")
            old_token = file_token(old_order)
            service = LoadOrderService(backup_dir)
            plan = service.build_plan(
                str(game),
                str(data),
                assets,
                ["workshop-first", "local", "workshop-second", "workshop-first"],
            )

            expected = (
                f'add_working_directory "{workshop_item.resolve()}";\r\n'
                'mod "first.pack";\r\n'
                'mod "local.pack";\r\n'
                'mod "second.pack";\r\n'
            )
            self.assertEqual(plan.content, expected)
            self.assertEqual(plan.working_directories, [str(workshop_item.resolve())])
            self.assertEqual(
                plan.ordered_mod_ids,
                ["workshop-first", "local", "workshop-second"],
            )

            written_plan, backup_path, new_token = service.write_plan(plan, old_token)
            self.assertEqual(Path(written_plan.target_path), old_order.resolve())
            self.assertEqual(old_order.read_bytes(), expected.encode("utf-8"))
            self.assertTrue(Path(backup_path).is_file())
            self.assertNotEqual(new_token, old_token)
            self.assertEqual(
                service.import_disk_order(str(game), list(assets.values())),
                ["workshop-first", "local", "workshop-second"],
            )

    def test_write_rejects_a_stale_order_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data = game / "data"
            pack = write_pack(data / "local.pack")
            game.mkdir(exist_ok=True)
            order_file = game / "used_mods.txt"
            order_file.write_text('mod "before.pack";\n', encoding="utf-8")
            stale_token = file_token(order_file)

            service = LoadOrderService(root / "backups")
            asset = make_asset(pack, "local", SOURCE_DATA)
            plan = service.build_plan(str(game), str(data), {"local": asset}, ["local"])
            order_file.write_text('mod "changed.pack";\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "其他程序修改"):
                service.write_plan(plan, stale_token)

    def test_fallback_file_remains_the_active_import_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data = game / "data"
            pack = write_pack(data / "local.pack")
            game.mkdir(exist_ok=True)
            old_primary = game / "used_mods.txt"
            old_primary.write_text('mod "old.pack";\r\n', encoding="utf-8", newline="")

            service = LoadOrderService(root / "backups")
            asset = make_asset(pack, "local", SOURCE_DATA)
            plan = service.build_plan(str(game), str(data), {"local": asset}, ["local"])
            original_write = LoadOrderService._atomic_write

            def fail_primary(path: Path, content: str) -> Path:
                if path.name == "used_mods.txt":
                    raise OSError("simulated primary failure")
                return original_write(path, content)

            with patch.object(LoadOrderService, "_atomic_write", side_effect=fail_primary):
                written, _, token = service.write_plan(plan, file_token(old_primary))

            self.assertEqual(Path(written.target_path).name, "my_mods.txt")
            self.assertEqual(
                current_order_path(str(game), "my_mods.txt").name,
                "my_mods.txt",
            )
            self.assertEqual(
                service.import_disk_order(str(game), [asset], "my_mods.txt"),
                ["local"],
            )
            self.assertEqual(token, file_token(game / "my_mods.txt"))


if __name__ == "__main__":
    unittest.main()
