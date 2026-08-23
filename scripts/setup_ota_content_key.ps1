[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern("^[A-Za-z0-9._-]{1,64}$")]
  [string]$KeyId,

  [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
  [string]$Repository = "ks-house/smart-gatekeeper",

  [Parameter(Mandatory = $true)]
  [ValidateCount(1, 8)]
  [ValidateNotNullOrEmpty()]
  [ValidatePattern("^[A-Za-z0-9._-]{1,255}$")]
  [string[]]$Environments,

  [Parameter(Mandatory = $true)]
  [string]$EncryptedBackupPath,

  [string[]]$LocalSecretsPaths = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SecretNames = @(
  "SECRET_OTA_CONTENT_KEY_HEX",
  "SECRET_OTA_CONTENT_KEY_ID"
)

function Invoke-CheckedProcess {
  param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [Parameter(Mandatory = $true)]
    [string]$Arguments,
    [AllowNull()]
    [string]$StandardInput,
    [int]$TimeoutSeconds = 30
  )

  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $FilePath
  $startInfo.Arguments = $Arguments
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $startInfo.RedirectStandardInput = $null -ne $StandardInput

  $process = [System.Diagnostics.Process]::new()
  $process.StartInfo = $startInfo
  if (-not $process.Start()) {
    throw "Failed to start required command: $FilePath"
  }
  try {
    if ($null -ne $StandardInput) {
      $process.StandardInput.Write($StandardInput)
      $process.StandardInput.Close()
    }
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
      $process.Kill()
      throw "Command timed out after $TimeoutSeconds seconds: $FilePath"
    }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if ($process.ExitCode -ne 0) {
      $detail = $stderr.Trim()
      if ([string]::IsNullOrWhiteSpace($detail)) {
        $detail = $stdout.Trim()
      }
      throw "Command failed ($FilePath, exit $($process.ExitCode)): $detail"
    }
    return [PSCustomObject]@{ Stdout = $stdout; Stderr = $stderr }
  }
  finally {
    $process.Dispose()
  }
}

function Get-SecretNames {
  param([Parameter(Mandatory = $true)][string]$Environment)
  $result = Invoke-CheckedProcess `
    -FilePath "gh" `
    -Arguments "secret list --env $Environment --repo $Repository --json name" `
    -StandardInput $null
  $parsed = ConvertFrom-Json -InputObject $result.Stdout
  return @($parsed | ForEach-Object { [string]$_.name })
}

function Set-EnvironmentSecret {
  param(
    [Parameter(Mandatory = $true)][string]$Environment,
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$Value
  )
  $null = Invoke-CheckedProcess `
    -FilePath "gh" `
    -Arguments "secret set $Name --env $Environment --repo $Repository" `
    -StandardInput $Value
}

function Resolve-NewBackupPath {
  $repositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
  ).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
  $target = [System.IO.Path]::GetFullPath($EncryptedBackupPath)
  $prefix = $repositoryRoot + [System.IO.Path]::DirectorySeparatorChar
  if ($target.Equals($repositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
      $target.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "EncryptedBackupPath must be outside the repository."
  }
  if (Test-Path -LiteralPath $target) {
    throw "EncryptedBackupPath already exists; overwrite is refused."
  }
  $parent = Split-Path -Parent $target
  if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "EncryptedBackupPath parent directory must already exist."
  }
  return $target
}

function Set-LocalContentKey {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ContentKeyHex
  )
  $resolved = [System.IO.Path]::GetFullPath($Path)
  if ((Split-Path -Leaf $resolved) -ne "secrets.h" -or
      -not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "Local secret target must be an existing include/secrets.h file: $resolved"
  }
  $text = [System.IO.File]::ReadAllText($resolved)
  foreach ($name in $SecretNames) {
    $matches = [regex]::Matches($text, "(?m)^\s*#define\s+$name\b.*$")
    if ($matches.Count -gt 1) {
      throw "Local secrets file contains duplicate $name definitions: $resolved"
    }
  }
  $values = [ordered]@{
    SECRET_OTA_CONTENT_KEY_HEX = $ContentKeyHex
    SECRET_OTA_CONTENT_KEY_ID = $KeyId
  }
  foreach ($entry in $values.GetEnumerator()) {
    $replacement = "#define $($entry.Key) `"$($entry.Value)`""
    $pattern = "(?m)^\s*#define\s+$($entry.Key)\b.*$"
    if ([regex]::IsMatch($text, $pattern)) {
      $text = [regex]::Replace($text, $pattern, $replacement)
    }
    else {
      $text = $text.TrimEnd("`r", "`n") + [Environment]::NewLine + $replacement + [Environment]::NewLine
    }
  }
  $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  [System.IO.File]::WriteAllText($resolved, $text, $utf8NoBom)
}

$contentKeyHex = $null
$secureContentKey = $null
try {
  if ($env:OS -ne "Windows_NT") {
    throw "Registration requires Windows DPAPI."
  }
  if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
    throw "GITHUB_TOKEN is not present in the current process environment."
  }
  $backupTarget = Resolve-NewBackupPath
  $null = Get-Command -Name "gh" -ErrorAction Stop
  $null = Invoke-CheckedProcess `
    -FilePath "gh" `
    -Arguments "auth status --hostname github.com" `
    -StandardInput $null

  foreach ($environment in $Environments) {
    $existing = @(Get-SecretNames -Environment $environment)
    $conflicts = @($SecretNames | Where-Object { $existing -contains $_ })
    if ($conflicts.Count -gt 0) {
      throw "Refusing to overwrite existing secrets in $environment`: $($conflicts -join ', ')"
    }
  }

  if (-not $PSCmdlet.ShouldProcess(
      "$Repository environments $($Environments -join ', ')",
      "generate, DPAPI-back up, register, and locally provision a dedicated OTA content key"
    )) {
    return
  }

  $bytes = New-Object byte[] 32
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try {
    $rng.GetBytes($bytes)
  }
  finally {
    $rng.Dispose()
  }
  $contentKeyHex = ([System.BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
  [Array]::Clear($bytes, 0, $bytes.Length)
  if ($contentKeyHex -notmatch "^[0-9a-f]{64}$") {
    throw "Generated OTA content key has an invalid format."
  }

  $secureContentKey = ConvertTo-SecureString -String $contentKeyHex -AsPlainText -Force
  $backupRecord = [ordered]@{
    schema_version = 1
    protection = "windows-dpapi-current-user"
    repository = $Repository
    environments = @($Environments)
    key_id = $KeyId
    content_key_dpapi = ConvertFrom-SecureString -SecureString $secureContentKey
  }
  $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  [System.IO.File]::WriteAllText(
    $backupTarget,
    (($backupRecord | ConvertTo-Json -Depth 4) + [Environment]::NewLine),
    $utf8NoBom
  )

  foreach ($environment in $Environments) {
    Set-EnvironmentSecret -Environment $environment -Name "SECRET_OTA_CONTENT_KEY_ID" -Value $KeyId
    Set-EnvironmentSecret -Environment $environment -Name "SECRET_OTA_CONTENT_KEY_HEX" -Value $contentKeyHex
  }
  foreach ($path in $LocalSecretsPaths) {
    Set-LocalContentKey -Path $path -ContentKeyHex $contentKeyHex
  }

  foreach ($environment in $Environments) {
    $registered = @(Get-SecretNames -Environment $environment)
    $missing = @($SecretNames | Where-Object { $registered -notcontains $_ })
    if ($missing.Count -gt 0) {
      throw "GitHub did not report all expected secrets in $environment`: $($missing -join ', ')"
    }
  }
  Write-Output "Dedicated Target OTA content key registered and locally provisioned."
  Write-Output "Repository/environments: $Repository / $($Environments -join ', ')"
  Write-Output "Key ID: $KeyId"
  Write-Output "Encrypted DPAPI backup: $backupTarget"
}
finally {
  $contentKeyHex = $null
  $secureContentKey = $null
}
