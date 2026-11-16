from unittest.mock import patch

import pytest

from backend.api import API
from tests.test_last_launch_comparison import select_game


@pytest.mark.parametrize("multiplayer", [False, True])
@pytest.mark.parametrize("method", ["launch_game", "continue_game"])
def test_audio_expansion_reaches_normal_multiplayer_and_save_launches(tmp_path, multiplayer, method):
    api = API(tmp_path / "state")
    try:
        select_game(api, tmp_path)
        api.settings_service.save({"enable_audio_pool_expansion": True, "multiplayer_mode": multiplayer})
        with (
            patch.object(api, "detect_game_running", return_value=False),
            patch.object(api.save_games, "latest", return_value={"name": "campaign.save"}),
            patch.object(api.save_games, "require", return_value={"name": "campaign.save"}),
            patch("backend.api.launch_game", return_value={"pid": 123}) as launch,
            patch("backend.api.query_workshop_subscription_status", return_value=[]),
        ):
            args = [[], "", "campaign.save"] if method == "launch_game" else [[], ""]
            result = api.call(method, args)
        assert result["ok"], result
        assert launch.call_args.kwargs["enable_audio_pool_expansion"] is True
        assert launch.call_args.args[2] == "campaign.save"
    finally:
        api.close()


@pytest.mark.parametrize("game_id", ["three_kingdoms", "rome2"])
def test_other_games_do_not_receive_warhammer_audio_patch(tmp_path, game_id):
    api = API(tmp_path / "state")
    try:
        select_game(api, tmp_path, game_id)
        api.settings_service.save({"enable_audio_pool_expansion": True})
        with (
            patch.object(api, "detect_game_running", return_value=False),
            patch("backend.api.launch_game", return_value={"pid": 123}) as launch,
        ):
            result = api.call("launch_game", [[]])
        assert result["ok"], result
        assert not launch.call_args.kwargs.get("enable_audio_pool_expansion", False)
    finally:
        api.close()
