# Variant Selector 自动兼容补丁研究

研究日期：2026-09-08

本文只研究《全面战争：战锤 3》Variant Selector 的真实接入协议、无双英灵录的适配方式、WH3 Mod Manager（WHMM）的参考实现能力，以及 Wyccc's Mod Manager 是否能够在启动时为原版和已启用 MOD 的未适配角色生成兼容数据。本文没有修改功能代码、没有生成 Pack，也不讨论 Pack 是否正确导入或覆盖。

## 结论先行

**可以做，但当前 Wyccc's Mod Manager 还没有这项能力，且“把 DB 中同 subtype 的所有 art set 全部加入选择器”不是安全实现。**

推荐把它做成现有“兼容补丁”体系中的一个独立提供者：按当前启用 MOD 的真实覆盖顺序计算最终 DB 视图，提取能够走通角色外观链的候选项，然后生成一个 Lua-only 运行时 Pack。脚本应在 Variant Selector 初始化后调用其公开 API，并且只为 `marthvs:get_subtype_variants(subtype) == nil` 的 subtype 注册列表，不改动 Variant Selector 本体和其他 MOD 已有的人工列表。

默认模式应只注册“至少有两套、可验证且互不相同的陆战外观”的角色。若把“所有角色”解释为包括只有一套外观的角色，技术上也能注册，Variant Selector 本体也会显示一个只有一个按钮的选择器；但这没有切换价值，会给大量人物增加无意义 UI。可以保留为一个明确命名的可选模式，不能作为默认行为。

本地原版数据验证尤其说明了这一点：当前有效关系中共有 591 个 subtype，Variant Selector 主表已覆盖 282 个；剩余 309 个中，302 个只有一个 art set，另外 7 个大多是任务战斗、快速战斗、海战、坐骑或 agent type 特例。按实际陆战 `uniform` 去重后，未覆盖组里只有 Thorek 的 base/anvil 是两套不同陆战外观，但它也是快速战斗/铁砧状态特例，不宜自动暴露。因此，**默认安全规则在当前原版数据上很可能不会补出新的“有意义选择器”**；功能主要价值在于为结构规范的 MOD 新角色自动适配。

## 一、Variant Selector 本体的真实协议

本地来源目录：

`C:\Users\Administrator\Desktop\战锤MOD相关\mod\第三方MOD\Variant Selector`

`pack_map.json` 将其映射为 Workshop `2888171970` 和 `!marthvariantselector.pack`。解包目录中只有 Lua 与 UI 模板，没有 DB 表，也没有 loc 文件。

### 1.1 注册数据格式

Variant Selector 的主表位于：

- [mvsmain.lua](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/marthvs/main/mvsmain.lua:1>)

扩展 MOD 的协议是：在虚拟路径 `marthvs/mod/*.lua` 放置一个 Lua 文件，文件返回如下结构：

```lua
return {
    ["agent_subtype_key"] = {
        "campaign_character_art_set_id_1",
        "campaign_character_art_set_id_2"
    }
}
```

框架先加载 `marthvs/main/mvsmain.lua`，再通过 `core:get_scripts_in_directory("marthvs/mod", true)` 发现所有扩展脚本并 `loadfile`。同一 subtype 的新 art set 会与主表已有列表比较，排序后追加；全新的 subtype 直接赋值。来源：[marthvariantselector.lua:1](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:1>)、[marthvariantselector.lua:36](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:36>)。

这里有两个重要边界：

1. 合并逻辑只拿新值与合并前的主列表比较。一个扩展表自身如果重复列出同一 art set，并不能保证被消重，所以生成器必须先消重。
2. 扩展表会向已有人工列表追加值。若自动生成器把 DB 中的任务战斗、快速战斗或状态专用 art set 一并输出，就会污染 Variant Selector 作者或其他 MOD 作者人工筛选过的列表。

### 1.2 公开运行时 API

框架还暴露全局对象 `marthvs`：

- `marthvs:get_subtype_variants(character_subtype_key)`：返回当前列表，未注册时返回 `nil`。
- `marthvs:set_subtype_variants(character_subtype_key, art_set_ids)`：用传入数组**替换**该 subtype 的完整列表，不是追加。
- `marthvs:get_character_variant_index(cqi)` / `set_character_variant_index(cqi, index)`：读写角色 CQI 对应的数字序号。

来源：[marthvariantselector.lua:73](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:73>)、[marthvariantselector.lua:79](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:79>)、[marthvariantselector.lua:88](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:88>)。

因此，最安全的自动补全入口不是静态 `marthvs/mod` 合并，而是独立 campaign 脚本在初始化后执行：

```lua
for subtype, art_sets in pairs(generated_candidates) do
    if marthvs:get_subtype_variants(subtype) == nil then
        marthvs:set_subtype_variants(subtype, art_sets)
    end
end
```

这样可以满足“只给没有 Variant Selector 的角色添加”，不会改写主表或其他 MOD 已经注册的 subtype。调用时机必须晚于 `marthvariantselector.lua` 建立全局 `marthvs`；可在 first tick/安全回调中检查对象存在后注册。

### 1.3 UI 与切换行为

角色被选中或人物详情面板打开时，框架按角色 subtype 查询注册表；只要结果不是 `nil` 就创建选择器按钮，没有检查数组长度是否大于 1。每个数组元素生成一个编号按钮，图标为 `ui/marthui/selector_variants/selector_N.png`。来源：[marthvariantselector.lua:133](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:133>)、[marthvariantselector.lua:162](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:162>)、[marthvariantselector.lua:355](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:355>)。

点击编号后，UI 发送：

```lua
CampaignUI.TriggerCampaignScriptEvent(cqi, "marthvs_variant_index:" .. index)
```

campaign 监听器解析数字索引，并执行：

```lua
cm:add_unit_model_overrides("character_cqi:" .. cqi, variants[index])
```

来源：[marthvariantselector.lua:307](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:307>)、[marthvariantselector.lua:323](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:323>)。

选择器标题、按钮文字和提示词由框架 Lua 硬编码为英文；本体没有 loc 协议。兼容补丁不需要生成 loc，也无法只靠新增 loc 改成本地化文本。

### 1.4 本体保存机制的边界

本体用 `marthvs_cvi` 保存 `CQI -> 数字索引`，见 [marthvariantselector.lua:481](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/第三方MOD/Variant Selector/script/campaign/mod/marthvariantselector.lua:481>)。本体源码中没有看到在新会话开始或 `PendingBattle` 时，按保存值显式重新调用 `add_unit_model_overrides` 的通用逻辑。

数字索引还依赖列表顺序稳定：只要生成规则、启用 MOD 或人工列表改变，旧存档的“第 2 项”就可能指向另一套 art set。无双英灵录为 Bulianshi 做过版本迁移，正好证明这是现实问题，而非理论问题。

## 二、角色外观所需的 DB key 链

Variant Selector 注册表的 value 不是 `uniform`、variant key 或模型路径，而是 `campaign_character_art_sets_tables.art_set_id`。自动发现至少需要以下有效关系：

| 顺序 | 表 | 关键字段 | 作用 |
| --- | --- | --- | --- |
| 1 | `agent_subtypes_tables` | `key` | 确认 subtype 在最终 DB 中有效 |
| 2 | `campaign_character_art_sets_tables` | `art_set_id`、`agent_subtype`、`agent_type`、`faction`、`culture`、`subculture`、`is_custom` | 将角色 subtype 映射到一个或多个 art set，并识别 QB/阵营/agent 类型特例 |
| 3 | `campaign_character_arts_tables` | `id`、`art_set_id`、`uniform`、`sea_uniform`、`navy_uniform`、`land_animation` 等 | 确认 art set 有实际层级记录，并取得陆战外观 |
| 4 | `agent_uniforms_tables` | `uniform_name`、`filename`、`battle_filename`、`campaign_porthole_filename` | 从 arts 的 `uniform` 解析到角色外观定义 |
| 5 | `variants_tables` | `variant_name`、`variant_filename` | 验证 uniform 使用的外观 key 最终能解析到 VMD/variant 资源 |

原版本地源文件：

- [campaign_character_art_sets_tables/data__.tsv](<C:/Users/Administrator/Desktop/战锤MOD相关/源码/db/campaign_character_art_sets_tables/data__.tsv:1>)：1506 个数据行，版本 7。
- [campaign_character_arts_tables/data__.tsv](<C:/Users/Administrator/Desktop/战锤MOD相关/源码/db/campaign_character_arts_tables/data__.tsv:1>)：1495 个数据行，版本 0。
- [agent_subtypes_tables/data__.tsv](<C:/Users/Administrator/Desktop/战锤MOD相关/源码/db/agent_subtypes_tables/data__.tsv:1>)：613 个数据行，版本 3。
- RPFM schema：[schema_wh3.ron](<C:/Users/Administrator/AppData/Roaming/FrodoWazEre/rpfm/config/schemas/schema_wh3.ron:102593>)，其中 `art_set_id` 是 character art sets 主键，`campaign_character_arts.id` 是数值主键，arts 的 `art_set_id` 引用 art sets。

实际筛选时不能只看表 2。无双英灵录存在两个已经写入 art sets、但没有 arts 行的 Bulianshi art set；作者的注册表有意未包含它们。这说明候选集合至少要做 `art_sets ∩ arts`，并继续验证 land uniform 链。

## 三、无双英灵录的实际适配

本地来源目录：

`C:\Users\Administrator\Desktop\战锤MOD相关\mod\无双英灵录`

### 3.1 Variant Selector 注册表

实际适配文件为：

- [wyccc_wushuang_yinglinglu.lua](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/marthvs/mod/wyccc_wushuang_yinglinglu.lua:1>)

它只返回 subtype -> art_set 数组，不调用 API，不含 loc。共注册 26 个 subtype，其中 22 个只有一个 art set，4 个有多套：

| subtype | 注册的 art_set_id | 对应陆战 uniform/variant |
| --- | --- | --- |
| `wyccc_hero_momiji` | `wyccc_hero_momiji_art`、`_art_02`、`_art_03` | `wyccc_hero_momiji`、`_02`、`_03` |
| `wyccc_lord_lulingqi` | `wyccc_lord_lulingqi_art`、`_art_02`、`_art_03` | `wyccc_lord_lulingqi`、`_02`、`_03` |
| `wyccc_lord_bulianshi` | `wyccc_lord_bulianshi_art`、`_art_03`、`_art_05`、`_art_06` | `wyccc_lord_bulianshi`、`_03`、`_05`、`_06` |
| `wyccc_lord_diaochan` | `wyccc_lord_diaochan_art`、`_art_02`、`_art_03` | `wyccc_lord_diaochan`、`_02`、`_03` |

注册行来源分别为 [Momiji:15](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/marthvs/mod/wyccc_wushuang_yinglinglu.lua:15>)、[Lulingqi:27](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/marthvs/mod/wyccc_wushuang_yinglinglu.lua:27>)、[Bulianshi:34](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/marthvs/mod/wyccc_wushuang_yinglinglu.lua:34>)、[Diaochan:40](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/marthvs/mod/wyccc_wushuang_yinglinglu.lua:40>)。

这也确认了两点：

- 单套外观角色可以被注册，框架会显示单选项；无双英灵录确实采用了这种语义。
- 人工注册列表不是“把 art_sets 表内所有同行照抄”。Bulianshi 的 `_art_02`、`_art_04` 存在于 `campaign_character_art_sets_tables`，但没有匹配的 `campaign_character_arts_tables` 行，因此作者只选了 01、03、05、06。

### 3.2 实际 DB 表与 key 关系

这些角色不是仅靠一段 Lua 生成新外观。每个选择项都在四组实际 DB 文件里走通：

- `db/campaign_character_art_sets_tables/!wyccc_xia_lvlq_buzhw_hongy_pulls.tsv`
- `db/campaign_character_arts_tables/!wyccc_xia_lvlq_buzhw_hongy_pulls.tsv`
- `db/agent_uniforms_tables/!wyccc_xia_lvlq_buzhw_hongy_pulls.tsv`
- `db/variants_tables/!wyccc_xia_lvlq_buzhw_hongy_pulls.tsv`
- Diaochan 对应四张表中的 `!wyccc_diaoc_gaia_guanyp_huangyy_jihl.tsv`
- Bulianshi 对应四张表中的 `!wyccc_characters_2b_a2_commander_bulianshi_caiwenji.tsv`

例如 Momiji/Lulingqi 的链为：

```text
campaign_character_art_sets.agent_subtype
  -> campaign_character_art_sets.art_set_id
  -> campaign_character_arts.art_set_id
  -> campaign_character_arts.uniform
  -> agent_uniforms.uniform_name
  -> agent_uniforms.filename
  -> variants.variant_name
  -> variants.variant_filename
```

本地逐行核验的最终模型目标分别为 Momiji `momiji`/`momiji2`/`momiji3`，Lulingqi `linhongyue`/`lulingqi2`/`lulingqi3`，Diaochan `diaochan1`/`diaochan2`/`diaochan3`，Bulianshi `bulianshi_01`/`03`/`05`/`06`。39 个注册的 subtype-art_set 映射全部存在相应 arts 链；Bulianshi 两个未完成映射没有被注册。

### 3.3 为什么四个多外观人物还有补充脚本

无双英灵录另有四个 campaign 脚本：

- [wyccc_momiji_variant_selector.lua](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_momiji_variant_selector.lua:1>)
- [wyccc_lulingqi_variant_selector.lua](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_lulingqi_variant_selector.lua:1>)
- [wyccc_diaochan_variant_selector.lua](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_diaochan_variant_selector.lua:1>)
- [wyccc_bulianshi_variant_selector.lua](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_bulianshi_variant_selector.lua:1>)

四者的共同目的不是注册 UI，而是增强选择状态的持久化和战斗前应用：

- subtype 过滤后监听同一 `UITrigger`，取得 Variant Selector 发来的数字索引；
- 记录 CQI 对应选择并调用 `cm:add_unit_model_overrides`；
- 会话开始遍历 faction characters，重新应用保存选择；
- `PendingBattle` 时处理攻守方角色，随后调用 `cm:update_pending_battle()`；
- 用各自 namespaced key 做 `save_named_value`/`load_named_value`。

以 Momiji 为例，应用函数在 [第 35 行](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_momiji_variant_selector.lua:35>)，UI 监听在 [第 165 行](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_momiji_variant_selector.lua:165>)，PendingBattle 在 [第 189 行](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_momiji_variant_selector.lua:189>)。Bulianshi 还保存版本号并在旧列表发生删除/重排后迁移数字索引，见 [第 8 行](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_bulianshi_variant_selector.lua:8>) 和 [第 168 行](<C:/Users/Administrator/Desktop/战锤MOD相关/mod/无双英灵录/script/campaign/mod/wyccc_bulianshi_variant_selector.lua:168>)。

自动补丁若要达到无双英灵录的稳定性，应生成一个覆盖所有自动 subtype 的通用持久化脚本，而不是为每个人复制一份监听器。保存值宜使用 art_set 字符串而非数字索引；收到 UI 的数字索引时立即解析成当前 art_set 再保存，这样启用 MOD 或排序变化后不会静默换成另一外观。

## 四、原版实际覆盖与误选风险

对本地原版表按 `agent_subtype -> art_set_id` 分组，并要求 art set 至少有一条 arts 记录后得到：

| 项目 | 数量 |
| --- | ---: |
| 有效 art_set 行 | 1494 |
| 有效 subtype 组 | 591 |
| subtype 存在多个 art_set | 288 |
| subtype 只有一个 art_set | 303 |
| Variant Selector 主表已注册 subtype | 282 |
| 未注册 subtype | 309 |
| 未注册但原始 art_set 数量大于 1 | 7 |

Variant Selector 主表的 282 个数组长度均为 2 至 6，没有原版 singleton：2 项 15 组、3 项 79 组、4 项 46 组、5 项 138 组、6 项 4 组。由此可见本体作者对原版采用的是“挑选有意义的多外观”，而非“全部人物都显示按钮”。

未注册但 raw art_set > 1 的 7 组是：

| subtype | 原始差异 | 自动处理判断 |
| --- | --- | --- |
| `wh_dlc07_brt_green_knight` | base + `_qb_general`，同一 land uniform，agent type 不同 | 排除 QB/agent type 特例 |
| `wh_dlc08_nor_shaman_sorcerer_death` | base + `_qb_general`，同一 land uniform | 排除 QB；外观实际重复 |
| `wh_main_emp_celestial_wizard` | base + `_qb_general`，同一 land uniform | 排除 QB；外观实际重复 |
| `wh2_dlc10_hef_mage_shadows` | base + `_qb_general`，同一 land uniform | 排除 QB；外观实际重复 |
| `wh2_dlc11_cst_aranessa` | 4 个 art set，land uniform 相同，只是 sea/navy uniform 不同 | 不属于陆战人物换装，排除重复 land 外观 |
| `wh2_dlc17_dwf_thorek` | base + anvil，land uniform 不同；anvil 带 QB faction | 坐骑/状态/QB 特例，默认排除，手工白名单才可加入 |
| `wh3_dlc24_tze_aekold_helbrass` | base + `_qb`，同一 land uniform，agent type 不同 | 排除 QB/agent type 特例 |

而且主表已注册的一些 subtype 也明确没有纳入同 subtype 的 `_qb_general` 行，例如 Handmaiden、Dark Elf Master、Loremaster、Noble、Black Orc Big Boss、Hag Witch、Alluress、Iridescent Horror、Werekin、Light Wizard、Witch Hunter 和 Goblin Big Boss。这是直接证据：**`agent_subtype` 相同不代表 art set 都是玩家可切换外观。**

## 五、WHMM 的参考实现与可确认边界

### 5.1 工坊适配器

prop joe 发布了 [Automated Variant Selector Compatibility (REQUIRES WH3MM)](https://steamcommunity.com/sharedfiles/filedetails/?id=3629192206)，工坊说明称它需要 WH3 Mod Manager 2.16.4+，扫描当前启用 MOD，并生成一个包含 Variant Selector 所需脚本的新 Pack。这证明“扫描启用项 -> 生成 Lua Pack”的产品路线已经实际使用。

但工坊适配器 Pack `3629192206` 没有安装在本机工坊目录，也未在本地 MOD 源目录找到；因此没有读到其 `whmmflows` 文件。本文不能把它具体使用了哪些表、过滤了哪些 subtype、怎样去重或怎样处理人工适配描述成已核验事实。

作者回复还给出两个已知边界：多个独立重皮肤 MOD 是否能成为同一角色的多个选项“取决于制作方式，通常不能”；生成 Pack 的日期差异可能造成多人版本不一致。这两点与本地数据链分析一致，不能承诺自动补丁解决所有重皮肤资源覆盖或天然保证多人同步。

更详细的 WHMM 证据核验见 [whmm-variant-selector-reference.md](./whmm-variant-selector-reference.md)。

### 5.2 本地 WHMM 源码实际提供什么

本地 `G:\git\WH3-Mod-Manager` 快照为提交 `0011d479735a947eecedb0093e1e7570103e428d`，版本 2.19.1。源码中没有 `Variant Selector`、`variant_selector` 或 `marthvs` 的专用 TypeScript 分支；它提供的是通用 `whmmflows` 节点执行器：

| 能力 | 关键源码 |
| --- | --- |
| 读取 `whmmflows` JSON、执行节点图 | [packFileSerializer.ts:1355](G:/git/WH3-Mod-Manager/src/packFileSerializer.ts:1355)、[nodeGraphExecutor.ts:318](G:/git/WH3-Mod-Manager/src/nodeGraphExecutor.ts:318) |
| 取得所有启用 MOD，可选加入 `db.pack` | [nodeExecutor.ts:541](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:541) |
| 按表名选择 DB 文件 | [nodeExecutor.ts:614](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:614) |
| 过滤、Lookup、GroupBy、Deduplicate | [nodeExecutor.ts:925](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:925)、[nodeExecutor.ts:3293](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:3293)、[nodeExecutor.ts:817](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:817)、[nodeExecutor.ts:4490](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:4490) |
| 用模板生成文本并写入 Pack | [nodeExecutor.ts:2972](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:2972)、[nodeExecutor.ts:2642](G:/git/WH3-Mod-Manager/src/nodeExecutor.ts:2642) |
| 将生成 Pack 加入本次启动列表 | [ipcMainListeners.ts:7927](G:/git/WH3-Mod-Manager/src/ipcMainListeners.ts:7927) |

通用能力足以说明 WHMM 可以承载一个扫描/文本生成工作流，但它不是完整参考算法。源码中的表选择与分组按来源收集行，不能自动等价于游戏最终覆盖后的 DB 视图；`Deduplicate` 也只是按列哈希保留首次记录，不识别 subtype 是否已在任意 `marthvs/mod` 脚本中人工注册。

此外，本地 WHMM flow 体系存在这些复刻时不应照搬的边界：

- 没有用于“候选 subtype 减去已注册 subtype”的安全 Lua anti-join；解析或执行任意第三方 Lua 也不应成为生成器职责。
- 工作流同时保存 DB 与 Lua 文本到同一输出 Pack 时，文本保存路径可能覆盖先前构建对象；它更适合本任务的 Lua-only 输出。
- flow 生成包追加在已启用列表末尾；按本项目的“列表顶部最高优先级”语义，这等于低优先级。Wyccc 当前兼容补丁架构反而能把运行时 Pack 插入顶部。
- 生成的本地文件时间/内容若不同，会影响多人校验；需要额外保证确定性和相同输入，不能只说脚本事件本身 MP-safe。

## 六、Wyccc's Mod Manager 当前能力差距

当前“兼容补丁”弹窗只有 Nanu Dynamic RoR 一个选项，见 [CompatibilityPatchModal.vue:15](../../frontend/src/components/CompatibilityPatchModal.vue:15)。后端只有对应生成器、状态缓存和启动接线：

- [dynamic_ror_compatibility.py](../../backend/dynamic_ror_compatibility.py:1)
- [dynamic_ror_patch_state.py](../../backend/dynamic_ror_patch_state.py:1)
- [api.py:1292](../../backend/api.py:1292)

可以复用的已有基础设施：

- [start_options.py:597](../../backend/start_options.py:597) 能解析显式启用 Pack、自动加载 Movie Pack、原版 DB，以及现有运行时补丁来源。
- [start_options.py:687](../../backend/start_options.py:687) 并发读取来源快照。
- [game_data.py:949](../../backend/game_data.py:949) 的 `_collect_effective_rows` 已按内部 DB 文件名优先级、来源优先级和原版回退计算最终有效行。
- [start_options.py:386](../../backend/start_options.py:386) 的 Pack writer 能写任意路径的原始字节，已有 Dynamic RoR 生成 Lua 的先例。
- [dynamic_ror_patch_state.py:53](../../backend/dynamic_ror_patch_state.py:53) 已有输入指纹、按需重建和状态复用模式。
- [api.py:1394](../../backend/api.py:1394) 将 `!!!!` 运行时 Pack 放在用户有序列表之前，即顶部最高优先级。

当前阻碍不是 Pack writer，而是数据范围。[game_data.py:437](../../backend/game_data.py:437) 的 `TABLE_ORDER` 和 [game_data.py:465](../../backend/game_data.py:465) 的 `TABLE_PREFIXES` 尚不包含本任务所需的五张表：

- `campaign_character_art_sets_tables`
- `campaign_character_arts_tables`
- `agent_subtypes_tables`
- `agent_uniforms_tables`
- `variants_tables`

`start_options.py` 只读取 `TABLE_PREFIXES` 命中的 DB 文件，见 [第 700 行](../../backend/start_options.py:700)。所以当前代码无法建立候选集合，也没有生成 Variant Selector 脚本、检测前置 MOD 或处理保存状态的逻辑。结论是：**现有架构适合扩展，但现成功能不能直接兼容 Variant Selector。**

## 七、建议的自动生成算法

### 7.1 前置 MOD 检测

不要只认 Pack 文件名或 Workshop ID。重命名、本地副本和合并 Pack 都会让这种检测误判。按最终启用内容检测以下特征更可靠：

- `script/campaign/mod/marthvariantselector.lua`
- `marthvs/main/mvsmain.lua`
- 至少一份 `ui/marthui/marth_daniel_*.twui.xml`

核心 Lua 与主表都存在才启用生成。若缺失，UI 应显示前置 MOD 不满足，并且不要生成一个必然引用空全局的 campaign 脚本。

### 7.2 构建最终候选集合

必须先按实际启动顺序计算每张表的**最终有效行**，而不是把所有 Pack 的行直接拼起来。推荐顺序：

1. 将上述五张表加入兼容补丁专用 schema/读取范围；避免不必要地扩大单位编辑器的公共表面。
2. 按每张表真实主键和内部 DB 文件优先级做 overlay。`campaign_character_arts_tables` 的主键是数值 `id`，不能误拿 `art_set_id` 当主键覆盖。
3. 仅保留 `campaign_character_art_sets.agent_subtype` 非空、且能在最终 `agent_subtypes` 找到的行。
4. 以 `art_set_id` 与最终 arts 相交。若同一 art set 有多级/多年龄 arts 行，应将它视为同一个选择项，而不是重复按钮。
5. 要求 arts 有非空 land `uniform`，能匹配最终 `agent_uniforms.uniform_name`；再验证 `agent_uniforms.filename` 能匹配最终 `variants.variant_name`。缺链项不进入自动候选。
6. 用“最终陆战外观签名”去重，例如 `uniform + agent_uniform.filename + variant.variant_filename`。同一 subtype 多个 art set 若签名相同，只保留规范的基础项。
7. 按 subtype 分组，生成稳定、确定性的 art set 顺序。优先选不带特殊后缀、无 faction 限制且与常规 agent type 一致的基础项，其余按稳定 key 排序。

### 7.3 默认排除条件

自动规则应宁可漏掉少量特殊外观，也不能把战斗状态或错误资源暴露给所有同 subtype 角色。默认排除：

- art set 没有任何有效 arts 行；
- land `uniform` 为空，或 uniform/variant 资源链断裂；
- 与已选项具有相同陆战外观签名；
- 同 subtype 内 `agent_type` 与常规基础项不同；
- `faction` 非空且明显指向快速战斗、任务战斗或场景专用阵营；
- key/文件语义为 `_qb`、`_qb_general`、dummy、proxy、ritual、caravan、horde 等场景实体；
- 坐骑、铁砧、战车、变身、升级阶段、伤残/状态外观；这些只能在验证游戏机制后放入手工 allowlist；
- 只有 sea/navy uniform 不同、land uniform 相同；
- subtype 已由 Variant Selector 主表或任意扩展脚本注册。

最后一条不应靠静态解析第三方 Lua 完成。推荐在生成数据层保留候选，运行时通过 `marthvs:get_subtype_variants` 判空，天然尊重已加载的所有人工适配。

### 7.4 两种覆盖模式

| 模式 | 候选要求 | 结果 |
| --- | --- | --- |
| 有意义外观（默认） | 未注册，至少 2 个不同且完整的陆战外观签名 | 只显示真正可切换角色，原版当前可能新增 0 个 |
| 全部角色（可选） | 未注册，至少 1 个完整外观 | 包含 singleton；符合无双英灵录的实际做法，但会出现大量只有一个按钮的 UI |

“全部角色”模式仍不能取消资源链验证和特殊状态排除。它只能把所有**安全、有效的常规角色 subtype** 注册，不应被描述成无条件收录 DB 中每一行。

### 7.5 生成物建议

生成一个独立、确定性的运行时 Pack，例如：

```text
!!!!wyccc_variant_selector_compatibility.pack
└─ script/campaign/mod/wyccc_variant_selector_compatibility.lua
```

脚本内包含：

- 稳定排序后的 `subtype -> art_set_id[]` 候选表；
- first tick 后的 `marthvs` 判空注册；
- 一个 namespaced `UITrigger` 监听器，只处理自动注册 subtype；
- `CQI -> art_set_id` 字符串保存；
- 会话开始与 `PendingBattle` 的统一重新应用；
- 对已死亡/无效 CQI 的防御性清理；
- 唯一 listener 名、save key 和脚本路径，避免与本体及其他 MOD 冲突。

Lua-only 输出不新增任何 DB 行，因此不会产生 `campaign_character_arts.id` 数值主键冲突。DB key 冲突只发生在输入端，应由最终有效视图解决。生成 Pack 放在顶部最高优先级，但使用唯一内部路径，不覆盖 Variant Selector 文件；高优先级主要保证生成脚本和将来的同名旧补丁不会被遮蔽。

## 八、重复适配、负载顺序与安全边界

### 重复适配

- 不要把全部候选直接写进 `marthvs/mod`，否则框架会给已有列表追加遗漏的 QB/状态项。
- 不要调用 `set_subtype_variants` 覆盖非空列表，因为它会替换人工排序与内容。
- 运行时只填 `nil`，可以同时尊重本体、无双英灵录和其他 MOD 的适配，无需执行或静态解释第三方 Lua。
- 生成脚本自身需幂等；重复 first tick/载入回调不能重复注册监听器或重排数组。

### 负载顺序

- 项目既有语义是列表顶部最高优先级。生成 Pack 应与现有 Dynamic RoR 补丁一样插入用户 MOD 之前，而不是追加到列表底部。
- 由于内部文件路径唯一，不依赖覆盖 Variant Selector 本体来工作。
- 每次启用列表、顺序、Pack 指纹或原版数据库版本改变时重建；输入未改变时复用完全相同的字节。
- Variant Selector 的扩展脚本通过 VFS 目录枚举发现，静态注册表通常不依赖 Pack 先后；API 判空方案仍需保证 campaign 调用晚于本体初始化。

### ID/key 冲突

- 不生成 DB，因此没有新 DB 主键。
- 输入侧相同 `art_set_id`、uniform key、variant key 必须按最终覆盖关系解析，不能把被覆盖版本同时当成两个选项。
- 同一 subtype 的两个 art set 若最后指向同一个 variant 资源，只能算一套外观。
- 选择状态保存 art_set 字符串；若该 art set 在新启动组合中消失，回退当前列表第 1 项并更新保存值，不用旧数字索引猜测。

### 不能自动解决的情况

1. 两个重皮肤 MOD 都覆盖原版同一个 uniform/variant key，而没有建立各自独立的 art_set/uniform/variant 链。最终 VFS 只剩一个有效资源，生成器无法从被覆盖资源中凭空构造第二套可选外观。
2. 坐骑、变身、任务战斗、快速战斗、海战专用 art set。相同 subtype 不代表可以对普通战役角色安全调用模型覆盖。
3. 模型或动画本身不兼容。DB 链完整只能证明资源可解析，不能证明任意角色状态下视觉和骨骼正确。
4. 多人自动同步。即使脚本使用 Campaign Script Event，双方仍必须有相同启用列表、相同生成候选、相同脚本字节和 Pack 元数据；WHMM 适配器作者已报告生成时间差异可能导致版本不一致。
5. Variant Selector 本体未来更改 API、UI 图标数量或脚本生命周期。补丁指纹和前置检测要带协议版本/兼容版本，不能永久假设当前源码。

## 九、实施范围建议

若进入实现，建议分成两个阶段：

1. **安全自动注册 MVP**：新增五表读取和最终 overlay；只收集至少两套不同陆战外观；运行时判空注册；生成 Lua-only Pack；不接管保存逻辑。先用原版、无双英灵录和若干规范 MOD 验证零误选。
2. **持久化增强**：参考无双英灵录，用一个通用脚本按 art_set 字符串保存并在会话开始/PendingBattle 重放；加入 singleton 可选模式、排除报告和手工 allowlist。

UI 最好同时报告：扫描到多少 subtype、多少已由 Variant Selector/其他 MOD 适配、多少自动新增、多少因 singleton/重复外观/链断裂/特殊状态被排除。这样“没有生成新角色”可以被解释为数据结论，而不是误判成生成失败。

## 最终判断

Wyccc's Mod Manager 的现有兼容补丁基础设施足以承载 Variant Selector 自动兼容，但当前版本尚未读取所需表，也没有生成或注册逻辑，因此现在不能直接完成用户目标。

新增功能后，可以可靠覆盖：**原版与当前已启用 MOD 中，最终 DB 链完整、拥有独立 art_set/uniform/variant 资源、尚未被 Variant Selector 人工注册的常规角色 subtype。** 它不能可靠覆盖：共享同一被覆盖资源的多个重皮肤、QB/任务/坐骑/变身/海战状态，以及任何只有 DB 名义差异却没有不同最终陆战外观的条目。

所以产品承诺应写成“自动为未适配且检测为安全的角色外观添加 Variant Selector”，而不是“无条件为原版和所有 MOD 的所有角色添加选择器”。
