param(
    [switch]$SkipPythonDependencies,
    [switch]$SkipPlatformIoPackages
)

$ErrorActionPreference = 'Stop'

function Get-ProjectRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_WORKTREE_PATH) -and
        (Test-Path -LiteralPath $env:ORCA_WORKTREE_PATH)) {
        return (Resolve-Path -LiteralPath $env:ORCA_WORKTREE_PATH).Path
    }

    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
}

function Assert-Command {
    param([Parameter(Mandatory=$true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Required command '$Name' is not available on PATH."
    }
    return $command
}

function Get-RequirementsFingerprint {
    param([Parameter(Mandatory=$true)][string[]]$Paths)

    $content = ($Paths | ForEach-Object {
        "FILE=$($_)`n$((Get-Content -LiteralPath $_ -Raw))"
    }) -join "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($content)
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha256.ComputeHash($bytes)
        return (($hash | ForEach-Object { $_.ToString('x2') }) -join '')
    } finally {
        $sha256.Dispose()
    }
}

$projectRoot = Get-ProjectRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'

Write-Host "[setup] Smart Gatekeeper worktree: $projectRoot" -ForegroundColor Cyan

$null = Assert-Command -Name 'git'
$null = Assert-Command -Name 'python'
$null = Assert-Command -Name 'pio'

$secretsPath = Join-Path $projectRoot 'include\secrets.h'
$secretsExamplePath = Join-Path $projectRoot 'include\secrets.h.example'
if (-not (Test-Path -LiteralPath $secretsPath)) {
    Copy-Item -LiteralPath $secretsExamplePath -Destination $secretsPath
    Write-Host '[setup] Created ignored include/secrets.h from the non-secret example.' -ForegroundColor Yellow
} else {
    Write-Host '[setup] Preserved existing ignored include/secrets.h.' -ForegroundColor DarkGray
}

$venvRoot = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvRoot 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host '[setup] Creating isolated Python environment (.venv)...' -ForegroundColor Cyan
    & python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "python -m venv failed with exit code $LASTEXITCODE."
    }
}

$requirementFiles = @(
    (Join-Path $projectRoot 'backend\app\requirements.lock'),
    (Join-Path $projectRoot 'ota\requirements.txt')
)
$requirementsMarker = Join-Path $venvRoot '.sgk-requirements.sha256'
$requirementsFingerprint = Get-RequirementsFingerprint -Paths $requirementFiles
$installedFingerprint = if (Test-Path -LiteralPath $requirementsMarker) {
    (Get-Content -LiteralPath $requirementsMarker -Raw).Trim()
} else {
    ''
}

if (-not $SkipPythonDependencies -and $requirementsFingerprint -ne $installedFingerprint) {
    Write-Host '[setup] Installing pinned project Python dependencies...' -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check --require-hashes -r $requirementFiles[0]
    if ($LASTEXITCODE -ne 0) {
        throw "Hash-locked backend dependency installation failed with exit code $LASTEXITCODE."
    }
    & $venvPython -m pip install --disable-pip-version-check -r $requirementFiles[1]
    if ($LASTEXITCODE -ne 0) {
        throw "Project dependency installation failed with exit code $LASTEXITCODE."
    }
    Set-Content -LiteralPath $requirementsMarker -Value $requirementsFingerprint -Encoding Ascii
} elseif ($SkipPythonDependencies) {
    Write-Host '[setup] Python dependency installation skipped by request.' -ForegroundColor Yellow
} else {
    Write-Host '[setup] Python dependencies are already current.' -ForegroundColor DarkGray
}

if (-not $SkipPlatformIoPackages) {
    Write-Host '[setup] Resolving cached PlatformIO packages for esp32c6...' -ForegroundColor Cyan
    & pio pkg install -e esp32c6
    if ($LASTEXITCODE -ne 0) {
        throw "PlatformIO package setup failed with exit code $LASTEXITCODE."
    }
} else {
    Write-Host '[setup] PlatformIO package installation skipped by request.' -ForegroundColor Yellow
}

$doctorPath = Join-Path $PSScriptRoot 'doctor.ps1'
if (Test-Path -LiteralPath $doctorPath) {
    & $doctorPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Environment doctor reported a required setup failure.'
    }
}

Write-Host '[setup] Worktree environment is ready.' -ForegroundColor Green
