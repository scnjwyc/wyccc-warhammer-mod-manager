from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import patch
from urllib.error import URLError

import pytest

from backend.ai_service import recognize_mod_types
from backend.api import API
from backend.mod_types import default_mod_types
from backend.storage import StateRepository
from tests.helpers import make_asset


class Response:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": self.content}}]}).encode()


@pytest.fixture
def api(tmp_path):
    instance = API(tmp_path / "state")
    instance.settings_service.save({
        "ai_enabled": True,
        "ai_base_url": "https://example.invalid/v1/",
        "ai_api_key": "test-key",
        "ai_model": "configured-model",
        "ai_temperature": 0.2,
        "language": "zh-CN",
    })
    asset = make_asset(tmp_path / "!!_nanu_dynamic_rors中文汉化.pack", "translation", "workshop", "123")
    asset.alias = "玩家标题"
    asset.notes = "玩家备注"
    asset.mod_type = "ui"
    asset.mod_types = ["ui"]
    instance._assets[asset.id] = asset
    instance.state_repository.save_user_mod_data(asset.id, asset.alias, asset.notes)
    instance.state_repository.set_mod_types(asset.id, ["ui"])
    yield instance
    instance.close()


def test_workshop_description_is_queried_and_language_tag_is_saved(api):
    description = "这是 nanu dynamic rors 的中文汉化，仅翻译原 MOD 文本，不新增单位。"
    with (
        patch.object(api.workshop_service, "refresh_localized", return_value={
            "123": {"title": "!!_nanu_dynamic_rors中文汉化", "description": description},
        }) as refresh,
        patch("backend.ai_service.request.urlopen", return_value=Response('```json\n{"mod_types":["language"]}\n```')) as urlopen,
    ):
        result = api.call("recognize_mod_types", ["translation"])

    assert result["ok"], result
    assert result["data"]["mod_types"] == ["language"]
    assert result["data"]["mod_type"] == "language"
    assert result["data"]["alias"] == "玩家标题"
    assert result["data"]["notes"] == "玩家备注"
    refresh.assert_called_once_with(["123"], "zh-CN", app_id=1142710)
    sent = urlopen.call_args.args[0]
    assert sent.full_url == "https://example.invalid/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer test-key"
    body = json.loads(sent.data)
    assert body["model"] == "configured-model"
    assert body["temperature"] == 0.2
    prompt = json.loads(body["messages"][1]["content"])
    assert prompt["mod"]["description"] == description
    assert prompt["mod"]["title"] == "!!_nanu_dynamic_rors中文汉化"
    assert "必须选择 language" in body["messages"][0]["content"]
    assert "依赖 MOD" in body["messages"][0]["content"]
    saved = StateRepository(api.data_dir / "state.db").list_user_mod_data()["translation"]
    assert saved["mod_types"] == ["language"]
    assert saved["alias"] == "玩家标题"
    assert saved["notes"] == "玩家备注"


def test_default_and_current_custom_types_are_sent_and_multiple_tags_persist(api):
    asset = api._assets["translation"]
    asset.workshop_id = ""
    asset.source = "data"
    asset.description = "Adds a UI panel and new music."
    custom = api.state_repository.create_mod_type("音乐音效")
    api.state_repository.update_mod_type(custom["id"], "音乐")
    response = {"mod_types": ["unknown", "ui", custom["id"], "ui"]}
    with (
        patch.object(api.workshop_service, "refresh_localized") as refresh,
        patch("backend.ai_service.request.urlopen", return_value=Response(json.dumps(response))) as urlopen,
    ):
        result = api.call("recognize_mod_types", [asset.id])
    assert result["ok"], result
    refresh.assert_not_called()
    assert result["data"]["mod_types"] == ["ui", custom["id"]]
    prompt = json.loads(json.loads(urlopen.call_args.args[0].data)["messages"][1]["content"])
    catalog = {item["id"]: item["name"] for item in prompt["available_types"]}
    assert catalog == {**{item["id"]: item["name"] for item in default_mod_types()}, custom["id"]: "音乐"}
    assert prompt["mod"]["description"] == asset.description
    assert api.state_repository.list_user_mod_data()[asset.id]["mod_types"] == ["ui", custom["id"]]


@pytest.mark.parametrize("content", [
    '{"mod_types":["ui","invented"]}',
    '{"mod_types":["语言包"]}',
    '{"mod_types":"language"}',
    '{"mod_types":[1]}',
    '{"title":"language"}',
    'not json',
])
def test_invalid_ai_result_preserves_existing_tags(api, content):
    api._assets["translation"].workshop_id = ""
    with patch("backend.ai_service.request.urlopen", return_value=Response(content)):
        result = api.call("recognize_mod_types", ["translation"])
    assert not result["ok"]
    assert api._assets["translation"].mod_types == ["ui"]
    assert api.state_repository.list_user_mod_data()["translation"]["mod_types"] == ["ui"]


@pytest.mark.parametrize("values", [[], ["unknown"]])
def test_no_match_uses_unknown(api, values):
    asset = replace(api._assets["translation"], workshop_id="")
    with patch("backend.ai_service.request.urlopen", return_value=Response(json.dumps({"mod_types": values}))):
        assert recognize_mod_types(asset, api.settings_service.get(), default_mod_types()) == ["unknown"]


@pytest.mark.parametrize("settings", [{"ai_enabled": False}, {"ai_model": ""}, {"ai_base_url": "invalid"}])
def test_configuration_is_validated_before_querying_steam(api, settings):
    api.settings_service.save(settings)
    with patch.object(api.workshop_service, "refresh_localized") as refresh:
        result = api.call("recognize_mod_types", ["translation"])
    assert not result["ok"]
    refresh.assert_not_called()


def test_cached_description_can_be_used_when_workshop_returns_no_copy(api):
    api._assets["translation"].description = "Chinese translation only."
    with (
        patch.object(api.workshop_service, "refresh_localized", return_value={}),
        patch("backend.ai_service.request.urlopen", return_value=Response('{"mod_types":["language"]}')) as urlopen,
    ):
        assert api.call("recognize_mod_types", ["translation"])["ok"]
    prompt = json.loads(json.loads(urlopen.call_args.args[0].data)["messages"][1]["content"])
    assert prompt["mod"]["description"] == "Chinese translation only."


def test_unavailable_workshop_description_does_not_send_ai_request(api):
    with (
        patch.object(api.workshop_service, "refresh_localized", return_value={}),
        patch("backend.ai_service.request.urlopen") as urlopen,
    ):
        result = api.call("recognize_mod_types", ["translation"])
    assert not result["ok"]
    assert "描述" in result["error"]["message"]
    urlopen.assert_not_called()


def test_ai_connection_failure_preserves_tags(api):
    api._assets["translation"].workshop_id = ""
    with patch("backend.ai_service.request.urlopen", side_effect=URLError("offline")):
        result = api.call("recognize_mod_types", ["translation"])
    assert not result["ok"]
    assert api.state_repository.list_user_mod_data()["translation"]["mod_types"] == ["ui"]


def test_game_switch_during_identification_does_not_apply_result(api):
    api._assets["translation"].workshop_id = ""

    def switch_game(*_args):
        api._game_context_revision += 1
        return ["language"]

    with patch("backend.api.recognize_mod_types", side_effect=switch_game):
        result = api.call("recognize_mod_types", ["translation"])
    assert not result["ok"]
    assert "游戏已切换" in result["error"]["message"]
    assert api.state_repository.list_user_mod_data()["translation"]["mod_types"] == ["ui"]


def test_deleted_custom_type_is_rejected_before_saving(api):
    api._assets["translation"].workshop_id = ""
    custom = api.state_repository.create_mod_type("音效")

    def delete_type(*_args):
        api.state_repository.delete_mod_type(custom["id"])
        return ["language", custom["id"]]

    with patch("backend.api.recognize_mod_types", side_effect=delete_type):
        result = api.call("recognize_mod_types", ["translation"])
    assert not result["ok"]
    assert api._assets["translation"].mod_types == ["ui"]
    assert api.state_repository.list_user_mod_data()["translation"]["mod_types"] == ["ui"]
