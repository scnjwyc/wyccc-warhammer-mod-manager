# Wyccc's Mod Manager 项目规则

- 只有使用 GPT5.6 Sol 以外的模型时才使用 superpower。
- 修改本项目时，只更新 `G:\git\wyccc-warhammer-mod-manager` 内的源码、测试和文档。
- 默认不得运行发布打包流程，也不得写入 `G:\Wyccc's Mod Manager`；只有用户明确要求打包或发布某个版本时，才视为对该版本的打包脚本、发布目录、Git 提交、Tag 和 Release 操作的授权。
- 获得版本发布授权后，只能使用项目内既有发布脚本，并且只处理该版本所需的源码、测试、文档、正式清单和 `G:\Wyccc's Mod Manager\Wyccc's Mod Manager.exe`，不得把发布范围扩大到其他用户文件。
- 任何设计文本的修改，都需要同步修改多语言文件，确保所有内置语言的对应文本保持一致。

## 分支默认规则

- 在没有特别强调或明确指定其他分支的情况下，所有代码修改默认直接放到主分支（`main`）。
