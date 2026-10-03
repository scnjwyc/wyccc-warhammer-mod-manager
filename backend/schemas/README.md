# 内置 RPFM 表结构

中文界面的「更新表结构」直接读取这里的完整定义，不发起网络请求，也不要求用户已有缓存。压缩文件保留上游 RON 原文，包括旧版本定义；具体来源提交、原文 SHA-256 与表数量见 `manifest.json`。目标表版本仍从玩家安装的游戏原版 Pack 确定。

定义来自 https://github.com/Frodo45127/rpfm-schemas，MIT 许可证原文保存在 `LICENSE.txt`，与资源一起包含在 EXE 中。

维护时先确认上游提交，再在仓库根目录运行：

```powershell
python scripts/update_bundled_schemas.py --revision <完整的上游提交SHA>
```

刷新后运行 `python -m pytest tests/test_schema_update.py`。内置定义随管理器版本更新；如果游戏表版本超出这份快照支持的范围，程序会停止更新并提示定义不支持该版本。
