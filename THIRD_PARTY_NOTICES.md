# Third-Party Notices

Wyccc's Mod Manager 的实现研究了以下开源项目。它们的许可证通知随本仓库保留，以明确原作者的权利；本项目自身的许可证见根目录 `LICENSE`。

## RimCrow

- 项目：https://github.com/Inky-Feather/RimCrow
- 本次研究所用本地版本：`20a69e522f15a34af52fb48e1f6b85ded110655e`
- 许可证：MIT License
- 版权所有：Copyright (c) 2026 RimCrow contributors
- 用途：桌面 MOD 管理器的信息组织、交互布局和前后端边界参考。
- 许可证原文：[licenses/RimCrow-LICENSE.txt](licenses/RimCrow-LICENSE.txt)

## WH3-Mod-Manager

- 项目：https://github.com/Shazbot/WH3-Mod-Manager
- 本次研究所用本地版本：`0011d479735a947eecedb0093e1e7570103e428d`
- 许可证：MIT License
- 版权所有：Copyright (c) 2022 Shazbot
- 用途：Warhammer III 的 Steam App ID、Pack 扫描、加载清单和启动流程参考。
- 许可证原文：[licenses/WH3-Mod-Manager-LICENSE.txt](licenses/WH3-Mod-Manager-LICENSE.txt)

## steamworks.js

- 项目：https://github.com/ceifa/steamworks.js
- 许可证：MIT License
- 版权所有：Copyright (c) 2022 Gabriel Francisco Dos Santos
- 用途：通过本机 Steamworks UGC 接口按语言读取 Workshop 标题、长描述和基础元数据。
- 原生模块取自上述 WH3-Mod-Manager 本地版本中随附的 steamworks.js 运行时。
- 许可证原文：[licenses/steamworks.js-LICENSE.txt](licenses/steamworks.js-LICENSE.txt)

上述项目的名称与版权归各自作者所有。列入本文件不表示原作者对 Wyccc's Mod Manager 提供背书。

## 包依赖

本项目还通过 Python 和 JavaScript 包管理器使用 pywebview、Vue、Pinia、Vite、Vitest、pytest、Ruff、PyInstaller 等第三方软件。它们分别受各自发布包中声明的许可证约束；依赖名称与版本范围以 `pyproject.toml`、`frontend/package.json` 和锁文件为准。本文件不是软件物料清单，也不会取代这些依赖随附的许可证文本。
