[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern("^[A-Za-z0-9._-]{1,64}$")]
  [string]$KeyId,

  [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
  [string]$Repository = "ks-house/smart-gatekeeper",

  [ValidatePattern("^[A-Za-z0-9_.-]{1,64}$")]
  [string]$Environment = "production",

  [string]$EncryptedBackupPath,

  [string]$PythonExecutable = "python",

  [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SecretNames = @(
  "OTA_SIGNING_PUBLIC_KEY_HEX",
  "OTA_SIGNING_KEY_ID",
  "OTA_SIGNING_PRIVATE_KEY_HEX"
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
      # The secret is sent only through stdin. Never place it in Arguments or logs.
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

    return [PSCustomObject]@{
      Stdout = $stdout
      Stderr = $stderr
    }
  }
  finally {
    $process.Dispose()
  }
}

function New-OtaSigningKeyMaterial {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonCommand
  )

  $pythonCode = @'
import hashlib
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private_key = Ed25519PrivateKey.generate()
private_seed = private_key.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
public_key = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
print(json.dumps({
    "private_seed_hex": private_seed.hex(),
    "public_key_hex": public_key.hex(),
    "public_key_sha256": hashlib.sha256(public_key).hexdigest(),
}, separators=(",", ":")))
'@

  try {
    $pythonResult = Invoke-CheckedProcess `
      -FilePath $PythonCommand `
      -Arguments "-" `
      -StandardInput $pythonCode
  }
  catch {
    throw "Ed25519 key generation failed. Install ota/requirements.txt into the selected Python environment. $($_.Exception.Message)"
  }
  $json = $pythonResult.Stdout

  $material = $json | ConvertFrom-Json
  if ($material.private_seed_hex -notmatch "^[0-9a-f]{64}$") {
    throw "Generated private seed is not exact lowercase 32-byte hex."
  }
  if ($material.public_key_hex -notmatch "^[0-9a-f]{64}$") {
    throw "Generated public key is not exact lowercase 32-byte hex."
  }
  if ($material.public_key_sha256 -notmatch "^[0-9a-f]{64}$") {
    throw "Generated public-key fingerprint is invalid."
  }
  return $material
}

function Resolve-BackupTarget {
  param(
    [Parameter(Mandatory = $true)]
    [string]$RequestedPath
  )

  $repositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
  ).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
  $backupTarget = [System.IO.Path]::GetFullPath($RequestedPath)
  $repositoryPrefix = $repositoryRoot + [System.IO.Path]::DirectorySeparatorChar

  if ($backupTarget.Equals(
      $repositoryRoot,
      [System.StringComparison]::OrdinalIgnoreCase
    ) -or $backupTarget.StartsWith(
      $repositoryPrefix,
      [System.StringComparison]::OrdinalIgnoreCase
    )) {
    throw "EncryptedBackupPath must be outside the repository."
  }
  if (Test-Path -LiteralPath $backupTarget) {
    throw "EncryptedBackupPath already exists; key backup overwrite is refused."
  }

  $parent = Split-Path -Parent $backupTarget
  if ([string]::IsNullOrWhiteSpace($parent) -or -not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "EncryptedBackupPath parent directory must already exist."
  }
  return $backupTarget
}

function Set-GitHubEnvironmentSecret {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name,

    [Parameter(Mandatory = $true)]
    [string]$Value
  )

  $arguments = "secret set $Name --env $Environment --repo $Repository"
  $null = Invoke-CheckedProcess -FilePath "gh" -Arguments $arguments -StandardInput $Value
}

$keyMaterial = $null
$privateSeed = $null
$securePrivate = $null
try {
  if ($ValidateOnly) {
    $keyMaterial = New-OtaSigningKeyMaterial -PythonCommand $PythonExecutable
    Write-Output "OTA signing key generation validation passed."
    Write-Output "Key ID: $KeyId"
    Write-Output "Public key: $($keyMaterial.public_key_hex)"
    Write-Output "Public key SHA-256: $($keyMaterial.public_key_sha256)"
    Write-Output "No GitHub secret or backup file was created."
    return
  }

  if ($env:OS -ne "Windows_NT") {
    throw "Actual registration requires Windows DPAPI; use -ValidateOnly on other platforms."
  }
  if ([string]::IsNullOrWhiteSpace($EncryptedBackupPath)) {
    throw "EncryptedBackupPath is required for actual registration."
  }
  if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
    throw "GITHUB_TOKEN is not present in the current process environment."
  }

  $backupTarget = Resolve-BackupTarget -RequestedPath $EncryptedBackupPath
  $null = Get-Command -Name "gh" -ErrorAction Stop
  $null = Get-Command -Name $PythonExecutable -ErrorAction Stop
  $null = Invoke-CheckedProcess -FilePath "gh" -Arguments "auth status --hostname github.com" -StandardInput $null

  $listResult = Invoke-CheckedProcess `
    -FilePath "gh" `
    -Arguments "secret list --env $Environment --repo $Repository --json name" `
    -StandardInput $null
  $existingNames = @($listResult.Stdout | ConvertFrom-Json | ForEach-Object { $_.name })
  $conflicts = @($SecretNames | Where-Object { $existingNames -contains $_ })
  if ($conflicts.Count -gt 0) {
    throw "Refusing to overwrite existing Environment Secrets: $($conflicts -join ', '). Use a separately reviewed rotation procedure."
  }

  $target = "$Repository environment '$Environment'"
  if (-not $PSCmdlet.ShouldProcess($target, "create an Ed25519 key, encrypted backup, and three OTA signing secrets")) {
    return
  }

  $keyMaterial = New-OtaSigningKeyMaterial -PythonCommand $PythonExecutable
  $privateSeed = [string]$keyMaterial.private_seed_hex
  $securePrivate = ConvertTo-SecureString -String $privateSeed -AsPlainText -Force
  $encryptedPrivate = ConvertFrom-SecureString -SecureString $securePrivate

  $backupRecord = [ordered]@{
    schema_version = 1
    protection = "windows-dpapi-current-user"
    repository = $Repository
    environment = $Environment
    key_id = $KeyId
    public_key_hex = [string]$keyMaterial.public_key_hex
    public_key_sha256 = [string]$keyMaterial.public_key_sha256
    private_seed_dpapi = $encryptedPrivate
  }
  $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  [System.IO.File]::WriteAllText(
    $backupTarget,
    (($backupRecord | ConvertTo-Json -Depth 3) + [Environment]::NewLine),
    $utf8NoBom
  )

  # Public metadata is registered first; the private seed is registered last.
  Set-GitHubEnvironmentSecret -Name "OTA_SIGNING_PUBLIC_KEY_HEX" -Value ([string]$keyMaterial.public_key_hex)
  Set-GitHubEnvironmentSecret -Name "OTA_SIGNING_KEY_ID" -Value $KeyId
  Set-GitHubEnvironmentSecret -Name "OTA_SIGNING_PRIVATE_KEY_HEX" -Value $privateSeed

  $verifyResult = Invoke-CheckedProcess `
    -FilePath "gh" `
    -Arguments "secret list --env $Environment --repo $Repository --json name" `
    -StandardInput $null
  $verifiedNames = @($verifyResult.Stdout | ConvertFrom-Json | ForEach-Object { $_.name })
  $missing = @($SecretNames | Where-Object { $verifiedNames -notcontains $_ })
  if ($missing.Count -gt 0) {
    throw "GitHub did not report all expected Environment Secret names: $($missing -join ', ')"
  }

  Write-Output "OTA signing secrets registered successfully."
  Write-Output "Repository/environment: $Repository / $Environment"
  Write-Output "Key ID: $KeyId"
  Write-Output "Public key: $($keyMaterial.public_key_hex)"
  Write-Output "Public key SHA-256: $($keyMaterial.public_key_sha256)"
  Write-Output "Encrypted DPAPI backup: $backupTarget"
  Write-Warning "The backup normally requires the same Windows account and machine. Store an independently protected recovery copy before production use."
}
finally {
  $privateSeed = $null
  $securePrivate = $null
  if ($null -ne $keyMaterial) {
    $keyMaterial.private_seed_hex = $null
  }
  $keyMaterial = $null
}
