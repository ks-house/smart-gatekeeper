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
    $readyPattern = 'PROFILE_READY\s*:?\s*' + [regex]::Escape($ProfileName) + '(?=\s|$)'
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
    $agentCmd = "codex --model $modelId -c model_reasoning_effort=`"high`" --ask-for-approval never --sandbox workspace-write"
    if ($AllowUnsafe) {
        $agentCmd = "codex --model $modelId -c model_reasoning_effort=`"high`" --dangerously-bypass-approvals-and-sandbox"
    }
}


Write-Host "🚀 Launching Orca Terminal Profile: [$Profile] (CLI: $agentCmd, Effort: High, Worktree: $Worktree)..." -ForegroundColor Cyan

$profilePath = ".orca/profiles/$Profile.md"
$title = "$Profile-worker"

# The current Orca guide permits low-level terminal creation for custom model
# argv. The profile document is loaded after the TUI becomes idle.
$createJson = & $orcaExecutable terminal create --worktree $Worktree --title $title --command $agentCmd --json | ConvertFrom-Json


if (-not $createJson.ok) {
    Write-Error "Failed to create Orca terminal for profile ${Profile}: $($createJson.error.message)"
    exit 1
}

$handle = $createJson.result.terminal.handle
Write-Host "✅ Terminal Created: $handle ($title)" -ForegroundColor Green

# Wait for tui-idle
Write-Host "⏳ Waiting for terminal handle $handle to reach tui-idle..." -ForegroundColor Yellow
$waitJson = Wait-ForAgentIdle -TerminalHandle $handle -Phase 'Agent startup'

$startupSnapshot = & $orcaExecutable terminal read --terminal $handle --json | ConvertFrom-Json
if (-not $startupSnapshot.ok) {
    throw "Agent startup inspection failed: $($startupSnapshot.error.message)"
}

$startupTail = $startupSnapshot.result.terminal.tail -join "`n"
if ($startupTail -match '(?m)^PS .+>\s*$') {
    throw "Agent CLI exited during startup and returned to PowerShell. Inspect terminal $handle for the exact CLI error."
}

Write-Host "🟢 Terminal is idle and ready." -ForegroundColor Green

# Load the repository role profile as ordinary agent context. Neither Codex nor
# agy accepts these Markdown files through a --profile flag.
$bootstrapPrompt = "Read $profilePath completely and use it as the active role instructions for this session. Also read AGENTS.md, wiki/index.md, and the recent tail of wiki/log.md before any task. Do not modify files during this bootstrap. Reply PROFILE_READY with the profile name, then return to idle."
$sendJson = & $orcaExecutable terminal send --terminal $handle --text $bootstrapPrompt --enter --json | ConvertFrom-Json

if (-not $sendJson.ok) {
    Write-Error "Profile bootstrap send failed: $($sendJson.error.message)"
    exit 1
}

Write-Host "📖 Waiting for profile bootstrap to complete..." -ForegroundColor Yellow
$profileReadyJson = Wait-ForProfileReady -TerminalHandle $handle -ProfileName $Profile
$profileWaitJson = Wait-ForAgentIdle -TerminalHandle $handle -Phase 'Profile bootstrap final idle'

Write-Host "✅ Profile [$Profile] loaded and idle." -ForegroundColor Green

# Dispatch task if TaskId provided
if ($TaskId -ne '') {
    Write-Host "📡 Dispatching Task [$TaskId] to terminal [$handle]..." -ForegroundColor Cyan
    $dispatchJson = & $orcaExecutable orchestration dispatch --task $TaskId --to $handle --inject --json | ConvertFrom-Json
    if (-not $dispatchJson.ok) {
        Write-Error "Dispatch failed: $($dispatchJson.error.message)"
        exit 1
    }
    Write-Host "🎉 Task [$TaskId] successfully dispatched to [$handle]!" -ForegroundColor Green
}
