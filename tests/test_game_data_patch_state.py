from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from backend.game_data_patch_state import (
    GAME_DATA_BUILDER_VERSION,
    GAME_DATA_PATCH_MANIFEST_NAME,
    build_game_data_inputs,
    ensure_game_data_patch,
    fingerprint_game_data_inputs,
    load_manifest_subscription_state,
)
from backend.models import ModAsset
from backend.start_options import GAME_DATA_PATCH_NAME


UNIT_SIZE_WORKSHOP_ID = "3765783838"


class GameDataPatchStateTests(unittest.TestCase):
    def test_builder_version_invalidates_pre_final_db_overlay_patches(self) -> None:
        self.assertEqual(GAME_DATA_BUILDER_VERSION, 9)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_path = self.root / "data"
        self.output_dir = self.root / "runtime"
        self.data_path.mkdir()
        self.first_pack = self.root / "first.pack"
        self.second_pack = self.root / "second.pack"
        self.first_pack.write_bytes(b"first")
        self.second_pack.write_bytes(b"second")
        (self.data_path / "db.pack").write_bytes(b"database")
        self.assets = {
            "first": self._asset("first", self.first_pack),
            "second": self._asset("second", self.second_pack),
        }
        self.active_ids = ["first", "second"]
        self.settings = {
            "unit_model_multiplier": 2,
            "unit_recruitment_capacity_multiplier": 1,
            "single_entity_unit_mode": "scale",
            "scale_lord_hero_health": False,
            "disable_unit_friendly_fire": False,
            "disable_spell_friendly_fire": False,
        }
        self.subscription_state = {UNIT_SIZE_WORKSHOP_ID: True}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _asset(mod_id: str, path: Path) -> ModAsset:
        return ModAsset(
            id=mod_id,
            pack_name=path.name,
            display_name=mod_id,
            path=str(path),
            directory=str(path.parent),
            source="data",
        )

    def _inputs(self, **changes):
        values = {
            "data_path": self.data_path,
            "assets": self.assets,
            "active_ids": self.active_ids,
            "playset_id": "default",
            "settings": self.settings,
            "subscription_state": self.subscription_state,
        }
        values.update(changes)
        return build_game_data_inputs(**values)

    def _ensure(self, **changes):
        values = {
            "output_dir": self.output_dir,
            "data_path": self.data_path,
            "assets": self.assets,
            "active_ids": self.active_ids,
            "playset_id": "default",
            "settings": self.settings,
            "subscription_state": self.subscription_state,
        }
        values.update(changes)
        return ensure_game_data_patch(**values)

    @staticmethod
    def _successful_builder(output_dir, _data_path, _assets, _active_ids, _settings, **_kwargs):
        output_path = Path(output_dir) / GAME_DATA_PATCH_NAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"generated patch")
        return {
            "path": str(output_path),
            "options": ["unit_model_multiplier"],
            "entry_count": 2,
            "game_data": {"unit_rows_scaled": 4},
        }

    def test_every_required_input_group_changes_the_fingerprint(self) -> None:
        base = self._inputs()
        base_digest = fingerprint_game_data_inputs(base)

        changed_settings = dict(self.settings, unit_model_multiplier=3)
        changed_recruitment_capacity = dict(
            self.settings,
            unit_recruitment_capacity_multiplier=3,
        )
        changed_single_entity_mode = dict(
            self.settings,
            single_entity_unit_mode="health",
        )
        changed_health_setting = dict(self.settings, scale_lord_hero_health=True)
        changed_subscription = {UNIT_SIZE_WORKSHOP_ID: False}
        variants = [
            self._inputs(settings=changed_settings),
            self._inputs(settings=changed_recruitment_capacity),
            self._inputs(settings=changed_single_entity_mode),
            self._inputs(settings=changed_health_setting),
            self._inputs(playset_id="campaign"),
            self._inputs(active_ids=list(reversed(self.active_ids))),
            self._inputs(subscription_state=changed_subscription),
        ]

        self.first_pack.write_bytes(b"first changed")
        variants.append(self._inputs())
        self.first_pack.write_bytes(b"first")
        current_ns = self.first_pack.stat().st_mtime_ns
        os.utime(self.first_pack, ns=(current_ns + 1_000_000, current_ns + 1_000_000))
        variants.append(self._inputs())
        (self.data_path / "db.pack").write_bytes(b"database changed")
        variants.append(self._inputs())

        for index, variant in enumerate(variants):
            with self.subTest(index=index):
                self.assertNotEqual(fingerprint_game_data_inputs(variant), base_digest)

    def test_matching_manifest_and_output_reuses_without_building(self) -> None:
        with patch(
            "backend.game_data_patch_state.build_game_data_patch",
            side_effect=self._successful_builder,
        ):
            first = self._ensure()

        with patch("backend.game_data_patch_state.build_game_data_patch") as builder:
            second = self._ensure()

        self.assertEqual(first["status"], "generated")
        self.assertEqual(second["status"], "reused")
        self.assertEqual(second["fingerprint"], first["fingerprint"])
        builder.assert_not_called()

    def test_modified_output_rebuilds_even_when_inputs_match(self) -> None:
        with patch(
            "backend.game_data_patch_state.build_game_data_patch",
            side_effect=self._successful_builder,
        ) as builder:
            first = self._ensure()
            Path(first["path"]).write_bytes(b"tampered")
            second = self._ensure()

        self.assertEqual(builder.call_count, 2)
        self.assertEqual(second["status"], "generated")
        self.assertIn("output", second["changed_inputs"])

    def test_disabled_settings_remove_stale_output_and_reuse_zero_manifest(self) -> None:
        self.output_dir.mkdir()
        stale_path = self.output_dir / GAME_DATA_PATCH_NAME
        stale_path.write_bytes(b"stale")
        disabled = {
            "unit_model_multiplier": 1,
            "single_entity_unit_mode": "scale",
            "scale_lord_hero_health": False,
            "disable_unit_friendly_fire": False,
            "disable_spell_friendly_fire": False,
        }

        with patch("backend.game_data_patch_state.build_game_data_patch") as builder:
            first = self._ensure(settings=disabled)
            second = self._ensure(settings=disabled)

        self.assertEqual(first["status"], "zero_modification")
        self.assertEqual(second["status"], "zero_modification")
        self.assertEqual(first["path"], "")
        self.assertFalse(stale_path.exists())
        self.assertTrue((self.output_dir / GAME_DATA_PATCH_MANIFEST_NAME).is_file())
        builder.assert_not_called()

    def test_builder_with_no_changed_rows_persists_zero_result(self) -> None:
        zero_result = {
            "path": "",
            "options": ["unit_model_multiplier"],
            "entry_count": 0,
            "game_data": {
                "unit_rows_scaled": 0,
                "land_rows_scaled": 0,
                "unit_friendly_fire_rows_changed": 0,
                "spell_friendly_fire_rows_changed": 0,
            },
        }
        with patch(
            "backend.game_data_patch_state.build_game_data_patch",
            return_value=deepcopy(zero_result),
        ):
            result = self._ensure()

        self.assertEqual(result["status"], "zero_modification")
        self.assertEqual(result["entry_count"], 0)
        self.assertEqual(result["game_data"], zero_result["game_data"])

    def test_manifest_exposes_last_verified_subscription_state(self) -> None:
        with patch(
            "backend.game_data_patch_state.build_game_data_patch",
            side_effect=self._successful_builder,
        ):
            self._ensure()

        self.assertEqual(
            load_manifest_subscription_state(self.output_dir),
            self.subscription_state,
        )


if __name__ == "__main__":
    unittest.main()
