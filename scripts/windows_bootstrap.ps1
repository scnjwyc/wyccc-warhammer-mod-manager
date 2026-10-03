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
        if ($FilePath -match '\.(cjs|mjs|js)$') {
            $ArgumentList = @($FilePath) + $ArgumentList
            $FilePath = Initialize-WmmNode
        }
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
    catch { return $false }
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
        try {
            $previousPreference = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & $executable @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
            if ($LASTEXITCODE -ne 0) { continue }
        }
        catch { continue }
        finally { $ErrorActionPreference = $previousPreference }
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
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $candidate -e "process.exit(Number(process.versions.node.split('.')[0]) >= 22 ? 0 : 1)" *> $null
            if ($LASTEXITCODE -ne 0) { continue }
        }
        catch { continue }
        finally { $ErrorActionPreference = $previousPreference }
        $nodeDirectory = Split-Path -Parent $candidate
        # Always put the selected runtime first, even if an older Node precedes it.
        $env:Path = "$nodeDirectory;$env:Path"
        $env:WMM_NODE = $candidate
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
    $interpreterProbe = "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or
        -not (Test-WmmPythonImports -Python $venvPython -Probe $interpreterProbe)) {
        if (Test-Path -LiteralPath $venvPath) {
            # Preserve a dead environment and create a clean one. No recursive deletion.
            $backup = "$venvPath.invalid-$(Get-Date -Format 'yyyyMMddHHmmss')-$([guid]::NewGuid().ToString('N'))"
            Move-Item -LiteralPath $venvPath -Destination $backup
            Write-Host "Saved unusable Python environment: $backup"
        }
        Write-Host "Creating Python environment: $venvPath"
        New-WmmVirtualEnvironment -Root $Root -VenvPath $venvPath
    }

    $probe = if ($IncludeBuildTools) {
        "import webview, PyInstaller, PIL, lz4.frame, zstandard, watchdog.observers, pytest, ruff"
    }
    else {
        "import webview, lz4.frame, zstandard, watchdog.observers"
    }
    if (-not (Test-WmmPythonImports -Python $venvPython -Probe $probe)) {
        $projectRequirement = if ($IncludeBuildTools) { "${Root}[build,dev]" } else { $Root }
        Write-Host "Installing required Python packages..."
        Invoke-WmmCommand -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "-e", $projectRequirement) -WorkingDirectory $Root
    }

    if (-not (Test-WmmPythonImports -Python $venvPython -Probe $probe)) {
        throw "The required Python packages could not be imported from $venvPython."
    }
    return $venvPython
}

function Get-WmmPnpm {
    param([string]$Root = (Split-Path -Parent $PSScriptRoot))
    $node = Initialize-WmmNode
    $package = Get-Content -LiteralPath (Join-Path $Root "frontend\package.json") -Raw | ConvertFrom-Json
    if ($package.packageManager -notmatch '^pnpm@([0-9]+\.[0-9]+\.[0-9]+)(?:\+.*)?$') {
        throw "frontend/package.json must pin an exact pnpm version in packageManager."
    }
    $version = $Matches[1]

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
            $env:WMM_PNPM = $pnpmOverride
            return $pnpmOverride
        }
        throw "WMM_PNPM does not point to a file: $pnpmOverride"
    }

    $prefix = Join-Path $Root ".build-tools\pnpm\$version"
    $cli = Join-Path $prefix "package\bin\pnpm.cjs"
    $actualVersion = ""
    if (Test-Path -LiteralPath $cli -PathType Leaf) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $actualVersion = & $node $cli --version 2>$null
            if ($LASTEXITCODE -ne 0) { $actualVersion = "" }
        }
        catch { $actualVersion = "" }
        finally { $ErrorActionPreference = $previousPreference }
    }
    if ($actualVersion -ne $version) {
        Write-Host "Preparing project-local pnpm $version..."
        $python = Get-WmmPython -Root $Root
        Invoke-WmmCommand -FilePath $python -ArgumentList @(
            (Join-Path $PSScriptRoot "prepare_pnpm.py"), "--version", $version, "--output-dir", $prefix
        ) -WorkingDirectory $Root
        $actualVersion = & $node $cli --version
        if ($LASTEXITCODE -ne 0 -or $actualVersion -ne $version) {
            throw "Project-local pnpm failed its version check (expected $version)."
        }
    }
    # The Python build runner uses these exact paths instead of PATH wrappers.
    $env:WMM_PNPM = $cli
    return $cli
}
