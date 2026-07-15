<#
    Generate/refresh the repository-root "Start BIM RAG.lnk" shortcut (Task 12).

    Usage:
        powershell -ExecutionPolicy Bypass -File .\scripts\create-shortcut.ps1

    Windows .lnk files always store an ABSOLUTE target path, so this script (only
    this script) resolves and bakes in the current absolute repository path. It
    is safe to rerun any time, including after the repository has been moved: it
    always regenerates the shortcut from the script's current on-disk location,
    replacing only the "Start BIM RAG.lnk" this script owns. If the repository
    is moved, rerun this script and then replace/recopy the desktop shortcut.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StartScript = Join-Path $RepoRoot 'scripts\start-dev.ps1'
$ShortcutPath = Join-Path $RepoRoot 'Start BIM RAG.lnk'

if (-not (Test-Path -LiteralPath $StartScript)) {
    Write-Error "Cannot find $StartScript"
    exit 1
}

$powershellCmd = Get-Command powershell.exe -ErrorAction SilentlyContinue
if (-not $powershellCmd) {
    Write-Error 'powershell.exe was not found on PATH.'
    exit 1
}
$PowerShellExe = $powershellCmd.Source

Write-Host "Repository root: $RepoRoot"
Write-Host "Target script:   $StartScript"
Write-Host ''

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $PowerShellExe
# -NoProfile reduces user-profile side effects; -ExecutionPolicy Bypass is a
# per-process override only (no admin rights needed, no system policy change).
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $StartScript + '"'
$shortcut.WorkingDirectory = $RepoRoot
$shortcut.IconLocation = "$PowerShellExe,0"
$shortcut.Description = 'Start the BIM RAG backend and frontend (local development)'
$shortcut.WindowStyle = 1  # normal (visible) window
$shortcut.Save()

Write-Host "Created/updated: $ShortcutPath" -ForegroundColor Green

# Programmatic validation: re-open the .lnk fresh (don't trust the in-memory
# object) and confirm the properties actually persisted as expected.
$verifyShell = New-Object -ComObject WScript.Shell
$verify = $verifyShell.CreateShortcut($ShortcutPath)
Write-Host "  TargetPath:       $($verify.TargetPath)"
Write-Host "  Arguments:        $($verify.Arguments)"
Write-Host "  WorkingDirectory: $($verify.WorkingDirectory)"
Write-Host "  IconLocation:     $($verify.IconLocation)"

if ($verify.TargetPath -ne $PowerShellExe) {
    throw 'Validation failed: TargetPath does not match powershell.exe.'
}
if ($verify.WorkingDirectory -ne $RepoRoot) {
    throw 'Validation failed: WorkingDirectory does not match the repository root.'
}
if ($verify.Arguments -notmatch [regex]::Escape($StartScript)) {
    throw 'Validation failed: Arguments do not reference scripts\start-dev.ps1.'
}

Write-Host ''
Write-Host "You can copy or move '$ShortcutPath' to the Desktop; it will keep working there."
Write-Host 'If you move the whole BIM_RAG repository, rerun this script and then replace the desktop shortcut.'
