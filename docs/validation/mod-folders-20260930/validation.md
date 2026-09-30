# MOD 文件夹与按钮栏验证

文件夹按游戏、播放集保存，包含成员与两个列表各自的折叠状态。文件夹仅收纳列表项目，不改变启用状态或实际加载顺序。右键菜单支持创建、加入已有文件夹和移出；文件夹行支持折叠、重命名和删除。搜索会展开包含结果的文件夹，清除搜索后恢复保存的折叠状态。

左下按钮栏从同步到 DATA 开始，以 MOD 启动排障结束。同步按钮为红字，排障按钮为绿字，游戏数据修改、单位数据修改为蓝字。所有新增界面文本覆盖六种内置语言。

验证结果：

- 前端全量：`node node_modules/vitest/vitest.mjs run --maxWorkers=2`，36 个文件、284 项测试通过。
- 后端全量：`python -m unittest discover -s tests -q`，403 项通过，其中 1 项按环境条件跳过。
- 前端构建：`node node_modules/vite/bin/vite.js build` 通过。
- `git diff --check` 通过。
- 浏览器使用验证数据检查了创建、加入、移出、重命名、折叠、搜索和按钮颜色；截图为 [preview.png](preview.png)。持久化、来源别名、跨游戏和跨播放集隔离由后端测试验证。

1.1.7 正式包通过既有 `scripts/package_release.ps1 -SkipInstall -SkipTests` 流程构建，测试由上述全量检查提前完成。文件版本和产品版本均为 1.1.7，产品名称为 Wyccc's Mod Manager。

- 文件大小：63,052,948 字节。
- SHA-256：`ae2d80c99fbbdf46e19c6855994686bf79ee9f2261c186705250dc74edd7e419`。

发布提交保留 1.1.6 更新清单；待两个平台的公开 EXE 下载均完成大小及 SHA-256 校验后，才单独推进更新清单。
