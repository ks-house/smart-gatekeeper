$ErrorActionPreference = 'Stop'

function Assert-True {
    param(
        [Parameter(Mandatory=$true)][bool]$Condition,
        [Parameter(Mandatory=$true)][string]$Message
    )
    if (-not $Condition) { throw $Message }
}

function Invoke-LauncherCase {
    param(
        [Parameter(Mandatory=$true)][string]$Mode,
        [Parameter(Mandatory=$true)][string]$EventPath,
        [Parameter(Mandatory=$true)][string]$LauncherPath,
        [Parameter(Mandatory=$true)][string]$MockOrcaPath,
        [Parameter(Mandatory=$false)][string]$Profile = 'gpt5.6-terra',
        [Parameter(Mandatory=$false)][int]$DispatchObservationSeconds = 30
    )

    $env:MOCK_MODE = $Mode
    $env:MOCK_EVENT_PATH = $EventPath
    $env:MOCK_PROFILE = $Profile
    $env:ORCA_CLI_COMMAND = $MockOrcaPath
    $previousErrorPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& powershell -NoProfile -ExecutionPolicy Bypass -File $LauncherPath `
            -Profile $Profile -TaskId task_mock123 -Worktree active `
            -DispatchObservationSeconds $DispatchObservationSeconds 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
    }

    [pscustomobject]@{
        exitCode = $exitCode
        output = ($output | ForEach-Object { [string]$_ }) -join "`n"
        events = if (Test-Path -LiteralPath $EventPath) {
            @(Get-Content -LiteralPath $EventPath -Encoding UTF8)
        } else {
            @()
        }
    }
}

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$launcherPath = Join-Path $projectRoot '.orca\scripts\launch_profiles.ps1'
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sgk-profile-launcher-test-{0}" -f [guid]::NewGuid().ToString('N'))
$resolvedTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
if (-not $resolvedTemporaryRoot.StartsWith($resolvedTempParent, [System.StringComparison]::OrdinalIgnoreCase) -or
    -not ([System.IO.Path]::GetFileName($resolvedTemporaryRoot)).StartsWith('sgk-profile-launcher-test-', [System.StringComparison]::Ordinal)) {
    throw "Refusing unsafe test directory: $resolvedTemporaryRoot"
}

New-Item -ItemType Directory -Path $resolvedTemporaryRoot | Out-Null
try {
    $mockOrcaPath = Join-Path $resolvedTemporaryRoot 'mock-orca.ps1'
    $mockSource = @'
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$RemainingArgs)

if ([string]::IsNullOrWhiteSpace($env:MOCK_EVENT_PATH)) {
    throw 'MOCK_EVENT_PATH is required.'
}
[System.IO.File]::AppendAllText(
    $env:MOCK_EVENT_PATH,
    (($RemainingArgs -join [char]31) + [Environment]::NewLine),
    [System.Text.UTF8Encoding]::new($false)
)

$action = if ($RemainingArgs.Count -gt 0) { $RemainingArgs[0] } else { '' }
if ($action -eq 'terminal' -and $RemainingArgs.Count -gt 1 -and $RemainingArgs[1] -eq 'create') {
    $createCount = if ($env:MOCK_CREATE_COUNT) { [int]$env:MOCK_CREATE_COUNT } else { 0 }
    $createCount++
    $env:MOCK_CREATE_COUNT = [string]$createCount
    [pscustomobject]@{
        ok = $true
        result = [pscustomobject]@{ terminal = [pscustomobject]@{ handle = "term_mock_$createCount" } }
    } | ConvertTo-Json -Depth 4 -Compress
    return
}

if ($action -eq 'terminal' -and $RemainingArgs.Count -gt 1 -and $RemainingArgs[1] -eq 'wait') {
    $waitCount = if ($env:MOCK_WAIT_COUNT) { [int]$env:MOCK_WAIT_COUNT } else { 0 }
    $waitCount++
    $env:MOCK_WAIT_COUNT = [string]$waitCount
    if ($env:MOCK_MODE -eq 'trust_blocked') {
        [pscustomobject]@{
            ok = $true
            result = [pscustomobject]@{
                wait = [pscustomobject]@{
                    satisfied = $false
                    status = 'blocked'
                    blockedReason = 'codex-trust-workspace'
                }
            }
        } | ConvertTo-Json -Depth 5 -Compress
        return
    }
    if ($env:MOCK_MODE -eq 'antigravity_renderer' -and $waitCount -eq 1) {
        [pscustomobject]@{
            ok = $false
            error = [pscustomobject]@{ code = 'timeout'; message = 'mock initial renderer timeout' }
        } | ConvertTo-Json -Depth 3 -Compress
        return
    }
    [pscustomobject]@{
        ok = $true
        result = [pscustomobject]@{ wait = [pscustomobject]@{ satisfied = $true; status = 'satisfied' } }
    } | ConvertTo-Json -Depth 4 -Compress
    return
}

if ($action -eq 'terminal' -and $RemainingArgs.Count -gt 1 -and $RemainingArgs[1] -eq 'read') {
    $cursorRead = [array]::IndexOf($RemainingArgs, '--cursor') -ge 0
    if ($cursorRead) {
        $cursorReadCount = if ($env:MOCK_CURSOR_READ_COUNT) { [int]$env:MOCK_CURSOR_READ_COUNT } else { 0 }
        $cursorReadCount++
        $env:MOCK_CURSOR_READ_COUNT = [string]$cursorReadCount
    } else {
        $cursorReadCount = 0
    }
    $tail = if ($env:MOCK_MODE -eq 'startup_shell' -or $env:MOCK_MODE -eq 'startup_shell_tab_missing') {
        @('PS C:\mock>')
    } elseif ($cursorRead -and $env:MOCK_MODE -eq 'delayed_marker' -and $cursorReadCount -le 12) {
        @('Rendering')
    } elseif ($cursorRead -and $env:MOCK_MODE -eq 'delayed_marker') {
        @('[Pasted Content 42 chars]')
    } elseif ($cursorRead -and $env:MOCK_MODE -eq 'no_submission_evidence') {
        @('Rendering')
    } elseif ($cursorRead) {
        @('Working')
    } else {
        @("PROFILE_READY $env:MOCK_PROFILE")
    }
    [pscustomobject]@{
        ok = $true
        result = [pscustomobject]@{
            terminal = [pscustomobject]@{ tail = $tail; latestCursor = 'cursor_mock_1' }
        }
    } | ConvertTo-Json -Depth 5 -Compress
    return
}

if ($action -eq 'terminal' -and $RemainingArgs.Count -gt 1 -and $RemainingArgs[1] -eq 'close' -and
    $env:MOCK_MODE -eq 'startup_shell_tab_missing') {
    [pscustomobject]@{
        ok = $false
        error = [pscustomobject]@{ code = 'tab_not_found'; message = 'mock terminal already absent' }
    } | ConvertTo-Json -Depth 3 -Compress
    return
}

if ($action -eq 'terminal' -and $RemainingArgs.Count -gt 1 -and
    ($RemainingArgs[1] -eq 'send' -or $RemainingArgs[1] -eq 'close')) {
    [pscustomobject]@{ ok = $true; result = [pscustomobject]@{} } | ConvertTo-Json -Compress
    return
}

if ($action -eq 'orchestration' -and $RemainingArgs.Count -gt 1 -and $RemainingArgs[1] -eq 'dispatch') {
    if ($env:MOCK_MODE -eq 'dispatch_rejected') {
        [pscustomobject]@{
            ok = $false
            error = [pscustomobject]@{ code = 'runtime_unavailable'; message = 'mock Dispatch rejection' }
        } | ConvertTo-Json -Depth 3 -Compress
    } else {
        [pscustomobject]@{
            ok = $true
            result = [pscustomobject]@{ dispatch = [pscustomobject]@{ id = 'ctx_mock123' } }
        } | ConvertTo-Json -Depth 4 -Compress
    }
    return
}

[pscustomobject]@{
    ok = $false
    error = [pscustomobject]@{ code = 'invalid_argument'; message = 'unexpected mock invocation' }
} | ConvertTo-Json -Depth 3 -Compress
'@
    [System.IO.File]::WriteAllText($mockOrcaPath, $mockSource, [System.Text.UTF8Encoding]::new($false))

    $successEventPath = Join-Path $resolvedTemporaryRoot 'success-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $success = Invoke-LauncherCase -Mode 'success' -EventPath $successEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath
    $successText = $success.events -join "`n"
    Assert-True ($success.exitCode -eq 0) "The staged launcher success case must exit zero: $($success.output)"
    Assert-True (($success.events | Where-Object { $_ -match '^terminal\x1fcreate\x1f' }).Count -eq 1) 'Success must create exactly one terminal.'
    Assert-True ($successText -match '--sandbox workspace-write') 'Success must keep the workspace-write sandbox.'
    Assert-True ($successText -match 'windows\.sandbox_private_desktop=false') 'Success must use the documented Windows desktop compatibility setting.'
    Assert-True ($successText -match 'features\.apps=false') 'Success must disable optional Apps startup.'
    Assert-True ($successText -match 'mcp_servers\.node_repl\.enabled=false') 'Success must disable the optional node_repl MCP.'
    Assert-True ($successText -match 'Reply exactly PROFILE_READY gpt5\.6-terra') 'The role bootstrap must be the initial agent prompt.'
    Assert-True (($success.events | Where-Object { $_ -match '^orchestration\x1fdispatch\x1f' -and $_ -match '\x1f--inject(?:\x1f|$)' }).Count -eq 1) 'Success must inject exactly one tracked Dispatch.'
    Assert-True (($success.events | Where-Object { $_ -match '^terminal\x1fread\x1f' -and $_ -match '\x1f--cursor\x1fcursor_mock_1(?:\x1f|$)' }).Count -eq 1) 'Paste recovery must read only after the pre-Dispatch cursor.'
    Assert-True (($success.events | Where-Object { $_ -match '^terminal\x1fsend\x1f' }).Count -eq 0) 'Positive Working evidence must not trigger an Enter.'
    Assert-True (($success.events | Where-Object { $_ -match '^terminal\x1fclose\x1f' }).Count -eq 0) 'A successful launch must not close its worker terminal.'

    $shellEventPath = Join-Path $resolvedTemporaryRoot 'startup-shell-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $startupShell = Invoke-LauncherCase -Mode 'startup_shell' -EventPath $shellEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath
    Assert-True ($startupShell.exitCode -ne 0) 'Two shell-return startup attempts must fail closed.'
    Assert-True (($startupShell.events | Where-Object { $_ -match '^terminal\x1fcreate\x1f' }).Count -eq 2) 'Startup failure must retry exactly once.'
    Assert-True (($startupShell.events | Where-Object { $_ -match '^terminal\x1fclose\x1f' }).Count -eq 2) 'Startup failure must close both exact terminals.'
    Assert-True (($startupShell.events | Where-Object { $_ -match '^orchestration\x1fdispatch\x1f' }).Count -eq 0) 'Startup failure must never Dispatch the Task.'

    $tabMissingEventPath = Join-Path $resolvedTemporaryRoot 'tab-missing-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $tabMissing = Invoke-LauncherCase -Mode 'startup_shell_tab_missing' -EventPath $tabMissingEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath
    Assert-True ($tabMissing.exitCode -ne 0) 'An exited agent with an already-absent tab must still fail closed.'
    Assert-True ($tabMissing.output -match 'tab_not_found') 'The already-absent terminal receipt must remain explicit.'
    Assert-True ($tabMissing.output -notmatch 'cleanup failed') 'Typed tab_not_found must not replace the original startup failure.'
    Assert-True (($tabMissing.events | Where-Object { $_ -match '^orchestration\x1fdispatch\x1f' }).Count -eq 0) 'An already-absent startup terminal must never Dispatch the Task.'

    $rejectionEventPath = Join-Path $resolvedTemporaryRoot 'dispatch-rejection-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $dispatchRejected = Invoke-LauncherCase -Mode 'dispatch_rejected' -EventPath $rejectionEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath
    Assert-True ($dispatchRejected.exitCode -ne 0) 'A rejected Dispatch must fail closed.'
    Assert-True ($dispatchRejected.output -match 'rejected before acceptance') 'A rejected Dispatch must preserve its stage boundary.'
    Assert-True (($dispatchRejected.events | Where-Object { $_ -match '^terminal\x1fclose\x1f' }).Count -eq 1) 'A rejected Dispatch must close its exact staged terminal.'
    Assert-True (($dispatchRejected.events | Where-Object { $_ -match '^terminal\x1fsend\x1f' }).Count -eq 0) 'A rejected Dispatch must not attempt paste recovery.'

    $delayedMarkerEventPath = Join-Path $resolvedTemporaryRoot 'delayed-marker-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $delayedMarker = Invoke-LauncherCase -Mode 'delayed_marker' -EventPath $delayedMarkerEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath
    Assert-True ($delayedMarker.exitCode -eq 0) "A marker appearing after the former five-second window must be recovered: $($delayedMarker.output)"
    Assert-True (($delayedMarker.events | Where-Object { $_ -match '^terminal\x1fread\x1f' -and $_ -match '\x1f--cursor\x1f' }).Count -ge 13) 'The delayed-marker case must observe beyond the former five-second window.'
    Assert-True (($delayedMarker.events | Where-Object { $_ -match '^terminal\x1fsend\x1f' -and $_ -match '\x1f--enter(?:\x1f|$)' }).Count -eq 1) 'The delayed exact marker must authorize exactly one Enter.'

    $noEvidenceEventPath = Join-Path $resolvedTemporaryRoot 'no-evidence-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $noEvidence = Invoke-LauncherCase -Mode 'no_submission_evidence' -EventPath $noEvidenceEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath -DispatchObservationSeconds 6
    Assert-True ($noEvidence.exitCode -ne 0) 'Absence of a marker and positive submission evidence must fail closed.'
    Assert-True ($noEvidence.output -match 'no positive UserPromptSubmit/Working evidence') 'The no-evidence failure must state the positive-evidence boundary.'
    Assert-True (($noEvidence.events | Where-Object { $_ -match '^terminal\x1fclose\x1f' }).Count -eq 0) 'An already accepted Dispatch must be retained for coordinator inspection.'

    $antigravityEventPath = Join-Path $resolvedTemporaryRoot 'antigravity-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $antigravity = Invoke-LauncherCase -Mode 'antigravity_renderer' -EventPath $antigravityEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath -Profile 'antigravity'
    $antigravityText = $antigravity.events -join "`n"
    Assert-True ($antigravity.exitCode -eq 0) "The agy renderer fallback must still reach mandatory final idle: $($antigravity.output)"
    Assert-True ($antigravityText -match 'agy --effort high --prompt-interactive') 'agy 1.1.11 must receive the supported interactive initial-prompt flag.'
    Assert-True ($antigravityText -notmatch '--dangerously-skip-permissions') 'The safe Antigravity launch must not auto-approve permissions.'
    Assert-True ($antigravityText -match 'Do not inspect, enumerate, or search outside this path') 'The Antigravity bootstrap must prohibit searches outside the exact worktree.'
    Assert-True ($antigravityText -match [regex]::Escape($projectRoot)) 'The Antigravity bootstrap must name the absolute project worktree.'
    Assert-True (($antigravity.events | Where-Object { $_ -match '^terminal\x1fwait\x1f' }).Count -ge 2) 'An initial marker fallback must still require a final tui-idle observation.'
    Assert-True (($antigravity.events | Where-Object { $_ -match '^orchestration\x1fdispatch\x1f' }).Count -eq 1) 'The renderer fallback may Dispatch only after final idle.'

    $trustEventPath = Join-Path $resolvedTemporaryRoot 'trust-blocked-events.txt'
    $env:MOCK_CREATE_COUNT = '0'
    $env:MOCK_WAIT_COUNT = '0'
    $env:MOCK_CURSOR_READ_COUNT = '0'
    $trustBlocked = Invoke-LauncherCase -Mode 'trust_blocked' -EventPath $trustEventPath `
        -LauncherPath $launcherPath -MockOrcaPath $mockOrcaPath -Profile 'antigravity'
    Assert-True ($trustBlocked.exitCode -ne 0) 'An exact-worktree trust prompt must fail closed.'
    Assert-True ($trustBlocked.output -match 'codex-trust-workspace') 'The trust failure must retain Orca blockedReason.'
    Assert-True ($trustBlocked.output -match 'will not auto-trust or persist broad permission') 'The trust diagnostic must preserve the no-broad-trust boundary.'
    Assert-True (($trustBlocked.events | Where-Object { $_ -match '^terminal\x1fcreate\x1f' }).Count -eq 1) 'A trust prompt must not trigger an automatic second launch.'
    Assert-True (($trustBlocked.events | Where-Object { $_ -match '^terminal\x1fclose\x1f' }).Count -eq 1) 'A trust prompt must close only its exact terminal.'
    Assert-True (($trustBlocked.events | Where-Object { $_ -match '^orchestration\x1fdispatch\x1f' }).Count -eq 0) 'A trust prompt must never Dispatch the Task.'

    Write-Host '[pass] Orca staged profile launcher Codex, agy 1.1.11, trust, renderer, and cleanup contracts.' -ForegroundColor Green
} finally {
    Remove-Item Env:MOCK_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_EVENT_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_CREATE_COUNT -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_WAIT_COUNT -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_CURSOR_READ_COUNT -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_PROFILE -ErrorAction SilentlyContinue
    Remove-Item Env:ORCA_CLI_COMMAND -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $resolvedTemporaryRoot) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
