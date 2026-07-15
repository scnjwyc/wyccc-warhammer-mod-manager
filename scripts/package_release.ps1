param(
    [string]$OutputDir = "",
    [switch]$SkipInstall,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
. (Join-Path $PSScriptRoot "windows_bootstrap.ps1")

try {
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
    Get-WmmPnpm | Out-Null
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
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
