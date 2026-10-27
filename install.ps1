param(
    [string]$FdsInstall = "$env:ProgramFiles\firemodels\FDS6",
    [string]$SmokeviewExe = "$env:ProgramFiles\firemodels\SMV6\smokeview.exe",
    [ValidateRange(1,256)][int]$MpiProcesses = 1,
    [switch]$SkipViewer
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
foreach ($folder in @('simulations','plots','docs','codes','archive','scripts')) {
    New-Item -ItemType Directory -Force (Join-Path $root $folder) | Out-Null
}
if (!(Test-Path -LiteralPath (Join-Path $FdsInstall 'bin\fds.exe'))) {
    throw 'Install the current FDS Windows bundle from https://pages.nist.gov/fds-smv/downloads.html, then rerun setup. For a custom location use -FdsInstall PATH.'
}
$FdsInstall = (Resolve-Path -LiteralPath $FdsInstall).Path
if (!(Test-Path -LiteralPath $SmokeviewExe)) { throw 'Smokeview not found. Supply -SmokeviewExe PATH.' }
$SmokeviewExe = (Resolve-Path -LiteralPath $SmokeviewExe).Path
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $python = & py -3 -c 'import sys; print(sys.executable)' }
if (!$python -and (Get-Command python -ErrorAction SilentlyContinue)) { $python = & python -c 'import sys; print(sys.executable)' }
if (!$python -or !(Test-Path -LiteralPath $python)) { throw 'Install Python 3.10 or newer from python.org, then rerun setup.' }
& $python -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
if ($python -match '[%\r\n"]' -or $root -match '[%\r\n"]') { throw 'Batch launcher paths cannot contain percent signs, quotes, or line breaks.' }
$oldPath = $env:PATH
try {
    $env:PATH = "$FdsInstall\bin;$FdsInstall\bin\mpi;$oldPath"
    # Capture native stderr without PowerShell 5.1's NativeCommandError wrapping.
    $version = (& $python -c 'import subprocess,sys; r=subprocess.run(sys.argv[1:], capture_output=True, text=True); print(r.stdout+r.stderr); sys.exit(r.returncode)' "$FdsInstall\bin\fds.exe" '-v' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch 'FDS-\d+\.\d+\.\d+') { throw 'FDS version check failed.' }
} finally { $env:PATH = $oldPath }
Write-Host $version
Write-Host 'Compare this version with the current official release: https://pages.nist.gov/fds-smv/downloads.html'
if (!$SkipViewer) {
    if (!(Get-Command git -ErrorAction SilentlyContinue)) { throw 'Install Git for Windows, then rerun setup (or use -SkipViewer for offline setup).' }
    $viewer = Join-Path $root 'visualization'
    if (Test-Path -LiteralPath $viewer) {
        if (!(Test-Path -LiteralPath (Join-Path $viewer 'index.html'))) { throw 'Existing visualization folder is incomplete; inspect it before retrying.' }
        Write-Host 'Keeping existing visualization folder; setup never overwrites viewer changes.'
    } else {
        & git clone --depth 1 https://github.com/ProfRino/fds-viewer.git $viewer
        if ($LASTEXITCODE -ne 0) { throw 'Viewer download failed. Check connectivity and rerun setup.' }
    }
}
$config = @{ fds_install=$FdsInstall; smokeview_exe=$SmokeviewExe; mpi_processes=$MpiProcesses; fds_version=$version }
$config | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $root 'scripts\config.local.json')
foreach ($entry in @{run_fds='run'; open_smv='smokeview'; serve_viewer='serve'; sim_status='status'; check_setup='check'}.GetEnumerator()) {
    $lines = @('@echo off','setlocal DisableDelayedExpansion',('"{0}" "%~dp0workflow.py" {1} %*' -f $python,$entry.Value),'exit /b %errorlevel%')
    [IO.File]::WriteAllLines((Join-Path $root ('scripts\'+$entry.Key+'.bat')), $lines, [Text.Encoding]::Default)
}
Write-Host 'Setup complete. Read README.md. Generated launchers and config are local-only.'
