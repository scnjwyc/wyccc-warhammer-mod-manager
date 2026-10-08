# 异常探针

设置 → 功能 → 异常探针，默认关闭。说明文本：

> 使用Memreader深入读取并记录异常片段，便于通过AI分析具体异常原因，日志位于游戏根目录，战锤3全面战争可用

订阅并下载 [Memreader Plus](https://steamcommunity.com/sharedfiles/filedetails/?id=3811098873)，在当前 MOD 列表中启用它，再开启探针。单独启用原版 Memreader 不满足依赖要求。设置会持久保存；依赖尚未就绪时可以保存开关，但探针不会生效。

使用内置功能时无需额外启用独立的 `wyccc_battle_probe.pack`。如果仍启用了独立探针 MOD，它由 MOD 列表单独控制；关闭设置中的内置探针不会关闭独立 MOD。两者共用单实例保护，避免重复采样。

用户通过启动器启动战锤3时，启动器检查本次实际启用列表、Plus 的 Workshop 源文件和 Steam 当前订阅状态，再把两份探针 Lua 加入现有运行时功能 Pack。无法确认订阅时跳过探针，仍可启动游戏并使用其它内置功能。依赖被禁用或下载文件消失后，下次启动会移除探针条目；在游戏未运行时保存关闭设置也会立即移除两份条目，同时保留其它内置功能。

目前复用已验证的战斗探针：每场战斗记录单位名册、原生地址、状态指针异常、Lua 回调和战斗心跳。探针只读游戏内存，不安装原生 hook、不写游戏内存。进入战斗后仍会检查 Plus 是否实际加载；缺失时跳过探针。原生读取仅对已核对的 WH3 9.0.2.0 可执行文件启用，其它版本保留脚本记录并记录版本不匹配。

日志在 `Warhammer3.exe` 所在的游戏根目录，使用 `wyccc_battle_probe_<日期时间>_<后缀>_roster.jsonl` 和同前缀的 `_trace1.jsonl` / `_trace2.jsonl` / `_trace3.jsonl`。每场事件日志最多轮换三份，每份约 4 MiB。出现异常时，将这些文件与同场 `memreader_crash_report_*.txt`、`script_log_*.txt`、minidump 一起交给 AI 分析。

启动器打包配置包含 `backend/resources/battle_probe`，Python 包也声明了这两份资源。源码核对与离线测试不代表已完成游戏内复测。
