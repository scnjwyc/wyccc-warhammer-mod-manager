# 游戏独立存档目录设计

## 目标

切换当前游戏后，所有存档操作读取该游戏自己的存档目录，不再始终读取《全面战争：战锤3》的存档。

## 默认目录

默认存档目录按当前游戏 ID 决定：

- `warhammer3`：`%APPDATA%\\The Creative Assembly\\Warhammer3\\save_games`
- `three_kingdoms`：`%APPDATA%\\The Creative Assembly\\ThreeKingdoms\\save_games`

现有 `WYCCC_MM_SAVE_DIR`、`WYCCC_WM_SAVE_DIR` 和 `WYCCC_WMM_SAVE_DIR` 环境变量继续优先于默认目录。它们是全局显式覆盖，适用于测试和用户手动指定的特殊存档位置。

## 服务与 API

`default_save_directory` 接受可选游戏 ID；未传入或无效时回退到战锤3，保持旧调用兼容。

`SaveGameService` 保存自身的游戏 ID，并在未显式传入目录时按该游戏确定目录。

API 在以下时机根据 `SettingsService.selected_game_definition()` 同步重建存档服务：

- API 初始化
- 保存设置后，包括切换 `selected_game`

因此下列操作始终共享同一个当前游戏存档服务：

- 存档列表
- 从存档读取 MOD 列表
- 按指定存档启动游戏
- 继续最新存档

不在设置界面增加自定义存档目录字段。

## 验证

测试覆盖：

- 三国和战锤3的默认目录解析。
- `SaveGameService(game_id="three_kingdoms")` 使用三国目录。
- 环境变量覆盖优先于游戏默认目录。
- API 保存 `selected_game="three_kingdoms"` 后，列表、读取存档 MOD、继续游戏都使用三国服务目录。
- 再切回战锤3后恢复战锤3服务目录。
