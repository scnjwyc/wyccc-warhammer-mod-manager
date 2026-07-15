from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

from .constants import WH3_EXECUTABLE, WH3_PROCESS_NAME


def is_game_running() -> bool:
    if os.name == "nt":
        try:
            completed = subprocess.run(
                [
                    "tasklist",
                    "/FI",
                    f"IMAGENAME eq {WH3_PROCESS_NAME}",
                    "/FO",
                    "CSV",
                    "/NH",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            rows = list(csv.reader(completed.stdout.splitlines()))
            return any(row and row[0].casefold() == WH3_PROCESS_NAME.casefold() for row in rows)
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        completed = subprocess.run(
            ["pgrep", "-f", WH3_PROCESS_NAME],
            capture_output=True,
            check=False,
            timeout=5,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def launch_game(
    game_path: str,
    mod_list_path: str,
    save_name: str = "",
) -> dict[str, int | str | list[str]]:
    game_root = Path(game_path)
    executable = game_root / WH3_EXECUTABLE
    if not executable.is_file():
        raise ValueError(f"找不到游戏可执行文件：{executable}")
    if not Path(mod_list_path).is_file():
        raise ValueError(f"找不到启动清单：{mod_list_path}")
    if is_game_running():
        raise ValueError("Warhammer3.exe 已经在运行")

    normalized_save_name = str(save_name or "").strip()
    if normalized_save_name and (
        Path(normalized_save_name).name != normalized_save_name
        or '"' in normalized_save_name
    ):
        raise ValueError("存档名称无效")
    arguments: list[str] = []
    if normalized_save_name:
        arguments.extend(
            ["game_startup_mode", "campaign_load", normalized_save_name, ";"]
        )
    arguments.append(f"{Path(mod_list_path).name};")
    argument = " ".join(
        f'"{value}"' if " " in value else value for value in arguments
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    process = subprocess.Popen(
        [str(executable), *arguments],
        cwd=str(game_root),
        close_fds=True,
        creationflags=creationflags,
    )
    return {
        "pid": process.pid,
        "argument": argument,
        "arguments": arguments,
        "executable": str(executable),
    }
