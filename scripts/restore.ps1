[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [string]$OutputRoot = "backups"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

function Invoke-Compose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = @(& docker compose @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $output | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "docker compose $($Arguments -join ' ') failed (exit code $exitCode)."
    }
    return $output
}

$servicesToRestart = @()
$containerDumpPath = $null
$preRestoreBackup = $null
$mediaWasMoved = $false
$oldMediaPath = $null
$stagingPath = $null

try {
    if (-not (Test-Path -LiteralPath ".env")) {
        throw "Missing .env. Configure the production-like Compose environment first."
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found."
    }
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if (-not $tar) { $tar = Get-Command tar -ErrorAction SilentlyContinue }
    if (-not $tar) { throw "tar.exe was not found. Install/enable Windows tar (bsdtar) or add tar to PATH." }

    $resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
    if (-not (Test-Path -LiteralPath $resolvedBackup -PathType Container)) {
        throw "BackupPath must point to a backup directory."
    }
    $manifestPath = Join-Path $resolvedBackup "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath)) { throw "manifest.json is missing." }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.backup_format -ne "playlist-bridge-backup-v1" -or $manifest.database -ne "vktospotify") {
        throw "Unsupported backup format or database name."
    }

    foreach ($fileName in @("database.dump", "media.tar.gz")) {
        $entry = @($manifest.files | Where-Object { $_.name -eq $fileName }) | Select-Object -First 1
        $filePath = Join-Path $resolvedBackup $fileName
        if (-not $entry -or -not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            throw "Required backup file is missing: $fileName"
        }
        $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash
        if ($actualHash -ne $entry.sha256) { throw "SHA-256 verification failed for $fileName." }
    }

    $mediaArchive = Join-Path $resolvedBackup "media.tar.gz"
    $null = & $tar.Source -tzf $mediaArchive | ForEach-Object {
        $entryName = "$_".Replace("\", "/")
        if ($entryName.StartsWith("/") -or $entryName -match '(^|/)\.\.(/|$)' -or $entryName -match '^[A-Za-z]:') {
            throw "Unsafe path found in media archive: $entryName"
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Media archive integrity check failed." }

    Write-Host "Verified backup: $resolvedBackup" -ForegroundColor Green
    Write-Host "WARNING: this operation replaces the production-like PostgreSQL database and media directory." -ForegroundColor Yellow
    Write-Host "An automatic pre-restore backup will be created before any destructive operation."
    $confirmation = Read-Host "Type RESTORE to continue"
    if ($confirmation -cne "RESTORE") { throw "Restore cancelled." }

    Invoke-Compose -Arguments @("up", "-d", "db") | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $null = & docker compose exec -T db pg_isready -U vktospotify -d vktospotify 2>$null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "PostgreSQL did not become ready within 120 seconds." }

    $backupScript = Join-Path $PSScriptRoot "backup.ps1"
    $backupOutput = @(& $backupScript -OutputRoot $OutputRoot -RetentionDays 0)
    if (-not (Test-Path -LiteralPath (Join-Path $OutputRoot "never-used-marker"))) { }
    $preRestoreBackup = [string]($backupOutput | Select-Object -Last 1)
    if ([string]::IsNullOrWhiteSpace($preRestoreBackup) -or
        -not (Test-Path -LiteralPath (Join-Path $preRestoreBackup "manifest.json"))) {
        throw "Could not create the mandatory pre-restore safety backup. No restore was performed."
    }
    Write-Host "Pre-restore safety backup: $preRestoreBackup" -ForegroundColor Green

    $running = @(Invoke-Compose -Arguments @("ps", "--status", "running", "--services") |
        ForEach-Object { "$_".Trim() } |
        Where-Object { $_ -in @("web", "worker") })
    $servicesToRestart = @($running)
    if ($servicesToRestart.Count -gt 0) {
        Invoke-Compose -Arguments @("stop", "--timeout", "180", "web", "worker") | Out-Null
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $containerDumpPath = "/tmp/playlist-bridge-restore-$stamp.dump"
    $databaseDump = Join-Path $resolvedBackup "database.dump"
    Invoke-Compose -Arguments @("cp", $databaseDump, "db:$containerDumpPath") | Out-Null
    $validateCommand = "pg_restore --list --file=/dev/null '$containerDumpPath'"
    Invoke-Compose -Arguments @("exec", "-T", "db", "sh", "-lc", $validateCommand) | Out-Null

    Write-Host "Replacing PostgreSQL database..."
    $recreateCommand = "dropdb --if-exists --force --username=vktospotify vktospotify && createdb --username=vktospotify --owner=vktospotify vktospotify"
    Invoke-Compose -Arguments @("exec", "-T", "db", "sh", "-lc", $recreateCommand) | Out-Null
    $restoreCommand = "pg_restore --exit-on-error --no-owner --no-acl --username=vktospotify --dbname=vktospotify '$containerDumpPath'"
    Invoke-Compose -Arguments @("exec", "-T", "db", "sh", "-lc", $restoreCommand) | Out-Null
    Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDumpPath) | Out-Null
    $containerDumpPath = $null

    Write-Host "Restoring user media..."
    $mediaPath = Join-Path $repoRoot "media"
    $stagingPath = Join-Path $repoRoot "media.restore-$stamp"
    $oldMediaPath = Join-Path $repoRoot "media.before-restore-$stamp"
    New-Item -ItemType Directory -Path $stagingPath -Force | Out-Null
    & $tar.Source -xzf $mediaArchive -C $stagingPath
    if ($LASTEXITCODE -ne 0) { throw "Could not extract media archive (tar exit code $LASTEXITCODE)." }

    if (Test-Path -LiteralPath $mediaPath) {
        Move-Item -LiteralPath $mediaPath -Destination $oldMediaPath
        $mediaWasMoved = $true
    }
    try {
        Move-Item -LiteralPath $stagingPath -Destination $mediaPath
        $stagingPath = $null
    } catch {
        if ($mediaWasMoved -and -not (Test-Path -LiteralPath $mediaPath)) {
            Move-Item -LiteralPath $oldMediaPath -Destination $mediaPath
            $mediaWasMoved = $false
        }
        throw
    }

    Write-Host "Database and media restore completed." -ForegroundColor Green
    if ($mediaWasMoved) {
        Write-Host "Previous media retained for rollback at: $oldMediaPath"
    }
    Write-Host "The previous database is preserved in the pre-restore backup: $preRestoreBackup"
}
catch {
    Write-Host "RESTORE FAILED. The pre-restore backup, if created, is the recovery point." -ForegroundColor Red
    if ($preRestoreBackup) { Write-Host "Recovery backup: $preRestoreBackup" -ForegroundColor Yellow }
    throw
}
finally {
    if ($containerDumpPath) {
        $null = & docker compose exec -T db rm -f $containerDumpPath 2>$null
    }
    if ($stagingPath -and (Test-Path -LiteralPath $stagingPath)) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    foreach ($service in $servicesToRestart) {
        try {
            Invoke-Compose -Arguments @("start", $service) | Out-Null
            Write-Host "Restarted service: $service"
        } catch {
            Write-Warning "Could not restart $service automatically: $_"
        }
    }
    Pop-Location
}
