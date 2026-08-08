# .orca/scripts/launch_profiles.ps1 — Orca Profile Terminal Launcher Script
param (
    [Parameter(Mandatory=$true)]
    [ValidateSet('gpt5.6-sol', 'gpt5.6-terra', 'gpt5.6-luna', 'sol', 'terra', 'luna')]
    [string]$Profile,

    [Parameter(Mandatory=$false)]
    [string]$TaskId = '',

    [Parameter(Mandatory=$false)]
    [string]$Worktree = 'active'
)

$ErrorActionPreference = 'Stop'

# Normalize profile name
if (-not $Profile.StartsWith('gpt5.6-')) {
    $Profile = "gpt5.6-$Profile"
}

Write-Host "🚀 Launching Orca Terminal Profile: [$Profile] (Effort: High, Worktree: $Worktree)..." -ForegroundColor Cyan

$profilePath = ".orca/profiles/$Profile.md"
$title = "$Profile-worker"


# Create Terminal in Orca
$createJson = orca terminal create --worktree $Worktree --title $title --command "codex --profile $profilePath --effort high" --json | ConvertFrom-Json

if (-not $createJson.ok) {
    Write-Error "Failed to create Orca terminal for profile $Profile: $($createJson.error.message)"
    exit 1
}

$handle = $createJson.result.terminal.handle
Write-Host "✅ Terminal Created: $handle ($title)" -ForegroundColor Green

# Wait for tui-idle
Write-Host "⏳ Waiting for terminal handle $handle to reach tui-idle..." -ForegroundColor Yellow
$waitJson = orca terminal wait --terminal $handle --for tui-idle --timeout-ms 60000 --json | ConvertFrom-Json

if (-not $waitJson.ok) {
    Write-Error "Terminal wait failed: $($waitJson.error.message)"
    exit 1
}

Write-Host "🟢 Terminal is idle and ready." -ForegroundColor Green

# Dispatch task if TaskId provided
if ($TaskId -ne '') {
    Write-Host "📡 Dispatching Task [$TaskId] to terminal [$handle]..." -ForegroundColor Cyan
    $dispatchJson = orca orchestration dispatch --task $TaskId --to $handle --inject --json | ConvertFrom-Json
    if (-not $dispatchJson.ok) {
        Write-Error "Dispatch failed: $($dispatchJson.error.message)"
        exit 1
    }
    Write-Host "🎉 Task [$TaskId] successfully dispatched to [$handle]!" -ForegroundColor Green
}
