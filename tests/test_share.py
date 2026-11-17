from __future__ import annotations

import tempfile
import unittest
import base64
import json
import zlib
from pathlib import Path
from unittest.mock import patch

from backend import share_code as share_code_module
from backend.api import API
from backend.constants import SOURCE_DATA, SOURCE_WORKSHOP
from backend.games import game_definitions
from backend.share import (
    PREFIX,
    export_share,
    parse_pending_workshop_mod_id,
    parse_share,
    resolve_share,
    resolve_share_with_pending,
)
from backend.share_adapters import (
    OfficialModLookupKeyAdapter,
    ShareCodeParseResult,
    ShareMod,
    Wh3LegacyShareCodeAdapter,
    WmmShareCodeAdapter,
)
from backend.share_adapters.wh3_legacy import LEGACY_PROJECT_METADATA
from backend.share_code import (
    DEFAULT_EXPORT_FORMAT_ID,
    ShareCodeService,
    default_share_code_service,
    share_context,
    share_mods_from_assets,
)
from tests.helpers import make_asset, write_pack


class ShareCodeTests(unittest.TestCase):
    def test_shares_are_bound_to_the_selected_game(self) -> None:
        for game in game_definitions():
            with self.subTest(game=game.id):
                code = export_share([], game.id)
                self.assertEqual(parse_share(code, game.id), [])
                other = "three_kingdoms" if game.id == "warhammer3" else "warhammer3"
                with self.assertRaisesRegex(ValueError, "所属游戏"):
                    parse_share(code, other)

    def test_old_shares_are_only_accepted_for_warhammer3(self) -> None:
        payload = zlib.compress(json.dumps({"schema_version": 1, "game": "wh3", "mods": []}).encode())
        encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        code = f"WMM1-{zlib.crc32(payload):08X}-{encoded}"
        self.assertEqual(parse_share(code, "warhammer3"), [])
        with self.assertRaisesRegex(ValueError, "所属游戏"):
            parse_share(code, "three_kingdoms")
        with self.assertRaisesRegex(ValueError, "旧版分享码"):
            parse_share("123;0|456;1", "three_kingdoms")

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

    def test_missing_workshop_item_keeps_a_resolvable_pending_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset = make_asset(
                write_pack(Path(temporary) / "123" / "Example Mod.pack"),
                "old-id",
                SOURCE_WORKSHOP,
                "123",
            )
            references = parse_share(export_share([asset]))

        ordered_ids, missing = resolve_share_with_pending(references, {})

        self.assertEqual(len(ordered_ids), 1)
        self.assertEqual(missing, references)
        self.assertEqual(
            parse_pending_workshop_mod_id(ordered_ids[0]),
            ("123", "example mod.pack"),
        )


if __name__ == "__main__":
    unittest.main()


def _lookup_line(
    digest: str,
    workshop_id: str,
    timestamp: str,
    pack_path: str,
    app_id: str = "1142710",
) -> str:
    return (
        f"mod_lookup_key://{digest}@steam_workshop:{app_id}/"
        f"{workshop_id}@{timestamp}/{pack_path}"
    )


def _official_example() -> str:
    """Ten synthetic launcher lines matching the real line grammar."""
    rows = [
        ("a1f0", "9000000001", "1740000001", "sample_first.pack"),
        ("b2e1", "3022341145", "1740000002", "chaos_daemons_roster.pack"),
        ("c3d2", "3105587120", "1740000003", "@@better_campaign_camera.pack"),
        ("d4c3", "3118647301", "1740000004", "zh_cn_localisation_fix.pack"),
        ("e5b4", "3200445512", "1740000005", "Battle Map Overhaul.pack"),
        ("f6a5", "3300117745", "1740000006", "better_alliance.pack"),
        ("a7f6", "3400881221", "1740000007", "unit_cards_remaster.pack"),
        ("b8e7", "3500992334", "1740000008", "region_trading.pack"),
        ("c9d8", "3601200545", "1740000009", "misc_fixes.pack"),
        ("d0c9", "9000000002", "1740000010", "sample_last.pack"),
    ]
    return "\n".join(
        _lookup_line(digest, workshop_id, timestamp, path)
        for digest, workshop_id, timestamp, path in rows
    )


class AdapterBoundaryTests(unittest.TestCase):
    def test_each_registered_adapter_owns_one_module_without_business_imports(self) -> None:
        import ast
        from pathlib import Path as _Path

        package = _Path("backend") / "share_adapters"
        forbidden = {"api", "storage", "steamworks_bridge", "models", "share_code"}
        adapter_modules = {
            type(adapter).__module__ for adapter in default_share_code_service()._adapters
        }
        # One adapter per file: no two registered formats share a module.
        self.assertEqual(len(adapter_modules), len(default_share_code_service()._adapters))
        for module in adapter_modules:
            with self.subTest(module=module):
                self.assertTrue(module.startswith("backend.share_adapters."))
                self.assertNotEqual(module, "backend.share_adapters.base")
                self.assertTrue((package / f"{module.rsplit('.', 1)[-1]}.py").is_file())

        module_names = {path.stem for path in package.glob("*.py")}
        for path in sorted(package.glob("*.py")):
            imported: set[str] = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom):
                    imported.add((node.module or "").split(".")[-1])
                elif isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[-1] for alias in node.names)
            with self.subTest(module=path.name):
                self.assertEqual(imported & forbidden, set())
                # base.py defines the contract; it must not know any format.
                if path.stem == "base":
                    self.assertEqual(imported & module_names, set())
                # Adapter files must not reach into sibling adapters.
                elif path.stem != "__init__":
                    self.assertEqual(imported & (module_names - {"base"}), set())

    def test_every_adapter_implements_the_bidirectional_contract(self) -> None:
        adapters = [WmmShareCodeAdapter(), OfficialModLookupKeyAdapter(), Wh3LegacyShareCodeAdapter()]
        self.assertEqual(
            [adapter.format_id for adapter in adapters],
            ["wmm-v2", "official-mod-lookup-key", "wh3-legacy"],
        )
        self.assertEqual(len({adapter.format_id for adapter in adapters}), len(adapters))
        for adapter in adapters:
            with self.subTest(adapter=adapter.format_id):
                self.assertTrue(callable(adapter.can_handle))
                self.assertTrue(callable(adapter.deserialize))
                self.assertTrue(callable(adapter.serialize))
                self.assertIsInstance(adapter.can_serialize, bool)


class WmmAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = WmmShareCodeAdapter()
        self.context = share_context("warhammer3")

    def test_round_trip_covers_empty_workshop_local_and_non_ascii_mods(self) -> None:
        cases = {
            "empty": [],
            "workshop": [
                ShareMod(
                    workshop_id="9000000001",
                    pack_name="shared_workshop.pack",
                    source=SOURCE_WORKSHOP,
                    mod_id="steam:9000000001:shared_workshop.pack",
                    position=0,
                )
            ],
            "local": [
                ShareMod(
                    pack_name="local_only.pack",
                    source=SOURCE_DATA,
                    mod_id="data:local_only.pack",
                    position=0,
                )
            ],
            "non-ascii": [
                ShareMod(
                    workshop_id="123",
                    pack_name="裁决之锤 中文.pack",
                    source=SOURCE_WORKSHOP,
                    mod_id="steam:123:裁决之锤 中文.pack",
                    position=0,
                ),
                ShareMod(
                    pack_name="本地增强.pack",
                    source=SOURCE_DATA,
                    mod_id="data:本地增强.pack",
                    position=1,
                ),
            ],
        }
        for name, mods in cases.items():
            with self.subTest(case=name):
                code = self.adapter.serialize(mods, self.context)
                self.assertTrue(code.startswith(f"{PREFIX}-"))
                result = self.adapter.deserialize(code, self.context)
                self.assertEqual(result.format_id, "wmm-v2")
                self.assertEqual(result.mods, mods)

    def test_serialized_form_matches_export_share(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mods = [
                make_asset(write_pack(root / "123" / "one.pack"), "one", SOURCE_WORKSHOP, "123"),
                make_asset(write_pack(root / "data" / "two.pack"), "two", SOURCE_DATA),
            ]
            self.assertEqual(
                self.adapter.serialize(share_mods_from_assets(mods), self.context),
                export_share(mods),
            )

    def test_rejects_corrupted_payload_and_wrong_game(self) -> None:
        code = self.adapter.serialize([], self.context)
        prefix, checksum, payload = code.split("-", 2)
        bad_checksum = "00000000" if checksum != "00000000" else "FFFFFFFF"
        with self.assertRaisesRegex(ValueError, "校验"):
            self.adapter.deserialize(f"{prefix}-{bad_checksum}-{payload}", self.context)
        with self.assertRaisesRegex(ValueError, "所属游戏"):
            self.adapter.deserialize(code, share_context("three_kingdoms"))


class LegacyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = Wh3LegacyShareCodeAdapter()
        self.context = share_context("warhammer3")

    def test_orders_tokens_and_keeps_missing_load_order_positions(self) -> None:
        result = self.adapter.deserialize("222;1|111;0|333", self.context)
        self.assertEqual(result.format_id, "wh3-legacy")
        self.assertEqual(
            [(mod.workshop_id, mod.position) for mod in result.mods],
            [("111", 0), ("222", 1), ("333", 2)],
        )
        self.assertTrue(all(mod.metadata[LEGACY_PROJECT_METADATA] for mod in result.mods))

    def test_skips_empty_tokens_and_tolerates_invalid_load_order(self) -> None:
        result = self.adapter.deserialize("123||456;x", self.context)
        self.assertEqual(
            [(mod.workshop_id, mod.position) for mod in result.mods],
            [("123", 0), ("456", 2)],
        )

    def test_empty_input_and_other_games_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "未识别到"):
            self.adapter.deserialize("||", self.context)
        with self.assertRaisesRegex(ValueError, "旧版分享码"):
            self.adapter.deserialize("123", share_context("three_kingdoms"))

    def test_serialize_round_trips_positions_and_rejects_local_mods(self) -> None:
        mods = self.adapter.deserialize("222;1|111;0", self.context).mods
        code = self.adapter.serialize(mods, self.context)
        self.assertEqual(code, "111;0|222;1")
        self.assertEqual(self.adapter.deserialize(code, self.context).mods, mods)
        with self.assertRaisesRegex(ValueError, "空 MOD 列表"):
            self.adapter.serialize([], self.context)
        with self.assertRaisesRegex(ValueError, "本地 MOD"):
            self.adapter.serialize([ShareMod(pack_name="local.pack")], self.context)

    def test_service_does_not_confuse_builtin_and_official_codes_for_legacy(self) -> None:
        service = default_share_code_service()
        wmm = WmmShareCodeAdapter().serialize([], self.context)
        self.assertEqual(service.deserialize(wmm, self.context).format_id, "wmm-v2")
        self.assertEqual(
            service.deserialize("123;0|456;1", self.context).format_id, "wh3-legacy"
        )


class OfficialAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = OfficialModLookupKeyAdapter()
        self.context = share_context("warhammer3")

    def test_user_example_decodes_ten_entries_in_order(self) -> None:
        result = self.adapter.deserialize(_official_example(), self.context)
        self.assertEqual(result.format_id, "official-mod-lookup-key")
        self.assertEqual(len(result.mods), 10)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.mods[0].workshop_id, "9000000001")
        self.assertEqual(result.mods[0].pack_name, "sample_first.pack")
        self.assertEqual(result.mods[0].metadata["hash"], "a1f0")
        self.assertEqual(result.mods[0].metadata["timestamp"], "1740000001")
        self.assertEqual(result.mods[-1].workshop_id, "9000000002")
        self.assertEqual(result.mods[-1].pack_name, "sample_last.pack")
        self.assertEqual(
            [mod.position for mod in result.mods], list(range(10))
        )
        self.assertIsNone(result.mods[0].source)
        self.assertIsNone(result.mods[0].mod_id)

    def test_decodes_encoded_paths_and_windows_separators(self) -> None:
        text = "\n".join(
            [
                _lookup_line("aa", "111", "10", "folder/My%20Mod%21.pack"),
                _lookup_line("bb", "222", "11", "folder%5CBack%20Slash.pack"),
            ]
        )
        result = self.adapter.deserialize(text, self.context)
        self.assertEqual(
            [mod.pack_name for mod in result.mods], ["My Mod!.pack", "Back Slash.pack"]
        )
        self.assertEqual(
            [mod.metadata["pack_path"] for mod in result.mods],
            ["folder/My%20Mod%21.pack", "folder%5CBack%20Slash.pack"],
        )

    def test_ignores_blank_comment_and_unknown_lines_but_reports_them(self) -> None:
        text = "\n".join(
            [
                "",
                "# The Creative Assembly profile",
                _lookup_line("aa", "111", "10", "one.pack"),
                "unsupported line",
                _lookup_line("bb", "111", "11", "ONE.PACK"),
                _lookup_line("cc", "222", "12", "two.pack"),
            ]
        )
        result = self.adapter.deserialize(text, self.context)
        self.assertEqual(
            [(mod.workshop_id, mod.pack_name) for mod in result.mods],
            [("111", "one.pack"), ("222", "two.pack")],
        )
        self.assertEqual(result.warnings, ["unsupported line"])

    def test_rejects_malformed_foreign_app_and_wrong_suffix_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "没有有效的 MOD 行"):
            self.adapter.deserialize(
                _lookup_line("aa", "111", "10", "folder/mod.zip"), self.context
            )
        with self.assertRaisesRegex(ValueError, "其他游戏"):
            self.adapter.deserialize(
                _lookup_line("aa", "111", "10", "one.pack", app_id="594570"), self.context
            )
        self.assertEqual(
            OfficialModLookupKeyAdapter()
            .deserialize(_lookup_line("aa", "111", "10", "ok.pack"), self.context)
            .format_id,
            "official-mod-lookup-key",
        )

    def test_round_trip_uses_preserved_metadata(self) -> None:
        text = _official_example()
        result = self.adapter.deserialize(text, self.context)
        self.assertEqual(self.adapter.serialize(result.mods, self.context), text)

    def test_serialize_refuses_mods_without_official_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            mods = share_mods_from_assets(
                [make_asset(write_pack(Path(temporary) / "one.pack"), "one", SOURCE_WORKSHOP, "123")]
            )
        with self.assertRaisesRegex(ValueError, "hash"):
            self.adapter.serialize(mods, self.context)
        with self.assertRaisesRegex(ValueError, "空 MOD 列表"):
            self.adapter.serialize([], self.context)

    def test_can_handle_requires_the_scheme(self) -> None:
        self.assertTrue(self.adapter.can_handle(_official_example()))
        self.assertFalse(self.adapter.can_handle("WMM1-00000000-AAAA"))
        self.assertFalse(self.adapter.can_handle("123;0|456;1"))


class ShareCodeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = default_share_code_service()
        self.context = share_context("warhammer3")

    def test_registration_order_is_stable(self) -> None:
        self.assertEqual(
            self.service.format_ids,
            ("wmm-v2", "official-mod-lookup-key", "wh3-legacy"),
        )

    def test_rejects_empty_oversized_and_unrecognized_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "请粘贴分享码"):
            self.service.deserialize("   ", self.context)
        with patch.object(share_code_module, "MAX_SHARE_CODE_CHARS", 8):
            with self.assertRaisesRegex(ValueError, "过长"):
                self.service.deserialize("x" * 9, self.context)
        wmm_only = ShareCodeService([WmmShareCodeAdapter()])
        with self.assertRaisesRegex(ValueError, "未识别到"):
            wmm_only.deserialize("123;0", self.context)

    def test_serialize_rejects_unknown_and_non_serializable_formats(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的分享码格式"):
            self.service.serialize([], self.context, format_id="nope")
        read_only = _ReadOnlyAdapter()
        service = ShareCodeService([read_only])
        with self.assertRaisesRegex(ValueError, "不支持导出"):
            service.serialize([], self.context, format_id=read_only.format_id)

    def test_references_bridge_keeps_legacy_reference_shape(self) -> None:
        references = self.service.references("222;1|111;0", self.context)
        self.assertEqual(
            references[0],
            {
                "workshop_id": "111",
                "pack_name": "",
                "source": "",
                "position": 0,
                "legacy_workshop_project": True,
            },
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = write_pack(Path(temporary) / "mod.pack")
            code = export_share([make_asset(path, "mod", SOURCE_DATA)])
        reference = self.service.references(code, self.context)[0]
        self.assertEqual(reference["id"], "mod")
        self.assertEqual(reference["pack_name"], "mod.pack")
        self.assertEqual(reference["source"], SOURCE_DATA)

    def test_official_lines_resolve_through_the_shared_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installed = make_asset(
                write_pack(root / "123" / "installed.pack"),
                "installed",
                SOURCE_WORKSHOP,
                "123",
            )
            references = self.service.references(
                _lookup_line("aa", "123", "10", "installed.pack"), self.context
            )
            ordered_ids, missing = resolve_share_with_pending(references, {installed.id: installed})
            self.assertEqual(ordered_ids, ["installed"])
            self.assertEqual(missing, [])
            ordered_ids, missing = resolve_share_with_pending(references, {})
            self.assertEqual(ordered_ids, ["pending:steam:123:installed.pack"])
            self.assertEqual(missing, references)


class _ReadOnlyAdapter:
    format_id = "read-only"
    can_serialize = False

    def can_handle(self, value: str) -> bool:
        return False

    def deserialize(self, value: str, context) -> ShareCodeParseResult:  # pragma: no cover
        raise AssertionError("never selected")

    def serialize(self, mods, context) -> str:  # pragma: no cover
        raise ValueError("不支持导出")


class _RecordingService:
    def __init__(self) -> None:
        self.inner = default_share_code_service()
        self.calls: list[str] = []

    def references(self, value: str, context):
        self.calls.append("deserialize")
        return self.inner.references(value, context)

    def serialize(self, mods, context, format_id: str = DEFAULT_EXPORT_FORMAT_ID) -> str:
        self.calls.append(f"serialize:{format_id}")
        return self.inner.serialize(mods, context, format_id=format_id)


class ShareServiceIntegrationTests(unittest.TestCase):
    def test_share_rpcs_go_through_the_adapter_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            api = API(Path(temporary) / "state")
            recorded = _RecordingService()
            api.share_codes = recorded

            exported = api.call("export_share", [[]])
            self.assertTrue(exported["ok"], exported)
            code = exported["data"]["share_code"]
            self.assertTrue(code.startswith(f"{PREFIX}-"))

            preview = api.call("preview_import_share", [code])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["ordered_mod_ids"], [])

            imported = api.call("import_share", [code])
            self.assertTrue(imported["ok"], imported)

            self.assertEqual(
                recorded.calls,
                ["serialize:wmm-v2", "deserialize", "deserialize"],
            )

    def test_pasted_twmods_file_text_with_bom_and_header_imports(self) -> None:
        # Exactly what the official launcher writes: UTF-8 BOM, "# TW Mod Profile"
        # comment, CRLF line endings. Neither the BOM nor the header is a MOD.
        content = "\r\n".join(
            [
                "# TW Mod Profile",
                "",
                _lookup_line("a1f0", "9000000001", "1740000001", "sample_first.pack"),
                _lookup_line("b2e1", "9000000002", "1740000010", "sample_last.pack"),
            ]
        )
        pasted = "\ufeff" + content
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            api = API(root / "state")
            installed = make_asset(
                write_pack(root / "workshop" / "9000000001" / "sample_first.pack"),
                "prayer-id",
                SOURCE_WORKSHOP,
                "9000000001",
            )
            api._assets = {installed.id: installed}
            with patch(
                "backend.api.query_workshop_subscription_status",
                return_value=[
                    {"workshop_id": "9000000002", "title": "Sample Last", "subscribed": False}
                ],
            ):
                preview = api.call("preview_import_share", [pasted])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["data"]["ordered_mod_ids"], ["prayer-id"])
            self.assertEqual(
                [item["workshop_id"] for item in preview["data"]["unsubscribed"]],
                ["9000000002"],
            )

            imported = api.call("import_share", [pasted])
            self.assertTrue(imported["ok"], imported)
            self.assertEqual(imported["data"]["pending_workshop_ids"], ["9000000002"])
            self.assertEqual(imported["data"]["ordered_mod_ids"], ["prayer-id"])


class ShareInputNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = default_share_code_service()
        self.context = share_context("warhammer3")

    def test_header_and_prose_only_text_is_not_imported_as_a_mod(self) -> None:
        for text in ("# TW Mod Profile", "# TW Mod Profile\n\n# another comment", "hello world"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "未识别到可导入的 MOD"):
                    self.service.deserialize(text, self.context)

    def test_bom_prefixed_single_official_line_is_recognized(self) -> None:
        result = self.service.deserialize(
            "\ufeff" + _lookup_line("a1f0", "9000000001", "1740000001", "mod.pack"),
            self.context,
        )
        self.assertEqual(result.format_id, "official-mod-lookup-key")
        self.assertEqual(result.mods[0].workshop_id, "9000000001")
        self.assertEqual(result.warnings, [])

    def test_comment_lines_inside_legacy_text_are_skipped(self) -> None:
        result = self.service.deserialize(
            "# WH3-Mod-Manager project\n111;0|222;1", self.context
        )
        self.assertEqual(result.format_id, "wh3-legacy")
        self.assertEqual([mod.workshop_id for mod in result.mods], ["111", "222"])

    def test_unknown_game_id_is_not_rewritten_to_warhammer3(self) -> None:
        self.assertEqual(share_context("bogus").game_id, "bogus")
        with self.assertRaisesRegex(ValueError, "不支持的分享码版本或游戏"):
            export_share([], "bogus")
        code = export_share([], "warhammer3")
        with self.assertRaisesRegex(ValueError, "所属游戏"):
            parse_share(code, "bogus")
