from __future__ import annotations

from copy import deepcopy
from typing import Any


APP_CHANGELOG: list[dict[str, Any]] = [
    {
        "version": "0.1.0",
        "date": "2026-07-15",
        "entries": [
            {
                "title": "管理器基础功能",
                "changes": [
                    {"type": "feature", "text": "使用播放集管理 MOD 启用状态与加载顺序，所有修改即时保存。"},
                    {"type": "feature", "text": "支持继续游戏、从存档列表载入、Workshop 管理与依赖缺失警告。"},
                    {"type": "feature", "text": "支持按当前语言优先检查 Gitee 或 GitHub，并在双源间自动回退。"},
                    {"type": "feature", "text": "右键菜单新增“打开文件目录”；批量选择时显示操作数量，并禁用 RPFM 单项操作。"},
                    {"type": "feature", "text": "支持下载校验、安全替换以及应用内更新日志。"},
                ],
            }
        ],
    }
]


def get_all_changelogs() -> list[dict[str, Any]]:
    """Return an isolated copy suitable for the desktop bridge."""
    return deepcopy(APP_CHANGELOG)
