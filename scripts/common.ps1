<#
    Shared helpers for the local BIM RAG dev launcher (Task 12).

    Dot-sourced by start-dev.ps1 and stop-dev.ps1. Not a required file per the
    task spec, but keeps port/identity/process-tree/runtime-record logic in one
    place instead of duplicated across both scripts.

    No external module dependency: everything here uses built-in Windows
    PowerShell 5.1 cmdlets and .NET types only.
#>

# Distinctive tokens embedded in each launcher-spawned terminal's command line so
# start-dev.ps1 (on reuse) and stop-dev.ps1 (on stop) can verify a recorded PID
# still belongs to a process THIS launcher started, not an unrelated process that
# happens to have reused the same PID (spec: "verify process identity before
# reuse or termination").
$BackendMarker = 'BIMRAG-LAUNCHER-BACKEND-V1'
$FrontendMarker = 'BIMRAG-LAUNCHER-FRONTEND-V1'

# Literal command fragments that identify each service's actual server process,
# used only as a narrow SECOND factor (see Get-PortOwnerIfMatching below) —
# never as sole justification for stopping a process.
$ServiceIdentityPattern = @{
    backend  = 'app\.main:app'
    frontend = 'vite'
}

function Write-Info {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host $Message -ForegroundColor Cyan
}

function Write-Good {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-Warn {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host $Message -ForegroundColor Yellow
}

function Write-ErrorMsg {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Test-CommandAvailable {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-SingleAddressPortOpen {
    param([Parameter(Mandatory)][System.Net.IPAddress]$Address, [Parameter(Mandatory)][int]$Port, [int]$TimeoutMs = 500)
    # The parameterless TcpClient() constructor creates an IPv4-only socket under
    # Windows PowerShell 5.1's .NET Framework runtime — it silently (exception,
    # caught below) refuses to connect to an IPv6 address no matter how that
    # address is passed in. The client's AddressFamily must be constructed to
    # match the target address explicitly.
    $client = New-Object System.Net.Sockets.TcpClient($Address.AddressFamily)
    try {
        $async = $client.BeginConnect($Address, $Port, $null, $null)
        $signaled = $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if ($signaled -and $client.Connected) {
            $client.EndConnect($async)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# Checks BOTH loopback address families explicitly. Different local dev servers
# bind different families by default on this stack (observed: uvicorn binds
# IPv4-only 127.0.0.1; Vite's default `host` resolution binds IPv6-only ::1) —
# relying on a single hardcoded family caused a false "port closed" read on the
# other service and a duplicate launch, so both are always tried.
function Test-PortOpen {
    param([Parameter(Mandatory)][int]$Port, [int]$TimeoutMs = 500)
    if (Test-SingleAddressPortOpen -Address ([System.Net.IPAddress]::Loopback) -Port $Port -TimeoutMs $TimeoutMs) { return $true }
    if (Test-SingleAddressPortOpen -Address ([System.Net.IPAddress]::IPv6Loopback) -Port $Port -TimeoutMs $TimeoutMs) { return $true }
    return $false
}

# Confirms port 8000 is answering as THIS project's backend (not merely "a"
# server on that port) by checking the FastAPI app title in its OpenAPI schema
# (app/api/app.py: FastAPI(title="BIM RAG Query API", ...)).
function Test-BimRagBackendIdentity {
    param(
        [string]$BaseUrl = 'http://localhost:8000',
        [int]$TimeoutSec = 3
    )
    try {
        $resp = Invoke-RestMethod -Uri "$BaseUrl/openapi.json" -TimeoutSec $TimeoutSec -ErrorAction Stop
        return ($resp.info.title -eq 'BIM RAG Query API')
    } catch {
        return $false
    }
}

# Confirms port 5173 is answering as THIS project's frontend by checking the
# page title (frontend/index.html: <title>BIM Model Explorer</title>), so an
# unrelated Vite dev server on the same port is not mistaken for BIM RAG.
function Test-BimRagFrontendIdentity {
    param(
        [string]$BaseUrl = 'http://localhost:5173',
        [int]$TimeoutSec = 3
    )
    try {
        $resp = Invoke-WebRequest -Uri $BaseUrl -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        return ($resp.StatusCode -eq 200 -and $resp.Content -match 'BIM Model Explorer')
    } catch {
        return $false
    }
}

# Bounded poll (never waits forever). Prints progress at coarse (~10s) intervals.
function Wait-Until {
    param(
        [Parameter(Mandatory)][scriptblock]$Condition,
        [int]$TimeoutSec = 60,
        [int]$IntervalSec = 2,
        [string]$Description = 'condition'
    )
    $elapsed = 0
    $nextReport = 10
    while ($elapsed -lt $TimeoutSec) {
        if (& $Condition) { return $true }
        if ($elapsed -ge $nextReport) {
            Write-Host ("  ... still waiting for {0} ({1}s elapsed)" -f $Description, $elapsed) -ForegroundColor DarkGray
            $nextReport += 10
        }
        Start-Sleep -Seconds $IntervalSec
        $elapsed += $IntervalSec
    }
    return $false
}

function Get-RuntimeRecordPath {
    param([Parameter(Mandatory)][string]$RepoRoot)
    Join-Path $RepoRoot '.runtime\dev-processes.json'
}

# Returns $null if no record exists or it cannot be parsed (never throws).
function Read-RuntimeRecord {
    param([Parameter(Mandatory)][string]$RepoRoot)
    $path = Get-RuntimeRecordPath -RepoRoot $RepoRoot
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        return Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $null
    }
}

# Record contains ONLY nonsecret operational data: launcher version, PIDs,
# service names/ports, start times. Never environment values, .env contents,
# credentials, or chat/model data.
function Save-RuntimeRecord {
    param(
        [Parameter(Mandatory)][string]$RepoRoot,
        [Parameter(Mandatory)]$Record
    )
    $dir = Join-Path $RepoRoot '.runtime'
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $path = Get-RuntimeRecordPath -RepoRoot $RepoRoot
    $Record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $path -Encoding UTF8
}

function Remove-RuntimeRecord {
    param([Parameter(Mandatory)][string]$RepoRoot)
    $path = Get-RuntimeRecordPath -RepoRoot $RepoRoot
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

function Get-ChildProcessIds {
    param([Parameter(Mandatory)][int]$ParentId)
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty ProcessId
}

function Get-ProcessCommandLine {
    param([Parameter(Mandatory)][int]$ProcessId)
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($p) { return $p.CommandLine }
    return $null
}

# Returns the PID currently listening on $Port ONLY IF its command line also
# matches $Pattern (defense-in-depth for the case where `uvicorn --reload`'s
# multiprocessing-spawned worker outlived the reload-watcher we already stopped,
# so it no longer carries our launcher marker but is still identifiably our own
# server). This is a narrow, pattern-verified fallback — never "stop whatever
# owns the port," which the spec explicitly prohibits.
function Get-PortOwnerIfMatching {
    param([Parameter(Mandatory)][int]$Port, [Parameter(Mandatory)][string]$Pattern)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    $ownerPid = $conn.OwningProcess
    $cmdLine = Get-ProcessCommandLine -ProcessId $ownerPid
    if ($cmdLine -and ($cmdLine -match $Pattern)) {
        return $ownerPid
    }
    return $null
}

# Enumerates a process tree via BFS. Re-scans a few times with a short pause:
# `uvicorn --reload` on Windows runs its actual server as a Python
# `multiprocessing.spawn` child of the reload watcher, and that child can appear
# a beat after the watcher itself starts — a single-pass scan can miss it and
# leave an orphan holding the port once the watcher is killed.
function Get-ProcessTreeIds {
    param(
        [Parameter(Mandatory)][int]$RootProcessId,
        [int]$Passes = 3,
        [int]$PauseMs = 400
    )
    $ids = New-Object System.Collections.Generic.List[int]
    $ids.Add($RootProcessId)

    for ($pass = 0; $pass -lt $Passes; $pass++) {
        $queue = New-Object System.Collections.Generic.Queue[int]
        foreach ($id in $ids) { $queue.Enqueue($id) }
        $foundNew = $false
        while ($queue.Count -gt 0) {
            $current = $queue.Dequeue()
            foreach ($childId in (Get-ChildProcessIds -ParentId $current)) {
                if (-not $ids.Contains($childId)) {
                    $ids.Add($childId)
                    $queue.Enqueue($childId)
                    $foundNew = $true
                }
            }
        }
        if ($pass -lt ($Passes - 1)) { Start-Sleep -Milliseconds $PauseMs }
        if (-not $foundNew -and $pass -gt 0) { break }
    }
    return $ids
}

# Stops a launcher-spawned terminal AND everything it spawned (e.g. the
# terminal -> poetry -> python -> uvicorn chain, or terminal -> npm -> node/vite),
# so no orphaned child survives. Only ever called after the caller has verified
# the root PID's command line contains the expected launcher marker.
function Stop-ProcessTree {
    param([Parameter(Mandatory)][int]$RootProcessId)

    $ids = Get-ProcessTreeIds -RootProcessId $RootProcessId
    foreach ($id in $ids) {
        try { Stop-Process -Id $id -Force -ErrorAction Stop } catch { }
    }
    return $ids
}
