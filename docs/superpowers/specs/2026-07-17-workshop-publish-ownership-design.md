# 0.8.0 多游戏、Workshop 与启动可靠性设计

## 目标

将 WMM 从仅支持《全面战争：战锤 3》的固定配置调整为默认战锤 3、同时支持《全面战争：三国》的通用 MOD 管理器；完成 Workshop 发布和更新的 Steam 所有权校验；移除过时的软件更新通道；并在缺少 Microsoft Edge WebView2 Runtime 时给出可操作的启动提示，而不是显示空白窗口。

## 范围与边界

- 默认游戏为《全面战争：战锤 3》，并支持《全面战争：三国》（Steam App ID `779340`）。
- 三国保留扫描、启用/排序、Steam Workshop、启动游戏、发布和更新 MOD 等通用能力。
- 仅《全面战争：战锤 3》显示“游戏数据修改”和“导入官方启动器”入口；后端也拒绝非战锤 3 对这两项功能的 RPC 调用。
- 切换到三国时自动扫描 Steam 库；若找不到正确安装目录，保留该游戏选择并要求用户手动填写，不能回退或误用战锤 3 的目录。
- 删除设置中的“软件更新通道”卡片、其自定义清单字段和后端覆盖逻辑；继续使用内置 Gitee/GitHub 更新来源、自动检查、手动检查与更新日志。
- Workshop 发布和更新不显示封面路径、封面选择控件或“确认拥有项目”复选框。后端始终使用 Pack 同目录、同名 `.png`，并继续拒绝超过 `1 MiB` 的文件。
- 已订阅但不在 `data` 的 MOD，只要 Steam `creator_id` 与当前 Steam 用户 64 位 ID 一致，就可显示并执行更新；缺失任一 ID、作者不匹配或身份查询失败时不显示更新按钮。作者昵称和头像只用于展示，失败不影响已取得的 `creator_id` 判断。
- 源码版本、Python/前端包元数据、Windows 版本信息、README、版本一致性测试和六种内置语言更新日志同步为 `0.8.0`。不生成 EXE、不修改发布清单中的真实文件大小/哈希、不创建 Tag 或 Release。

## 多游戏架构

采用游戏注册表，而不是在界面层覆盖单一 `game_path`。覆盖单一路径会在切换后丢失战锤 3 目录，并可能把错误的 Steam App ID 用于三国 Workshop；为每个游戏保存独立路径可避免这两类问题。

新增不可变 `GameDefinition` 注册表，至少定义：内部 ID、显示名、Steam App ID、默认 Steam 安装目录、可执行文件名、进程名，以及 `supports_game_data_modification` 和 `supports_official_profile_import` 能力标志。战锤 3 定义为 `warhammer3` / `1142710` / `Warhammer3.exe`；三国定义为 `three_kingdoms` / `779340` / `Three_Kingdoms.exe`。`GamePaths` 携带当前游戏定义，使可执行文件、Steam manifest、Workshop 目录和进程检测不再硬编码战锤 3。

设置迁移到 schema `12`：

```json
{
  "selected_game": "warhammer3",
  "game_installations": {
    "warhammer3": {"game_path": "", "workshop_path": ""},
    "three_kingdoms": {"game_path": "", "workshop_path": ""}
  }
}
```

旧版 `game_path` 和 `workshop_path` 仅迁移到 `warhammer3`，再从持久化设置中移除。切换游戏时前端切换到该游戏自己的路径草稿；后端根据选中的游戏发现 Steam manifest、安装目录、`data` 与 `workshop/content/<app-id>`。三国未检测到时，`detect_paths` 返回 `found: false` 和空的三国路径，而不是抛出“未能定位战锤 3”错误或覆盖另一游戏的路径。目录健康检查使用所选游戏的可执行文件，扫描与启动在目录不完整时保持不可用。

所有依赖 Steam App ID 的通用操作——元数据刷新、订阅、强制更新、分享码订阅、发布/更新——从当前 `GameDefinition` 读取 App ID。官方 `.twmods` 解析和游戏数据运行时 Pack 是战锤 3 专用：前端仅在能力标志为真时挂载入口，API 在其他游戏上返回清晰错误，启动三国时跳过战锤 3 的游戏数据/运行时 Pack 生成。

## Workshop 所有权与发布

`steam_runtime/workshop_bridge.js` 增加只读 `get_current_user` 操作，从现有 `client.localplayer` 返回当前 Steam 64 位 ID 与显示名。`backend/steamworks_bridge.py` 提供受控包装函数；`API.get_workshop_update_eligibility(mod_ids)` 一次查询当前用户，并仅返回具有有效 Workshop ID、非空 `creator_id` 且两者完全匹配的已扫描 MOD ID。

前端在右键菜单打开时请求所选 MOD 的资格。请求返回前资格集合为空；使用递增请求序号忽略过期结果。多选遵循全有或全无：只要所选项中有一个不符合资格，就不显示“更新 MOD”。上传仍要求 Data 来源且未关联 Workshop；更新接受 Data 或仅 Workshop 来源的 Pack，但最终上传前仍由 Steamworks bridge 查询真实项目所有者，防止陈旧前端资格或直接 RPC 绕过。

发布窗口移除封面行、封面提示、`confirmed` 状态和复选框。提交按钮只受忙碌状态、语言加载和非空标题限制，提交负载不再包含 `preview_path`。`_require_workshop_cover` 在临时上传目录创建前固定解析同名 PNG、检查可读性和 `1_024 * 1_024` 字节上限，再将 Pack 与 PNG 一起暂存，并将该 PNG 传给 Steam。

## 软件更新通道

自定义 `update_manifest_url` 不是隐藏字段：从默认设置、迁移/标准化、公开设置、`UpdateService.check` 参数、前端 Store 和 SettingsModal 中一起删除。已保存的旧字段会在 schema 12 规范化时丢弃。更新检查始终以现有内置清单源为准，保留自动检查、手动检查、忽略版本和更新日志。

## 启动可靠性与 WebView2

截图中的纯白内容区说明 Vue 根节点没有完成挂载，但目前没有受影响用户的 `app.log`，不能把它确定为单一原因。已知边界是：`index.html` 本身只有空的 `#app`，且 Vite 产物目标为 `chrome120`；缺失/损坏/过旧的 WebView2、前端资源缺失或渲染期异常都可能产生相同表象。

启动前新增独立的 WebView2 检测模块，遵循 Microsoft Edge WebView2 Runtime 的注册表 `pv` 版本约定。在 Windows 上检测不到有效 Runtime 时：记录明确日志、显示原生“下载 / 退出”对话框，用户选择下载则打开微软官方 WebView2 下载页，随后安全退出，绝不创建主窗口。`run_desktop` 也会记录和捕获 WebView 启动失败。

前端入口提供默认可见的深色启动占位页；`window.onerror` 和未处理 Promise 拒绝会把占位页替换为可读的故障说明和诊断标识，避免纯白。构建脚本在打包前验证 `frontend/dist/index.html` 引用的本地 JS/CSS 资源均存在。上述措施能覆盖 Runtime 缺失和资源/渲染失败的可诊断性，但仍保留日志收集以确认具体事故原因。

## 用户体验与本地化

设置窗口增加游戏选择器和按游戏变化的目录占位符、检测提示、手动填写说明。非战锤 3 时：主界面不渲染游戏数据修改按钮，分享窗口不渲染“导入官方启动器”按钮，已打开的相关对话框在切换后关闭。所有新增、删除或改名的可见文案同步中文、英文、韩文、俄文、日文和西班牙文。

## 验证

- 后端测试覆盖 schema 11 到 12 的迁移、两游戏 Steam 路径发现、手动目录/可执行文件健康检查、当前游戏 App ID 透传、非战锤 3 专用 RPC 拒绝、三国启动不生成战锤 3 运行时 Pack，以及 WebView2 注册表检测和缺失 Runtime 的原生提示路径。
- Steamworks/API 测试覆盖 `get_current_user`、资格查询失败收敛为空、作者 ID 匹配/不匹配、仅 Workshop 来源可更新、最终 Steam 所有者校验和同名 PNG 继续校验。
- 前端测试覆盖游戏选择、未发现三国时的手动路径提示、非战锤 3 隐藏两项入口、删除更新通道/封面/确认复选框、资格异步竞态和多选全有或全无。
- 最终运行后端测试、前端测试、前端生产构建、Ruff、Python 编译检查与 `git diff --check`；不运行打包或发布流程。
