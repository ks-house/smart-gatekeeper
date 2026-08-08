param(
    [switch]$Json,
    [switch]$Strict
)

$ErrorActionPreference = 'Stop'

function Get-ProjectRoot {
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_WORKTREE_PATH) -and
        (Test-Path -LiteralPath $env:ORCA_WORKTREE_PATH)) {
        return (Resolve-Path -LiteralPath $env:ORCA_WORKTREE_PATH).Path
    }
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
}

function Get-OrcaExecutable {
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_CLI_COMMAND)) {
        return $env:ORCA_CLI_COMMAND
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_DEV_REPO_ROOT)) {
        return 'orca-dev'
    }
    return 'orca'
}

$checks = @()
function Add-Check {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][ValidateSet('pass','warn','fail','info')][string]$Status,
        [Parameter(Mandatory=$true)][string]$Detail,
        [bool]$Required = $false
    )
    $script:checks += [pscustomobject]@{
        name = $Name
        status = $Status
        required = $Required
        detail = $Detail
    }
}

$projectRoot = Get-ProjectRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'

foreach ($commandName in @('git', 'python', 'pio')) {
    $command = Get-Command $commandName -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        Add-Check -Name $commandName -Status fail -Detail 'Not found on PATH.' -Required $true
    } else {
        Add-Check -Name $commandName -Status pass -Detail $command.Source -Required $true
    }
}

$orcaExecutable = Get-OrcaExecutable
$orcaCommand = Get-Command $orcaExecutable -ErrorAction SilentlyContinue
if ($null -eq $orcaCommand) {
    Add-Check -Name 'orca-runtime' -Status fail -Detail "$orcaExecutable is not available on PATH." -Required $true
} else {
    try {
        $orcaStatus = (& $orcaExecutable status --json 2>$null) | ConvertFrom-Json
        if ($orcaStatus.ok -and $orcaStatus.result.runtime.state -eq 'ready') {
            Add-Check -Name 'orca-runtime' -Status pass -Detail "ready; version $($orcaStatus.result.runtime.appVersion)" -Required $true
        } else {
            Add-Check -Name 'orca-runtime' -Status fail -Detail 'Orca runtime is not ready.' -Required $true
        }
    } catch {
        Add-Check -Name 'orca-runtime' -Status fail -Detail $_.Exception.Message -Required $true
    }
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -m pip check *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Check -Name 'python-venv' -Status pass -Detail '.venv exists and pip check passed.' -Required $true
    } else {
        Add-Check -Name 'python-venv' -Status fail -Detail '.venv exists but pip check failed.' -Required $true
    }
} else {
    Add-Check -Name 'python-venv' -Status fail -Detail 'Run .orca/scripts/setup_worktree.ps1.' -Required $true
}

$secretsPath = Join-Path $projectRoot 'include\secrets.h'
if (Test-Path -LiteralPath $secretsPath) {
    Add-Check -Name 'firmware-local-config' -Status pass -Detail 'Ignored include/secrets.h exists; contents were not read.' -Required $true
} else {
    Add-Check -Name 'firmware-local-config' -Status fail -Detail 'include/secrets.h is missing; run setup.' -Required $true
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerReady = $false
if ($null -ne $dockerCommand) {
    & docker info --format '{{.ServerVersion}}' *> $null
    $dockerReady = ($LASTEXITCODE -eq 0)
}
if ($dockerReady) {
    Add-Check -Name 'docker' -Status pass -Detail 'Docker daemon is available for backend and Flutter fallback.'
} else {
    Add-Check -Name 'docker' -Status warn -Detail 'Docker daemon is unavailable; backend integration and containerized Flutter checks cannot run.'
}

$flutterCommand = Get-Command flutter -ErrorAction SilentlyContinue
if ($null -ne $flutterCommand) {
    Add-Check -Name 'flutter-lane' -Status pass -Detail "Native Flutter CLI: $($flutterCommand.Source)"
} elseif ($dockerReady) {
    Add-Check -Name 'flutter-lane' -Status pass -Detail 'Native Flutter is absent; the project Docker image supplies Flutter and JDK 17.'
} else {
    Add-Check -Name 'flutter-lane' -Status fail -Detail 'Neither native Flutter nor the Docker fallback is available.' -Required $true
}

$javaCommand = Get-Command java -ErrorAction SilentlyContinue
if ($null -ne $javaCommand) {
    $previousErrorPreference = $ErrorActionPreference
    try {
        # java -version writes its normal version banner to stderr.
        $ErrorActionPreference = 'Continue'
        $javaVersionText = (& java -version 2>&1 | Select-Object -First 1) -join ''
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    if ($javaVersionText -match 'version "(\d+)') {
        $javaMajor = [int]$Matches[1]
        if ($javaMajor -ge 17) {
            Add-Check -Name 'native-java' -Status pass -Detail $javaVersionText
        } elseif ($dockerReady) {
            Add-Check -Name 'native-java' -Status warn -Detail "$javaVersionText; native Android needs JDK 17, Docker fallback is available."
        } else {
            Add-Check -Name 'native-java' -Status warn -Detail "$javaVersionText; native Android needs JDK 17."
        }
    }
} else {
    Add-Check -Name 'native-java' -Status warn -Detail 'Java is absent; use the Docker Flutter lane.'
}

foreach ($optionalCommand in @('adb', 'gh', 'wsl')) {
    $command = Get-Command $optionalCommand -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        Add-Check -Name $optionalCommand -Status warn -Detail 'Optional command is not available.'
    } else {
        Add-Check -Name $optionalCommand -Status pass -Detail $command.Source
    }
}

if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
    Add-Check -Name 'github-token' -Status warn -Detail 'GITHUB_TOKEN is not present; publishing is unavailable.'
} else {
    & gh auth status *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Check -Name 'github-token' -Status pass -Detail 'GITHUB_TOKEN is present and gh authentication succeeded.'
    } else {
        Add-Check -Name 'github-token' -Status warn -Detail 'GITHUB_TOKEN is present but gh authentication failed.'
    }
}

Add-Check -Name 'physical-gates' -Status info -Detail 'Samsung/OEM, ESP32-C6 radio/GPIO, relay/sensor, boot rollback, OTA-G1..G4, and RELAY-G0..G2 remain pending/fail-closed.'

$failures = @($checks | Where-Object { $_.status -eq 'fail' })
$warnings = @($checks | Where-Object { $_.status -eq 'warn' })
$result = [pscustomobject]@{
    ok = ($failures.Count -eq 0 -and (-not $Strict -or $warnings.Count -eq 0))
    projectRoot = $projectRoot
    checks = $checks
    summary = [pscustomobject]@{
        pass = @($checks | Where-Object { $_.status -eq 'pass' }).Count
        warn = $warnings.Count
        fail = $failures.Count
        info = @($checks | Where-Object { $_.status -eq 'info' }).Count
    }
}

if ($Json) {
    $result | ConvertTo-Json -Depth 6
} else {
    foreach ($check in $checks) {
        $color = switch ($check.status) {
            'pass' { 'Green' }
            'warn' { 'Yellow' }
            'fail' { 'Red' }
            default { 'Cyan' }
        }
        Write-Host ("[{0}] {1}: {2}" -f $check.status.ToUpperInvariant(), $check.name, $check.detail) -ForegroundColor $color
    }
    Write-Host ("Doctor summary: {0} pass, {1} warn, {2} fail." -f $result.summary.pass, $result.summary.warn, $result.summary.fail)
}

if (-not $result.ok) {
    exit 1
}
