"""Emit a real apply RPC response and its durable state for frontend regression tests."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from backend.crash_diagnostics import parse_launch_list
from backend.load_order import file_token
from backend.models import GamePaths
from backend.storage import StateRepository
from tests.helpers import make_asset, write_pack


def applied_fixture(restore: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="wmm-diagnostics-bridge-") as temporary:
        root = Path(temporary)
        game = root / "game"
        data = game / "data"
        data.mkdir(parents=True)
        (game / "Warhammer3.exe").write_bytes(b"fixture")
        order = game / "used_mods.txt"
        order.write_bytes(b"original\r\n")
        api = API(root / "state")
        paths = GamePaths(game_path=str(game), data_path=str(data))
        api._assets = {
            item: make_asset(write_pack(data / f"{item}.pack", byte_mask=3), item, "data")
            for item in "abc"
        }
        api.state_repository.update_current_playset(list("abc"), "warhammer3")
        api._last_order_token = file_token(order)

        def trial(_probe, path, *_args):
            return {"verdict": "crash" if "b.pack" in parse_launch_list(Path(path))[1] else "ok"}

        try:
            with (
                patch.object(api.settings_service, "resolve_game_paths", return_value=paths),
                patch.object(api, "detect_game_running", return_value=False),
                patch("backend.diagnostics_api.GameProbe.run", autospec=True, side_effect=trial),
            ):
                assert api.call("start_mod_diagnostics", [list("abc"), "bisect"])["ok"]
                api.diagnostics.session._thread.join(5)
                state = api.diagnostics.session.status()
                assert state["can_apply"]
                response = api.call("apply_diagnostics_result", [state["id"], restore, file_token(order)])
                assert response["ok"], response
                # A fresh repository connection checks committed state, not a cached object.
                repository = StateRepository(api.state_repository.database_path)
                return {"payload": response["data"],
                        "persisted_ids": repository.get_current_playset()["mod_ids"],
                        "disk_pack_names": parse_launch_list(order)[1],
                        "disk_token": file_token(order)}
        finally:
            api.close()


if __name__ == "__main__":
    print(json.dumps(applied_fixture("--restore" in sys.argv)))
