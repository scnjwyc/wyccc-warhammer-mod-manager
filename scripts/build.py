from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PACKAGING = ROOT / "packaging"
STEAM_RUNTIME = ROOT / "steam_runtime"
EXECUTABLE_NAME = "Wyccc's Mod Manager"
DEFAULT_RELEASE_DIR = (
    Path(r"G:\Wyccc's Mod Manager")
    if os.name == "nt"
    else ROOT / "dist" / "release"
)


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    printable = subprocess.list2cmdline(command)
    print(f"> {printable}")
    subprocess.run(command, cwd=cwd, check=True)


def find_pnpm() -> str:
    names = ("pnpm.cmd", "pnpm") if os.name == "nt" else ("pnpm",)
    for name in names:
        candidate = shutil.which(name)
        if candidate:
            return candidate
    raise SystemExit("找不到 pnpm；请先安装 Node.js 22+ 与 pnpm 11+，并加入 PATH。")


def find_node_for_packaging() -> Path | None:
    candidates: list[Path] = []
    for environment_name in (
        "WMM_STEAMWORKS_NODE",
        "WMM_NODE",
        "WWM_STEAMWORKS_NODE",
        "WWM_NODE",
        "WWMM_STEAMWORKS_NODE",
        "WWMM_NODE",
    ):
        value = os.environ.get(environment_name, "").strip()
        if value:
            candidates.append(Path(value).expanduser())
    path_node = shutil.which("node.exe") or shutil.which("node")
    if path_node:
        candidates.append(Path(path_node))
    program_files = os.environ.get("ProgramFiles", "").strip()
    if program_files:
        candidates.append(Path(program_files) / "nodejs" / "node.exe")
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "nodejs" / "node.exe")
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        candidates.append(
            Path(user_profile)
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            probe = subprocess.run(
                [str(candidate), "-p", "process.versions.node.split('.')[0]"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            if probe.returncode == 0 and int(probe.stdout.strip()) >= 22:
                return candidate.resolve(strict=False)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
    return None


def build_frontend(*, install: bool, tests: bool) -> None:
    pnpm = find_pnpm()
    if install:
        install_command = [pnpm, "install"]
        if (FRONTEND / "pnpm-lock.yaml").is_file():
            install_command.append("--frozen-lockfile")
        run(install_command, cwd=FRONTEND)
    if tests:
        run([pnpm, "test"], cwd=FRONTEND)
    run([pnpm, "build"], cwd=FRONTEND)


def package_desktop(output_dir: Path) -> Path:
    static_root = FRONTEND / "dist"
    if not (static_root / "index.html").is_file():
        raise SystemExit("frontend/dist 不存在，无法打包。")
    output_dir = output_dir.expanduser().resolve(strict=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    icon_path = PACKAGING / "wmm.ico"
    if not icon_path.is_file():
        run([sys.executable, str(ROOT / "scripts" / "generate_icon.py")])
    version_file = PACKAGING / "version_info.txt"
    build_root = ROOT / "build"
    build_root.mkdir(parents=True, exist_ok=True)
    separator = ";" if os.name == "nt" else ":"
    node_executable = find_node_for_packaging()
    if node_executable is None:
        raise SystemExit("找不到 Node.js，无法把 Steamworks 工坊查询运行时加入发布版。")
    bridge_script = STEAM_RUNTIME / "workshop_bridge.js"
    native_binding = (
        STEAM_RUNTIME
        / "steamworks"
        / "dist"
        / "win64"
        / "steamworksjs.win32-x64-msvc.node"
    )
    if not bridge_script.is_file() or not native_binding.is_file():
        raise SystemExit("Steamworks 工坊查询运行时不完整，无法打包。")
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--noconsole",
            "--noupx",
            "--name",
            EXECUTABLE_NAME,
            "--icon",
            str(icon_path),
            "--version-file",
            str(version_file),
            "--collect-all",
            "webview",
            "--add-data",
            f"{static_root}{separator}frontend/dist",
            "--add-data",
            f"{STEAM_RUNTIME}{separator}steam_runtime",
            "--add-binary",
            f"{node_executable}{separator}steam_runtime",
            "--distpath",
            str(output_dir),
            "--workpath",
            str(build_root / "pyinstaller"),
            "--specpath",
            str(build_root),
            str(ROOT / "main.py"),
        ]
    )
    executable = output_dir / f"{EXECUTABLE_NAME}.exe"
    if not executable.is_file():
        raise SystemExit(f"打包结束但未找到可执行文件：{executable}")
    return executable


def main() -> int:
    parser = argparse.ArgumentParser(description="验证、构建并可选打包桌面应用")
    parser.add_argument("--package", action="store_true", help="使用 PyInstaller 生成单文件程序")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_RELEASE_DIR),
        help="发布目录；仅在 --package 时使用",
    )
    parser.add_argument("--skip-install", action="store_true", help="不执行 pnpm install")
    parser.add_argument("--skip-tests", action="store_true", help="跳过前后端测试")
    args = parser.parse_args()

    if not args.skip_tests:
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    build_frontend(install=not args.skip_install, tests=not args.skip_tests)
    if args.package:
        executable = package_desktop(Path(args.output_dir))
        print(f"可执行文件：{executable}")
    print("构建完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
