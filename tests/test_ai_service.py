from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.ai_service import generate_mod_user_data
from backend.models import ModAsset
from backend.warhammer_translation import build_mod_translation_prompts


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class AiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        path = Path("sample.pack").resolve(strict=False)
        self.asset = ModAsset(
            id="steam:123:sample.pack",
            pack_name="sample.pack",
            display_name="Sample Units",
            path=str(path),
            directory=str(path.parent),
            source="workshop",
            workshop_id="123",
            author="Example",
            description="Adds several custom units.",
        )

    def test_openai_compatible_generation_parses_json_and_sends_local_config(self) -> None:
        response = _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '```json\n{"title":"示例单位",'
                                '"description":"新增数个单位"}\n```'
                            )
                        }
                    }
                ]
            }
        )
        with patch("backend.ai_service.request.urlopen", return_value=response) as urlopen:
            generated = generate_mod_user_data(
                self.asset,
                {
                    "ai_enabled": True,
                    "ai_base_url": "https://example.invalid/v1/",
                    "ai_api_key": "secret",
                    "ai_model": "example-model",
                    "ai_temperature": 0.2,
                },
            )

        self.assertEqual(generated, {"alias": "示例单位", "notes": "新增数个单位"})
        sent = urlopen.call_args.args[0]
        self.assertEqual(sent.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(sent.headers["Authorization"], "Bearer secret")
        body = json.loads(sent.data.decode("utf-8"))
        self.assertEqual(body["model"], "example-model")
        self.assertIn("sample.pack", body["messages"][1]["content"])

    def test_generation_uses_glossary_first_translation_prompt(self) -> None:
        asset = replace(
            self.asset,
            display_name="Celestial Dragon Guards of Nan Gau",
            description="Adds Celestial Dragon Guards to Nan-Gau.",
        )
        response = _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"title":"南皋天廷龙卫",'
                                '"description":"为南皋新增天廷龙卫。"}'
                            )
                        }
                    }
                ]
            }
        )

        with TemporaryDirectory() as temporary_directory:
            glossary_path = Path(temporary_directory) / "术语库.md"
            glossary_path.write_text(
                "| 英文 | 中文译名 |\n"
                "| --- | --- |\n"
                "| Celestial Dragon Guard | 天廷龙卫 |\n"
                "| Nan Gau | 南皋 |\n"
                "| Unused Term | 不应发送 |\n",
                encoding="utf-8",
            )
            with patch("backend.ai_service.request.urlopen", return_value=response) as urlopen:
                generated = generate_mod_user_data(
                    asset,
                    {
                        "ai_enabled": True,
                        "ai_base_url": "https://example.invalid/v1",
                        "ai_model": "example-model",
                        "ai_glossary_path": str(glossary_path),
                        "language": "zh-CN",
                    },
                )

        self.assertEqual(
            generated,
            {"alias": "南皋天廷龙卫", "notes": "为南皋新增天廷龙卫。"},
        )
        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        system_prompt = body["messages"][0]["content"]
        user_prompt = body["messages"][1]["content"]
        self.assertIn("阶段一：术语预处理（必须先做）", system_prompt)
        self.assertIn("目标语言是：简体中文（zh-CN）", system_prompt)
        self.assertIn("先结合标题理解 MOD", system_prompt)
        self.assertIn("总结归纳原始描述，再把总结翻译成目标语言", system_prompt)
        self.assertIn("禁止联网搜索", system_prompt)
        self.assertIn("禁止查询、对照或声称对照了原版英文/中文 LOC", system_prompt)
        self.assertIn("Celestial Dragon Guard → 天廷龙卫", user_prompt)
        self.assertIn("Nan Gau → 南皋", user_prompt)
        self.assertNotIn("Unused Term", user_prompt)

    def test_generation_prompt_allows_direct_translation_when_glossary_has_no_match(self) -> None:
        response = _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"示例单位","description":"新增数个单位。"}'
                        }
                    }
                ]
            }
        )
        with TemporaryDirectory() as temporary_directory:
            glossary_path = Path(temporary_directory) / "术语库.md"
            glossary_path.write_text(
                "| 英文 | 中文译名 |\n| --- | --- |\n| Other Term | 其他术语 |\n",
                encoding="utf-8",
            )
            with patch("backend.ai_service.request.urlopen", return_value=response) as urlopen:
                generate_mod_user_data(
                    self.asset,
                    {
                        "ai_enabled": True,
                        "ai_base_url": "https://example.invalid/v1",
                        "ai_model": "example-model",
                        "ai_glossary_path": str(glossary_path),
                        "language": "ja-JP",
                    },
                )

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        user_prompt = body["messages"][1]["content"]
        system_prompt = body["messages"][0]["content"]
        self.assertIn("目标语言是：日语（ja-JP）", system_prompt)
        self.assertIn("目标语言：日语（ja-JP）", user_prompt)
        self.assertIn("备注先结合标题总结原描述、再翻译", user_prompt)
        self.assertIn("本地词库未命中。请按上下文直接翻译", user_prompt)
        self.assertNotIn("Other Term", user_prompt)

    def test_generation_requires_an_enabled_config_and_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "未启用"):
            generate_mod_user_data(self.asset, {"ai_enabled": False})
        with self.assertRaisesRegex(ValueError, "模型"):
            generate_mod_user_data(
                self.asset,
                {"ai_enabled": True, "ai_base_url": "http://localhost:1234/v1", "ai_model": ""},
            )

    def test_generation_prompt_supports_spanish_as_a_target_language(self) -> None:
        system_prompt, user_prompt = build_mod_translation_prompts(
            self.asset,
            target_language="es-ES",
        )

        self.assertIn("目标语言是：西班牙语（es-ES）", system_prompt)
        self.assertIn("目标语言：西班牙语（es-ES）", user_prompt)


if __name__ == "__main__":
    unittest.main()
