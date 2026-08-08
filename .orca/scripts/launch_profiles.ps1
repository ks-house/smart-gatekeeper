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
    [switch]$AllowUnsafe,

    [Parameter(Mandatory=$false)]
    [ValidateRange(6, 120)]
    [int]$DispatchObservationSeconds = 30
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

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
        [int]$MaxWindows = 3,

        [Parameter(Mandatory=$false)]
        [string]$ReadyProfileFallback = ''
    )

    for ($window = 1; $window -le $MaxWindows; $window++) {
        $response = & $script:orcaExecutable terminal wait --terminal $TerminalHandle --for tui-idle --timeout-ms 60000 --json | ConvertFrom-Json
        $blockedReason = @(
            [string]$response.result.wait.blockedReason,
            [string]$response.result.blockedReason,
            [string]$response.error.details.blockedReason,
            [string]$response.error.blockedReason
        ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
        if (-not [string]::IsNullOrWhiteSpace($blockedReason)) {
            if ($blockedReason -eq 'codex-trust-workspace') {
                throw "$Phase blocked by exact-worktree trust ($blockedReason). The launcher will not auto-trust or persist broad permission; trust only '$script:projectRoot' in an isolated interactive session, then rerun."
            }
            throw "$Phase blocked by Orca: $blockedReason"
        }
        if ($response.ok -and $response.result.wait.satisfied) {
            return $response
        }

        # agy 1.1.11 can render the exact assistant marker before Orca's first
        # tui-idle observation settles. The marker may satisfy only this initial
        # startup observation; final tui-idle remains mandatory before Dispatch.
        if (-not [string]::IsNullOrWhiteSpace($ReadyProfileFallback) -and
            -not $response.ok -and $response.error.code -eq 'timeout') {
            $snapshot = & $script:orcaExecutable terminal read --terminal $TerminalHandle --json | ConvertFrom-Json
            if (-not $snapshot.ok) {
                throw "$Phase fallback inspection failed: $($snapshot.error.message)"
            }
            $tailText = $snapshot.result.terminal.tail -join "`n"
            $readyPattern = 'PROFILE_READY\s*:?\s*' + [regex]::Escape($ReadyProfileFallback) + '(?=\s|$|\u2022)'
            if ($tailText -match $readyPattern) {
                Write-Host "$Phase emitted the exact profile marker before the initial tui-idle observation; requiring final tui-idle." -ForegroundColor Yellow
                return $snapshot
            }
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

        [Parameter(Mandatory=$true)]
        [string]$PreDispatchRenderedText,

        [Parameter(Mandatory=$false)]
        [int]$ObservationSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($ObservationSeconds)
    $enterSent = $false
    $pasteMarkerPattern = '(?s)\[Pasted Content \d+ chars\]\s*$'
    while ((Get-Date) -lt $deadline) {
        # Read only output produced after the cursor captured immediately before
        # this Dispatch. A stale paste marker from any earlier prompt must never
        # authorize an Enter keypress.
        $snapshot = & $script:orcaExecutable terminal read --terminal $TerminalHandle --cursor $SinceCursor --limit 80 --json | ConvertFrom-Json
        if (-not $snapshot.ok) {
            throw "Dispatch submission inspection failed: $($snapshot.error.message)"
        }

        $tailText = $snapshot.result.terminal.tail -join "`n"
        if (-not $enterSent -and $tailText -match $pasteMarkerPattern) {
            $submit = & $script:orcaExecutable terminal send --terminal $TerminalHandle --enter --json | ConvertFrom-Json
            if (-not $submit.ok) {
                throw "Dispatch was injected but Enter submission failed: $($submit.error.message)"
            }
            Write-Host "Dispatch injection required one bounded Enter submission." -ForegroundColor Yellow
            $enterSent = $true
        }

        # Absence of the paste marker is not submission evidence. Require an
        # exact post-Dispatch renderer/hook signal before reporting success.
        if ($tailText -match '(?m)(?:^|\n)\s*(?:\u2022\s*)?(?:UserPromptSubmit|Working)(?=\s|$)') {
            Write-Host "Dispatch submission/working evidence observed after the pre-Dispatch cursor." -ForegroundColor Green
            return $snapshot
        }

        # Orca renderer preview and cursor reads can settle out of order. A
        # post-Dispatch terminal show may expose a newly rendered paste marker
        # while the cursor read still has zero new output. Never trust a marker
        # that was already present before Dispatch, and still require positive
        # cursor-bound processing evidence after the single Enter.
        if (-not $enterSent) {
            $renderedSnapshot = & $script:orcaExecutable terminal show --terminal $TerminalHandle --json | ConvertFrom-Json
            if (-not $renderedSnapshot.ok) {
                throw "Dispatch renderer inspection failed: $($renderedSnapshot.error.message)"
            }
            $renderedText = @(
                [string]$renderedSnapshot.result.terminal.preview,
                [string]$renderedSnapshot.result.preview,
                [string]($renderedSnapshot.result.terminal.tail -join "`n")
            ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
            if ($PreDispatchRenderedText -notmatch $pasteMarkerPattern -and
                $renderedText -match $pasteMarkerPattern) {
                $submit = & $script:orcaExecutable terminal send --terminal $TerminalHandle --enter --json | ConvertFrom-Json
                if (-not $submit.ok) {
                    throw "Dispatch renderer showed an exact paste marker but Enter submission failed: $($submit.error.message)"
                }
                Write-Host "Dispatch renderer preview required one bounded Enter submission; awaiting cursor-bound processing evidence." -ForegroundColor Yellow
                $enterSent = $true
            }
        }

        if ($tailText -match '(?s)(?:^|\n)PS [^\r\n]+>\s*$') {
            throw 'Agent returned to PowerShell before Dispatch submission was proven.'
        }

        Start-Sleep -Milliseconds 500
    }

    $markerDetail = if ($enterSent) { 'an exact paste marker was submitted once but processing was not proven' } else { 'no exact paste marker was recoverable' }
    throw "Dispatch acceptance produced no positive cursor-bound UserPromptSubmit/Working evidence within $ObservationSeconds seconds; $markerDetail."
}

# Normalize the profile name and build a CLI command supported by the installed
# agent binary. Markdown role profiles are loaded through a bootstrap prompt;
# Codex --profile accepts only $CODEX_HOME/<name>.config.toml, not a Markdown path.
if ($Profile -eq 'antigravity' -or $Profile -eq 'gpt5.6-antigravity') {
    $Profile = "antigravity"
    # agy 1.1.11 requires -i/--prompt-interactive for an initial prompt that
    # continues as an interactive session; a positional prompt exits instead.
    $agentCmd = "agy --effort high --prompt-interactive"
    if ($AllowUnsafe) {
        $agentCmd = "agy --dangerously-skip-permissions --effort high --prompt-interactive"
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

$profilePath = Join-Path $projectRoot ".orca\profiles\$Profile.md"
$title = "$Profile-worker"

# Pass the bootstrap as the agent's initial argv prompt. Starting a blank TUI
# and injecting the first prompt can race Codex startup hooks and exit the TUI.
$bootstrapPrompt = "Your repository scope is the exact worktree '$projectRoot'. Do not inspect, enumerate, or search outside this path. Read '$profilePath' completely and use it as the active role instructions for this session. Also read '$projectRoot\AGENTS.md', '$projectRoot\wiki\index.md', and the recent tail of '$projectRoot\wiki\log.md' before any task. Do not modify files during this bootstrap. Reply exactly PROFILE_READY $Profile, then return to idle."
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
        $readyFallback = if ($Profile -eq 'antigravity') { $Profile } else { '' }
        $waitJson = Wait-ForAgentIdle -TerminalHandle $handle -Phase 'Agent startup' -ReadyProfileFallback $readyFallback

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
    if (-not $closeJson.ok -and $closeJson.error.code -ne 'tab_not_found') {
        throw "Agent startup failed and exact terminal cleanup failed for ${handle}: $($closeJson.error.message). Original error: $startupError"
    }
    if (-not $closeJson.ok -and $closeJson.error.code -eq 'tab_not_found') {
        Write-Host "Exact terminal $handle was already absent during cleanup (tab_not_found)." -ForegroundColor Yellow
    }
    if ($startupAttempt -eq 2) {
        throw "Agent startup failed during both bounded attempts; exact terminal $handle was closed. Original error: $startupError"
    }
    if ([string]$startupError -match 'codex-trust-workspace') {
        throw "Agent startup requires exact-worktree trust; exact terminal $handle was closed without changing trust. Original error: $startupError"
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
    if (-not $closeJson.ok -and $closeJson.error.code -ne 'tab_not_found') {
        throw "Profile bootstrap failed and exact terminal cleanup failed for ${handle}: $($closeJson.error.message). Original error: $bootstrapError"
    }
    throw "Profile bootstrap failed; exact terminal $handle was closed or already absent. Original error: $bootstrapError"
}

Write-Host "✅ Profile [$Profile] loaded and idle." -ForegroundColor Green

# Dispatch task if TaskId provided
if ($TaskId -ne '') {
    Write-Host "📡 Dispatching Task [$TaskId] to terminal [$handle]..." -ForegroundColor Cyan
    try {
        $preDispatchSnapshot = & $orcaExecutable terminal read --terminal $handle --json | ConvertFrom-Json
        if (-not $preDispatchSnapshot.ok) {
            throw "Pre-Dispatch terminal inspection failed: $($preDispatchSnapshot.error.message)"
        }
        $preDispatchCursor = [string]$preDispatchSnapshot.result.terminal.latestCursor
        if ([string]::IsNullOrWhiteSpace($preDispatchCursor)) {
            throw "Pre-Dispatch terminal inspection returned no latest cursor."
        }
        $preDispatchRenderedSnapshot = & $orcaExecutable terminal show --terminal $handle --json | ConvertFrom-Json
        if (-not $preDispatchRenderedSnapshot.ok) {
            throw "Pre-Dispatch renderer inspection failed: $($preDispatchRenderedSnapshot.error.message)"
        }
        $preDispatchRenderedText = @(
            [string]$preDispatchRenderedSnapshot.result.terminal.preview,
            [string]$preDispatchRenderedSnapshot.result.preview,
            [string]($preDispatchRenderedSnapshot.result.terminal.tail -join "`n")
        ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1
        $preDispatchRenderedText = [string]$preDispatchRenderedText
        $dispatchJson = & $orcaExecutable orchestration dispatch --task $TaskId --to $handle --inject --json | ConvertFrom-Json
        if (-not $dispatchJson.ok) {
            throw "Dispatch was rejected before acceptance: $($dispatchJson.error.message)"
        }
    } catch {
        $dispatchError = $_
        $closeJson = & $orcaExecutable terminal close --terminal $handle --json | ConvertFrom-Json
        if (-not $closeJson.ok -and $closeJson.error.code -ne 'tab_not_found') {
            throw "Dispatch failed before acceptance and exact terminal cleanup failed for ${handle}: $($closeJson.error.message). Original error: $dispatchError"
        }
        throw "Dispatch failed before acceptance; exact terminal $handle was closed or already absent. Original error: $dispatchError"
    }

    try {
        $dispatchSubmitJson = Ensure-DispatchSubmitted -TerminalHandle $handle -SinceCursor $preDispatchCursor `
            -PreDispatchRenderedText $preDispatchRenderedText -ObservationSeconds $DispatchObservationSeconds
    } catch {
        $submissionError = $_
        $dispatchId = [string]$dispatchJson.result.dispatch.id
        $stopError = ''
        try {
            $stopJson = & $orcaExecutable orchestration worker-stop --dispatch $dispatchId --json | ConvertFrom-Json
            if (-not $stopJson.ok) {
                $stopError = "$($stopJson.error.code): $($stopJson.error.message)"
            }
        } catch {
            $stopError = [string]$_
        }
        $closeJson = & $orcaExecutable terminal close --terminal $handle --json | ConvertFrom-Json
        if (-not $closeJson.ok -and $closeJson.error.code -ne 'tab_not_found') {
            throw "Dispatch $dispatchId submission verification failed and exact terminal cleanup failed for ${handle}: $($closeJson.error.message). worker-stop: $stopError. Original error: $submissionError"
        }
        if (-not [string]::IsNullOrWhiteSpace($stopError)) {
            throw "Dispatch $dispatchId submission verification failed; exact terminal $handle was closed or already absent, but worker-stop failed: $stopError. Original error: $submissionError"
        }
        throw "Dispatch $dispatchId submission verification failed; worker-stop was accepted and exact terminal $handle was closed or already absent. Original error: $submissionError"
    }
    Write-Host "🎉 Task [$TaskId] successfully dispatched to [$handle]!" -ForegroundColor Green
}
