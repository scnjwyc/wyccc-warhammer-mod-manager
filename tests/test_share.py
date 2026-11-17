from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from backend.constants import SOURCE_DATA, SOURCE_WORKSHOP
from backend.games import game_definitions
from backend.share import (
    export_share, parse_share, quick_checksum, parse_pending_workshop_mod_id,
    resolve_share, resolve_share_with_pending,
)
from tests.helpers import make_asset, write_pack


class ShareCodeTests(unittest.TestCase):
    def test_imports_real_official_mixed_profile_in_order(self):
        sample = Path(__file__).resolve().parent / "fixtures/official-mod-profile.twmods"
        refs = parse_share(sample.read_text("utf-8"))
        self.assertEqual([r.get("workshop_id") for r in refs], ["2969242283", "3380488529", "3630096234", None])
        self.assertEqual(refs[-1]["relative_path"], "data/jeanne_mod.pack")
        self.assertEqual(refs[-1]["source"], SOURCE_DATA)

    def test_exports_official_keys_and_resolves_on_another_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = make_asset(write_pack(root / "workshop/123/first.pack"), "old-first", SOURCE_WORKSHOP, "123")
            first.workshop_updated_at = 1770000000000
            second = make_asset(write_pack(root / "game/data/second.pack"), "old-second", SOURCE_DATA)
            code = export_share([first, second], game_path=root / "game")
            self.assertTrue(code.startswith("# TW Mod Profile\n"))
            self.assertIn("@steam_workshop:1142710/123@1770000000/first.pack", code)
            self.assertIn("@game_dir:data/second.pack", code)
            self.assertNotIn("WMM1", code)
            installed = {
                "new-first": make_asset(Path(first.path), "new-first", SOURCE_WORKSHOP, "123"),
                "new-second": make_asset(root / "other-game/data/second.pack", "new-second", SOURCE_DATA),
            }
            self.assertEqual(resolve_share(parse_share(code), installed), (["new-first", "new-second"], []))

    def test_workshop_profiles_are_bound_to_the_selected_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            asset = make_asset(write_pack(Path(temporary) / "one.pack"), "one", SOURCE_WORKSHOP, "123")
            for game in game_definitions():
                if game.mod_format != "pack":
                    continue
                with self.subTest(game=game.id):
                    code = export_share([asset], game.id)
                    self.assertEqual(parse_share(code, game.id)[0]["workshop_id"], "123")
                    other = "three_kingdoms" if game.id == "warhammer3" else "warhammer3"
                    with self.assertRaisesRegex(ValueError, "share.wrongGame"):
                        parse_share(code, other)

    def test_only_an_explicit_official_empty_profile_can_clear_a_list(self):
        self.assertEqual(parse_share(export_share([])), [])
        for invalid in ["", "random text", "# a comment", "123;0|456;1", "WMM1-12345678-data", "WWM1-old", "WWMM1-old"]:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "share.invalidOfficial"):
                parse_share(invalid)

    def test_rejects_malformed_or_partly_invalid_input(self):
        good = "mod_lookup_key://" + "a" * 32 + "@game_dir:data/ok.pack"
        for invalid in [good + "\nunknown line", good.replace("data/ok", "../ok"), good.replace("data/ok", "%2E%2E/ok"), good.replace("data/ok", "C:/ok"), good.replace("a" * 32, "abc")]:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "share.invalidOfficial"):
                parse_share(invalid)
        with self.assertRaisesRegex(ValueError, "share.tooLarge"):
            parse_share("x" * (5 * 1024 * 1024 + 1))

    def test_local_only_profile_preserves_unicode_and_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = make_asset(write_pack(root / "data/人物.pack"), "local", SOURCE_DATA)
            code = export_share([asset], game_path=root)
            refs = parse_share("\ufeff" + code.replace("\n", "\r\n"))
            wrong = make_asset(write_pack(root / "workshop/321/人物.pack"), "wrong", SOURCE_WORKSHOP, "321")
            self.assertEqual(resolve_share(refs, {wrong.id: wrong, asset.id: asset}), (["local"], []))

    def test_export_does_not_silently_omit_missing_or_external_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external = make_asset(write_pack(root / "outside/one.pack"), "outside", SOURCE_DATA)
            with self.assertRaisesRegex(ValueError, "share.outsideGame"):
                export_share([external], game_path=root / "game")
            missing = make_asset(root / "missing.pack", "missing", SOURCE_WORKSHOP, "123")
            with self.assertRaisesRegex(ValueError, "share.unreadablePack"):
                export_share([missing])

    def test_export_uses_installed_workshop_time_when_online_metadata_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "workshop"
            asset = make_asset(write_pack(root / "content/1142710/123/one.pack"), "one", SOURCE_WORKSHOP, "123")
            (root / "appworkshop_1142710.acf").write_text(
                '"AppWorkshop" { "WorkshopItemsInstalled" { "123" { "timeupdated" "1770000000" } } }',
                encoding="utf-8",
            )
            self.assertEqual(asset.workshop_updated_at, 0)
            self.assertIn("/123@1770000000/one.pack", export_share([asset]))

    def test_quick_checksum_includes_size_and_samples_head_and_tail(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.pack"
            for size in [0, 7, 1048576, 1048577, 1572864, 3 * 1048576]:
                with self.subTest(size=size):
                    content = (bytes(range(256)) * (size // 256 + 1))[:size]
                    path.write_bytes(content)
                    # Official samples hash LE64 size before the sampled bytes.
                    sampled = content[:1048576] + (content[-1048576:] if size > 1048576 else b"")
                    expected = hashlib.md5(struct.pack("<Q", size) + sampled).hexdigest()
                    self.assertEqual(quick_checksum(path), expected)

    def test_multi_pack_workshop_project_only_enables_named_packs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            a = make_asset(write_pack(root / "123/a.pack"), "a", SOURCE_WORKSHOP, "123")
            b = make_asset(write_pack(root / "123/b.pack"), "b", SOURCE_WORKSHOP, "123")
            refs = parse_share(export_share([b, a]))
            self.assertEqual(resolve_share(refs, {"a": a, "b": b}), (["b", "a"], []))
            self.assertEqual(resolve_share(parse_share(export_share([b])), {"a": a, "b": b}), (["b"], []))

    def test_missing_workshop_item_keeps_a_resolvable_pending_position(self):
        with tempfile.TemporaryDirectory() as temporary:
            asset = make_asset(write_pack(Path(temporary) / "123/Example Mod.pack"), "old", SOURCE_WORKSHOP, "123")
            refs = parse_share(export_share([asset]))
        ids, missing = resolve_share_with_pending(refs, {})
        self.assertEqual(missing, refs)
        self.assertEqual(parse_pending_workshop_mod_id(ids[0]), ("123", "example mod.pack"))


if __name__ == "__main__":
    unittest.main()
