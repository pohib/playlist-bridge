[CmdletBinding()]
param(
    [string]$OutputRoot = "backups",
    [ValidateRange(0, 3650)]
    [int]$RetentionDays = 30
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

$backupDirectory = $null
$containerDumpPath = $null
$servicesToRestart = @()

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

    $outputPath = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
        $OutputRoot
    } else {
        Join-Path $repoRoot $OutputRoot
    }
    New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
    $outputPath = (Resolve-Path -LiteralPath $outputPath).Path

    Write-Host "Checking the production-like PostgreSQL service..."
    Invoke-Compose -Arguments @("up", "-d", "db") | Out-Null
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $null = & docker compose exec -T db pg_isready -U vktospotify -d vktospotify 2>$null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "PostgreSQL did not become ready within 120 seconds." }

    $running = @(Invoke-Compose -Arguments @("ps", "--status", "running", "--services") |
        ForEach-Object { "$_".Trim() } |
        Where-Object { $_ -in @("web", "worker") })
    $servicesToRestart = @($running)

    if ($servicesToRestart.Count -gt 0) {
        Write-Host "Pausing web/worker for a consistent database + media snapshot (Celery receives a graceful stop)..."
        Invoke-Compose -Arguments @("stop", "--timeout", "180", "web", "worker") | Out-Null
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $backupDirectory = Join-Path $outputPath $stamp
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null

    $containerDumpPath = "/tmp/playlist-bridge-$stamp.dump"
    $databaseDump = Join-Path $backupDirectory "database.dump"
    $mediaArchive = Join-Path $backupDirectory "media.tar.gz"
    $mediaPath = Join-Path $repoRoot "media"
    if (-not (Test-Path -LiteralPath $mediaPath)) {
        New-Item -ItemType Directory -Path $mediaPath -Force | Out-Null
    }

    Write-Host "Creating PostgreSQL custom-format dump..."
    $dumpCommand = "pg_dump --format=custom --no-owner --no-acl --username=vktospotify --dbname=vktospotify --file='$containerDumpPath'"
    Invoke-Compose -Arguments @("exec", "-T", "db", "sh", "-lc", $dumpCommand) | Out-Null
    Invoke-Compose -Arguments @("cp", "db:$containerDumpPath", $databaseDump) | Out-Null
    $validateCommand = "pg_restore --list --file=/dev/null '$containerDumpPath'"
    Invoke-Compose -Arguments @("exec", "-T", "db", "sh", "-lc", $validateCommand) | Out-Null
    Invoke-Compose -Arguments @("exec", "-T", "db", "rm", "-f", $containerDumpPath) | Out-Null
    $containerDumpPath = $null

    Write-Host "Archiving user media..."
    & $tar.Source -czf $mediaArchive -C $mediaPath .
    if ($LASTEXITCODE -ne 0) { throw "Could not create media.tar.gz (tar exit code $LASTEXITCODE)." }
    & $tar.Source -tzf $mediaArchive | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "The generated media archive failed its integrity check." }

    $files = @(
        @{
            name = "database.dump"
            size_bytes = (Get-Item -LiteralPath $databaseDump).Length
            sha256 = (Get-FileHash -LiteralPath $databaseDump -Algorithm SHA256).Hash
        },
        @{
            name = "media.tar.gz"
            size_bytes = (Get-Item -LiteralPath $mediaArchive).Length
            sha256 = (Get-FileHash -LiteralPath $mediaArchive -Algorithm SHA256).Hash
        }
    )
    $manifest = [ordered]@{
        backup_format = "playlist-bridge-backup-v1"
        created_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        database = "vktospotify"
        files = $files
        note = "Secrets and .env are intentionally excluded. Preserve TOKEN_ENCRYPTION_KEY separately."
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 6
    [System.IO.File]::WriteAllText(
        (Join-Path $backupDirectory "manifest.json"),
        $manifestJson,
        [System.Text.UTF8Encoding]::new($false)
    )

    if ($RetentionDays -gt 0) {
        $cutoff = [DateTimeOffset]::UtcNow.AddDays(-$RetentionDays)
        Get-ChildItem -LiteralPath $outputPath -Directory | Where-Object { $_.FullName -ne $backupDirectory } | ForEach-Object {
            $candidateManifest = Join-Path $_.FullName "manifest.json"
            if (Test-Path -LiteralPath $candidateManifest) {
                try {
                    $candidate = Get-Content -LiteralPath $candidateManifest -Raw | ConvertFrom-Json
                    if ($candidate.backup_format -eq "playlist-bridge-backup-v1" -and
                        [DateTimeOffset]::Parse($candidate.created_at_utc) -lt $cutoff) {
                        Remove-Item -LiteralPath $_.FullName -Recurse -Force
                        Write-Host "Removed expired backup: $($_.Name)"
                    }
                } catch {
                    Write-Warning "Skipped backup directory with an unreadable manifest: $($_.FullName)"
                }
            }
        }
    }

    Write-Host "Backup completed and verified: $backupDirectory" -ForegroundColor Green
    Write-Output $backupDirectory
}
catch {
    if ($backupDirectory -and (Test-Path -LiteralPath $backupDirectory)) {
        Remove-Item -LiteralPath $backupDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    if ($containerDumpPath) {
        $null = & docker compose exec -T db rm -f $containerDumpPath 2>$null
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
