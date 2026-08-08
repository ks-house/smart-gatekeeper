# .orca/scripts/launch_profiles.ps1 — Orca Profile Terminal Launcher Script
param (
    [Parameter(Mandatory=$true)]
    [ValidateSet('gpt5.6-sol', 'gpt5.6-terra', 'gpt5.6-luna', 'gpt5.6-antigravity', 'sol', 'terra', 'luna', 'antigravity')]
    [string]$Profile,


    [Parameter(Mandatory=$false)]
    [string]$TaskId = '',

    [Parameter(Mandatory=$false)]
    [string]$Worktree = 'active',

    [Parameter(Mandatory=$false)]
    [switch]$AllowUnsafe
)

$ErrorActionPreference = 'Stop'

function Get-OrcaExecutable {
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
    return 'orca'
}

$orcaExecutable = Get-OrcaExecutable

function Wait-ForAgentIdle {
    param (
        [Parameter(Mandatory=$true)]
        [string]$TerminalHandle,

        [Parameter(Mandatory=$true)]
        [string]$Phase,

        [Parameter(Mandatory=$false)]
        [int]$MaxWindows = 3
    )

    for ($window = 1; $window -le $MaxWindows; $window++) {
        $response = & $script:orcaExecutable terminal wait --terminal $TerminalHandle --for tui-idle --timeout-ms 60000 --json | ConvertFrom-Json
        if ($response.ok -and $response.result.wait.satisfied) {
            return $response
        }

        if (-not $response.ok -and $response.error.code -eq 'timeout' -and $window -lt $MaxWindows) {
            Write-Host "⏳ $Phase is still running after wait window $window/$MaxWindows; continuing..." -ForegroundColor Yellow
            continue
        }

        $detail = if ($response.error.message) { $response.error.message } else { $response.result.wait.status }
        throw "$Phase failed to reach tui-idle: $detail"
    }
}

function Wait-ForProfileReady {
    param (
        [Parameter(Mandatory=$true)]
        [string]$TerminalHandle,

        [Parameter(Mandatory=$true)]
        [string]$ProfileName,

        [Parameter(Mandatory=$false)]
        [int]$TimeoutSeconds = 180
    )

    $readyMarker = "PROFILE_READY $ProfileName"
    # Orca terminal rendering can append its activity bullet directly after the
    # assistant text (for example, "PROFILE_READY name•Running Stop hook").
    # Accept that renderer boundary, but not punctuation from the bootstrap
    # instruction itself ("PROFILE_READY name, then return to idle").
    $readyPattern = 'PROFILE_READY\s*:?\s*' + [regex]::Escape($ProfileName) + '(?=\s|$|\u2022)'
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $snapshot = & $script:orcaExecutable terminal read --terminal $TerminalHandle --json | ConvertFrom-Json
        if (-not $snapshot.ok) {
            throw "Profile bootstrap inspection failed: $($snapshot.error.message)"
        }

        $tailText = $snapshot.result.terminal.tail -join "`n"
        if ($tailText -match $readyPattern) {
            return $snapshot
        }

        Start-Sleep -Milliseconds 1000
    }

    throw "Profile bootstrap did not emit '$readyMarker' within $TimeoutSeconds seconds."
}

function Ensure-DispatchSubmitted {
    param (
        [Parameter(Mandatory=$true)]
        [string]$TerminalHandle,

        [Parameter(Mandatory=$true)]
        [string]$SinceCursor,

        [Parameter(Mandatory=$false)]
        [int]$ObservationSeconds = 5
    )

    $deadline = (Get-Date).AddSeconds($ObservationSeconds)
    while ((Get-Date) -lt $deadline) {
        # Read only output produced after the cursor captured immediately before
        # this Dispatch. A stale paste marker from any earlier prompt must never
        # authorize an Enter keypress.
        $snapshot = & $script:orcaExecutable terminal read --terminal $TerminalHandle --cursor $SinceCursor --limit 80 --json | ConvertFrom-Json
        if (-not $snapshot.ok) {
            throw "Dispatch submission inspection failed: $($snapshot.error.message)"
        }

        $tailText = $snapshot.result.terminal.tail -join "`n"
        if ($tailText -match '(?s)\[Pasted Content \d+ chars\]\s*$') {
            $submit = & $script:orcaExecutable terminal send --terminal $TerminalHandle --enter --json | ConvertFrom-Json
            if (-not $submit.ok) {
                throw "Dispatch was injected but Enter submission failed: $($submit.error.message)"
            }
            Write-Host "Dispatch injection required one bounded Enter submission." -ForegroundColor Yellow
            return $submit
        }

        Start-Sleep -Milliseconds 500
    }

    # No exact unsubmitted paste marker was observed. The agent either accepted
    # the injected prompt directly or progressed before the first inspection.
    return $null
}

# Normalize the profile name and build a CLI command supported by the installed
# agent binary. Markdown role profiles are loaded through a bootstrap prompt;
# Codex --profile accepts only $CODEX_HOME/<name>.config.toml, not a Markdown path.
if ($Profile -eq 'antigravity' -or $Profile -eq 'gpt5.6-antigravity') {
    $Profile = "antigravity"
    $agentCmd = "agy --effort high"
    if ($AllowUnsafe) {
        $agentCmd = "agy --dangerously-skip-permissions --effort high"
    }
} else {
    if (-not $Profile.StartsWith('gpt5.6-')) {
        $Profile = "gpt5.6-$Profile"
    }
    $modelId = $Profile -replace '^gpt5\.6-', 'gpt-5.6-'
    # Orca lifecycle commands connect to the local runtime. Keep filesystem
    # access at workspace-write while permitting the required outbound IPC.
    $agentCmd = "codex --model $modelId -c model_reasoning_effort=`"high`" -c sandbox_workspace_write.network_access=true -c windows.sandbox_private_desktop=false -c features.apps=false -c mcp_servers.node_repl.enabled=false --ask-for-approval never --sandbox workspace-write"
    if ($AllowUnsafe) {
        $agentCmd = "codex --model $modelId -c model_reasoning_effort=`"high`" -c features.apps=false -c mcp_servers.node_repl.enabled=false --dangerously-bypass-approvals-and-sandbox"
    }
}


Write-Host "🚀 Launching Orca Terminal Profile: [$Profile] (CLI: $agentCmd, Effort: High, Worktree: $Worktree)..." -ForegroundColor Cyan

$profilePath = ".orca/profiles/$Profile.md"
$title = "$Profile-worker"

# Pass the bootstrap as the agent's initial argv prompt. Starting a blank TUI
# and injecting the first prompt can race Codex startup hooks and exit the TUI.
$bootstrapPrompt = "Read $profilePath completely and use it as the active role instructions for this session. Also read AGENTS.md, wiki/index.md, and the recent tail of wiki/log.md before any task. Do not modify files during this bootstrap. Reply exactly PROFILE_READY $Profile, then return to idle."
$escapedBootstrapPrompt = $bootstrapPrompt.Replace("'", "''")
$agentCmd = "$agentCmd '$escapedBootstrapPrompt'"

# The current Orca guide permits low-level terminal creation for custom model
# argv. The profile document is loaded by the initial CLI prompt. Codex can
# occasionally exit before consuming that prompt without producing an error;
# close only that exact terminal and retry once before failing closed.
$handle = $null
for ($startupAttempt = 1; $startupAttempt -le 2; $startupAttempt++) {
    $createJson = & $orcaExecutable terminal create --worktree $Worktree --title $title --command $agentCmd --json | ConvertFrom-Json
    if (-not $createJson.ok) {
        throw "Failed to create Orca terminal for profile ${Profile}: $($createJson.error.message)"
    }

    $handle = $createJson.result.terminal.handle
    Write-Host "Terminal Created: $handle ($title), startup attempt $startupAttempt/2" -ForegroundColor Green
    $startupSucceeded = $false
    $startupError = $null
    try {
        Write-Host "Waiting for terminal handle $handle to reach tui-idle..." -ForegroundColor Yellow
        $waitJson = Wait-ForAgentIdle -TerminalHandle $handle -Phase 'Agent startup'

        $startupSnapshot = & $orcaExecutable terminal read --terminal $handle --json | ConvertFrom-Json
        if (-not $startupSnapshot.ok) {
            throw "Agent startup inspection failed: $($startupSnapshot.error.message)"
        }

        $startupTail = $startupSnapshot.result.terminal.tail -join "`n"
        if ($startupTail -match '(?s)(?:^|\n)PS [^\r\n]+>\s*$') {
            throw "Agent CLI exited before profile bootstrap and returned to PowerShell."
        }
        $startupSucceeded = $true
    } catch {
        $startupError = $_
    }

    if ($startupSucceeded) {
        break
    }

    Write-Host "Agent startup failed; closing exact terminal $handle." -ForegroundColor Yellow
    $closeJson = & $orcaExecutable terminal close --terminal $handle --json | ConvertFrom-Json
    if (-not $closeJson.ok) {
        throw "Agent startup failed and exact terminal cleanup failed for ${handle}: $($closeJson.error.message). Original error: $startupError"
    }
    if ($startupAttempt -eq 2) {
        throw "Agent startup failed during both bounded attempts; exact terminal $handle was closed. Original error: $startupError"
    }
    Write-Host "Retrying profile startup once in a new terminal." -ForegroundColor Yellow
    $handle = $null
}

Write-Host "🟢 Terminal is idle and ready." -ForegroundColor Green

Write-Host "📖 Waiting for profile bootstrap to complete..." -ForegroundColor Yellow
try {
    $profileReadyJson = Wait-ForProfileReady -TerminalHandle $handle -ProfileName $Profile
    $profileWaitJson = Wait-ForAgentIdle -TerminalHandle $handle -Phase 'Profile bootstrap final idle'
} catch {
    $bootstrapError = $_
    $closeJson = & $orcaExecutable terminal close --terminal $handle --json | ConvertFrom-Json
    if (-not $closeJson.ok) {
        throw "Profile bootstrap failed and exact terminal cleanup failed for ${handle}: $($closeJson.error.message). Original error: $bootstrapError"
    }
    throw "Profile bootstrap failed; exact terminal $handle was closed. Original error: $bootstrapError"
}

Write-Host "✅ Profile [$Profile] loaded and idle." -ForegroundColor Green

# Dispatch task if TaskId provided
if ($TaskId -ne '') {
    Write-Host "📡 Dispatching Task [$TaskId] to terminal [$handle]..." -ForegroundColor Cyan
    $preDispatchSnapshot = & $orcaExecutable terminal read --terminal $handle --json | ConvertFrom-Json
    if (-not $preDispatchSnapshot.ok) {
        throw "Pre-Dispatch terminal inspection failed: $($preDispatchSnapshot.error.message)"
    }
    $preDispatchCursor = [string]$preDispatchSnapshot.result.terminal.latestCursor
    if ([string]::IsNullOrWhiteSpace($preDispatchCursor)) {
        throw "Pre-Dispatch terminal inspection returned no latest cursor."
    }
    $dispatchJson = & $orcaExecutable orchestration dispatch --task $TaskId --to $handle --inject --json | ConvertFrom-Json
    if (-not $dispatchJson.ok) {
        Write-Error "Dispatch failed: $($dispatchJson.error.message)"
        exit 1
    }
    $dispatchSubmitJson = Ensure-DispatchSubmitted -TerminalHandle $handle -SinceCursor $preDispatchCursor
    Write-Host "🎉 Task [$TaskId] successfully dispatched to [$handle]!" -ForegroundColor Green
}
