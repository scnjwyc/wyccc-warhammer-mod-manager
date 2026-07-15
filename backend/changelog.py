from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_CHANGELOG_LANGUAGE = "zh-CN"
SUPPORTED_CHANGELOG_LANGUAGES = frozenset({"zh-CN", "en-US", "ko-KR", "ru-RU", "ja-JP"})

CHANGELOG_STRUCTURE: tuple[dict[str, Any], ...] = (
    {
        "version": "0.5.0",
        "date": "2026-07-15",
        "entries": (
            (
                "v050_settings_title",
                (
                    ("feature", "v050_settings_pages"),
                    ("feature", "v050_about_page"),
                ),
            ),
            (
                "v050_startup_title",
                (
                    ("feature", "v050_restore_last_order"),
                    ("feature", "v050_drag_lists"),
                    ("improvement", "v050_button_style"),
                ),
            ),
            (
                "v050_workshop_title",
                (
                    ("feature", "v050_publish_language"),
                    ("feature", "v050_change_note"),
                    ("feature", "v050_share_subscribe"),
                ),
            ),
            (
                "v050_language_title",
                (
                    ("feature", "v050_system_language"),
                    ("feature", "v050_builtin_languages"),
                    ("improvement", "v050_single_language_ui"),
                ),
            ),
            (
                "v050_warning_title",
                (
                    ("fix", "v050_outdated_check"),
                    ("improvement", "v050_enabled_dependency_scope"),
                    ("improvement", "v050_dependency_cache_warning"),
                ),
            ),
            (
                "v050_docs_title",
                (
                    ("improvement", "v050_readme"),
                ),
            ),
        ),
    },
    {
        "version": "0.3.0",
        "date": "2026-07-15",
        "entries": (
            (
                "v030_title",
                (
                    ("fix", "v030_data_location"),
                    ("feature", "v030_ignore_issues"),
                    ("feature", "v030_warning_window"),
                ),
            ),
        ),
    },
    {
        "version": "0.2.0",
        "date": "2026-07-15",
        "entries": (
            (
                "v020_title",
                (
                    ("feature", "v020_dual_source"),
                    ("feature", "v020_context_menu"),
                    ("fix", "v020_pyinstaller"),
                ),
            ),
        ),
    },
    {
        "version": "0.1.0",
        "date": "2026-07-15",
        "entries": (
            (
                "v010_title",
                (
                    ("feature", "v010_playsets"),
                    ("feature", "v010_game_workshop"),
                    ("feature", "v010_updates"),
                ),
            ),
        ),
    },
)


CHANGELOG_TEXT: dict[str, dict[str, str]] = {
    "zh-CN": {
        "v050_settings_title": "设置与关于项目",
        "v050_settings_pages": "设置界面拆分为基础设置、功能（游戏启动增强）、AI 集成和关于项目四个分页。",
        "v050_about_page": "新增关于项目页，集中显示版本与更新信息；下载入口仅指向 GitHub、Gitee 发布页，反馈与交流提供 GitHub Issues 和 QQ 群 592799189。",
        "v050_startup_title": "启动恢复与列表操作",
        "v050_restore_last_order": "首次启动时自动读取 Warhammer III 上次使用的 used_mods.txt，仅按本机已安装 MOD 恢复启用状态与加载顺序，不会下载或订阅缺失 MOD。",
        "v050_drag_lists": "已启用与未启用 MOD 均支持单项或 Ctrl、Shift 批量拖拽；可在两栏之间移动，已启用顺序即时保存，未启用顺序仅在本次运行中保留。",
        "v050_button_style": "统一打开目录、重新扫描、刷新工坊信息和打开游戏目录等按钮样式，并将页面入口统一命名为“创意工坊页面”。",
        "v050_workshop_title": "创意工坊发布与分享码导入",
        "v050_publish_language": "发布 MOD 更新时可选择语言，默认使用当前界面语言；切换语言后自动载入对应的创意工坊标题与描述，只有英文简介时自动使用英文。",
        "v050_change_note": "将“更新说明”调整为默认为空的“更新日志”，并通过本地 Steamworks 补丁写入所选发布语言。",
        "v050_share_subscribe": "分享码导入会列出未订阅的 MOD，在用户确认后自动订阅，并在下载完成、重新扫描后还原到播放集。",
        "v050_language_title": "内置多语言",
        "v050_system_language": "首次启动时根据系统语言自动选择简体中文、英语、韩语、俄语或日语；检测失败或系统语言不受支持时默认使用英语。",
        "v050_builtin_languages": "界面与更新日志现已内置简体中文、英语、韩语、俄语和日语。",
        "v050_single_language_ui": "统一各语言下的按钮、标题、状态与提示文本，避免界面混用其他语言。",
        "v050_warning_title": "警告检测与提示修复",
        "v050_outdated_check": "修复过期 MOD 检查的时间比较方向错误；现在仅当 MOD 在游戏本体更新后尚未更新时提示，同步更新说明文本，并兼容旧版忽略记录。",
        "v050_enabled_dependency_scope": "缺失依赖警告现在只检查已启用 MOD；启用、停用、排序、跨栏拖放、切换播放集或导入后都会立即重新检测。",
        "v050_dependency_cache_warning": "当 Steam 暂时无法读取部分创意工坊依赖时，明确说明正在使用缓存且缺失依赖结果可能不是最新状态，并允许在本次运行中忽略该提示。",
        "v050_docs_title": "文档与项目说明",
        "v050_readme": "重写 README 的用户功能介绍，精简不必要的实现细节，并补充 Warhammer Mod Manager 与 RimCrow 的致谢。",
        "v030_title": "问题管理与文件定位",
        "v030_data_location": "修复 Data 目录中的 MOD 无法在资源管理器中准确定位 Pack 文件的问题。",
        "v030_ignore_issues": "右键菜单新增“忽略问题”，支持按 MOD 忽略或恢复过期与缺失依赖警告。",
        "v030_warning_window": "将警告入口移到“已启用 MOD”标题栏中央，并新增可逐条忽略问题的居中窗口。",
        "v020_title": "更新与批量操作",
        "v020_dual_source": "支持按当前语言优先检查 Gitee 或 GitHub，并在双源间自动回退。",
        "v020_context_menu": "右键菜单新增“打开文件目录”；批量选择时显示操作数量，并禁用 RPFM 单项操作。",
        "v020_pyinstaller": "修复产品名称含撇号时 PyInstaller 一键打包失败的问题。",
        "v010_title": "管理器基础功能",
        "v010_playsets": "使用播放集管理 MOD 启用状态与加载顺序，所有修改即时保存。",
        "v010_game_workshop": "支持继续游戏、从存档列表载入、Workshop 管理与依赖缺失警告。",
        "v010_updates": "支持自动检查新版本、下载校验、安全替换以及应用内更新日志。",
    },
    "en-US": {
        "v050_settings_title": "Settings and About",
        "v050_settings_pages": "Settings are divided into Basic, Features (game launch enhancements), AI Integration, and About pages.",
        "v050_about_page": "Added an About page with version and update information. Downloads link only to the GitHub and Gitee release pages, while feedback and discussion use GitHub Issues and QQ group 592799189.",
        "v050_startup_title": "Startup recovery and list controls",
        "v050_restore_last_order": "On first launch, the manager reads Warhammer III's last used_mods.txt and restores enabled state and load order for locally installed MODs only; missing MODs are never downloaded or subscribed automatically.",
        "v050_drag_lists": "Enabled and inactive MODs support single, Ctrl, and Shift batch dragging. MODs can move between lists; enabled order saves instantly, while inactive order lasts for the current session only.",
        "v050_button_style": "Unified the styles of directory, rescan, Workshop refresh, and game-directory actions, and consistently named the page entry Workshop Page.",
        "v050_workshop_title": "Workshop publishing and share-code import",
        "v050_publish_language": "Choose a language when publishing a MOD update, defaulting to the current interface language. Changing language loads the corresponding Workshop title and description, with automatic English fallback when only English content exists.",
        "v050_change_note": "Renamed Update Notes to an initially empty Update Log and added the selected publishing language through the local Steamworks patch.",
        "v050_share_subscribe": "Share-code import lists unsubscribed MODs, subscribes after confirmation, and restores them to the playset after download and rescan.",
        "v050_language_title": "Built-in languages",
        "v050_system_language": "On first launch, the interface follows the system language when it is Simplified Chinese, English, Korean, Russian, or Japanese; detection failures and unsupported languages default to English.",
        "v050_builtin_languages": "The interface and changelog now include Simplified Chinese, English, Korean, Russian, and Japanese.",
        "v050_single_language_ui": "Unified buttons, headings, status text, and prompts so the selected interface language is not mixed with other languages.",
        "v050_warning_title": "Warning detection and messaging fixes",
        "v050_outdated_check": "Fixed the reversed timestamp comparison in outdated-MOD detection. A warning now appears only when a MOD has not been updated since the game update; the help text was clarified and previous ignore records remain compatible.",
        "v050_enabled_dependency_scope": "Missing-dependency warnings now apply only to enabled MODs and are recomputed immediately after enabling, disabling, reordering, cross-list dragging, switching playsets, or importing.",
        "v050_dependency_cache_warning": "When Steam temporarily cannot read some Workshop dependencies, the manager now explains that cached data is in use and missing-dependency results may be stale, and the notice can be ignored for the current session.",
        "v050_docs_title": "Documentation and project information",
        "v050_readme": "Reworked the README around user-facing features, removed unnecessary implementation detail, and added acknowledgements for Warhammer Mod Manager and RimCrow.",
        "v030_title": "Issue management and file location",
        "v030_data_location": "Fixed locating Pack files for MODs stored in Data from File Explorer.",
        "v030_ignore_issues": "Added Ignore Issue to the context menu, allowing outdated and missing-dependency warnings to be ignored or restored per MOD.",
        "v030_warning_window": "Moved the warning entry to the center of the Enabled MODs heading and added a centered window for ignoring individual issues.",
        "v020_title": "Updates and batch actions",
        "v020_dual_source": "Added language-aware update priority between Gitee and GitHub with automatic fallback.",
        "v020_context_menu": "Added Open File Location to the context menu; batch selections show their item count and disable the single-item RPFM action.",
        "v020_pyinstaller": "Fixed one-click PyInstaller packaging when the product name contains an apostrophe.",
        "v010_title": "Core manager features",
        "v010_playsets": "Manage enabled MODs and load order with playsets; every change is saved immediately.",
        "v010_game_workshop": "Supports continuing games, loading from the save list, Workshop management, and missing-dependency warnings.",
        "v010_updates": "Supports automatic update checks, verified downloads, safe replacement, and an in-app changelog.",
    },
    "ko-KR": {
        "v050_settings_title": "설정 및 프로젝트 정보",
        "v050_settings_pages": "설정을 기본 설정, 기능(게임 실행 향상), AI 통합 및 프로젝트 정보의 네 페이지로 나눴습니다.",
        "v050_about_page": "버전과 업데이트 정보를 한곳에 제공하는 프로젝트 정보 페이지를 추가했습니다. 다운로드는 GitHub와 Gitee 릴리스 페이지만 연결하며, 피드백과 소통은 GitHub Issues와 QQ 그룹 592799189를 이용합니다.",
        "v050_startup_title": "시작 복원 및 목록 조작",
        "v050_restore_last_order": "처음 실행할 때 Warhammer III의 마지막 used_mods.txt를 읽고 로컬에 설치된 MOD의 활성 상태와 로드 순서만 복원합니다. 누락된 MOD를 다운로드하거나 구독하지 않습니다.",
        "v050_drag_lists": "활성 및 비활성 MOD 목록 모두 단일, Ctrl, Shift 일괄 드래그를 지원합니다. 목록 사이로 이동할 수 있으며 활성 순서는 즉시 저장되고 비활성 순서는 현재 실행 중에만 유지됩니다.",
        "v050_button_style": "폴더 열기, 다시 검색, 창작마당 정보 새로 고침, 게임 폴더 열기 등의 버튼 스타일을 통일하고 페이지 항목 이름을 창작마당 페이지로 통일했습니다.",
        "v050_workshop_title": "창작마당 게시 및 공유 코드 가져오기",
        "v050_publish_language": "MOD 업데이트 게시 언어를 선택할 수 있으며 기본값은 현재 인터페이스 언어입니다. 언어를 바꾸면 해당 창작마당 제목과 설명을 불러오며 영어 내용만 있으면 영어를 자동 사용합니다.",
        "v050_change_note": "업데이트 설명을 기본적으로 비어 있는 업데이트 로그로 바꾸고 로컬 Steamworks 패치를 통해 선택한 게시 언어를 기록합니다.",
        "v050_share_subscribe": "공유 코드 가져오기에서 미구독 MOD를 표시하고 확인 후 자동 구독하며 다운로드와 재검색 후 플레이 세트에 복원합니다.",
        "v050_language_title": "내장 다국어",
        "v050_system_language": "처음 실행할 때 시스템 언어가 중국어 간체, 영어, 한국어, 러시아어 또는 일본어이면 자동으로 적용하며, 감지에 실패하거나 지원하지 않는 언어이면 영어를 기본값으로 사용합니다.",
        "v050_builtin_languages": "인터페이스와 변경 내역에 중국어 간체, 영어, 한국어, 러시아어 및 일본어를 내장했습니다.",
        "v050_single_language_ui": "선택한 인터페이스 언어에 다른 언어가 섞이지 않도록 버튼, 제목, 상태 및 알림 문구를 통일했습니다.",
        "v050_warning_title": "경고 감지 및 안내 수정",
        "v050_outdated_check": "오래된 MOD 검사에서 시간 비교 방향이 반대로 적용되던 문제를 수정했습니다. 이제 게임 업데이트 후 MOD가 갱신되지 않은 경우에만 경고하며, 도움말을 명확히 하고 이전 무시 기록도 계속 호환합니다.",
        "v050_enabled_dependency_scope": "누락 종속성 경고는 이제 활성 MOD만 검사하며, 활성화, 비활성화, 순서 변경, 목록 간 드래그, 플레이 세트 전환 또는 가져오기 후 즉시 다시 검사합니다.",
        "v050_dependency_cache_warning": "Steam에서 일부 창작마당 종속성을 일시적으로 읽지 못하면 캐시 사용 중이며 누락 종속성 결과가 최신이 아닐 수 있음을 명확히 안내하고, 현재 실행 중에는 해당 알림을 무시할 수 있습니다.",
        "v050_docs_title": "문서 및 프로젝트 정보",
        "v050_readme": "README를 사용자 기능 중심으로 다시 정리하고 불필요한 구현 세부 정보를 줄였으며 Warhammer Mod Manager와 RimCrow에 대한 감사를 추가했습니다.",
        "v030_title": "문제 관리 및 파일 위치",
        "v030_data_location": "Data 폴더의 MOD Pack 파일을 파일 탐색기에서 정확히 찾지 못하던 문제를 수정했습니다.",
        "v030_ignore_issues": "컨텍스트 메뉴에 문제 무시를 추가하여 MOD별로 오래됨 및 누락된 종속성 경고를 무시하거나 복원할 수 있습니다.",
        "v030_warning_window": "경고 항목을 활성 MOD 제목 중앙으로 옮기고 개별 문제를 무시할 수 있는 중앙 창을 추가했습니다.",
        "v020_title": "업데이트 및 일괄 작업",
        "v020_dual_source": "현재 언어에 따라 Gitee 또는 GitHub를 우선 확인하고 자동 대체하도록 했습니다.",
        "v020_context_menu": "컨텍스트 메뉴에 파일 위치 열기를 추가했습니다. 일괄 선택 시 항목 수를 표시하고 단일 항목 RPFM 작업을 비활성화합니다.",
        "v020_pyinstaller": "제품 이름에 아포스트로피가 있을 때 PyInstaller 원클릭 패키징이 실패하는 문제를 수정했습니다.",
        "v010_title": "관리자 기본 기능",
        "v010_playsets": "플레이 세트로 MOD 활성 상태와 로드 순서를 관리하며 모든 변경을 즉시 저장합니다.",
        "v010_game_workshop": "게임 계속하기, 저장 목록 불러오기, 창작마당 관리 및 누락된 종속성 경고를 지원합니다.",
        "v010_updates": "자동 업데이트 확인, 다운로드 검증, 안전한 교체 및 앱 내 변경 내역을 지원합니다.",
    },
    "ru-RU": {
        "v050_settings_title": "Настройки и сведения о проекте",
        "v050_settings_pages": "Настройки разделены на четыре страницы: основные, функции запуска игры, интеграция ИИ и сведения о проекте.",
        "v050_about_page": "Добавлена страница проекта с версией и сведениями об обновлениях. Ссылки для загрузки ведут только на выпуски GitHub и Gitee, а для обратной связи доступны GitHub Issues и группа QQ 592799189.",
        "v050_startup_title": "Восстановление при запуске и управление списками",
        "v050_restore_last_order": "При первом запуске менеджер читает последний used_mods.txt Warhammer III и восстанавливает состояние и порядок только для установленных локально MOD, не загружая и не подписывая отсутствующие MOD.",
        "v050_drag_lists": "Списки включённых и отключённых MOD поддерживают одиночное и групповое перетаскивание с Ctrl или Shift. MOD можно переносить между списками; порядок включённых сохраняется сразу, а порядок отключённых — только на текущий сеанс.",
        "v050_button_style": "Унифицирован стиль кнопок открытия папок, повторного сканирования, обновления сведений Мастерской и открытия папки игры; название перехода к странице Мастерской также приведено к единому виду.",
        "v050_workshop_title": "Публикация в Мастерской и импорт кода",
        "v050_publish_language": "При обновлении MOD можно выбрать язык, по умолчанию совпадающий с языком интерфейса. Его смена загружает соответствующие название и описание Мастерской; если доступен только английский, он выбирается автоматически.",
        "v050_change_note": "Поле описания обновления заменено на изначально пустой журнал обновления; выбранный язык публикации передаётся через локальный патч Steamworks.",
        "v050_share_subscribe": "Импорт кода показывает MOD без подписки, подписывает их после подтверждения и восстанавливает в наборе после загрузки и повторного сканирования.",
        "v050_language_title": "Встроенные языки",
        "v050_system_language": "При первом запуске интерфейс автоматически использует системный язык, если это упрощённый китайский, английский, корейский, русский или японский; при ошибке определения и для неподдерживаемых языков используется английский.",
        "v050_builtin_languages": "Интерфейс и журнал изменений теперь доступны на упрощённом китайском, английском, корейском, русском и японском языках.",
        "v050_single_language_ui": "Тексты кнопок, заголовков, состояний и сообщений унифицированы, чтобы в интерфейсе не смешивались разные языки.",
        "v050_warning_title": "Исправления проверки и сообщений о проблемах",
        "v050_outdated_check": "Исправлено обратное сравнение времени при проверке устаревших MOD. Теперь предупреждение появляется только если MOD не обновлялся после обновления игры; пояснение уточнено, а прежние записи игнорирования остаются совместимыми.",
        "v050_enabled_dependency_scope": "Предупреждения об отсутствующих зависимостях теперь проверяются только для включённых MOD и сразу пересчитываются после включения, отключения, изменения порядка, перетаскивания между списками, смены набора или импорта.",
        "v050_dependency_cache_warning": "Если Steam временно не может прочитать часть зависимостей Мастерской, менеджер сообщает об использовании кеша и возможной неактуальности результатов; уведомление можно скрыть до конца текущего сеанса.",
        "v050_docs_title": "Документация и сведения о проекте",
        "v050_readme": "README переработан с акцентом на пользовательские функции, лишние технические подробности сокращены, а Warhammer Mod Manager и RimCrow добавлены в благодарности.",
        "v030_title": "Управление проблемами и расположение файлов",
        "v030_data_location": "Исправлено точное выделение Pack-файла MOD из папки Data в Проводнике.",
        "v030_ignore_issues": "В контекстное меню добавлено игнорирование устаревших MOD и отсутствующих зависимостей с возможностью восстановления для каждого MOD.",
        "v030_warning_window": "Кнопка предупреждений перенесена в центр заголовка включённых MOD; добавлено окно для игнорирования отдельных проблем.",
        "v020_title": "Обновления и групповые действия",
        "v020_dual_source": "Добавлен приоритет Gitee или GitHub по языку с автоматическим переходом на второй источник.",
        "v020_context_menu": "В контекстное меню добавлено открытие расположения файла; для группового выбора показывается число элементов и отключается одиночная операция RPFM.",
        "v020_pyinstaller": "Исправлена упаковка PyInstaller одним нажатием, когда имя продукта содержит апостроф.",
        "v010_title": "Основные функции менеджера",
        "v010_playsets": "Наборы управляют включением MOD и порядком загрузки; все изменения сохраняются сразу.",
        "v010_game_workshop": "Поддерживаются продолжение игры, загрузка из списка сохранений, управление Мастерской и предупреждения об отсутствующих зависимостях.",
        "v010_updates": "Поддерживаются автоматическая проверка обновлений, проверка загрузки, безопасная замена и журнал изменений в приложении.",
    },
    "ja-JP": {
        "v050_settings_title": "設定とプロジェクト情報",
        "v050_settings_pages": "設定画面を基本設定、機能（ゲーム起動の拡張）、AI 統合、プロジェクト情報の4ページに分割しました。",
        "v050_about_page": "バージョンと更新情報をまとめたプロジェクト情報ページを追加しました。ダウンロード先は GitHub と Gitee のリリースページだけにし、フィードバックと交流には GitHub Issues と QQ グループ 592799189 を案内します。",
        "v050_startup_title": "起動時の復元と一覧操作",
        "v050_restore_last_order": "初回起動時に Warhammer III が最後に使用した used_mods.txt を読み、ローカルにインストール済みの MOD だけを有効状態と読み込み順へ復元します。不足 MOD のダウンロードや購読は行いません。",
        "v050_drag_lists": "有効・無効の両 MOD 一覧で、単一および Ctrl・Shift による複数ドラッグに対応しました。一覧間の移動が可能で、有効順は即時保存、無効順は現在の実行中のみ保持します。",
        "v050_button_style": "フォルダーを開く、再スキャン、ワークショップ情報の更新、ゲームフォルダーを開くなどのボタンスタイルを統一し、ページ入口の名称もワークショップページに統一しました。",
        "v050_workshop_title": "ワークショップ公開と共有コードのインポート",
        "v050_publish_language": "MOD 更新の公開言語を選択でき、初期値には現在の表示言語を使用します。言語を切り替えると対応するワークショップタイトルと説明を読み込み、英語しかない場合は自動的に英語を使用します。",
        "v050_change_note": "更新説明を初期状態が空の更新ログに変更し、ローカル Steamworks パッチから選択した公開言語を書き込むようにしました。",
        "v050_share_subscribe": "共有コードのインポート時に未購読 MOD を表示し、確認後に自動購読します。ダウンロード後の再スキャンでプレイセットへ復元します。",
        "v050_language_title": "内蔵多言語",
        "v050_system_language": "初回起動時、システム言語が簡体字中国語、英語、韓国語、ロシア語、日本語のいずれかなら自動選択し、検出失敗または未対応言語の場合は英語を既定値にします。",
        "v050_builtin_languages": "画面と更新履歴に簡体字中国語、英語、韓国語、ロシア語、日本語を内蔵しました。",
        "v050_single_language_ui": "選択した表示言語に別の言語が混ざらないよう、ボタン、見出し、状態、通知文を統一しました。",
        "v050_warning_title": "警告判定と案内の修正",
        "v050_outdated_check": "古い MOD の判定で更新時刻の比較方向が逆だった問題を修正しました。ゲーム本体の更新後に MOD が更新されていない場合だけ警告し、説明文を明確化するとともに旧版の無視設定も引き継ぎます。",
        "v050_enabled_dependency_scope": "依存関係不足の警告は有効な MOD だけを対象とし、有効化、無効化、並べ替え、一覧間のドラッグ、プレイセット切り替え、インポートの直後に再判定するようにしました。",
        "v050_dependency_cache_warning": "Steam が一部のワークショップ依存関係を一時的に取得できない場合、キャッシュ使用中で依存関係不足の結果が最新でない可能性を明示し、今回の実行中は通知を無視できるようにしました。",
        "v050_docs_title": "ドキュメントとプロジェクト情報",
        "v050_readme": "README をユーザー向け機能中心に整理し、不要な実装詳細を減らし、Warhammer Mod Manager と RimCrow への謝辞を追加しました。",
        "v030_title": "問題管理とファイル位置",
        "v030_data_location": "Data フォルダー内の MOD の Pack ファイルをエクスプローラーで正確に選択できない問題を修正しました。",
        "v030_ignore_issues": "右クリックメニューに問題を無視する機能を追加し、MOD ごとに古さと依存関係不足の警告を無視・復元できます。",
        "v030_warning_window": "警告入口を有効な MOD の見出し中央へ移動し、個別の問題を無視できる中央ウィンドウを追加しました。",
        "v020_title": "更新と一括操作",
        "v020_dual_source": "現在の言語に応じて Gitee または GitHub を優先確認し、自動的に代替ソースへ切り替えるようにしました。",
        "v020_context_menu": "右クリックメニューにファイルの場所を開く操作を追加しました。複数選択時は件数を表示し、単一項目用の RPFM 操作を無効にします。",
        "v020_pyinstaller": "製品名にアポストロフィがある場合に PyInstaller のワンクリックパッケージが失敗する問題を修正しました。",
        "v010_title": "マネージャーの基本機能",
        "v010_playsets": "プレイセットで MOD の有効状態と読み込み順を管理し、すべての変更を即時保存します。",
        "v010_game_workshop": "ゲームの続行、セーブ一覧からの読み込み、ワークショップ管理、依存関係不足の警告に対応しました。",
        "v010_updates": "更新の自動確認、ダウンロード検証、安全な置換、アプリ内更新履歴に対応しました。",
    },
}


def _build_changelog(language: str) -> list[dict[str, Any]]:
    catalog = CHANGELOG_TEXT[language]
    releases: list[dict[str, Any]] = []
    for release in CHANGELOG_STRUCTURE:
        entries = []
        for title_key, changes_spec in release["entries"]:
            entries.append(
                {
                    "title": catalog[title_key],
                    "changes": [
                        {"type": change_type, "text": catalog[text_key]}
                        for change_type, text_key in changes_spec
                    ],
                }
            )
        releases.append(
            {
                "version": release["version"],
                "date": release["date"],
                "entries": entries,
            }
        )
    return releases


APP_CHANGELOG: list[dict[str, Any]] = _build_changelog(DEFAULT_CHANGELOG_LANGUAGE)


def get_all_changelogs(language: str = DEFAULT_CHANGELOG_LANGUAGE) -> list[dict[str, Any]]:
    """Return an isolated changelog in one of the built-in interface languages."""
    normalized = language if language in SUPPORTED_CHANGELOG_LANGUAGES else DEFAULT_CHANGELOG_LANGUAGE
    return deepcopy(_build_changelog(normalized))
