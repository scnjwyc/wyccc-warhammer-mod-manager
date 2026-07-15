param(
    [switch]$PrepareOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$frontend = Join-Path $root "frontend"
. (Join-Path $PSScriptRoot "windows_bootstrap.ps1")

try {
    $python = Get-WmmPython -Root $root
    $pnpm = Get-WmmPnpm

    Write-Host "Preparing the frontend..."
    Invoke-WmmCommand -FilePath $pnpm -ArgumentList @("install", "--frozen-lockfile") -WorkingDirectory $frontend
    Invoke-WmmCommand -FilePath $pnpm -ArgumentList @("build") -WorkingDirectory $frontend

    if ($PrepareOnly) {
        Write-Host "Desktop launch prerequisites are ready."
        exit 0
    }

    Write-Host "Starting Wyccc's Mod Manager..."
    Invoke-WmmCommand -FilePath $python -ArgumentList @((Join-Path $root "main.py")) -WorkingDirectory $root
    exit 0
}
catch {
    Write-Host "WMM startup failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ScriptStackTrace) {
        Write-Host $_.ScriptStackTrace -ForegroundColor DarkRed
    }
    exit 1
}
