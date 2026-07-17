# Runtime Data Directory Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop frozen builds from creating `data/` beside a Desktop EXE while preserving data from earlier portable releases.

**Architecture:** `resolve_runtime_data_dir()` will choose the normal user-data directory for frozen builds. When a legacy sibling `data/` exists and the user-data destination is absent or empty, a helper will copy it through a temporary staging directory and atomically activate the copy; any migration failure falls back to the source directory for that run.

**Tech Stack:** Python 3.12, `pathlib`, `shutil`, `tempfile`, `unittest`, PyInstaller.

## Global Constraints

- Never create `<EXE directory>/data` for a new frozen-build installation.
- Never delete the legacy portable data directory automatically.
- Never merge or overwrite an existing non-empty user-data directory.
- Preserve `--data-dir` and `WYCCC_MM_DATA_DIR`-family overrides.
- Do not rewrite the already published `0.6.5` tag.

---

### Task 1: Select and migrate the runtime data directory

**Files:**
- Modify: `tests/test_main.py:295-313`
- Modify: `main.py:3-9`
- Modify: `main.py:113-131`

**Interfaces:**
- Consumes: `backend.app_settings.default_data_dir() -> pathlib.Path`
- Produces: `_migrate_legacy_portable_data(portable: Path, destination: Path) -> Path`
- Produces: `resolve_runtime_data_dir(override: str = "") -> Path`

- [ ] **Step 1: Replace the portable-default test and add migration regression tests**

```python
def test_frozen_build_uses_user_data_without_creating_sibling_data(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        desktop = root / "Desktop"
        desktop.mkdir()
        executable = desktop / "Wyccc's Mod Manager.exe"
        user_data = root / "Roaming" / "WycccModManager"
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(executable)),
            patch.dict(os.environ, {}, clear=True),
            patch("main.default_data_dir", return_value=user_data),
        ):
            data_dir = resolve_runtime_data_dir()

        self.assertEqual(data_dir, user_data)
        self.assertFalse((desktop / "data").exists())

def test_frozen_build_migrates_existing_portable_data(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        desktop = root / "Desktop"
        portable = desktop / "data"
        portable.mkdir(parents=True)
        (portable / "settings.json").write_text('{"language":"zh-CN"}', encoding="utf-8")
        user_data = root / "Roaming" / "WycccModManager"
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(desktop / "Wyccc's Mod Manager.exe")),
            patch.dict(os.environ, {}, clear=True),
            patch("main.default_data_dir", return_value=user_data),
        ):
            data_dir = resolve_runtime_data_dir()

        self.assertEqual(data_dir, user_data)
        self.assertEqual(
            (user_data / "settings.json").read_text(encoding="utf-8"),
            '{"language":"zh-CN"}',
        )
        self.assertTrue((portable / "settings.json").is_file())

def test_existing_user_data_wins_over_portable_data(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        desktop = root / "Desktop"
        portable = desktop / "data"
        portable.mkdir(parents=True)
        (portable / "settings.json").write_text("portable", encoding="utf-8")
        user_data = root / "Roaming" / "WycccModManager"
        user_data.mkdir(parents=True)
        (user_data / "settings.json").write_text("user", encoding="utf-8")
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(desktop / "Wyccc's Mod Manager.exe")),
            patch.dict(os.environ, {}, clear=True),
            patch("main.default_data_dir", return_value=user_data),
        ):
            data_dir = resolve_runtime_data_dir()

        self.assertEqual(data_dir, user_data)
        self.assertEqual(
            (user_data / "settings.json").read_text(encoding="utf-8"),
            "user",
        )
        self.assertEqual(
            (portable / "settings.json").read_text(encoding="utf-8"),
            "portable",
        )

def test_failed_portable_migration_falls_back_to_portable_data(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        desktop = root / "Desktop"
        portable = desktop / "data"
        portable.mkdir(parents=True)
        (portable / "settings.json").write_text("portable", encoding="utf-8")
        user_data = root / "Roaming" / "WycccModManager"
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", str(desktop / "Wyccc's Mod Manager.exe")),
            patch.dict(os.environ, {}, clear=True),
            patch("main.default_data_dir", return_value=user_data),
            patch("main.shutil.copytree", side_effect=OSError("copy denied")),
        ):
            data_dir = resolve_runtime_data_dir()

        self.assertEqual(data_dir, portable)
        self.assertFalse(user_data.exists())
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv-build\Scripts\python.exe -m unittest `
  tests.test_main.PackagedRuntimeTests.test_frozen_build_uses_user_data_without_creating_sibling_data `
  tests.test_main.PackagedRuntimeTests.test_frozen_build_migrates_existing_portable_data `
  tests.test_main.PackagedRuntimeTests.test_existing_user_data_wins_over_portable_data `
  tests.test_main.PackagedRuntimeTests.test_failed_portable_migration_falls_back_to_portable_data -v
```

Expected: the first test fails because the current code returns and creates `<EXE directory>/data`; the migration tests fail because no migration helper exists.

- [ ] **Step 3: Implement staged migration and the new frozen-build default**

Add imports:

```python
import shutil
import tempfile
```

Add the helper and update directory resolution:

```python
def _migrate_legacy_portable_data(portable: Path, destination: Path) -> Path:
    if not portable.is_dir():
        return destination
    try:
        if destination.exists():
            if not destination.is_dir():
                return portable
            if any(destination.iterdir()):
                return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{destination.name}-portable-migration-",
            dir=destination.parent,
        ) as temporary:
            staged = Path(temporary) / destination.name
            shutil.copytree(portable, staged)
            if destination.exists():
                destination.rmdir()
            staged.replace(destination)
        return destination
    except OSError:
        return portable


def resolve_runtime_data_dir(override: str = "") -> Path:
    if override:
        return Path(override).expanduser().resolve(strict=False)
    destination = default_data_dir()
    has_data_override = any(
        os.environ.get(name)
        for name in (
            "WYCCC_MM_DATA_DIR",
            "WYCCC_WM_DATA_DIR",
            "WYCCC_WMM_DATA_DIR",
        )
    )
    if getattr(sys, "frozen", False) and not has_data_override:
        portable = Path(sys.executable).resolve().parent / "data"
        return _migrate_legacy_portable_data(portable, destination)
    return destination
```

- [ ] **Step 4: Run focused and full backend tests**

Run:

```powershell
.\.venv-build\Scripts\python.exe -m unittest tests.test_main -v
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: all tests pass, including the unchanged explicit-override test.

- [ ] **Step 5: Commit the runtime fix**

```powershell
git add main.py tests/test_main.py
git diff --cached --check
git commit -m "fix: keep runtime data off the desktop"
```

### Task 2: Document the new storage behavior and verify the tree

**Files:**
- Modify: `README.md:153-161`
- Modify: `README.en.md:153-161`

**Interfaces:**
- Consumes: the behavior implemented by `resolve_runtime_data_dir()`
- Produces: user-facing upgrade and cleanup guidance

- [ ] **Step 1: Update both local-data sections**

Replace the Chinese paragraph with:

```markdown
PyInstaller 发布结果只包含 EXE；发布版默认同样使用上述用户目录，因此从桌面直接运行不会再创建 `data/`。如果用户目录尚无数据而 EXE 同目录存在旧版 `data/`，首次启动会先将其完整复制到用户目录，旧目录会保留以便确认迁移结果后手动删除。命令行 `--data-dir` 和环境变量 `WYCCC_MM_DATA_DIR` 可显式覆盖。升级安装也会在新目录尚不存在时依次读取旧版 `%APPDATA%\WycccWarhammerManager\`、`%APPDATA%\WycccWarhammerModManager\`，避免丢失现有设置与播放集。
```

Replace the English paragraph with:

```markdown
The PyInstaller release contains only the EXE and uses the same per-user directory by default, so running it directly from the Desktop no longer creates `data/`. If the user directory has no data and an older sibling `data/` exists beside the EXE, the first launch copies it into the user directory while retaining the source for manual cleanup after verification. The `--data-dir` command-line option and `WYCCC_MM_DATA_DIR` environment variable can explicitly override this behavior. During an upgrade, if no data exists in the new location, the application also checks the legacy `%APPDATA%\WycccWarhammerManager\` and `%APPDATA%\WycccWarhammerModManager\` directories in order so existing settings and playsets are not lost.
```

- [ ] **Step 2: Run documentation and source verification**

Run:

```powershell
.\.venv-build\Scripts\ruff.exe check .
.\.venv-build\Scripts\python.exe -m compileall -q backend main.py tests
git diff --check
```

Expected: Ruff reports `All checks passed!`; compileall and diff-check exit successfully.

- [ ] **Step 3: Run frontend regression verification**

```powershell
$nodeBin = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin'
$env:Path = "$nodeBin;$env:Path"
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd' test
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd' build
```

Expected: 24 frontend files and 118 tests pass; Vite production build succeeds.

- [ ] **Step 4: Commit documentation**

```powershell
git add README.md README.en.md docs/superpowers/plans/2026-07-17-runtime-data-directory-migration.md
git diff --cached --check
git commit -m "docs: explain runtime data migration"
```

- [ ] **Step 5: Recheck release impact**

Confirm `git rev-list -n 1 0.6.5` still points to `02f0e7e045549b44523b8cbc7a00590c300a4e3d`, the new commits are not tagged as 0.6.5, and no remote release/tag is modified without a separate patch-release authorization.
