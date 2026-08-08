param(
    [ValidateSet('Quick', 'Software', 'Full', 'Firmware', 'Backend', 'Contracts', 'App')]
    [string]$Suite = 'Quick',
    [switch]$EnforceFormat
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'The project .venv is missing. Run .orca/scripts/setup_worktree.ps1 first.'
}

$results = @()
function Invoke-ValidationStep {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][scriptblock]$Action
    )

    Write-Host "[validate] $Name" -ForegroundColor Cyan
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    $global:LASTEXITCODE = 0
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) {
            throw "Command exited with code $LASTEXITCODE."
        }
        $timer.Stop()
        $script:results += [pscustomobject]@{ name = $Name; status = 'passed'; seconds = [math]::Round($timer.Elapsed.TotalSeconds, 2) }
        Write-Host "[pass] $Name" -ForegroundColor Green
    } catch {
        $timer.Stop()
        $script:results += [pscustomobject]@{ name = $Name; status = 'failed'; seconds = [math]::Round($timer.Elapsed.TotalSeconds, 2); error = $_.Exception.Message }
        Write-Host "[fail] $Name - $($_.Exception.Message)" -ForegroundColor Red
        throw
    }
}

$runDoctor = @('Quick', 'Software', 'Full') -contains $Suite
$runBackend = @('Quick', 'Software', 'Full', 'Backend') -contains $Suite
$runContracts = @('Quick', 'Software', 'Full', 'Contracts') -contains $Suite
$runRootTests = @('Software', 'Full') -contains $Suite
$runFirmware = @('Full', 'Firmware') -contains $Suite
$runApp = @('Full', 'App') -contains $Suite

if ($runDoctor) {
    Invoke-ValidationStep 'Environment doctor' { & (Join-Path $PSScriptRoot 'doctor.ps1') }
}

if ($runBackend) {
    Invoke-ValidationStep 'Backend unit tests' { & $venvPython -m unittest discover -s backend/tests -p 'test_*.py' }
    Invoke-ValidationStep 'Backend Compose configuration' { & docker compose -f backend/docker-compose.yml config --quiet }
}

if ($runContracts) {
    Invoke-ValidationStep 'Orca lifecycle probe tests' { & powershell -NoProfile -ExecutionPolicy Bypass -File .orca/tests/test_lifecycle_probe.ps1 }
    Invoke-ValidationStep 'Protocol canonical vectors' { & $venvPython protocol/tools/verify_vectors.py }
    Invoke-ValidationStep 'Protocol Python tests' { & $venvPython -m unittest discover -s protocol/tests -p 'test_*.py' }
    Invoke-ValidationStep 'Observability tests' { & $venvPython -m unittest discover -s observability/tests -p 'test_*.py' }
    Invoke-ValidationStep 'OTA contract gate' { & $venvPython scripts/ota_contract_gate.py contract }
    Invoke-ValidationStep 'Hardwareless release gates' { & $venvPython -m unittest tests/test_hardwareless_implementation_gates.py }
}

if ($runRootTests) {
    Invoke-ValidationStep 'Root software test suite' { & $venvPython -m unittest discover -s tests -p 'test_*.py' }
}

if ($runFirmware) {
    Invoke-ValidationStep 'ESP32-C6 PlatformIO build' { & pio run -e esp32c6 -j 4 }
}

if ($runApp) {
    $flutterCommand = Get-Command flutter -ErrorAction SilentlyContinue
    if ($null -ne $flutterCommand) {
        Invoke-ValidationStep 'Flutter analyze and tests (native)' {
            $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("sgk-app-validation-{0}" -f [guid]::NewGuid().ToString('N'))
            $resolvedTempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
            $resolvedTemporaryRoot = [System.IO.Path]::GetFullPath($temporaryRoot)
            if (-not $resolvedTemporaryRoot.StartsWith($resolvedTempParent, [System.StringComparison]::OrdinalIgnoreCase) -or
                -not ([System.IO.Path]::GetFileName($resolvedTemporaryRoot)).StartsWith('sgk-app-validation-', [System.StringComparison]::Ordinal)) {
                throw "Refusing unsafe temporary validation path: $resolvedTemporaryRoot"
            }

            New-Item -ItemType Directory -Path $resolvedTemporaryRoot | Out-Null
            try {
                # Copy tracked and non-ignored app sources only. Native pub get,
                # Gradle, analyze, and tests must never mutate the worktree.
                $appFiles = @(& git -C $projectRoot ls-files --cached --others --exclude-standard -- gatekeeper_app)
                if ($LASTEXITCODE -ne 0) { throw 'Could not enumerate app source files.' }
                foreach ($appFile in $appFiles) {
                    $relativePath = $appFile.Substring('gatekeeper_app/'.Length).Replace('/', [System.IO.Path]::DirectorySeparatorChar)
                    $sourcePath = Join-Path $projectRoot $appFile
                    $destinationPath = Join-Path $resolvedTemporaryRoot $relativePath
                    $destinationParent = Split-Path -Parent $destinationPath
                    if (-not (Test-Path -LiteralPath $destinationParent)) {
                        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
                    }
                    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
                }

                Push-Location -LiteralPath $resolvedTemporaryRoot
                & flutter pub get
                if ($LASTEXITCODE -ne 0) { throw "flutter pub get exited with code $LASTEXITCODE." }
                if ($EnforceFormat) {
                    & dart format --output=none --set-exit-if-changed lib test
                    if ($LASTEXITCODE -ne 0) { throw "dart format exited with code $LASTEXITCODE." }
                }
                & dart analyze lib test
                if ($LASTEXITCODE -ne 0) { throw "dart analyze exited with code $LASTEXITCODE." }
                & flutter test
                if ($LASTEXITCODE -ne 0) { throw "flutter test exited with code $LASTEXITCODE." }
            } finally {
                if ((Get-Location).Path -eq $resolvedTemporaryRoot) {
                    Pop-Location
                }
                if (Test-Path -LiteralPath $resolvedTemporaryRoot) {
                    Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
                }
            }
        }
    } else {
        Invoke-ValidationStep 'Flutter analyze and tests (Docker)' {
            & docker compose -f gatekeeper_app/docker-compose.yml build flutter-builder
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            $prepareContainerWorkspace = 'rm -rf /tmp/sgk-app-validation && mkdir -p /tmp/sgk-app-validation && cp /workspace/pubspec.yaml /workspace/pubspec.lock /workspace/analysis_options.yaml /workspace/.metadata /tmp/sgk-app-validation/ && cp -a /workspace/lib /workspace/test /workspace/android /tmp/sgk-app-validation/'
            $containerCommand = "$prepareContainerWorkspace && cd /tmp/sgk-app-validation && flutter pub get && dart analyze lib test && flutter test"
            if ($EnforceFormat) {
                $containerCommand = "$prepareContainerWorkspace && cd /tmp/sgk-app-validation && flutter pub get && dart format --output=none --set-exit-if-changed lib test && dart analyze lib test && flutter test"
            }
            & docker compose -f gatekeeper_app/docker-compose.yml run --rm flutter-builder bash -lc $containerCommand
        }
    }
}

$totalSeconds = [math]::Round((($results | Measure-Object -Property seconds -Sum).Sum), 2)
Write-Host "[validate] Suite $Suite passed in $totalSeconds seconds." -ForegroundColor Green
$results | Format-Table -AutoSize
