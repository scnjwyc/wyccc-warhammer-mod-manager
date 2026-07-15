# Wyccc's Mod Manager

**简体中文** | [English](README.en.md)

一个面向《全面战争：战锤 3》（Total War: WARHAMMER III）的轻量 MOD 管理器。

当前版本为 `0.5.0`。它把 MOD、播放集、Steam 创意工坊与游戏启动集中在一个界面中，无需复杂配置即可开始使用。

## 当前功能

- 无需复杂配置，轻松上手。
- 一目了然地管理已启用与未启用 MOD；支持 Ctrl 多选、Shift 连选、批量拖拽排序，以及在两个列表之间直接拖放。
- 自动排序，新手无需刻意关心MOD排序。
- MOD列表基于播放集（类似Paradox游戏），使用播放集保存不同搭配。任何启用、停用或排序操作都会立即更新当前播放集。
- 快速搜索、筛选和整理 MOD，并可保存别名、备注与自定义类型。也支持AI自动生成MOD别名与简介。
- 强大的MOD发布工具，便于MODDER发布与更新自己的MOD，对于同时维护了多种语言的MOD，不用再担心发布后语言被覆盖。
- 分享或导入播放集；你可以分享你当前的MOD列表给联机的朋友，他可以导入你的分享并自动订阅缺失的MOD。
- 自动检查缺失依赖与 MOD 版本问题，可按 MOD 忽略不需要的警告（例如语言MOD的依赖缺失通常是误报）。
- 直接启动游戏、继续最近的战役，或从存档列表选择指定存档载入。
- 自动检查新版本，并在应用内查看更新日志、下载和安装更新。
- 内置简体中文、English、한국어、Русский和日本語五种语言支持。

## 界面与架构

主界面保持三栏：左侧是选中 MOD 的基本信息，中间是未启用列表，右侧是有顺序的已启用列表。详情展示名称、来源、作者、创建/更新时间、路径、Workshop 基本信息、简介、别名和备注。

| 层级 | 技术与职责 |
| --- | --- |
| 前端 | Vue 3、Pinia、Vite；负责三栏界面、列表交互、播放集和设置窗口 |
| 桌面容器 | pywebview；加载构建后的前端并向页面暴露单一 RPC 入口 |
| 后端 | Python 标准库为主；负责 Steam 路径发现、Pack 扫描、加载清单、启动和本地持久化 |
| Workshop 多语言桥接 | Node.js + steamworks.js；与 WH3-Mod-Manager 相同，直接调用本机 Steamworks UGC 查询指定语言 |
| 设置与缓存 | 原子写入的 JSON：`settings.json`、`workshop_cache.json` |
| 用户状态 | SQLite：播放集及其启用顺序、别名、备注、多选类型、隐藏状态、本地 MOD 关联的 Workshop ID 和清单备份索引 |

主要目录：

```text
backend/          Python 后端与显式 RPC 接口
frontend/         Vue 前端
frontend/dist/    前端生产构建产物（构建后生成）
tests/            Python 测试
licenses/         参考项目许可证原文
main.py           桌面程序入口
```

## 开发运行

环境要求：

- Windows 10/11（当前主要目标平台）
- Python 3.11 或更高版本
- Node.js 22 或更高版本
- pnpm 11
- 已安装的 Steam 版《全面战争：战锤 3》用于实际扫描和启动

### Windows 一键入口

在项目根目录直接双击以下文件：

- `一键启动管理器.cmd`：自动准备 Python 与前端依赖、构建最新前端，然后启动 pywebview 桌面窗口；程序不提供浏览器模式。
- `一键打包发布版.cmd`：运行后端及前端测试、构建前端并生成唯一发布文件 `Wyccc's Mod Manager.exe`，默认输出到 `G:\Wyccc's Mod Manager`。

两个入口共用项目内的 `.venv-build` 环境。首次运行可能需要下载依赖，因此仍需预先安装 Python 3.11+、Node.js 22+ 与 pnpm 11+。打包成功后，窗口会保留并显示结果；全新的发布目录中只生成 `Wyccc's Mod Manager.exe`。

需要改变打包目录时，可以先设置 `WMM_OUTPUT_DIR`，再运行打包入口：

```powershell
$env:WMM_OUTPUT_DIR = "D:\WMM-Release"
.\一键打包发布版.cmd
```

安装 Python 开发依赖：

```powershell
cd G:\git\wyccc-warhammer-mod-manager
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

安装前端依赖：

```powershell
cd G:\git\wyccc-warhammer-mod-manager\frontend
pnpm install
```

开发时使用两个终端。先启动 Vite：

```powershell
cd G:\git\wyccc-warhammer-mod-manager\frontend
pnpm dev
```

再启动 pywebview，并指向 Vite 地址：

```powershell
cd G:\git\wyccc-warhammer-mod-manager
.\.venv\Scripts\Activate.ps1
python main.py --dev-url http://127.0.0.1:5173
```

可用 `--data-dir <目录>` 临时覆盖应用数据目录，便于开发和隔离测试。

## 测试与构建

分别运行后端与前端测试：

```powershell
cd G:\git\wyccc-warhammer-mod-manager
python -m pytest

cd frontend
pnpm test
```

项目构建入口会执行检查并生成前端生产资源：

```powershell
cd G:\git\wyccc-warhammer-mod-manager
python scripts/build.py
```

构建完成后，可从项目根目录启动：

```powershell
python main.py
```

如需生成可分发包，先安装构建依赖，再使用可选打包入口：

```powershell
python -m pip install -e ".[build]"
python scripts/build.py --package
```

可用 `--output-dir <目录>` 指定发布位置，例如：

```powershell
python scripts/build.py --package --output-dir "G:\Wyccc's Mod Manager"
```

打包产物仍应在真实的战锤 3 安装环境中进行人工验证。本项目当前不提供安装器。

## 本地数据、隐私与联网

程序不需要单独的管理器账户，也不包含遥测。除用户在发布窗口确认“上传到工坊/更新到工坊”外，程序不会上传本地 Pack；加载顺序、别名、备注和类型始终保存在本机。从源码运行时，Windows 默认应用数据目录为：

```text
%APPDATA%\WycccModManager\
```

PyInstaller 发布结果只包含 EXE；程序首次运行后会在 EXE 同目录创建 `data/` 保存便携数据，如果发布目录不可写则回退到上述用户目录。命令行 `--data-dir` 和环境变量 `WYCCC_MM_DATA_DIR` 可显式覆盖。升级安装会在新目录尚不存在时依次读取旧版 `%APPDATA%\WycccWarhammerManager\`、`%APPDATA%\WycccWarhammerModManager\`，避免丢失现有设置与播放集。

其中可能包含：

- `settings.json`：路径和扫描选项。
- `state.db`：播放集及其启用顺序、个人标记、MOD 类型和本地 Workshop 关联。
- `workshop_cache.json`：已获取的公开 Workshop 元数据。
- `backups/`：保存前的加载清单备份。
- `updates/`：已校验的待安装 EXE、替换脚本及失败回滚日志。
- `logs/app.log`：管理器自身运行日志。

启用启动后台刷新或点击“刷新工坊信息”时，程序会向 Steam 的公开 `GetPublishedFileDetails` 接口批量获取英文默认信息，并通过本机 Steamworks UGC 接口补充当前语言的标题和长描述；结果按语言缓存在 `workshop_cache.json`。旧版网页抓取缓存会在首次刷新时自动改用 Steamworks 重建，以避免 Steam Community 的请求限流。打开创意工坊页面时会交给系统浏览器处理。发布自有 MOD 时，只有所选 Pack、预览图、标题、描述、标签、可见性和更新说明会提交给 Steam Workshop；预览图必须为 PNG/JPEG 且不超过 1 MB。

## 许可证与致谢

本项目使用 [MIT License](LICENSE)。本项目许多交互与实现受到了以下工具的启发：

- [Warhammer Mod Manager](https://github.com/Shazbot/WH3-Mod-Manager)
- [RimCrow](https://github.com/Inky-Feather/RimCrow)

感谢上述项目的作者与贡献者。相关许可证说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [licenses](licenses/) 目录。

《全面战争：战锤 3》及相关商标属于其各自权利人。本项目是独立的社区工具，与 Creative Assembly、SEGA、Valve 或 Steam 无隶属关系。
