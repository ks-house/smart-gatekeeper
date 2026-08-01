[CmdletBinding()]
param(
  [string]$Package = "com.kshouse.gatekeeper_app",
  [string]$Serial = "",
  [string]$ApkPath = "",
  [ValidateRange(1, 200)]
  [int]$Trials = 20
)

$ErrorActionPreference = "Stop"
$adbCommand = Get-Command adb -ErrorAction Stop
$adbPrefix = @()
if ($Serial) {
  $adbPrefix = @("-s", $Serial)
}

function Invoke-Adb {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
  & $adbCommand.Source @adbPrefix @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "adb failed: $($Arguments -join ' ')"
  }
}

if ($ApkPath) {
  $resolvedApk = (Resolve-Path -LiteralPath $ApkPath).Path
  Invoke-Adb install -r $resolvedApk
}

$packageList = (& $adbCommand.Source @adbPrefix shell pm list packages $Package) -join "`n"
if ($LASTEXITCODE -ne 0 -or $packageList -notmatch "package:$([regex]::Escape($Package))") {
  throw "Debug APK is not installed for package $Package. Pass -ApkPath or install it first."
}

# Clear Android's post-install stopped state once, then kill only the ordinary
# background process. The following explicit debug broadcasts therefore create
# a native receiver process without relying on a running Flutter engine.
Invoke-Adb shell monkey -p $Package -c android.intent.category.LAUNCHER 1 | Out-Null
Invoke-Adb shell input keyevent 3 | Out-Null
Invoke-Adb shell am kill $Package | Out-Null

$action = "$Package.blewake.DEBUG_COMMAND"
$component = "$Package/.blewake.BleWakeDebugCommandReceiver"
Invoke-Adb logcat -c
Invoke-Adb shell am broadcast -a $action -n $component --es command reset | Out-Null

for ($iteration = 1; $iteration -le $Trials; $iteration++) {
  Invoke-Adb shell am broadcast -a $action -n $component `
    --es command inject `
    --es scenario hardwareless `
    --ei iteration $iteration `
    --el latency_ms $iteration `
    --ez success true | Out-Null
}

Invoke-Adb shell am broadcast -a $action -n $component --es command dump | Out-Null
$logs = (& $adbCommand.Source @adbPrefix logcat -d -s "BLE_WAKE_POC:I" "*:S") -join "`n"
if ($LASTEXITCODE -ne 0) {
  throw "Unable to read BLE_WAKE_POC logcat output."
}

if ($logs -notmatch ('"attempts":' + $Trials)) {
  throw "Expected $Trials synthetic attempts in the native journal summary."
}
if ($logs -notmatch '"source":"synthetic"') {
  throw "Synthetic source marker is missing; refusing to treat this as a valid hardwareless run."
}

Write-Output $logs
Write-Output "PASS: native receiver seam recorded $Trials synthetic trials."
Write-Output "NOTE: this validates only hardwareless dispatch/journal/statistics; it is not Samsung BLE wake evidence."
