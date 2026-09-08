# Variant Selector 自动兼容可行性研究

研究日期：2026-09-08。目标项目：Wyccc's Mod Manager，研究时 HEAD 为 `7c716b7`。

## 结论

**可以接入现有「兼容补丁」功能，为原版及当前启用 MOD 中尚未注册的角色补上 Variant Selector。单套外观也应支持。** 扫描范围可以覆盖所有来源，但无法承诺任意角色的所有 art set 都适合开放：任务战形态、受剧情控制的变身、按派系区分的外观需要筛选或专项规则。

应复用 Variant Selector 的界面和公开 API，自动生成候选数据与注册/恢复脚本。已有人工适配的角色保持原有列表及顺序；自动补丁只接管尚未登记、且能确定有效外观链的角色。

本次完成源码研究、样本统计和 Lua 接口实验，尚未实现管理器功能，也未进行游戏内验证。

## 1. 三组参考各自说明什么

| 参考 | 已核实的做法 | 对管理器的意义 |
| --- | --- | --- |
| Variant Selector 作者的适配说明及本地框架源码 | `agent_subtype -> art_set_id[]`，加载 `marthvs/mod/*.lua`；提供读取/设置 subtype 列表的 API | 有明确扩展点，无需复制选择器 UI |
| 无双英灵录 | 单套也登记；多套按人工顺序登记，并有独立的读档/战前恢复脚本 | 满足「所有未适配角色」时应保留单套入口，并处理持久化 |
| WHMM / Automated Variant Selector Compatibility | 管理器扫描已启用 MOD，生成 Variant Selector 可读取的脚本 | 证明管理器自动生成适配的路线已有先例；不能把订阅辅助 MOD 等同于管理器已实现生成 |

作者说明要求填写 `campaign_character_art_sets_tables` 的 `art_set_id`、`agent_subtype`，也明确支持新角色。[Variant Selector 官方适配说明](https://steamcommunity.com/workshop/filedetails/discussion/2888171970/5440953210414305791/)

WHMM 配套 MOD 的作者明确要求 WHMM 2.16.4 或更新版本，由管理器扫描启用 MOD 并生成脚本。该配套 MOD 的具体流程文件本次未取得，因此不能宣称已经核实其所有过滤、去重和恢复细节。[Automated Variant Selector Compatibility 官方说明](https://steamcommunity.com/sharedfiles/filedetails/?id=3629192206)

WHMM 通用执行机制、可确认的边界及来源详见 [WHMM 参考研究](whmm-variant-selector-reference.md)。

## 2. 框架源码验证

本地源码根目录：`C:/Users/Administrator/Desktop/战锤MOD相关`。本节路径相对于该目录。

框架文件：`mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua`。

- 第 36–70 行：先读取 `marthvs/main/mvsmain.lua`，再执行并合并 `marthvs/mod` 的扩展表。
- 第 1–34 行：同 subtype 的新增值与已有列表按字符串比较，新增部分排序后追加；不会整体重排原列表，也不保证去掉输入数组内部重复值。生成器仍须自己去重，扩展文件先后也可能影响最终序号。
- 第 83–102 行：`marthvs:get_subtype_variants(key)` 获取现有列表，`set_subtype_variants(key, list)` 直接替换列表。
- 第 108–118 行：提供每个角色的选择序号读取/设置接口。
- 第 162–218、369–380、405–409 行：界面判断是否存在注册表，没有要求列表必须大于一项。**单套外观能显示入口和一个编号。**
- 第 307–343 行：点击经 `CampaignUI.TriggerCampaignScriptEvent` / `UITrigger` 同步，最终调用 `cm:add_unit_model_overrides("character_cqi:" .. cqi, art_set)`。
- 第 482–495 行：保存/读取 `marthvs_cvi`，内容是 CQI 对应的列表序号；该文件没有在新会话重新应用 override 的逻辑。

实际已安装的 Variant Selector 源代码也已只读核对：

`X:/SteamLibrary/steamapps/workshop/content/1142710/2888171970/!marthvariantselector.pack`

其中上述脚本及 `mvsmain.lua` 与本地参考文件字节一致。脚本 SHA-256 为 `c162e9b8aaf8366c71ad26d0b595e3306875acb5ba93f4eb3e87d18b35a88df0`；主表 SHA-256 为 `7da84bb195f197107204363f5646defbb6b5cd89c8f0025b4b8dc9e59ff5958f`。这是框架版本的来源核对，不涉及用户 MOD 的导入或覆盖流程。

CA 随游戏提供的 API 文档 `源码/documentation/script/campaign/episodic_scripting.html:2616` 明确要求 `add_unit_model_overrides` 在新会话重新设置，第二个参数来自 `campaign_character_art_sets`。因此，仅保存选择序号不构成完整的模型恢复。

框架作者将功能定位为战役使用，并记录详情面板关闭前肖像可能不刷新的问题；管理器不能据此承诺自定义战斗选择界面或所有肖像立即刷新。[Variant Selector 官方页面](https://steamcommunity.com/workshop/filedetails/?id=2888171970)

## 3. 无双英灵录的实际适配

注册文件：`mod/无双英灵录/marthvs/mod/wyccc_wushuang_yinglinglu.lua`。

当前文件登记 **26 个 subtype**，其中 22 个单套、4 个多套：

| 角色 | subtype | 登记外观数 |
| --- | --- | ---: |
| 红叶 | `wyccc_hero_momiji` | 3 |
| 吕玲绮 | `wyccc_lord_lulingqi` | 3 |
| 步练师 | `wyccc_lord_bulianshi` | 4 |
| 貂蝉 | `wyccc_lord_diaochan` | 3 |

该文件第 1–4 行说明单套登记用于重新应用主外观。源码例子包括 `wyccc_hero_2b`、`wyccc_hero_a2`，不是通过复制同一外观凑成两项。

持久化参考：`mod/无双英灵录/script/campaign/mod/wyccc_bulianshi_variant_selector.lua`。

- 第 11–25 行：步练师当前顺序是主套、`_03`、`_05`、`_06`，并为旧六套列表提供序号迁移。
- 第 47–75 行：记录选择并按 CQI 应用 art set。
- 第 156–182 行：保存选择及版本，读档时迁移旧索引。
- 第 184–229 行：监听选择事件、PendingBattle，并在会话初始化后恢复模型；战前必要时调用 `cm:update_pending_battle()`。

貂蝉、吕玲绮、红叶的同目录脚本使用相同方向。通用实现可以提炼这套生命周期，但应仅管理自动补丁拥有的角色和用户实际选过的外观。

### 不能盲目追加全部 DB 行的实证

`mod/无双英灵录/db/campaign_character_art_sets_tables/!wyccc_characters_2b_a2_commander_bulianshi_caiwenji.tsv:8` 和 `:10` 仍能查到步练师 `_02`、`_04` 两个 art set；现有选择表和版本迁移明确没有把它们列入当前四套。

**如果通用补丁对已注册角色追加所有扫描到的 art set，就会重新暴露人工排除的选项。** 是否仍有 DB 行，不能替代作者对可选外观的决定。应以现有注册为边界，整 subtype 跳过，而不只是对字符串去重。

### 本地尚未注册的样本

在 `!wyccc_diaoc_gaia_guanyp_huangyy_jihl.tsv` 第 6–9 行发现下列主 subtype 有 art set，但上述注册文件未登记：

| subtype | art set |
| --- | --- |
| `wyccc_hero_gaiya` | `wyccc_hero_gaiya_art` |
| `wyccc_hero_guanyinping` | `wyccc_hero_guanyinping_art` |
| `wyccc_hero_huangyueying` | `wyccc_hero_huangyueying_art` |
| `wyccc_hero_nabat` | `wyccc_hero_nabat_art` |

这是本地无双源码与该注册表的差集，不表示当前完整 MOD 组合中绝无其他脚本给它们注册。最终仍需游戏内通过公开 API 判断。

## 4. 原版静态样本统计及覆盖边界

输入：`源码/db/campaign_character_art_sets_tables/data__.tsv` 与框架 `marthvs/main/mvsmain.lua`。

方法：按 TSV 表头读取，跳过第二行元数据；按 `agent_subtype` 分组，对照这份纯数据 Lua 主表中的键。没有把任务战、剧情条件等当作普通外观过滤，因此结果是**候选规模，不是最终可安全补丁人数**。

| 指标 | 数量 |
| --- | ---: |
| 原版 art-set 行 | 1,506 |
| 非空 subtype | 597 |
| Variant Selector 主表登记 subtype | 282 |
| 原版表中未被主表登记的 subtype | 315 |
| 上述缺项中只有一条 art-set 行 | 308 |
| 上述缺项中有多条 art-set 行 | 7 |

这份数字只代表本地原版 TSV 和当前已装框架主表，不推定其等于所有未来游戏版本或用户最终启用组合。

7 个多行缺项中，艾蕊娜萨有 4 个 art set；其余 6 个包含任务战专用行或角色类型不同的行。例如：

- 索雷克另一个 art set 限定 `wh_main_dwf_dwarfs_qb1` 派系。
- 阴影系高精法师同时有 wizard 行和 `_qb_general` 的 general 行。
- 绿骑士、艾柯德同样包含任务战将领用途的行。

这些差异直接存在于上述原版 TSV 的 `agent_type`、`faction`、`art_set_id`。不能只做 subtype 分组后把所有行都开放，也不能只靠 `_qb` 字符串决定所有 MOD 的语义。

`agent_subtypes_tables` 的 `show_in_ui` / `recruitable` 也不能单独作为排除条件：无双的 `wyccc_hero_gaiya` 本地行 `show_in_ui=false`，而脚本招募角色仍可能需要适配。

## 5. 建议的实现方案

以下是基于已读源码提出的实现建议，尚非已经交付的行为。

### 5.1 数据扫描

1. 输入使用当前游戏的原版数据库、当前启用 MOD，以及现有来源解析器纳入的自动加载 Movie 来源；不扫描订阅但未启用的所有 MOD 来生成可选项。
2. 按实际生效优先级解析 `campaign_character_art_sets_tables`，按 `art_set_id` 取有效行，再按 subtype 建候选列表。同名 art set 被替换后不能当作两套独立皮肤。
3. 补齐 `campaign_character_arts_tables`、`agent_uniforms_tables`、`variants_tables` 的关联读取，并用 `agent_subtypes_tables` 校验 subtype。允许合法空值和多条 arts 行，不能强行假设一对一。
4. 对任务战、派系/文化限制及特殊状态保留筛选依据。存在多种角色类型或依赖剧情脚本的情况，使用明确规则处理；不能确定时输出跳过原因。
5. 单 art set 保留；数组中同名 art set 去重。自动数据有稳定排序，但不改变作者列表。

典型模型链为：`subtype -> art_set -> campaign_character_arts.uniform -> agent_uniforms -> variants -> 模型资源`。肖像还依赖 art set 对应的 portrait settings。仅增加注册不会自动补齐缺失美术或把资源覆盖转换成新的 DB 外观链。[作者关于 portrait settings 的说明](https://steamcommunity.com/workshop/filedetails/discussion/2888171970/5440953210414305791/)

### 5.2 注册时保护已有适配

单纯生成 `marthvs/mod/wyccc_auto.lua` 会进入框架的表合并阶段，不容易保证「已有角色完全不碰」和人工编号稳定。更合适的方式是生成候选数据，由战役脚本在框架及既有注册初始化后使用公开 API 补缺：

```lua
-- 仅展示已经做过接口实验的核心判断，不是可直接发布的完整脚本。
if marthvs:get_subtype_variants(subtype) == nil then
    marthvs:set_subtype_variants(subtype, candidate_art_sets)
end
```

需要检查 `marthvs` 和两个方法是否存在。已有非空列表或空表都保留；空表可能代表作者主动限制。初始化应以明确的生命周期和有界重试处理，而不是仅凭文件名或随意延迟保证先后。

运行时只维护本补丁登记成功的 subtype。对之后由其他脚本接管或改变列表的 subtype，恢复逻辑也应停止管理。对于主动通过 nil 隐藏、动态解锁或变身的角色，单次 nil 判断无法识别作者意图，需要规则或专项适配；这是不能承诺全角色无条件支持的原因之一。

管理器不能在宿主 Python 中执行任意 MOD Lua 来推测注册结果。静态统计可以辅助诊断，最终已注册判定由游戏内框架完成。

### 5.3 恢复用户选择

- 复用框架的 `UITrigger` 同步链；所有客户端用同一 art-set 数据解释事件。
- 对本补丁拥有的角色，仅在玩家实际选择后保存 `{CQI, subtype, art_set_id}`。单套角色选过后也适用，避免下次会话失去刷新结果。
- 保存 art-set ID，而不是只保存序号；生成数据变化后按 ID 找回新索引，再调用框架的 `set_character_variant_index` 更新界面。
- 参考无双，在新会话初始化后和待战阶段恢复所记录的外观。只遍历记录角色/参战角色，避免频繁扫描全世界。
- art set 被删除、subtype 变化或已有适配接管时，停止应用失效记录并记录原因，不强制改选另一套。
- 不对从未选择过的角色自动套第一项，以保留游戏默认外观和剧情行为。

现有框架和无双脚本支持这条技术路线，但坐骑切换、特殊变身、AI 回合及多人存读档还必须游戏内验证。不能把 Lua 接口实验写成这些行为已经通过。

### 5.4 管理器接入位置

| 现有位置 | 可复用内容 / 需要变化 |
| --- | --- |
| [CompatibilityPatchModal.vue](../../frontend/src/components/CompatibilityPatchModal.vue:16) | 增加独立开关；目前前置缺失会拦整个表单，扩展后应按各补丁分别判断，避免 RoR 未启用阻止保存 Variant Selector 设置 |
| [app_settings.py](../../backend/app_settings.py:225)、[api.py](../../backend/api.py:601) | 新设置默认关闭；保存时分别保留两项设置，不能沿用只读写 RoR 的逻辑 |
| [start_options.py](../../backend/start_options.py:735) | 复用当前来源快照和输入顺序；增加本功能所需表和框架识别信息的读取 |
| [game_data.py](../../backend/game_data.py:892) | 复用已有效果行选择：原版兜底，MOD 内部 DB 名优先，同名按来源顺序决定 |
| [dynamic_ror_patch_state.py](../../backend/dynamic_ror_patch_state.py:185) | 参考输入指纹、缓存、来源变化时重建、关闭后清理生成物的生命周期 |
| [start_options.py](../../backend/start_options.py:386)、[api.py](../../backend/api.py:1292) | 复用独立运行时 Pack 写入及启动计划接入，新增本功能生成器 |
| [languages.js](../../frontend/src/languages.js:522) | 实现时同步所有内置语言的界面文案 |

源码实查：本项目的 `TABLE_SCHEMAS` 与 `ALL_TABLE_ORDER` **目前均不含**上文五张角色外观相关表。现有来源快照也只读取 `TABLE_PREFIXES`，因此不能仅加 UI 开关就获得角色数据；必须补解析范围和相应表版本。

补丁数据只需提供候选 Lua 与注册/恢复 Lua，不必修改角色数值或复制框架的 UI。基础依赖是 Variant Selector 本体；本管理器实现生成逻辑后，无需把 WHMM 的自动兼容辅助 MOD 设为必需依赖。

缓存应纳入：有序来源、所需 DB、框架/注册相关输入、生成器及筛选规则版本。静态统计只能报告候选数；「实际跳过已有适配数」应以游戏内注册日志为准。

## 6. 已做验证与实施后的验收

本次已完成：

1. 读取框架、无双注册与恢复脚本、CA API 文档，以及管理器现有兼容补丁入口。
2. 对照本地框架源码和已安装框架的两个 Lua 文件，确认字节一致。
3. 读取原版 TSV 与无双表，得出上面的明确样本数量，并找出任务战行和步练师排除项。
4. 使用本机 Lua 执行**实际框架代码和实际注册数据**，以轻量 stub 替代游戏事件/UI 环境。验证 26 个无双注册能加载、单套列表保留、API 可以补缺、已有四套顺序不会被补缺判断替换、已有空注册不会被补缺判断打开。实验全部通过。
5. 直接导入当前 Python 数据模块，确认五张相关表尚未纳入解析和快照范围。

该实验验证数据及公开 API，不模拟游戏渲染、剧情或联机。

正式实现至少覆盖以下结果：

| 场景 | 预期 |
| --- | --- |
| 原版未适配、仅单套外观的普通角色 | 显示单项入口，点击仍使用自身有效 art set |
| MOD 新角色、多个有效且未登记的外观 | 正常列出、切换，并在读档/进战斗后保持 |
| 步练师等已有人工适配 | 顺序不变，排除的 `_02`、`_04` 不重新出现 |
| 仅替换相同资源路径的换皮 MOD | 不虚构「原版/换皮」两项 |
| 任务战、条件外观、特殊变身 | 根据规则排除或专项处理，记录具体原因 |
| 换坐骑、保存后更改 MOD 组合 | 不把过期序号用于另一个 art set，不破坏原有坐骑或剧情行为 |
| 缺少/关闭 Variant Selector | 独立提示或跳过，本补丁不注册；其他兼容补丁仍可配置 |
| 多人新开档、读档及待战 | 选择、恢复结果一致，无同步差异 |

可优先完成「普通角色补缺 + 单套入口 + 选择持久化」，以明确规则逐步扩展特殊角色；产品描述应表达自动发现已有外观，不承诺自动创造新皮肤或任意 MOD 的变身兼容。
