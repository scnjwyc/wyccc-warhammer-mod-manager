# WHMM 对 Variant Selector 的兼容：来源核验

研究日期：2026-09-08。本文只记录 WHMM 参考实现及其可确认边界，供兼容补丁功能研究使用；没有修改程序、MOD、游戏数据或更新日志。

## 结论与证据范围

WHMM 已有可参考的自动适配路线：作者 prop joe 发布的 [Automated Variant Selector Compatibility](https://steamcommunity.com/sharedfiles/filedetails/?id=3629192206) 要求 WH3 Mod Manager 2.16.4 及以上，通过扫描启用 MOD，生成包含变体注册脚本的新 Pack。这个条目的存在及作者说明能证明自动生成注册数据的路线可行，不能单独证明它覆盖所有原版角色、所有 MOD 特例或多个互相覆盖的重皮肤。

本地 `G:\git\WH3-Mod-Manager` 为提交 `0011d479735a947eecedb0093e1e7570103e428d`，提交日期 2026-03-11，版本 2.19.1（[package.json](G:/git/WH3-Mod-Manager/package.json:4)）。以下 WHMM 源码结论仅针对这个快照，不声称它是上游最新版。已先使用 CodeGraph，再补充定向源码搜索与截断区间读取。

该源码没有 `Variant Selector`、`variant_selector`、`variantSelector` 或 `marthvs` 专用实现。它提供通用 `whmmflows` 工作流执行器。配套工坊条目 `3629192206` 没有在已安装工坊及本地 MOD 源目录中找到；桌面 `whmmflows` 仅有单位倍率工作流 `pj_unitmultiplier`。因此，**尚未读取这个适配器的具体 flow，不能把通用节点的能力当作它实际使用的 DB 表、过滤条件、输出路径或去重策略。**

## WHMM 源码能够确认的处理链

| 环节 | 已确认行为 | 来源 |
| --- | --- | --- |
| 读取工作流 | 从输入 Pack 筛出 `whmmflows\` 文件，解析 JSON，结合用户选项执行节点图 | [packFileSerializer.ts:1355](G:/git/WH3-Mod-Manager/src/packFileSerializer.ts:1355) |
| 取得输入 | `AllEnabledMods` 按 `appData.enabledMods` 逐项加入输入；`includeBaseGame` 默认开启 | [nodeExecutor.ts:541](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:541) |
| 原版来源 | 上述节点加入当前游戏配置的一份基础 DB Pack；WH3 映射为 `db.pack` | [nodeExecutor.ts:567](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:567)、[supportedGames.ts:116](G:/git/WH3-Mod-Manager/src/supportedGames.ts:116) |
| 表选择 | 按节点给出的 DB 表名读取各输入 Pack，将匹配的 DB 文件加入 `TableSelection` | [nodeExecutor.ts:614](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:614) |
| 建立对应关系 | `GroupByColumns` 可按一列分组，收集另一列的值；`Lookup` 支持表关联 | [nodeExecutor.ts:817](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:817)、[nodeExecutor.ts:3391](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:3391) |
| 多变体过滤 | `GroupByColumns.onlyForMultiple` 开启时仅留下收集值数量大于 1 的组；默认关闭。它按原始数量判断，本节点不先对值去重 | [nodeExecutor.ts:838](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:838)、[nodeExecutor.ts:875](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:875) |
| 输出 Lua 文本 | `GroupedColumnsToText` 按 `{0}`／`{1}` 模板生成字符串；通用文本节点可包裹前后文本 | [nodeExecutor.ts:3221](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:3221)、[packFileSerializer.ts:1194](G:/git/WH3-Mod-Manager/src/packFileSerializer.ts:1194) |
| 生成结果 | `SaveChanges` 接收文本时交给 `SaveText`，以 UTF-8 写入节点指定的 Pack 内路径，输出到游戏目录下的 `whmm_flows` | [nodeExecutor.ts:2744](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:2744)、[nodeExecutor.ts:2642](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:2642) |
| 随本次配置加载 | 将生成 Pack 的目录和文件名加入启动 MOD 列表 | [ipcMainListeners.ts:7927](G:/git/WH3-Mod-Manager/src/ipcMainListeners.ts:7927) |

这些源码证明，兼容器无需在 WHMM TypeScript 中新增一个 Variant Selector 专用分支，就可以用 DB 查询、分组、文本模板生成注册脚本。**这是实现能力推断；具体适配器是否采用这组节点仍需其 flow 才能确定。** 特别是 `AllEnabledMods` 的通用默认值不等于工坊适配器已开启原版扫描。

WHMM 上述表选择和分组节点依次收集来源行，没有在这些节点内完成按游戏最终 DB 优先级裁决同键记录的处理。因此，不能直接拿其分组结果代替本项目已有的最终 DB 数据视图；是否先去重、按什么键去重，都由具体 flow 决定。来源同上，尤其是 [表选择循环](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:633) 与 [分组追加](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:875)。

## 去重与 Lua 注册需要区分

WHMM 的通用 `Deduplicate` 节点依据所选列值生成哈希，跨输入表保留首次出现的记录；可选 `dedupeAgainstVanilla` 将原版已有值也视为重复。这个节点面向 DB 行，没有识别 Variant Selector 已注册 subtype 的逻辑。不能据此声称工坊兼容器会跳过人工适配。来源：[nodeExecutor.ts:4490](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:4490)、[nodeExecutor.ts:4627](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:4627)。

为判断生成结果应如何接入，核对了本地 Variant Selector 框架本身的两个入口：

- `marthvs/mod/*.lua` 返回 `subtype -> art_set_id 数组`。框架先加载主表，再依次加载扩展表；同一 subtype 的新增值与已有值比较，排序后追加。这个合并函数不能保证清除一个新数组内部本来就重复的值，因此生成器仍应先去重。[marthvariantselector.lua:1](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:1>)、[加载入口:36](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:36>)。
- `marthvs:get_subtype_variants(key)` 返回当前注册列表或 `nil`；`marthvs:set_subtype_variants(key, art_set_ids)` **替换整份列表**，并非追加接口。[marthvariantselector.lua:79](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:79>)。

本地框架的存在证明这两条接入方式可供新功能使用，但**不能据此确定 WHMM 工坊兼容器选的是返回表还是运行时 API**。若本项目的目标严格是“仅给尚未适配的角色补上”，运行时查询当前注册状态后仅填补 `nil` 是可研究的方案；它属于本项目设计推断，不是已核验的 WHMM 行为。

## 对覆盖范围的判断

| 用户场景 | WHMM 参考证据能支持的结论 |
| --- | --- |
| 已存在多个独立外观的 MOD 角色 | 官方适配器说明支持自动收集变体；具体 DB 映射未核验 |
| 原版遗漏角色 | 通用工作流可读原版 DB，但没有配套 flow，无法证实实际扫描与过滤范围 |
| 只有一套外观的角色 | 作者评论称传奇领主拥有多于一套变体时应出现按钮；这只代表适配器作者的使用说明。框架本地源码显示按钮条件只是查询到注册表，未要求数组长度大于 1，所以不能把“两套以上”当作框架硬限制 |
| 同一传奇领主装多个重皮肤 MOD | 作者在回应此场景时表示通常无法直接作为独立变体；是否可行取决于 MOD 制作方式。需要另外设计资源隔离与 DB 重建，不能把自动写注册表等同于自动拆出多个重皮肤 |
| 坐骑、变身角色、任务战斗专用角色 | 没有读取具体 flow，无法证明它进行了相应过滤、坐骑映射或特殊状态处理；应由角色 DB 链及框架运行时机制另行论证 |
| 已经人工适配的角色 | 框架扩展表能合并，API 会替换；WHMM 适配器究竟如何避免改变人工列表与顺序，尚未核验 |

上述作者评论可见 [工坊适配器官方页面](https://steamcommunity.com/sharedfiles/filedetails/?id=3629192206)（2026-01-05 关于传奇领主，2026-02-01 回应多重皮肤）；框架按钮条件见 [marthvariantselector.lua:355](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:355>)。

## 给总研究的可用参考

值得复用的是“按当前启用 MOD 读取角色数据，生成一个小型注册脚本，交给原框架显示与切换”的路线。WHMM 通用工作流源码足以支撑这一点。本项目不必为了它移植 WHMM 的完整节点编辑器。

当前证据尚不足以复刻工坊适配器的具体算法，也不足以承诺“任意重皮肤、坐骑、变身、任务角色都能自动变成选择器选项”。正式方案应以本项目的最终 DB 视图、Variant Selector 真实注册入口，以及无双英灵录已完成适配的数据链为依据；对 WHMM 未核验的部分保持明确标注。

源码远程定位可使用固定提交，例如 [WHMM 节点执行器（固定提交）](https://github.com/Shazbot/WH3-Mod-Manager/blob/0011d479735a947eecedb0093e1e7570103e428d/src/nodeExecutor.ts#L541) 与 [工作流入口（固定提交）](https://github.com/Shazbot/WH3-Mod-Manager/blob/0011d479735a947eecedb0093e1e7570103e428d/src/packFileSerializer.ts#L1355)，避免未来上游行号变化造成误读。
