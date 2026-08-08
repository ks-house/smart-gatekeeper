param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^task_[A-Za-z0-9]+$')]
    [string]$TaskId,

    [Parameter(Mandatory=$true)]
    [ValidatePattern('^ctx_[A-Za-z0-9]+$')]
    [string]$DispatchId,

    [string]$ExpectedHead = '',
    [ValidateRange(1, 100)]
    [int]$Iterations = 7,
    [ValidateRange(0, 3600)]
    [int]$IntervalSeconds = 65,
    [string]$From = '',
    [string]$DispatchCapability = '',
    [string]$OrcaExecutable = '',
    [switch]$RequireClean
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'

function Get-OrcaExecutable {
    if (-not [string]::IsNullOrWhiteSpace($script:OrcaExecutable)) {
        return $script:OrcaExecutable
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_CLI_COMMAND)) {
        return $env:ORCA_CLI_COMMAND
    }
    if ($null -ne (Get-Command orca -ErrorAction SilentlyContinue)) {
        return 'orca'
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_DEV_REPO_ROOT) -and
        $null -ne (Get-Command orca-dev -ErrorAction SilentlyContinue)) {
        return 'orca-dev'
    }
    throw 'No Orca CLI executable is available.'
}

function Invoke-OrcaJson {
    param(
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [Parameter(Mandatory=$true)][string]$Operation
    )

    # Never include Arguments in an error: staged Dispatches can carry a
    # capability value that must not be echoed into reports or logs.
    $raw = @(& $script:ResolvedOrcaExecutable @Arguments 2>&1)
    $text = ($raw | ForEach-Object { [string]$_ }) -join "`n"
    try {
        $response = $text | ConvertFrom-Json
    } catch {
        throw "$Operation returned non-JSON output."
    }
    if (-not $response.ok) {
        $code = if ($response.error.code) { $response.error.code } else { 'unknown_error' }
        $message = if ($response.error.message) { $response.error.message } else { 'No error message.' }
        throw "$Operation failed ($code): $message"
    }
    return $response
}

function Invoke-GitLines {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)

    $lines = @(& git @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments[0]) failed with exit code $LASTEXITCODE."
    }
    return @($lines | ForEach-Object { [string]$_ })
}

function Assert-RepositoryState {
    param([Parameter(Mandatory=$true)][string]$Phase)

    $head = (Invoke-GitLines -Arguments @('rev-parse', 'HEAD') | Select-Object -First 1).Trim()
    if ($head -ne $script:ExpectedHead) {
        throw "$Phase changed HEAD: expected $($script:ExpectedHead), observed $head."
    }

    $status = (Invoke-GitLines -Arguments @('status', '--porcelain=v1', '--untracked-files=all')) -join "`n"
    if ($status -ne $script:BaselineStatus) {
        throw "$Phase changed the worktree status."
    }

    $rawStatus = (Invoke-GitLines -Arguments @('status', '--porcelain=v1', '--untracked-files=all', '--', 'raw')) -join "`n"
    if (-not [string]::IsNullOrWhiteSpace($rawStatus)) {
        throw "$Phase observed a modified raw/ tree."
    }
}

function Assert-RuntimeReady {
    param([Parameter(Mandatory=$true)][string]$Phase)

    $status = Invoke-OrcaJson -Arguments @('status', '--json') -Operation "$Phase runtime status"
    $runtime = $status.result.runtime
    if ($runtime.state -ne 'ready' -or -not $runtime.reachable -or
        [string]::IsNullOrWhiteSpace([string]$runtime.runtimeId)) {
        throw "$Phase runtime is not ready and reachable."
    }
    if ([string]::IsNullOrWhiteSpace($script:RuntimeId)) {
        $script:RuntimeId = [string]$runtime.runtimeId
    } elseif ([string]$runtime.runtimeId -ne $script:RuntimeId) {
        throw "$Phase runtime identity changed during the probe."
    }
}

$ResolvedOrcaExecutable = Get-OrcaExecutable
$ExpectedHead = if ([string]::IsNullOrWhiteSpace($ExpectedHead)) {
    (Invoke-GitLines -Arguments @('rev-parse', 'HEAD') | Select-Object -First 1).Trim()
} else {
    $ExpectedHead.Trim().ToLowerInvariant()
}

if ($ExpectedHead -notmatch '^[0-9a-f]{40}$') {
    throw 'ExpectedHead must be a full 40-character Git commit SHA.'
}

$BaselineStatus = (Invoke-GitLines -Arguments @('status', '--porcelain=v1', '--untracked-files=all')) -join "`n"
if ($RequireClean -and -not [string]::IsNullOrWhiteSpace($BaselineStatus)) {
    throw 'The lifecycle probe requires a clean worktree.'
}

$rawBaseline = (Invoke-GitLines -Arguments @('status', '--porcelain=v1', '--untracked-files=all', '--', 'raw')) -join "`n"
if (-not [string]::IsNullOrWhiteSpace($rawBaseline)) {
    throw 'The lifecycle probe refuses to run with modified raw/ content.'
}

$RuntimeId = ''
$heartbeatReceipts = @()
$startedAt = [DateTimeOffset]::UtcNow

for ($iteration = 1; $iteration -le $Iterations; $iteration++) {
    Assert-RepositoryState -Phase "iteration $iteration preflight"
    Assert-RuntimeReady -Phase "iteration $iteration preflight"

    $arguments = @('orchestration', 'send')
    if (-not [string]::IsNullOrWhiteSpace($From)) {
        $arguments += @('--from', $From)
    }
    if (-not [string]::IsNullOrWhiteSpace($DispatchCapability)) {
        $arguments += @('--dispatch-capability', $DispatchCapability)
    }
    $arguments += @(
        '--type', 'heartbeat',
        '--subject', 'lifecycle longevity probe',
        '--task-id', $TaskId,
        '--dispatch-id', $DispatchId,
        '--phase', "longevity-$iteration-of-$Iterations",
        '--json'
    )

    $receipt = Invoke-OrcaJson -Arguments $arguments -Operation "heartbeat $iteration"
    $message = $receipt.result.message
    if ($message.type -ne 'heartbeat') {
        throw "heartbeat $iteration returned the wrong message type."
    }
    $payload = $message.payload | ConvertFrom-Json
    if ($payload.taskId -ne $TaskId -or $payload.dispatchId -ne $DispatchId) {
        throw "heartbeat $iteration returned mismatched lifecycle identity."
    }
    if ([string]$receipt._meta.runtimeId -ne $RuntimeId) {
        throw "heartbeat $iteration returned a different runtime identity."
    }

    $heartbeatReceipts += [pscustomobject]@{
        iteration = $iteration
        messageId = [string]$message.id
        runtimeId = [string]$receipt._meta.runtimeId
        acceptedAt = [DateTimeOffset]::UtcNow.ToString('o')
    }
    Write-Host "[probe] accepted heartbeat $iteration/$Iterations as $($message.id)" -ForegroundColor Green

    if ($iteration -lt $Iterations -and $IntervalSeconds -gt 0) {
        Start-Sleep -Seconds $IntervalSeconds
    }
}

Assert-RepositoryState -Phase 'final pre-completion boundary'
Assert-RuntimeReady -Phase 'final pre-completion boundary'
$finishedAt = [DateTimeOffset]::UtcNow

# This harness intentionally does not send worker_done. Only the active worker
# may review the evidence and use the exact completion command from its injected
# Dispatch preamble, exactly once.
[pscustomobject]@{
    ok = $true
    taskId = $TaskId
    dispatchId = $DispatchId
    expectedHead = $ExpectedHead
    runtimeId = $RuntimeId
    heartbeatCount = $heartbeatReceipts.Count
    startedAt = $startedAt.ToString('o')
    finishedAt = $finishedAt.ToString('o')
    durationSeconds = [math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
    worktreeStatusUnchanged = $true
    rawUnchanged = $true
    completionSent = $false
    receipts = $heartbeatReceipts
} | ConvertTo-Json -Depth 6
