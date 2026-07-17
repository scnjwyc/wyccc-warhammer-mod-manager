# 0.7.5 Workshop 发布与更新权限设计

## 目标

将 MOD 发布和更新流程收紧为固定封面文件与 Steam 所有权校验，同时让已订阅、但不在 `data` 目录中的自有 Workshop MOD 可以更新。

## 范围

- 发布和更新弹窗不显示封面路径或封面选择控件。
- 后端始终使用待上传 Pack 同目录、同名的 `.png` 文件作为 Workshop 预览图，并继续拒绝超过 `1 MiB` 的文件。
- 发布和更新弹窗移除“确认拥有项目”的复选框；填写有效标题后即可提交。
- 更新按钮只在当前 Steam 账号与该 Workshop 项目的 `creator_id` 相等时显示，不再以 Pack 是否位于 `data` 为前提。
- `creator_id` 缺失、当前 Steam 账号无法读取或二者不匹配时，不显示更新按钮。
- 作者昵称或头像获取失败不影响更新按钮；它们不是授权依据。
- 源码版本、版本信息、README 和六种内置语言的更新日志同步为 `0.7.5`。

不在范围内：生成 EXE、修改带真实文件大小和 SHA-256 的更新清单、创建 Git tag 或发布 Release。

## 授权规则

一个 MOD 可在界面中显示“更新 MOD”按钮，当且仅当以下条件同时成立：

1. MOD 有有效的 Workshop ID。
2. 当前扫描结果中有非空的 `creator_id`。
3. Steamworks 桥能读取当前 Steam 账号的 64 位 ID。
4. `creator_id` 与当前 Steam ID 完全相等。

MOD 的来源（`data`、`workshop` 或两者同时存在）不参与上述判断。作者显示名 `author`、头像和个人资料请求仅用于展示，失败不会改变第 2 条已取得的 `creator_id`。

右键多选采用全有或全无的规则：只要当前选择中有一个 MOD 不满足授权规则，就不显示批量更新按钮。这样不会出现按钮写着多个项目、实际却跳过无权项目的情况。

## 组件与数据流

### Steamworks 身份查询

`steam_runtime/workshop_bridge.js` 增加只读的 `get_current_user` 操作，使用现有 `client.localplayer` API 返回当前 Steam 账号的 64 位 ID 和昵称。`backend/steamworks_bridge.py` 为它提供受控包装函数。

`backend/api.py` 增加 `get_workshop_update_eligibility(mod_ids)` RPC：

- 一次读取当前 Steam ID；
- 仅将有 Workshop ID、`creator_id` 非空且匹配的已扫描 MOD ID 放入 `eligible_mod_ids`；
- Steam 身份查询失败时返回空的 `eligible_mod_ids`，而不是把失败当成授权；
- 不把作者昵称或头像请求结果作为输入。

前端在打开某个 MOD 的右键菜单时请求当前选择的资格。请求返回之前资格集合为空，因此按钮不会短暂显示给无权项目。使用请求序号忽略已经过时的异步结果，避免用户快速切换右键目标时旧结果改变新菜单。

### 右键菜单与提交

`ModContextMenu.vue` 将“上传 MOD”和“更新 MOD”拆开判断：

- 上传仍要求 Pack 位于 `data` 且尚未关联 Workshop 项目。
- 更新由 `canUpdateWorkshop` 属性控制，完全以资格 RPC 的结果为准。

`App.vue` 将资格集合传给右键菜单，并在处理 `publish-update` 操作时再次仅接受当前已获资格的选中项。已订阅的自有 MOD 即使只有 Workshop 来源，也可进入更新弹窗。

`WorkshopPublishModal.vue` 删除只读封面路径、封面帮助文字、`confirmed` 状态和确认复选框。提交按钮只受忙碌状态、语言加载状态和标题是否为空限制；提交负载继续不包含可由用户指定的 `preview_path`。

### 后端发布路径

发布模式继续要求 `data` 来源，因为创建新 Workshop 项目只能从本地自有 MOD 发起。更新模式改为允许任何已扫描的关联 Workshop Pack 作为上传源，包括仅在 Workshop 目录中的 Pack。

无论发布还是更新，`_require_workshop_cover(source_pack)` 都在临时上传目录创建前运行，固定寻找同目录同名 PNG 并校验不超过 `1 MiB`。实际调用 Steam 时仍使用该文件作为预览图。

Steamworks 的现有更新路径继续在 `updateItem` 前查询 Workshop 项目所有者，并将项目所有者与当前 Steam ID 比较。这是最终授权边界：即使前端资格结果陈旧或 RPC 被绕过，Steam 仍拒绝无权更新。

## 错误处理

- 缺少同名 PNG、PNG 不可读取或大于 `1 MiB`：阻止上传并显示现有后端错误。
- 无法读取当前 Steam ID、缺少 `creator_id` 或 ID 不匹配：静默视为无更新资格，不显示按钮。
- 用户在资格查询完成后切换 Steam 账号，或远端项目所有者变化：提交时的 Steamworks 所有者校验拒绝更新并通过现有 toast 显示原因。
- 新建 Workshop 项目后仍沿用 Steam 返回的协议接受提示，不引入新的人工所有权确认步骤。

## 版本与文案

将 `0.7.5` 同步到应用常量、Python/前端包元数据、Windows 版本信息、前端备用版本、README 和版本一致性测试。更新日志在中文、英文、韩文、俄文、日文和西班牙文中简洁说明：固定同名 PNG 封面校验、取消人工所有权勾选、以及自有已订阅 MOD 可更新。

没有真实 0.7.5 EXE 时，`packaging/update-manifest.json` 保持已发布版本，避免写入虚假的下载链接、大小或哈希。

## 验证

- 前端组件测试确认封面行和确认复选框均不存在，标题有效时可提交，且提交负载没有 `preview_path`。
- 前端菜单和应用测试确认：仅 Workshop 来源但 ID 匹配时可更新；有 `data` 来源但 ID 不匹配时不可更新；缺少 `creator_id` 时不可更新；昵称或头像失败不改变有 `creator_id` 的授权结果；混合多选不显示批量更新。
- 后端和桥接测试确认当前 Steam ID 查询、资格 RPC 的失败收敛、仅 Workshop Pack 的更新路径，以及提交时的最终所有者校验。
- 保留并运行同名 PNG 缺失和超大 PNG 拒绝测试。
- 完成后运行后端测试、前端测试、前端生产构建、Ruff 和 `git diff --check`。
