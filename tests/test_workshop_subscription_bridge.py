import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.steamworks_bridge import (
    SteamworksBridgeError,
    find_node_executable,
    get_subscribed_workshop_items,
)


@pytest.mark.parametrize("ids", [[], ["101", "102", "101"]])
def test_native_subscription_list_uses_selected_app_without_querying_metadata(tmp_path: Path, ids: list[str]):
    node = find_node_executable()
    if node is None:
        pytest.skip("Node.js runtime is unavailable")
    runtime = tmp_path / "steam_runtime"
    runtime.mkdir()
    (runtime / "workshop_bridge.js").write_text(
        (Path(__file__).parents[1] / "steam_runtime" / "workshop_bridge.js").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    native = runtime / "steamworks"
    native.mkdir()
    (native / "index.js").write_text(
        'module.exports = { init(appId) { '
        'if (appId !== 779340) throw new Error("wrong game"); '
        'return { workshop: { getSubscribedItems() { '
        f'return {json.dumps(ids)}.map(BigInt); '
        '} } }; } };',
        encoding="utf-8",
    )
    with patch("backend.steamworks_bridge.find_node_executable", return_value=node):
        result = get_subscribed_workshop_items(app_id=779340, root=tmp_path)
    assert result == list(dict.fromkeys(ids))


@pytest.mark.parametrize("source", [None, {}, ["bad-id"], [None]])
def test_unavailable_or_malformed_subscription_list_is_not_treated_as_empty(source):
    with patch("backend.steamworks_bridge._run_bridge_request", return_value={"subscribed_ids": source}):
        with pytest.raises(SteamworksBridgeError, match="invalid subscribed item data"):
            get_subscribed_workshop_items()
