# Dynamic Variant Selector Patch

工坊文件：**wyccc_variant_selector_patch.pack**。

这是 Wyccc's Mod Manager 的订阅功能 MOD。管理器检测到工坊目录中的该文件后，默认开启动态 Variant Selector 适配；它不显示在管理器的 MOD 列表中，无需勾选或排序。兼容补丁面板可以关闭该功能。

使用条件：

- 使用包含本功能的 Wyccc's Mod Manager 启动《全面战争：战锤 III》。
- 订阅本 MOD，并启用 [Variant Selector](https://steamcommunity.com/sharedfiles/filedetails/?id=2888171970)。

启动游戏时，管理器读取原版、当前启用的 MOD 以及游戏自动加载的 Movie Pack，按实际 DB 覆盖关系解析角色外观。运行时为尚未适配的角色注册选择器，包括只有一套外观的角色。已有适配及其外观顺序保持不变，例如无双英灵录的手工适配。跳过断开的外观数据链及带有快速战斗、任务战斗标记的专用外观。

选定的外观按角色 CQI、角色类型及外观 ID 保存，读档和进入战斗时恢复；MOD 更新改变选项排序后仍按 ID 恢复。未选择过的角色保留游戏分配的初始外观。若已选外观被删除，则清除该选择。联机选择通过 Variant Selector 的同步事件处理，各玩家仍需使用一致的 MOD。

取消订阅、关闭功能或停用 Variant Selector 后，下次通过管理器启动游戏时会清理生成的兼容补丁。

## 构建及上传准备

在仓库根目录运行：

~~~powershell
.\.venv-build\Scripts\python.exe scripts\build_variant_selector_feature_mod.py
~~~

输出位于本目录。Pack 只包含功能标记；实际角色适配由管理器根据玩家启用的 MOD 生成，不复制 Variant Selector 的代码或素材。

封面源文件是 `scripts/build_variant_selector_cover.ps1`，成品为本目录的 `cover.png`（500×500），并同步为 Pack 同目录的 `wyccc_variant_selector_patch.png`。需要重新生成时运行：

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts\build_variant_selector_cover.ps1
~~~

上传时使用名称 **Dynamic Variant Selector Patch**，并将 Variant Selector（工坊 ID 2888171970）列为必需物品。feature.json 是源元数据，不会自动创建工坊物品。本目录的构建命令不会上传工坊，也不会构建或部署管理器程序。

## 验证范围

自动化测试覆盖 DB 覆盖优先级、单外观角色、无效引用、已有适配保留、存档重排恢复、订阅门槛和补丁清理。Lua 模拟验证同步选择与战斗恢复；游戏内按钮显示、战役/战斗模型效果及真实联机仍需实测。

本地原版 DB 和无双英灵录的样本验证得到 614 个候选角色类型。加载 Variant Selector 原有注册表和无双英灵录手工注册表后，实际新增 306 个缺失适配，所有已有注册保持不变。盖娅、关银屏、黄月英、纳巴特均获得注册，步练师仍保留原来的四套外观。数量取决于游戏数据版本和当前启用的 MOD。
