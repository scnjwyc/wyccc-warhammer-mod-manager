# Steamworks Workshop bridge

此目录用于调用 Steam 客户端的 Workshop 能力。`workshop_bridge.js` 通过 steamworks.js
查询指定语言的标题和长描述、取消订阅、请求强制更新，并为用户明确选择的本地 MOD
创建或更新 Workshop 项目；更新前会比较项目所有者与当前本机 Steam 账号。Python 后端
通过标准输入/输出与它通信。

源码运行时使用 `WMM_STEAMWORKS_NODE`、`WMM_NODE` 或 `PATH` 中的 Node.js。旧版
`WWM_*`、`WWMM_*` 环境变量仍可兼容读取。发布打包
流程会将构建时检测到的 `node.exe` 一并放入 PyInstaller 单文件程序，不要求发布版用户
另行安装 Node.js。

`steamworks/` 中的原生模块来自本项目研究使用的 WH3-Mod-Manager 本地版本，其上游为
[steamworks.js](https://github.com/ceifa/steamworks.js)，许可证见
`../licenses/steamworks.js-LICENSE.txt`。
