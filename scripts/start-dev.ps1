<#
    Start BIM RAG (Task 12): checks prerequisites, starts/reuses the backend and
    frontend dev servers in two visible terminals, waits for readiness, and opens
    the app in the default browser exactly once.

    Usage:
        powershell -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1

    This script does not install dependencies, run ingestion, prepare viewer
    artifacts, or mutate the database. It only starts/reuses two already-built
    local dev servers.
#>

[CmdletBinding()]
param(
    # `poetry run uvicorn --reload` on Windows can measurably exceed a minute on
    # a cold start here: `poetry run` resolution overhead plus the reload file
    # watcher's initial recursive scan of `backend/` (including the large CUDA
    # torch install under `.venv/`) before the app starts serving. 150s gives
    # real headroom without waiting forever if something is actually wrong.
    [int]$BackendTimeoutSec = 150,
    [int]$FrontendTimeoutSec = 90,
    # Convenience for scripted validation; normal double-click launches open the
    # browser (spec: "open http://localhost:5173 ... once ready").
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$RepoRoot     = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BackendDir   = Join-Path $RepoRoot 'backend'
$FrontendDir  = Join-Path $RepoRoot 'frontend'
$BackendUrl   = 'http://localhost:8000'
$FrontendUrl  = 'http://localhost:5173'
$BackendPort  = 8000
$FrontendPort = 5173

function Stop-WithPause {
    param([int]$Code = 1)
    Write-Host ''
    Read-Host 'Press Enter to close this window'
    exit $Code
}

Write-Info 'BIM RAG launcher'
Write-Info "Repository root: $RepoRoot"
Write-Host ''

# ---------------------------------------------------------------------------
# 1. Prerequisite checks (read-only; never installs/modifies anything)
# ---------------------------------------------------------------------------
Write-Info 'Checking prerequisites...'
$failed = $false

if (-not (Test-CommandAvailable 'powershell.exe')) {
    Write-ErrorMsg 'Windows PowerShell (powershell.exe) was not found on PATH.'
    $failed = $true
}
if (-not (Test-CommandAvailable 'poetry')) {
    Write-ErrorMsg 'Poetry was not found on PATH. Install it: https://python-poetry.org/docs/#installation'
    $failed = $true
}
if (-not (Test-CommandAvailable 'npm')) {
    Write-ErrorMsg 'npm was not found on PATH. Install Node.js: https://nodejs.org/'
    $failed = $true
}

$backendPyproject = Join-Path $BackendDir 'pyproject.toml'
if (-not (Test-Path -LiteralPath $backendPyproject)) {
    Write-ErrorMsg "Missing $backendPyproject"
    $failed = $true
}

$frontendPackageJson = Join-Path $FrontendDir 'package.json'
if (-not (Test-Path -LiteralPath $frontendPackageJson)) {
    Write-ErrorMsg "Missing $frontendPackageJson"
    $failed = $true
}

if (-not $failed) {
    # Backend Poetry environment usable? `poetry env info` + a plain module
    # import (no DB/OpenAI access — app.main only builds the FastAPI app object;
    # config/DB connections are lazily created per request) — no install occurs.
    $backendUsable = $false
    Push-Location $BackendDir
    try {
        $envPath = & poetry env info --path 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($envPath)) {
            & poetry run python -c "import app.main" 2>$null
            if ($LASTEXITCODE -eq 0) { $backendUsable = $true }
        }
    } catch {
        $backendUsable = $false
    } finally {
        Pop-Location
    }
    if (-not $backendUsable) {
        Write-ErrorMsg 'The backend Poetry environment is not ready.'
        Write-ErrorMsg 'Run this once, then re-launch:'
        Write-ErrorMsg '    cd backend; poetry install'
        $failed = $true
    }

    # Frontend dependencies installed sufficiently to run `npm run dev`?
    $frontendNodeModules = Join-Path $FrontendDir 'node_modules'
    $frontendVitePkg = Join-Path $frontendNodeModules 'vite\package.json'
    if (-not (Test-Path -LiteralPath $frontendNodeModules) -or -not (Test-Path -LiteralPath $frontendVitePkg)) {
        Write-ErrorMsg 'Frontend dependencies are not installed.'
        Write-ErrorMsg 'Run this once, then re-launch:'
        Write-ErrorMsg '    cd frontend; npm install'
        $failed = $true
    }
}

# Existence only — never opened/printed/logged.
$envFile = Join-Path $RepoRoot '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    Write-ErrorMsg "Missing repository-root .env file ($envFile)."
    Write-ErrorMsg 'Create it before launching (see README.md "Configuration").'
    $failed = $true
}

$modelAssetsDir = Join-Path $RepoRoot 'model_assets'
$hasArtifact = $false
if (Test-Path -LiteralPath $modelAssetsDir) {
    $hasArtifact = [bool](
        Get-ChildItem -LiteralPath $modelAssetsDir -Filter '*.frag' -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
}
if (-not $hasArtifact) {
    Write-Warn 'No prepared viewer artifact (*.frag) found under model_assets\.'
    Write-Warn '3D model visualization may be unavailable until one is prepared (see frontend\README.md).'
}

if ($failed) {
    Write-Host ''
    Write-ErrorMsg 'Prerequisite checks failed. Nothing was started.'
    Stop-WithPause
}

Write-Good 'Prerequisites OK.'
Write-Host ''

# ---------------------------------------------------------------------------
# 2. Load and prune the existing runtime record (stale-PID defensive check)
# ---------------------------------------------------------------------------
function ConvertTo-ServiceMap {
    param($RawRecord)
    $map = [ordered]@{}
    if ($RawRecord -and $RawRecord.services) {
        foreach ($prop in $RawRecord.services.PSObject.Properties) {
            $map[$prop.Name] = $prop.Value
        }
    }
    return $map
}

function Test-RecordEntryAlive {
    param($Entry, [string]$Marker)
    if ($null -eq $Entry) { return $false }
    $proc = Get-Process -Id $Entry.pid -ErrorAction SilentlyContinue
    if ($null -eq $proc) { return $false }
    $cmdLine = Get-ProcessCommandLine -ProcessId $Entry.pid
    if ($null -eq $cmdLine -or ($cmdLine -notmatch [regex]::Escape($Marker))) { return $false }
    return $true
}

$rawRecord = Read-RuntimeRecord -RepoRoot $RepoRoot
$services = ConvertTo-ServiceMap -RawRecord $rawRecord

foreach ($svc in @('backend', 'frontend')) {
    if ($services.Contains($svc)) {
        $marker = if ($svc -eq 'backend') { $BackendMarker } else { $FrontendMarker }
        if (-not (Test-RecordEntryAlive -Entry $services[$svc] -Marker $marker)) {
            $services.Remove($svc)
        }
    }
}

function Save-Services {
    $record = [ordered]@{
        launcherVersion = '1.0'
        updatedAt       = (Get-Date).ToString('o')
        services        = $services
    }
    Save-RuntimeRecord -RepoRoot $RepoRoot -Record $record
}

# ---------------------------------------------------------------------------
# 3. Classify both ports (reused / absent / conflict) BEFORE starting anything,
#    then only start whichever services are actually absent (§5: never leave
#    one service started when the launch as a whole is going to abort).
# ---------------------------------------------------------------------------
Write-Info "Backend (port $BackendPort)..."
function Get-PortClassification {
    param([int]$Port, [scriptblock]$IdentityCheck, [string]$ServiceLabel)
    if (-not (Test-PortOpen -Port $Port)) { return 'Absent' }
    if (& $IdentityCheck) { return 'Reused' }
    Write-ErrorMsg "  Port $Port is already in use by another application (not the BIM RAG $ServiceLabel)."
    Write-ErrorMsg '  Free the port or stop that application, then re-launch.'
    return 'Conflict'
}

$backendClass = Get-PortClassification -Port $BackendPort -ServiceLabel 'backend' -IdentityCheck {
    Test-BimRagBackendIdentity -BaseUrl $BackendUrl
}
if ($backendClass -eq 'Reused') { Write-Good '  Already running - reusing the existing BIM RAG backend.' }

Write-Info "Frontend (port $FrontendPort)..."
$frontendClass = Get-PortClassification -Port $FrontendPort -ServiceLabel 'frontend' -IdentityCheck {
    Test-BimRagFrontendIdentity -BaseUrl $FrontendUrl
}
if ($frontendClass -eq 'Reused') { Write-Good '  Already running - reusing the existing BIM RAG frontend.' }

# Classify BOTH ports before starting anything: a conflict on one service must
# not leave the other service started with nothing to pair it with.
if ($backendClass -eq 'Conflict' -or $frontendClass -eq 'Conflict') {
    Write-Host ''
    Write-ErrorMsg 'Launch aborted due to port conflict(s). See messages above. Nothing was started.'
    Stop-WithPause
}

$backendStatus = $backendClass
if ($backendClass -eq 'Absent') {
    Write-Host '  Starting backend terminal...'
    $cmd = "`$host.UI.RawUI.WindowTitle = 'BIM RAG Backend'; `$env:BIMRAG_MARKER = '$BackendMarker'; " +
           "Set-Location -LiteralPath '$BackendDir'; poetry run uvicorn app.main:app --reload"
    $proc = Start-Process -FilePath 'powershell.exe' -WorkingDirectory $BackendDir `
        -ArgumentList @('-NoExit', '-NoProfile', '-Command', $cmd) -PassThru
    $services['backend'] = [ordered]@{
        owned     = $true
        pid       = $proc.Id
        port      = $BackendPort
        name      = 'backend'
        startedAt = (Get-Date).ToString('o')
    }
    $backendStatus = 'Started'
}
Save-Services

$frontendStatus = $frontendClass
if ($frontendClass -eq 'Absent') {
    Write-Host '  Starting frontend terminal...'
    $cmd = "`$host.UI.RawUI.WindowTitle = 'BIM RAG Frontend'; `$env:BIMRAG_MARKER = '$FrontendMarker'; " +
           "Set-Location -LiteralPath '$FrontendDir'; npm run dev"
    $proc = Start-Process -FilePath 'powershell.exe' -WorkingDirectory $FrontendDir `
        -ArgumentList @('-NoExit', '-NoProfile', '-Command', $cmd) -PassThru
    $services['frontend'] = [ordered]@{
        owned     = $true
        pid       = $proc.Id
        port      = $FrontendPort
        name      = 'frontend'
        startedAt = (Get-Date).ToString('o')
    }
    $frontendStatus = 'Started'
}
Save-Services

# ---------------------------------------------------------------------------
# 5. Wait for bounded readiness (never waits forever)
# ---------------------------------------------------------------------------
Write-Host ''
Write-Info 'Waiting for services to become ready...'

$backendHealthy = Wait-Until -Description 'backend /health' -TimeoutSec $BackendTimeoutSec -Condition {
    try {
        $r = Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 2 -ErrorAction Stop
        return ($r.status -eq 'ok')
    } catch {
        return $false
    }
}

if (-not $backendHealthy) {
    Write-ErrorMsg "Backend did not become healthy within ${BackendTimeoutSec}s."
    Write-ErrorMsg "Check the 'BIM RAG Backend' terminal window for details."
    Stop-WithPause
}
Write-Good '  Backend application is up.'

# /health confirms the app is up; /ready additionally reports DB connectivity
# (spec: distinguish application availability from database readiness).
$backendFullyReady = $false
$dbMessage = $null
try {
    $readyResp = Invoke-RestMethod -Uri "$BackendUrl/ready" -TimeoutSec 5 -ErrorAction Stop
    if ($readyResp.status -eq 'ok') {
        $backendFullyReady = $true
    } else {
        $dbMessage = $readyResp.database.error
    }
} catch {
    $dbMessage = 'could not reach /ready'
}

if ($backendFullyReady) {
    Write-Good '  Backend ready (database connected).'
} else {
    # Do not hide this, and do not claim the full application is ready — but
    # also do not block forever, since the frontend has its own degraded-state
    # handling for a backend/database that is not fully up (spec_v006 Task 11).
    Write-Warn "  Backend application is up, but the database is not ready: $dbMessage"
    Write-Warn '  The application is NOT fully ready until this is resolved.'
}

$frontendReady = Wait-Until -Description 'frontend' -TimeoutSec $FrontendTimeoutSec -Condition {
    Test-BimRagFrontendIdentity -BaseUrl $FrontendUrl
}

if (-not $frontendReady) {
    Write-ErrorMsg "Frontend did not become ready within ${FrontendTimeoutSec}s."
    Write-ErrorMsg "Check the 'BIM RAG Frontend' terminal window for details."
    Stop-WithPause
}
Write-Good '  Frontend is up.'

# ---------------------------------------------------------------------------
# 6. Open the browser exactly once (never submits a query / never calls OpenAI)
# ---------------------------------------------------------------------------
Write-Host ''
if (-not $NoBrowser) {
    Write-Info "Opening $FrontendUrl ..."
    Start-Process $FrontendUrl
} else {
    Write-Info 'Skipping browser open (-NoBrowser).'
}

Write-Host ''
Write-Good 'BIM RAG is running.'
Write-Host "  Backend:  $BackendUrl  ($backendStatus)"
Write-Host "  Frontend: $FrontendUrl  ($frontendStatus)"
if (-not $backendFullyReady) {
    Write-Warn '  Note: backend database is not ready - see the backend terminal.'
}
Write-Host ''
Write-Host 'To stop launcher-owned services later, run:'
Write-Host "    powershell -ExecutionPolicy Bypass -File `"$RepoRoot\scripts\stop-dev.ps1`""
Write-Host ''

# Successful startup: this orchestration window may close on its own.
Start-Sleep -Seconds 2
