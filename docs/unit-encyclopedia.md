# 单位图鉴

启动器选择 Warhammer III 后，底部「单位图鉴」打开铺满启动器内部的派系页。选择派系后，单位固定分为「领主与英雄」「普通单位」两页，各页展示按类别排列的全部兵牌，通过滚动条浏览，不再每 72 个单位分页。点击兵牌，左侧显示单位名称、类别、描述、费用、生命、属性与能力。支持名称和 Key 搜索；当前页没有搜索结果时切换至有匹配单位的另一页。支持返回、Esc 和键盘焦点循环。更改加载列表后重新打开或点击「重新读取」，读取新的快照。

单位名称右侧的「修改」按钮打开现有单位数据修改界面，并按单位 Key 精确筛选，避免同时显示同名或前缀相同的变体。清空搜索可继续浏览所有单位。关闭编辑器返回当前图鉴单位；保存成功后重新读取属性，保留派系、选中单位和搜索条件。

图鉴保留已经构建的单位编辑数据，打开修改界面时只传输所选单位，避免再次扫描和合并全部 Pack。搜索其他单位时按需读取完整列表，并保留当前草稿。单个单位响应同时保留其他单位的已保存修改，防止保存时覆盖丢失；原有整表修改入口继续可用。复用前检查游戏上下文、MOD 顺序、自动加载 Movie Pack、文件大小和修改时间、语言及保存的单位修改；变化时重新读取数据。后台最多保留两个图鉴快照。

第一层按游戏文化（例如帝国、震旦）归组，与原版种族选择页一致。序章基斯里夫单独标注；找不到文化关联的单位进入「其他单位」。浏览图鉴不需要订阅单位修改功能，也不写入游戏 Pack；修改入口沿用原编辑器的订阅要求和保存补丁流程，游戏运行中不能进入修改。

## 数据和素材

- `backend/unit_encyclopedia.py` 复用单位修改功能的 `collect_game_data_source_snapshot`、`build_unit_table_snapshot`、权限合并与 DB 行优先级。原版作为底层，启用 MOD 与自动加载的 Movie Pack 参与覆盖；同内部文件名的冲突按现有加载顺序解决，内部 DB 文件名优先级保持一致。
- 保存的单位编辑会反映到图鉴；被禁用单位、海军占位和没有招募权限的隐藏辅助记录不进入列表。显示数据库基础规模，不应用启动时生成的全局兵力倍率、游戏内兵力规模、战役加成或战斗临时效果。
- 兵牌首先沿 `main_units.land_unit → unit_variants.unit_card` 查找。领主和英雄同时读取 `units_custom_battle_permissions.general_portrait` 的兵牌与头像；坐骑变体可复用相同 `unit_card` 对应的角色图片。忽略原版 `placeholder` 兵牌，找不到有效图片时保留可操作的文字占位。
- 原版种族画、兵牌、详情图、属性图标、类别图标、能力图标和羊皮纸来自本机 `ui.pack` / `ui2.pack` / `ui3.pack`，启用 MOD 的同路径素材优先。序章的原版占位横幅和徽记复用正式基斯里夫素材。程序不内置整包游戏图片，也不读取其他开发目录的解包素材。
- 派系徽记沿 `factions.subculture → cultures_subcultures.culture` 关联，读取最终生效的 `factions.flags_path`，优先采用文化同名或多人对战代表派系。路径及图片均支持 MOD 覆盖，并按可用尺寸回退；混沌矮人读取声明的正式旗帜目录，避免误用带 PH 的文化占位图片。「流浪军团」和「其他单位」使用原版通用图标。
- `backend/encyclopedia_assets.py` 复用公共 Pack 索引读取器，只索引 UI 图片。图片按当前页分批读取，单批最多 96 个请求；缓存以 Pack 路径、大小和修改时间区分。游戏更新后旧快照停止返回过期图片。
- 本地化遵循启动器语言、英文回退及 MOD 的 LOC 覆盖顺序；原版富文本转换为普通文本。所有界面文案包含六种内置语言。
- 原版部分属性的常规名称和描述为空时，读取对应的 UI 词条。例如 `guerrilla_deploy` 使用 `ui_text_replacements_localised_text_guerrilla_deployment`，中文显示「先锋部署」。优先保留 MOD 提供的属性名称和描述。
- 图鉴表已登记无版本头时使用的读取结构；旧 MOD 的 `land_units_to_unit_abilites_junctions_tables` 按 v0（没有 `culture` 字段）读取，带版本头的 v1 仍按其声明读取。支持仅 GUID 头和空表。
- 面板生命包含实体基础生命与单位额外生命；速度从实体、坐骑或引擎记录读取。远程伤害明确显示「单发远程伤害」，与游戏按射击周期计算的远程威力不同。
- 远程详情显示「射击间隔（基础）」与「弹丸数」，分别读取最终生效投射物的 `base_reload_time`（秒）和 `projectile_number`。步兵与炮兵均沿现有编辑器的武器关联读取。基础间隔不包含装填技能、射击动画或战斗临时效果；弹丸数为每次发射数量，不是全单位齐射总数。

## 验证（2026-09-27）

本机当前启用的 15 个 MOD 加原版共 16 个来源，读取到 28 个派系分组、2,774 个单位；2,719 个单位解析到图片，55 个使用文字占位。原版剑士为 120 人、护甲 30、近战攻击 32、武器威力 28、总生命 8,280。真实数据通过 RPC 在浏览器中展示，完成派系进入、切换单位、搜索、返回及连续 Esc 关闭；没有页面脚本错误。

1540×960 与 1024×768 两种窗口尺寸完成检查，图鉴未出现横向溢出。启动器入口另用真实 App 组件与隔离的界面状态验证；该入口截图的 MOD 列表为空，不代表实际扫描列表。

- 后端定向回归：148 tests、20 subtests 通过，涵盖数据覆盖顺序、Movie Pack、修改值、角色和坐骑图片、占位图排除、LOC 覆盖、缺失引用、图片失效、快照隔离和原有编辑功能。
- 前端：33 个测试文件、263 项测试通过。首次全量并行运行时旧单位编辑器的 2,050 行分页测试超过 5 秒；单文件复跑与限制为 2 个 worker 的全量运行均通过。
- Vite 生产构建通过。保留已有的 bundle 大小提示；未运行 EXE 打包和发布流程。

无版本头兼容修复另用当前源码启动器的配置验证：11 个启用 MOD、12 个来源、28 个派系、3,077 个单位，图鉴及图片 RPC 成功。`!mystandalone.pack` 与 `longersfo639949.pack` 的旧版能力关联表在修复前触发同一个 `KeyError`，修复后按 v0 正常读取。新增真实 Pack 读取回归覆盖无版本头、仅 GUID 头、新旧表并存和空表；图鉴、通用数据读取、单位编辑和三国单位编辑共 80 项测试、19 个子用例通过。该验证使用当前配置的隔离副本，未更改原配置或游戏 Pack。详情见 [兼容修复运行记录](validation/unit-encyclopedia-20260927/versionless-fix.json)。

全屏与修改入口验证使用生产构建和配置副本：1920×1080、1024×768 下图鉴均从 `(0, 0)` 填满窗口，无横向溢出。真实 RPC 打开 `wh_main_emp_inf_swordsmen` 时编辑器仅显示该单位；在副本中将近战攻击从 30 保存为 31，返回图鉴后显示 31，选择和搜索条件保留，取消编辑也正常返回。图鉴、编辑器及多语言共 56 项前端测试通过，包含订阅提示和游戏运行限制；生产构建通过。测试修改仅写入临时配置及临时补丁，完成后清理。详见 [全屏与修改运行记录](validation/unit-encyclopedia-20260927/fullscreen-edit-check.json)。

派系徽记修复前，原版 28 个分组中有 18 个缺少图标。修复后原版 28 个分组的徽记均可读取；使用当前 13 个启用 MOD 的隔离配置副本、生产构建和真实 RPC，3,297 个单位对应的 28 张派系卡片全部加载徽记，没有页面、RPC 或图片加载错误。图鉴定向回归 21 项测试、5 个子用例通过，覆盖旗帜目录重定向、代表派系选择、尺寸回退、混沌矮人占位规避、MOD 覆盖和通用图标。详见 [徽记修复运行记录](validation/unit-encyclopedia-20260927/faction-crests-check.json)。

两页列表、远程详情和修改入口提速验证使用本次当前配置的隔离副本。3,145 个可见单位中，震旦的 109 个领主与英雄、41 个普通单位分别完整展示在两页，滚动高度大于可视高度；1920×1200 与 1024×768 下无横向溢出。原版白银之路贼寇显示「先锋部署」、基础射击间隔 11 秒、弹丸数 1。当前 MOD 中另有 `emp_huangdiweidui` 未提供可读取名称，仍保留原始 Key。

修改前连续两次打开单位编辑数据分别耗时 5.62 秒、5.62 秒；复用图鉴数据后为 0.124 秒、0.115 秒。生产界面点击修改至显示所选单位，实测 0.249 秒、0.237 秒，每次只传输一行，无需手动搜索；页面及 RPC 无错误。保存后图鉴仍会重新读取数据，这组耗时衡量打开编辑器，不包含保存补丁及图鉴刷新。详见 [修改前计时](validation/unit-encyclopedia-20260927/details-performance-baseline.json) 与 [功能和计时记录](validation/unit-encyclopedia-20260927/details-performance-check.json)。

本轮后端相关回归 69 项测试、22 个子用例通过；图鉴、修改界面和多语言前端 58 项测试通过，生产构建通过。覆盖单单位修改时保留其他编辑、扩展搜索时保留草稿、过期响应、MOD 顺序/文件/Movie Pack/语言/保存数据变化时缓存失效。扩展 API 检查中的 4 个工坊强制更新用例被环境的游戏运行检测提前拦截；隔离该检测后 4 项均通过，与本轮修改无关。

```powershell
python -m pytest tests/test_unit_encyclopedia.py tests/test_unit_data.py tests/test_game_data.py tests/test_three_kingdoms_unit_data.py tests/test_storage_and_api.py tests/test_unit_data_state.py -q
cd frontend
node node_modules/vitest/vitest.mjs run --maxWorkers=2
node node_modules/vite/bin/vite.js build
```

截图和运行记录位于 [validation/unit-encyclopedia-20260927](validation/unit-encyclopedia-20260927/)：

- [派系页](validation/unit-encyclopedia-20260927/factions.png)
- [帝国单位列表](validation/unit-encyclopedia-20260927/empire.png)
- [剑士数据面板](validation/unit-encyclopedia-20260927/swordsmen.png)
- [1024×768 震旦页面](validation/unit-encyclopedia-20260927/cathay-1024.png)
- [启动器入口布局](validation/unit-encyclopedia-20260927/launcher-entry.png)
- [运行记录](validation/unit-encyclopedia-20260927/runtime-check.json)
- [全屏派系页](validation/unit-encyclopedia-20260927/fullscreen-factions.png)
- [徽记修复后的派系页](validation/unit-encyclopedia-20260927/faction-crests-fixed.png)
- [全屏单位面板及修改按钮](validation/unit-encyclopedia-20260927/fullscreen-unit.png)
- [定位当前单位的编辑器](validation/unit-encyclopedia-20260927/unit-editor-selected.png)
- [1024×768 全屏单位面板](validation/unit-encyclopedia-20260927/fullscreen-unit-1024.png)
- [领主与英雄页](validation/unit-encyclopedia-20260927/two-pages-characters.png)
- [普通单位页与远程详情](validation/unit-encyclopedia-20260927/two-pages-ranged.png)
- [1024×768 两页布局](validation/unit-encyclopedia-20260927/two-pages-1024.png)
