$ErrorActionPreference = 'Stop'

function Assert-True {
    param(
        [Parameter(Mandatory=$true)][bool]$Condition,
        [Parameter(Mandatory=$true)][string]$Message
    )
    if (-not $Condition) { throw $Message }
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$probePath = Join-Path $projectRoot '.orca\scripts\probe_lifecycle.ps1'
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sgk-orca-probe-test-{0}" -f [guid]::NewGuid().ToString('N'))
$resolvedTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
if (-not $resolvedTemporaryRoot.StartsWith($resolvedTempParent, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not ([System.IO.Path]::GetFileName($resolvedTemporaryRoot)).StartsWith('sgk-orca-probe-test-', [System.StringComparison]::Ordinal)) {
    throw "Refusing unsafe test directory: $resolvedTemporaryRoot"
}

New-Item -ItemType Directory -Path $resolvedTemporaryRoot | Out-Null
try {
    $mockOrcaPath = Join-Path $resolvedTemporaryRoot 'mock-orca.ps1'
    $mockSource = @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$RemainingArgs)
$action = if ($RemainingArgs.Count -gt 0) { $RemainingArgs[0] } else { '' }
if ($action -eq 'status') {
    $statusCount = if ($env:MOCK_STATUS_COUNT) { [int]$env:MOCK_STATUS_COUNT } else { 0 }
    $statusCount++
    $env:MOCK_STATUS_COUNT = [string]$statusCount
    $runtimeId = if ($env:MOCK_MODE -eq 'runtime_change' -and $statusCount -ge 2) { 'runtime-b' } else { 'runtime-a' }
    [pscustomobject]@{
        id = 'local-status'
        ok = $true
        result = [pscustomobject]@{
            app = [pscustomobject]@{ running = $true; pid = 123 }
            runtime = [pscustomobject]@{ state = 'ready'; reachable = $true; runtimeId = $runtimeId }
            graph = [pscustomobject]@{ state = 'ready' }
        }
        _meta = [pscustomobject]@{ runtimeId = $runtimeId }
    } | ConvertTo-Json -Depth 6 -Compress
    return
}

if ($action -eq 'orchestration' -and $RemainingArgs.Count -gt 1 -and $RemainingArgs[1] -eq 'send') {
    if ($env:MOCK_MODE -eq 'heartbeat_failure') {
        [pscustomobject]@{
            id = 'failure'
            ok = $false
            error = [pscustomobject]@{ code = 'runtime_unavailable'; message = 'mock transport unavailable' }
            _meta = [pscustomobject]@{ runtimeId = 'none' }
        } | ConvertTo-Json -Depth 4 -Compress
        return
    }

    function Get-ArgValue([string]$Name) {
        $index = [array]::IndexOf($RemainingArgs, $Name)
        if ($index -lt 0 -or $index + 1 -ge $RemainingArgs.Count) { return '' }
        return $RemainingArgs[$index + 1]
    }
    $taskId = Get-ArgValue '--task-id'
    $dispatchId = Get-ArgValue '--dispatch-id'
    $phase = Get-ArgValue '--phase'
    $heartbeatCount = if ($env:MOCK_HEARTBEAT_COUNT) { [int]$env:MOCK_HEARTBEAT_COUNT } else { 0 }
    $heartbeatCount++
    $env:MOCK_HEARTBEAT_COUNT = [string]$heartbeatCount
    $payload = [pscustomobject]@{ taskId = $taskId; dispatchId = $dispatchId; phase = $phase } | ConvertTo-Json -Compress
    [pscustomobject]@{
        id = "receipt-$heartbeatCount"
        ok = $true
        result = [pscustomobject]@{
            message = [pscustomobject]@{ id = "msg-$heartbeatCount"; type = 'heartbeat'; payload = $payload }
        }
        _meta = [pscustomobject]@{ runtimeId = 'runtime-a' }
    } | ConvertTo-Json -Depth 6 -Compress
    return
}

[pscustomobject]@{
    id = 'unexpected'
    ok = $false
    error = [pscustomobject]@{ code = 'invalid_argument'; message = 'unexpected mock invocation' }
    _meta = [pscustomobject]@{ runtimeId = 'runtime-a' }
} | ConvertTo-Json -Depth 4 -Compress
'@
    [System.IO.File]::WriteAllText($mockOrcaPath, $mockSource, [System.Text.UTF8Encoding]::new($false))

    $head = (& git -C $projectRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Could not resolve test HEAD.' }
    $common = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $probePath,
        '-TaskId', 'task_test123', '-DispatchId', 'ctx_test123',
        '-ExpectedHead', $head, '-Iterations', '2', '-IntervalSeconds', '0',
        '-From', 'term_test123', '-DispatchCapability', 'dcap_SECRET_SENTINEL',
        '-OrcaExecutable', $mockOrcaPath
    )

    $env:MOCK_MODE = 'success'
    $env:MOCK_STATUS_COUNT = '0'
    $env:MOCK_HEARTBEAT_COUNT = '0'
    $successOutput = @(& powershell @common 2>&1)
    $successExit = $LASTEXITCODE
    $successText = ($successOutput | ForEach-Object { [string]$_ }) -join "`n"
    Assert-True ($successExit -eq 0) 'The success probe must exit zero.'
    Assert-True ($successText -match '"heartbeatCount"\s*:\s*2') 'The success probe must report two accepted heartbeats.'
    Assert-True ($successText -match '"completionSent"\s*:\s*false') 'The probe must never claim worker completion.'
    Assert-True ($successText -notmatch 'dcap_SECRET_SENTINEL') 'The probe must not echo its Dispatch capability.'

    $env:MOCK_MODE = 'heartbeat_failure'
    $env:MOCK_STATUS_COUNT = '0'
    $env:MOCK_HEARTBEAT_COUNT = '0'
    $previousErrorPreference = $ErrorActionPreference
    try {
        # Expected native failures are test data, not harness failures.
        $ErrorActionPreference = 'Continue'
        $failureOutput = @(& powershell @common 2>&1)
        $failureExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    $failureText = ($failureOutput | ForEach-Object { [string]$_ }) -join "`n"
    Assert-True ($failureExit -ne 0) 'A runtime_unavailable heartbeat must fail closed.'
    Assert-True ($failureText -match 'runtime_unavailable') 'The failure must retain the typed transport error.'
    Assert-True ($failureText -notmatch 'dcap_SECRET_SENTINEL') 'A failed probe must not echo its Dispatch capability.'

    $env:MOCK_MODE = 'runtime_change'
    $env:MOCK_STATUS_COUNT = '0'
    $env:MOCK_HEARTBEAT_COUNT = '0'
    $previousErrorPreference = $ErrorActionPreference
    try {
        # Expected native failures are test data, not harness failures.
        $ErrorActionPreference = 'Continue'
        $changeOutput = @(& powershell @common 2>&1)
        $changeExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }
    $changeText = ($changeOutput | ForEach-Object { [string]$_ }) -join "`n"
    Assert-True ($changeExit -ne 0) 'A runtime identity transition must fail closed.'
    Assert-True ($changeText -match 'runtime identity changed') 'The runtime transition failure must be explicit.'
    Assert-True ($changeText -notmatch 'dcap_SECRET_SENTINEL') 'A transition failure must not echo its Dispatch capability.'

    Write-Host '[pass] Orca lifecycle probe success, transport-failure, runtime-transition, and capability-redaction mutations.' -ForegroundColor Green
} finally {
    Remove-Item Env:MOCK_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_STATUS_COUNT -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_HEARTBEAT_COUNT -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $resolvedTemporaryRoot) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
