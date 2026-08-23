<#
.SYNOPSIS
    Nightly backup wrapper for Formulation Workbench (Windows).

.DESCRIPTION
    Runs `formulation-backup backup`, ships the artefact into $OutputDir,
    and prunes archives older than $RetentionDays.  Suitable for Task
    Scheduler; exit code is non-zero on failure.

.PARAMETER OutputDir
    Directory where backup artefacts are written.

.PARAMETER RetentionDays
    Delete backup files older than this many days.  Default: 30.

.EXAMPLE
    powershell -File .\scripts\ops\backup.ps1 -OutputDir C:\Backups\Formulation
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "$env:ProgramData\FormulationWorkbench\backups",

    [Parameter(Mandatory = $false)]
    [int]$RetentionDays = 30
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}

$logDir = Join-Path $env:ProgramData "FormulationWorkbench\logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$logFile = Join-Path $logDir "backup.log"

function Write-BackupLog {
    param([string]$Message)
    $stamp = [DateTimeOffset]::UtcNow.ToString("o")
    Add-Content -Path $logFile -Value "[$stamp] $Message"
}

try {
    Write-BackupLog "backup starting -> $OutputDir"
    $artefact = & formulation-backup backup --output-dir $OutputDir
    if ($LASTEXITCODE -ne 0) {
        throw "formulation-backup exited with $LASTEXITCODE"
    }
    Write-BackupLog "backup produced $artefact"

    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem -Path $OutputDir -File -Include "*.db.gz","*.db","*.sha256" -Recurse |
        Where-Object { $_.LastWriteTimeUtc -lt $cutoff } |
        ForEach-Object {
            Write-BackupLog "pruning $($_.FullName)"
            Remove-Item -Force $_.FullName
        }

    Write-BackupLog "backup done"
} catch {
    Write-BackupLog "backup failed: $_"
    exit 1
}
