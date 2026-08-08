param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('gpt5.6-sol', 'gpt5.6-terra', 'gpt5.6-luna', 'antigravity')]
    [string]$Profile,

    [Parameter(Mandatory=$true)]
    [string]$Objective,

    [string]$RunId = '',
    [string]$RunObjective = '',
    [string]$Worktree = 'active',
    [switch]$AllowUnsafe
)

$ErrorActionPreference = 'Stop'

function Get-OrcaExecutable {
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_CLI_COMMAND)) { return $env:ORCA_CLI_COMMAND }
    if ($null -ne (Get-Command orca -ErrorAction SilentlyContinue)) { return 'orca' }
    if (-not [string]::IsNullOrWhiteSpace($env:ORCA_DEV_REPO_ROOT) -and
        $null -ne (Get-Command orca-dev -ErrorAction SilentlyContinue)) { return 'orca-dev' }
    return 'orca'
}

$orcaExecutable = Get-OrcaExecutable
$status = (& $orcaExecutable status --json) | ConvertFrom-Json
if (-not $status.ok -or $status.result.runtime.state -ne 'ready') {
    throw 'Orca runtime is not ready.'
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
    if ([string]::IsNullOrWhiteSpace($RunObjective)) { $RunObjective = $Objective }
    $runReceipt = (& $orcaExecutable orchestration run-create --objective $RunObjective --json) | ConvertFrom-Json
    if (-not $runReceipt.ok) { throw $runReceipt.error.message }
    $RunId = $runReceipt.result.run.id
} else {
    $runReceipt = (& $orcaExecutable orchestration run-use --id $RunId --json) | ConvertFrom-Json
    if (-not $runReceipt.ok) { throw $runReceipt.error.message }
}

$profilePath = ".orca/profiles/$Profile.md"
$taskSpec = "Read AGENTS.md fully, wiki/index.md, recent wiki/log.md, and $profilePath before work. Use $Profile as the active role. Objective: $Objective. Preserve raw/, OTA recovery, append-only wiki/log.md, software-versus-physical evidence separation, and exactly-once worker_done lifecycle requirements."
$taskReceipt = (& $orcaExecutable orchestration task-create --spec $taskSpec --json) | ConvertFrom-Json
if (-not $taskReceipt.ok) { throw $taskReceipt.error.message }
$taskId = $taskReceipt.result.task.id

$launchArguments = @{
    Profile = $Profile
    TaskId = $taskId
    Worktree = $Worktree
}
if ($AllowUnsafe) { $launchArguments.AllowUnsafe = $true }
& (Join-Path $PSScriptRoot 'launch_profiles.ps1') @launchArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dispatchReceipt = (& $orcaExecutable orchestration dispatch-show --task $taskId --json) | ConvertFrom-Json
if (-not $dispatchReceipt.ok) { throw $dispatchReceipt.error.message }

[pscustomobject]@{
    runId = $RunId
    taskId = $taskId
    dispatchId = $dispatchReceipt.result.dispatch.id
    profile = $Profile
    worktree = $Worktree
    completionEvidence = 'Wait for accepted worker_done; ready/idle/heartbeat/timeout are not completion.'
} | ConvertTo-Json
