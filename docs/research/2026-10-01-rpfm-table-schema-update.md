# MOD 表结构更新：RPFM 源码核对

核对时间：2026-10-01。最新稳定版为 [RPFM v5.1.0](https://github.com/Frodo45127/rpfm/releases/tag/v5.1.0)，源码提交 `e8992600bf8ea86153e3e530985f8665ecfd301e`；官方 schema 快照为 `5d841c5c2a73d27495c6fed7282dc011c5517e1c`。

## 可直接采用的实现规则

RPFM 的更新目标是**已安装游戏原版 Pack 中该表的最新有效定义**，从可解码的原版同名表中取 `definition.version` 最大值。它比较完整 Definition，所以相同版本号但字段布局改变也能更新；原版没有该表时返回错误，并非直接选择 schema 的最大版本。[`Dependencies::update_db`](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_extensions/src/dependencies/mod.rs#L2287)

迁移按字段名完全相等匹配，保留行数和行序，并按新字段顺序生成每行：旧有同类型字段保留值；删去旧独有字段；新增字段使用目标默认值；同名不同类型字段先转换，转换失败才使用目标默认值。默认值优先取 `schema.patches[table_name][field_name]["default_value"]`，否则取字段自身 `default_value`。字段改名等同于删除旧列、新增新列。[`TableInMemory::set_definition`](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/files/table/local.rs#L761)、[`Field::default_value`](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/schema/mod.rs#L1883)

DB 解码必须使用 MOD 的旧定义，编码使用新定义。正版本需要精确匹配；没有版本标记时 header 版本为 `0`，依照 schema 列表顺序逐个尝试版本 `<1` 的定义，并要求所有行解码成功且读到文件末尾。负版本是无版本表历史布局，不能仅取 `0`。编码只在目标版本 `>0` 时写版本标记。保留 mysterious byte 和已有 GUID；当前管理器支持的 11 个游戏都使用 GUID，RPFM 只在 GUID 为空或明确要求重生成时建立新 UUID。[DB 解码及编码](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/files/db/mod.rs#L166)、[游戏定义](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/games/supported_games.rs)

## 完整 schema 与获取方式

完整文件从官方仓库直接下载，无需安装 RPFM：`https://raw.githubusercontent.com/Frodo45127/rpfm-schemas/master/<filename>`。可通过 [GitHub 分支 API](https://api.github.com/repos/Frodo45127/rpfm-schemas/commits/master) 获取提交，再把 URL 中 `master` 换为该 SHA 以固定同次批量操作的快照。各游戏映射来自 RPFM 自身的游戏定义和 [schema 仓库](https://github.com/Frodo45127/rpfm-schemas/tree/5d841c5c2a73d27495c6fed7282dc011c5517e1c)：

| 管理器游戏 ID | schema 文件 |
| --- | --- |
| `warhammer3` | `schema_wh3.ron` |
| `warhammer2` | `schema_wh2.ron` |
| `warhammer` | `schema_wh.ron` |
| `three_kingdoms` | `schema_3k.ron` |
| `pharaoh_dynasties` | `schema_ph_dyn.ron` |
| `pharaoh` | `schema_ph.ron` |
| `troy` | `schema_troy.ron` |
| `thrones_of_britannia` | `schema_tob.ron` |
| `attila` | `schema_att.ron` |
| `rome2` | `schema_rom2.ron` |
| `shogun2` | `schema_sho2.ron` |

RON 根结构包括 `version`、`definitions`、`patches`。根 `version: 5` 是 schema 格式版本。`definitions` 为表名到 Definition 列表的 map；每个 Definition 有 `version`、`fields`、`localised_fields`、`localised_key_order`。每个 Field 包含字段名、类型、默认值和枚举/位域/颜色等 metadata。解析器需支持括号结构体、列表、map、裸枚举、负整数、布尔、转义字符串、`Some(...)`、`None`、tuple 和嵌套 `SequenceU16/U32(Definition)`；不能用只抓 name/type 的正则替代完整解析。[完整 WH3 文件](https://github.com/Frodo45127/rpfm-schemas/blob/5d841c5c2a73d27495c6fed7282dc011c5517e1c/schema_wh3.ron)、[Schema / Definition / FieldType](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/schema/mod.rs#L209)

建议下载成功且解析验证通过后原子替换缓存，保存 schema SHA/时间；网络失败可用已验证缓存。没有缓存且获取失败时停止该游戏批次。现有精简 `wh3_db_schema.json` 不具备所有表的历史定义和 metadata，不能作为完整迁移依据。缓存与原版目标定义应按游戏隔离；一批操作固定 schema 快照。

## 字段二进制与转换边界

| 类型 | 二进制或转换规则 |
| --- | --- |
| `I16/I32/I64`、`F32/F64` | little endian，长度依次 2/4/8 与 4/8 字节。 |
| `StringU8/StringU16` | `u16` 长度前缀，分别计算 UTF-8 字节数与 UTF-16 code units。 |
| `OptionalI16/I32/I64` | bool flag 后**始终存在整数**，flag 为 false 时仍读 sentinel；RPFM writer 总是写 true。 |
| `OptionalStringU8/U16` | flag=false 后没有长度或内容；flag=true 后普通 sized string；writer 把空串写成 false。 |
| `ColourRGB` | 4 字节 LE u32；`0504FF` 对应 `FF 04 05 00`，不是 3 字节。 |
| `SequenceU16/U32` | `u16/u32` 行数，随后为嵌套 Definition 的行数据。 |

以上以 [reader](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/binary/reader.rs#L388)、[writer](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/binary/writer.rs#L272) 实际函数为准；`FieldType` 附近把所有 optional 都描述为“false 无值”的注释不适用于整数。

数字转 Boolean 使用 `value >= 1`，因此负数和 `0.5` 都为 false；Boolean 转数字使用 `1/0`，转颜色使用 `FFFFFF/000000`。字符串转 Boolean 只接受不区分大小写的 `true/false/1/0`，不 trim，也不接受 yes/no。字符串转数字严格解析并检查范围；数字互转使用 Rust `as`，浮点转整数截断，整数缩窄可能回绕。数字转字符串使用 Rust `to_string`，不使用显示用的四位小数格式。[`convert_between_types`](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/files/table/mod.rs#L846)、[实际 Boolean parser](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/utils.rs#L64)

新字段默认值为空时数值为零、Boolean 为 false、字符串为空、Sequence 为零行；非法数值默认值回落为零。上游 `new_from_type_and_value` 存在两个边界：Optional 整数在 `Some(default)` 分支返回普通整数变体；无默认颜色返回空串而非 `000000`。管理器应写正确目标类型并确保颜色可编码，不复制这些变体缺陷。[默认值工厂](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/files/table/mod.rs#L648)

RPFM 匹配的是 `fields_processed()`：位域拆为 `name_1...name_N` Boolean，枚举先按标签转换为字符串，RGB 分量合成颜色，numeric patch 可将字段转换为整数。直接对 raw fields 操作可实现相同普通字段行为，但当这些 metadata 改变时应实现对应语义，或明确跳过，避免旧枚举编号被解释成新含义。[字段预处理](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/schema/mod.rs#L1338)

Sequence 在上游只保存 opaque blob，更新不递归迁移嵌套 Definition：U16/U32 互转只改 count 前缀，同宽复制 blob。管理器如支持嵌套变化，必须递归解码、匹配、编码并检查 count 范围；否则跳过嵌套结构改变的表。`localised_fields` 是生成 LOC 的 metadata，普通 DB 的结构更新不调用 LOC 生成；已有 `.loc` 文件应原样保留。[Sequence 转换](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_lib/src/files/table/mod.rs#L988)、[独立 LOC 生成命令](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_extensions/src/dependencies/mod.rs#L2330)

## 集成与验证建议

v5.1.0 源码树已没有 `rpfm_cli`，GUI 更新通过 server 的 `Command::UpdateTable` 执行。把历史 CLI 可执行文件、RPFM GUI 安装路径或其服务当运行时依赖会增加版本耦合；原生 Python schema parser + Pack/DB codec 更适合此管理器。[源码树](https://github.com/Frodo45127/rpfm/tree/e8992600bf8ea86153e3e530985f8665ecfd301e)、[更新命令](https://github.com/Frodo45127/rpfm/blob/e8992600bf8ea86153e3e530985f8665ecfd301e/rpfm_server/src/background_thread.rs#L1730)

每个 Pack 先在内存迁移并用目标定义完整重读验证，再备份、原子替换；没有待更新表时不重写。未知表、未知旧版本、损坏表和无法确定原版目标应给出具体结果；不应猜字段布局。所有非 DB payload、依赖、Pack 类型和用户选中 MOD 顺序需要保留。批量操作可逐 Pack 提交，某个 Pack 的失败不阻止其他可更新 Pack。

必要测试包括：列重排/增删/重命名，类型转换成功与失败默认，schema patch 默认，无版本的多候选完整解码，GUID/mysterious byte 保留，UTF-16 非 BMP 字符，Optional 数字 false sentinel，Optional 空串，ColourRGB，Sequence 嵌套变更/数量上限，未知表不改写，原版版本低于网络 schema，LOC/非 DB 字节保留，同次批量快照固定，以及重复更新无字节变化。本次已从固定官方提交实际获取全部 11 个 RON；TOB/Attila/Rome2 有 SequenceU32，Pharaoh/Dynasties 有 OptionalI64，不能仅凭 WH3 fixture 判断全游戏支持。此快照的非空枚举/位域字段/numeric patch 均为零，但每个游戏都有颜色组字段（60–108 个），相同颜色 raw 布局可以正常保留；布局改变时才需额外转换。

## 本次实现与验证

右键入口支持单个与多选 MOD，一次 RPC 使用同一游戏 schema 快照。每个 Pack 独立提交，失败不阻止后续 Pack；原文件备份至管理器数据目录 `backups/table-schemas/<game_id>/`。结果面板列出更新、无须更新、未完全更新及失败，并显示备份路径、跳过原因和无法转换后采用默认值的数量。完整 schema 每次联网校验 ETag，网络不可用时明确提示使用缓存。未知表原样保留，已知表解码失败或复杂颜色/枚举/嵌套布局不兼容时不改动该 Pack。整数缩窄越界采用目标默认值并报告，避免静默回绕。

2026-10-01 验证：11 个游戏的完整官方 RON 均可解析；WH3 实时获取 1742 个表定义并通过第二次联网缓存校验。读取当前安装游戏的原版 Pack，在临时副本中验证 `building_levels_tables` v2→v3、`land_units_tables` v53→v54、`main_units_tables` v6→v7，迁移后完整解码成功，非 DB 内容保持原样。

相关后端回归 98 项通过（另有 63 个 subtests），前端 85 项通过，Ruff 和 Vite 构建通过。后端扩展回归在模拟游戏未运行的环境中执行，避免用户当前运行的游戏影响既有工坊测试；新增测试单独覆盖真实运行状态的拦截。验证没有修改用户的实际 MOD 或游戏数据。
