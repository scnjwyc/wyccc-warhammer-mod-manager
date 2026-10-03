"""Real launch, bootstrap, and comparison RPC responses for frontend validation."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.api import API
from tests.helpers import write_pack


def fixture():
    with tempfile.TemporaryDirectory(prefix="wmm-launch-comparison-") as temporary:
        root = Path(temporary)
        game = root / "game"
        (game / "data").mkdir(parents=True)
        (game / "Warhammer3.exe").touch()
        workshop = root / "workshop"
        workshop.mkdir()
        api = API(root / "state")
        try:
            with patch.object(api, "detect_game_running", return_value=False), patch("backend.api.is_game_running", return_value=False):
                assert api.call("save_settings", [{
                    "game_path": str(game), "workshop_path": str(workshop), "language": "zh-CN",
                    "fetch_workshop_metadata": False, "live_mod_detection": False,
                }])["ok"]
                for name in ("a", "b", "c", "new"):
                    write_pack(game / "data" / f"{name}.pack", byte_mask=3)
                assert api.call("scan_mods", [False])["ok"]
                ids = {Path(asset.pack_name).stem: asset.id for asset in api._assets.values()}
                for name, title in zip(("a", "b", "c", "new"), ("龙裔扩展", "江湖英雄", "建筑调整", "新兵种合集")):
                    assert api.call("save_mod_user_data", [ids[name], title])["ok"]
                with patch("backend.api.launch_game", return_value={"pid": 123}):
                    result = api.call("launch_game", [[ids[name] for name in ("a", "b", "c")]])
                assert result["ok"], result
                history = api.call("list_launch_history")
                assert history["ok"], history
                record_id = history["data"]["items"][0]["id"]
                with patch("backend.api.launch_game", return_value={"pid": 124}):
                    assert api.call("launch_game", [[ids[name] for name in ("b", "c")]])["ok"]
                assert api.call("save_load_order", [[ids[name] for name in ("c", "b", "new")]])["ok"]
                history = api.call("list_launch_history")
                payload = api.call("get_launch_record", [record_id])
                snapshots = {row["id"]: api.call("get_launch_record", [row["id"]]) for row in history["data"]["items"]}
                api.set_game_running(False, force=True)
                bootstrap = api.call("get_bootstrap")
                bootstrap["data"]["show_changelog"] = False
                scan = api.call("scan_mods", [False])
                loaded = api.call("load_launch_record", [payload["data"]["id"], scan["data"]["order_token"]])
                assert payload["ok"] and loaded["ok"], (payload, loaded)
                return {"snapshot": payload, "snapshots": snapshots, "history": history, "loaded": loaded, "bootstrap": bootstrap,
                        "scan": scan,
                        "diagnostics": api.call("get_mod_diagnostics"),
                        "crash": api.call("get_crash_diagnosis")}
        finally:
            api.close()


if __name__ == "__main__":
    print(json.dumps(fixture()))
