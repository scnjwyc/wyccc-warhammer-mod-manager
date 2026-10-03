param(
    [string]$OutputDir = "",
    [switch]$SkipInstall,
    [switch]$SkipTests,
    [switch]$CheckOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$transcriptStarted = $false
$buildLock = $null
$exitCode = 1

try {
    $logDir = Join-Path $root "build\logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $logPath = Join-Path $logDir "release-$(Get-Date -Format 'yyyyMMdd-HHmmss')-$PID.log"
    Start-Transcript -Path $logPath | Out-Null
    $transcriptStarted = $true
    Write-Host "Build log: $logPath"
    # Prevent two desktop shortcut clicks from sharing PyInstaller output.
    $buildLock = [System.IO.File]::Open(
        (Join-Path $root "build\release.lock"), [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None
    )
    . (Join-Path $PSScriptRoot "windows_bootstrap.ps1")
    if (-not $OutputDir) {
        if ($env:WMM_OUTPUT_DIR) {
            $OutputDir = $env:WMM_OUTPUT_DIR
        }
        else {
            $OutputDir = "G:\Wyccc's Mod Manager"
        }
    }
    $OutputDir = [System.IO.Path]::GetFullPath($OutputDir)

    $python = Get-WmmPython -Root $root -IncludeBuildTools
    $pnpm = Get-WmmPnpm -Root $root
    Write-Host "Python: $python"
    Write-Host "Node.js: $env:WMM_NODE"
    Write-Host "pnpm: $pnpm"
    if ($CheckOnly) {
        Write-Host "Build prerequisites are ready. No release was packaged."
        $exitCode = 0
    }
    else {
        $arguments = @((Join-Path $root "scripts\build.py"), "--package", "--output-dir", $OutputDir)
        if ($SkipInstall) {
            $arguments += "--skip-install"
        }
        if ($SkipTests) {
            $arguments += "--skip-tests"
        }

        Write-Host "Building release into: $OutputDir"
        Invoke-WmmCommand -FilePath $python -ArgumentList $arguments -WorkingDirectory $root

        $executable = Join-Path $OutputDir "Wyccc's Mod Manager.exe"
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            throw "Build completed without the expected executable: $executable"
        }
        Write-Host "Release ready: $executable"
        $exitCode = 0
    }
}
catch {
    Write-Host "WMM release build failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ScriptStackTrace) { Write-Host $_.ScriptStackTrace -ForegroundColor DarkRed }
}
finally {
    if ($buildLock) { $buildLock.Dispose() }
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
        Write-Host "Build log saved: $logPath"
    }
}
exit $exitCode
