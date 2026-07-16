Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-WmmCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = ""
    )

    if ($WorkingDirectory) {
        Push-Location -LiteralPath $WorkingDirectory
    }
    try {
        # Windows PowerShell turns native stderr into error records.  With the
        # script-wide Stop preference that used to abort on the first stderr
        # line (usually just "Traceback") before we could inspect the exit
        # code.  Let the native program print its complete diagnostic, then
        # convert a non-zero exit code into one clear PowerShell exception.
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $FilePath @ArgumentList | Out-Host
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($exitCode -ne 0) {
            throw "Command failed with exit code ${exitCode}: $FilePath"
        }
    }
    finally {
        if ($WorkingDirectory) {
            Pop-Location
        }
    }
}

function Test-WmmPythonImports {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Probe
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Python -c $Probe *> $null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function New-WmmVirtualEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$VenvPath
    )

    $launchers = @()
    $pythonOverride = if ($env:WMM_PYTHON) {
        $env:WMM_PYTHON
    }
    elseif ($env:WWM_PYTHON) {
        $env:WWM_PYTHON
    }
    else {
        $env:WWMM_PYTHON
    }
    if ($pythonOverride) {
        $launchers += ,@($pythonOverride)
    }
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($py) {
        $launchers += ,@($py.Source, "-3")
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python) {
        $launchers += ,@($python.Source)
    }
    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
        $launchers += ,@($bundledPython)
    }

    foreach ($launcher in $launchers) {
        $executable = $launcher[0]
        $prefix = @($launcher | Select-Object -Skip 1)
        & $executable @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            continue
        }
        Invoke-WmmCommand -FilePath $executable -ArgumentList ($prefix + @("-m", "venv", $VenvPath)) -WorkingDirectory $Root
        return
    }

    throw "Python 3.11 or newer was not found. Install Python, or set WMM_PYTHON to python.exe."
}

function Initialize-WmmNode {
    $candidates = @()
    $nodeOverride = if ($env:WMM_NODE) {
        $env:WMM_NODE
    }
    elseif ($env:WWM_NODE) {
        $env:WWM_NODE
    }
    else {
        $env:WWMM_NODE
    }
    if ($nodeOverride) {
        $candidates += $nodeOverride
    }
    $node = Get-Command "node.exe" -ErrorAction SilentlyContinue
    if ($node) {
        $candidates += $node.Source
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "nodejs\node.exe")
    }
    $candidates += (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            continue
        }
        $nodeDirectory = Split-Path -Parent $candidate
        if (($env:Path -split ";") -notcontains $nodeDirectory) {
            $env:Path = "$nodeDirectory;$env:Path"
        }
        return $candidate
    }
    throw "Node.js 22 or newer was not found. Install Node.js, or set WMM_NODE to node.exe."
}

function Get-WmmPython {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$IncludeBuildTools
    )

    $venvPath = Join-Path $Root ".venv-build"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host "Creating Python environment: $venvPath"
        New-WmmVirtualEnvironment -Root $Root -VenvPath $venvPath
    }

    $probe = if ($IncludeBuildTools) {
        "import webview, PyInstaller, PIL, lz4.frame, zstandard, watchdog.observers"
    }
    else {
        "import webview, lz4.frame, zstandard, watchdog.observers"
    }
    if (-not (Test-WmmPythonImports -Python $venvPython -Probe $probe)) {
        $projectRequirement = if ($IncludeBuildTools) { "${Root}[build]" } else { $Root }
        Write-Host "Installing required Python packages..."
        Invoke-WmmCommand -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "-e", $projectRequirement) -WorkingDirectory $Root
    }

    if (-not (Test-WmmPythonImports -Python $venvPython -Probe $probe)) {
        throw "The required Python packages could not be imported from $venvPython."
    }
    return $venvPython
}

function Get-WmmPnpm {
    Initialize-WmmNode | Out-Null

    $pnpmOverride = if ($env:WMM_PNPM) {
        $env:WMM_PNPM
    }
    elseif ($env:WWM_PNPM) {
        $env:WWM_PNPM
    }
    else {
        $env:WWMM_PNPM
    }
    if ($pnpmOverride) {
        if (Test-Path -LiteralPath $pnpmOverride -PathType Leaf) {
            $env:Path = "$(Split-Path -Parent $pnpmOverride);$env:Path"
            return $pnpmOverride
        }
        throw "WMM_PNPM does not point to a file: $pnpmOverride"
    }

    foreach ($name in @("pnpm.cmd", "pnpm")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    $fallbacks = @(
        (Join-Path $env:APPDATA "npm\pnpm.cmd"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd")
    )
    foreach ($fallback in $fallbacks) {
        if (Test-Path -LiteralPath $fallback -PathType Leaf) {
            $env:Path = "$(Split-Path -Parent $fallback);$env:Path"
            return $fallback
        }
    }
    throw "pnpm was not found. Install Node.js 22+ and pnpm 11+, or set WMM_PNPM."
}
