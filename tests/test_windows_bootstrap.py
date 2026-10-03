from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


BOOTSTRAP = Path(__file__).resolve().parents[1] / "scripts" / "windows_bootstrap.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(os.name != "nt" or not POWERSHELL, reason="Windows bootstrap")


def run_powershell(tmp_path, script):
    path = tmp_path / "probe.ps1"
    path.write_text(f". '{BOOTSTRAP}'\n{script}", encoding="utf-8-sig")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )


def test_build_installs_test_dependencies_when_missing(tmp_path):
    scripts = tmp_path / ".venv-build" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").touch()
    result = run_powershell(tmp_path, f"""
$script:installed = $false
function Test-WmmPythonImports {{
    param($Python, $Probe)
    if ($Probe -match 'sys.version_info') {{ return $true }}
    if ($Probe -match 'pytest') {{ return $script:installed }}
    return $true
}}
function Invoke-WmmCommand {{
    param($FilePath, $ArgumentList, $WorkingDirectory)
    if ($ArgumentList -contains '{tmp_path}[build,dev]') {{ $script:installed = $true }}
}}
Get-WmmPython -Root '{tmp_path}' -IncludeBuildTools | Out-Null
if (-not $script:installed) {{ throw 'Release environment did not install pytest/dev dependencies' }}
"""
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_broken_python_environment_is_rebuilt(tmp_path):
    scripts = tmp_path / ".venv-build" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").touch()
    result = run_powershell(tmp_path, f"""
$script:rebuilt = $false
function Test-WmmPythonImports {{ param($Python, $Probe); return $script:rebuilt }}
function New-WmmVirtualEnvironment {{ param($Root, $VenvPath); $script:rebuilt = $true }}
function Invoke-WmmCommand {{ throw 'Attempted pip on a dead interpreter' }}
Get-WmmPython -Root '{tmp_path}' -IncludeBuildTools | Out-Null
if (-not $script:rebuilt) {{ throw 'Broken environment was not rebuilt' }}
"""
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pnpm_is_resolved_from_project_version_without_global_wrapper(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text(json.dumps({"packageManager": "pnpm@11.7.0"}))
    package = tmp_path / ".build-tools" / "pnpm" / "11.7.0" / "package"
    (package / "bin").mkdir(parents=True)
    (package / "bin" / "pnpm.cjs").write_text("console.log('11.7.0')")
    result = run_powershell(tmp_path, f"""
function Initialize-WmmNode {{ return 'node.exe' }}
$env:WMM_PNPM = ''; $env:WWM_PNPM = ''; $env:WWMM_PNPM = ''
$cli = Get-WmmPnpm -Root '{tmp_path}'
if ($cli -ne '{package / 'bin' / 'pnpm.cjs'}') {{ throw 'Used a global pnpm wrapper' }}
if ($env:WMM_PNPM -ne $cli) {{ throw 'Build subprocess cannot find the selected pnpm' }}
"""
    )
    assert result.returncode == 0, result.stdout + result.stderr
