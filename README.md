# Wyccc's Mod Manager

一个面向《全面战争：战锤 3》（Total War: WARHAMMER III）的轻量 MOD 管理器。

当前版本为 `0.1.0`，定位是可运行的早期版本：专注于发现本机已经存在的 Pack、编排启用顺序、写入游戏启动清单并启动游戏。项目借鉴了 RimCrow 的桌面管理器交互思路，并参考 WH3-Mod-Manager 核对战锤 3 的目录、Pack 与启动行为，但代码按本项目的精简边界重新组织。

## 当前功能

- 自动检测 Steam 安装库，也可手动指定游戏目录和 Workshop 内容目录。
- 扫描以下位置中已经存在的 `.pack`：
  - `<游戏目录>/data`
  - `<Steam 库>/steamapps/workshop/content/1142710`
- 扫描范围固定为 Data 与 Steam Workshop，不提供 Modding、Merged 扫描开关。
- 读取 `data/manifest.txt` 排除原版 Pack；清单不可用时仍会排除少量核心原版 Pack。
- 读取 PFH5 文件头，区分 Mod Pack、Movie Pack 与无法识别的 Pack。这里不解析 Pack 内部文件。
- 在“未启用 / 已启用”列表之间移动 MOD；支持 Ctrl 切换多选、Shift 连续选择和批量启用/停用；新启用的 MOD 会按 Pack 文件名的默认规则插入，同时保留既有手动顺序；按优先级显示时，已启用列表支持拖放及上移、下移。
- 使用 RimCrow 风格的条件标签筛选列表：支持多个条件、`AND / OR`、前置 `-` 排除，以及 `name:`、`file:`、`author:`、`type:`、`source:`、`workshop:`、`creator:` 字段；类型和常用字段会给出候选项。
- 搜索框旁可按优先级、文件名、模组名、作者、更新时间或创建时间调整列表显示。该排序只作用于显示副本，不会修改实际加载顺序；非优先级排序时会禁用拖放与上下移动按钮。
- 启用、停用、导入、播放集切换和排序后会立即把顺序写入 `used_mods.txt`，必要时回退到 `my_mods.txt`；写入前备份既有清单，并检测外部修改。
- 首次扫描时可从已有 `used_mods.txt` 或 `my_mods.txt` 导入顺序。
- 保存个人别名、备注以及一个或多个 MOD 类型；内置类型不可删改，自定义类型可在类型管理窗口维护。
- AI 可把标题翻译为当前设置语言，并结合标题总结原始描述后生成同语言摘要备注；内置战锤翻译约束，优先复用本地共享术语库，未命中时直接翻译，不联网搜索或查询原版 LOC。
- 使用播放集管理启用项和完整加载顺序；始终提供“默认”播放集，启用、禁用、导入和排序会立即更新当前播放集，旧预设会自动迁移。
- 导出、导入本项目分享码；也可读取 WH3-Mod-Manager 的 `workshopId[;loadOrder]|...` 简单格式。旧格式只记录项目 ID，因此导入时会按 Pack 名稳定排序并启用该 Workshop 项目中的全部 Pack。
- 显示本地预览图；可选请求 Steam 补充 Workshop 标题、简介、创建者 ID、预览地址和更新时间。
- 右键菜单支持启用/停用、多选类型、调整实际加载顺序、隐藏、在 RPFM 打开、复制到 Data、访问/取消订阅/强制更新 Workshop 项目；RPFM 通过 Windows 的 `.pack` 文件关联启动，不需要单独配置路径。
- Data 目录中的自有 MOD 可创建 Workshop 项目；已关联 Workshop ID 的本地 MOD 可更新现有项目。更新提交前会由本机 Steamworks 校验当前 Steam 账号是否为项目所有者。
- “打开目录”会在资源管理器中定位并选中对应 Pack；也可打开游戏目录或 Workshop 页面。
- 可启动新游戏、继续最新战役存档，或从按更新时间排列的存档列表载入指定存档。
- 读取 PFH5 Pack 头依赖与 Steam Workshop Required Items；缺少本地 Pack 或必需工坊项目时显示红色警告。
- 启动时可按 24 小时间隔自动检查管理器新版本；用户确认后下载单 EXE、校验大小与 SHA-256，再安全替换并重启。设置页可忽略指定版本和查看完整更新日志。
- 界面语言可选择中文、English、한국어、Русский和日本語；当前阶段管理器自身的五种界面选择统一使用中文文本，待功能完成后再补充翻译词条。
- Workshop 标题和描述按当前界面语言分别获取并缓存；目标语言字段缺失或请求失败时逐字段回退到英文默认内容。

## 明确不包含的范围

本项目有意不实现下列模块；它们不是隐藏设置，也不会参与扫描或保存：

- MOD 分组。
- 依赖关系图、依赖自动订阅或自动补齐。基础缺失依赖检测已包含在扫描流程中。
- 贴图优化。
- Pack 文件内容搜索。主界面的文本框只筛选已经扫描到的 MOD 元数据。
- 模组设置文件编辑。
- 游戏日志分析。程序自身的 `app.log` 仅用于记录管理器运行情况，不是日志分析功能。
- 规则中心、规则检测、合规检查或智能排序。新启用 MOD 的固定 Pack 文件名插入规则不属于规则中心，也不会重排既有手动顺序。
- MOD 详情中的“支持语言”和“文件统计”。

当前版本不提供 Workshop 浏览器、批量订阅或 Workshop MOD 自动安装流程，也不提供 Pack 合并、Pack 内容编辑、冲突分析和智能排序。取消订阅、强制更新以及自有 MOD 的上传/更新只能由用户在选中 MOD 的右键菜单中明确触发。

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

### 发布自动更新

自动更新使用一个公开的 HTTPS JSON 清单。清单格式见 `packaging/update-manifest.example.json`；每次发布时需要填写新版本号、EXE 的公开 HTTPS 下载地址、文件字节数、SHA-256 和更新说明。发布前把长期稳定的清单地址写入 `backend/constants.py` 的 `DEFAULT_UPDATE_MANIFEST_URL`，普通用户即可直接自动检查；设置页也允许切换到私有更新通道。

可用 PowerShell 计算发布 EXE 的校验值与大小：

```powershell
$exe = "G:\Wyccc's Mod Manager\Wyccc's Mod Manager.exe"
(Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash.ToLowerInvariant()
(Get-Item -LiteralPath $exe).Length
```

清单应先上传并验证，再原子替换线上旧清单。管理器只接受 HTTPS（本机开发测试例外），不会静默下载或安装；下载完成后还会检查 Windows EXE 的 `MZ` 文件头。源码模式支持检查与下载，只有打包后的 Windows EXE 可以执行自替换。

## 战锤 3 路径约定

Steam App ID 为 `1142710`。自动检测会读取 Steam 注册表位置、`libraryfolders.vdf` 和 `appmanifest_1142710.acf`，并验证：

```text
<Steam 库>/steamapps/common/Total War WARHAMMER III/Warhammer3.exe
<Steam 库>/steamapps/common/Total War WARHAMMER III/data/
<Steam 库>/steamapps/workshop/content/1142710/
```

Workshop 扫描本身只读取本地内容目录：每个数字目录视为一个 Workshop 项目，并发现其中所有 `.pack`。扫描不会自动改变订阅或下载状态；只有用户明确执行右键菜单中的 Steam 操作时才会调用本机 Steamworks。

## `used_mods.txt` 行为

保存时，管理器按界面中的已启用顺序生成 UTF-8、CRLF 换行的启动清单。示例：

```text
add_working_directory "D:\SteamLibrary\steamapps\workshop\content\1142710\1234567890";
mod "example.pack";
```

- 位于游戏 `data` 根目录的 Pack 不需要 `add_working_directory`。
- 其他来源的目录只写入一次，即使同一目录包含多个启用 Pack。
- `mod` 行严格跟随界面中的启用顺序。
- 写入使用同目录临时文件和原子替换，并在写后校验字节内容。
- 已存在的当前生效清单会先备份到应用数据目录；若它在扫描后被其他程序修改，保存会中止并要求重新扫描。
- 如果写入 `used_mods.txt` 失败，程序会尝试写入 `my_mods.txt`，并记住实际成功的文件；后续校验、导入与启动不会误用旧的 `used_mods.txt`。
- 启动时以游戏目录为工作目录，执行 `Warhammer3.exe`，并传入实际清单文件名加分号，例如 `used_mods.txt;`。

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

启用启动后台刷新或点击“刷新工坊信息”时，程序会向 Steam 的公开 `GetPublishedFileDetails` 接口批量获取英文默认信息，并通过本机 Steamworks UGC 接口补充当前语言的标题和长描述；结果按语言缓存在 `workshop_cache.json`。旧版网页抓取缓存会在首次刷新时自动改用 Steamworks 重建，以避免 Steam Community 的请求限流。打开 Workshop 页面时会交给系统浏览器处理。发布自有 MOD 时，只有所选 Pack、预览图、标题、描述、标签、可见性和更新说明会提交给 Steam Workshop；预览图必须为 PNG/JPEG 且不超过 1 MB。

## 当前局限

- 这是早期版本，尚未提供正式安装器；自动更新依赖发布者维护 HTTPS 清单与可下载的单 EXE。
- 主要针对 Windows 与 Steam 版游戏；其他商店版本和兼容层尚未验证。
- Pack 检查仅限 PFH5 文件头和基础文件元数据，不验证 Pack 内部结构或游戏版本兼容性。
- Workshop 英文默认元数据来自公开接口，其他语言由本机 Steamworks 提供；Steam 客户端或网络不可用时仍可使用本地 Pack，但标题、简介或预览可能回退英文或来自缓存。
- 管理器只负责表达用户选择的顺序，不判断该顺序是否正确，也不会推断冲突或兼容关系。

## 许可证与致谢

本项目使用 [MIT License](LICENSE)。研究参考项目及许可证说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [licenses](licenses/) 目录。

《全面战争：战锤 3》及相关商标属于其各自权利人。本项目是独立的社区工具，与 Creative Assembly、SEGA、Valve 或 Steam 无隶属或背书关系。
