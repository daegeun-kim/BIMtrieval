<#
    Stop BIM RAG launcher-owned services (Task 12).

    Usage:
        powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1

    Reads ONLY the repository-owned runtime record (.runtime\dev-processes.json),
    re-verifies each recorded process's identity before touching it, and stops
    just that process tree. Services this launcher reused (did not start) are
    never recorded as owned and are therefore never touched here. This script
    never selects a process for termination merely because it owns port 8000 or
    5173, and never kills all Python/Node/Uvicorn/Vite/Poetry/npm processes.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Write-Info 'BIM RAG stop'
Write-Info "Repository root: $RepoRoot"
Write-Host ''

$record = Read-RuntimeRecord -RepoRoot $RepoRoot
if ($null -eq $record -or -not $record.services) {
    Write-Info 'No launcher-owned services recorded. Nothing to stop.'
    exit 0
}

$anyStopped = $false

foreach ($prop in $record.services.PSObject.Properties) {
    $name = $prop.Name
    $entry = $prop.Value
    $marker = if ($name -eq 'backend') { $BackendMarker } else { $FrontendMarker }

    if (-not $entry.owned) {
        Write-Info "$name : not owned by this launcher - leaving it running."
        continue
    }

    $proc = Get-Process -Id $entry.pid -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Write-Info "$name : recorded process (PID $($entry.pid)) already exited - clearing stale record."
        continue
    }

    $cmdLine = Get-ProcessCommandLine -ProcessId $entry.pid
    if ($null -eq $cmdLine -or ($cmdLine -notmatch [regex]::Escape($marker))) {
        Write-Warn "$name : PID $($entry.pid) no longer matches this launcher's process identity."
        Write-Warn '  Leaving it running (will not stop a process this launcher cannot verify) and clearing the stale record.'
        continue
    }

    Write-Info "Stopping $name (PID $($entry.pid), port $($entry.port))..."
    $stoppedIds = Stop-ProcessTree -RootProcessId $entry.pid
    Write-Good "  Stopped $($stoppedIds.Count) process(es)."
    $anyStopped = $true

    # Defense in depth: `uvicorn --reload` on Windows runs the actual server as
    # a `multiprocessing.spawn` child of the reload watcher we just verified and
    # killed. If that child was spawned a beat too late for the tree walk above
    # to see it, it survives as an orphan still holding the port. Check for that
    # narrowly: only touch the current port occupant if ITS OWN command line
    # also matches this service's known invocation — never merely because it
    # owns the port.
    Start-Sleep -Milliseconds 500
    $pattern = $ServiceIdentityPattern[$name]
    $orphanPid = Get-PortOwnerIfMatching -Port $entry.port -Pattern $pattern
    if ($orphanPid) {
        Write-Warn "  Port $($entry.port) is still held by PID $orphanPid (an orphaned reload worker)."
        Write-Warn "  Its command line matches the expected $name invocation - stopping it too."
        Stop-ProcessTree -RootProcessId $orphanPid | Out-Null
    }
}

# Every recorded entry has now been either stopped or found stale/mismatched;
# the record no longer describes anything this launcher should later stop.
Remove-RuntimeRecord -RepoRoot $RepoRoot

Write-Host ''
if ($anyStopped) {
    Write-Good 'Done. Launcher-owned services stopped.'
} else {
    Write-Info 'Nothing needed to be stopped.'
}
