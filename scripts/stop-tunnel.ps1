$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repoRoot "compose.yaml"

function Get-ProjectQuickTunnels {
    @(
        Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object {
            $_.CommandLine -match '(?i)\btunnel\b' -and
            $_.CommandLine -match '(?i)--url\s+["'']?https?://(127\.0\.0\.1|localhost):8000(?:/)?(?:["'']|\s|$)'
        }
    )
}

Push-Location $repoRoot

try {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "       VK TO SPOTIFY - STOP" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    if (-not (Test-Path -LiteralPath $composeFile)) {
        throw "compose.yaml was not found in $repoRoot"
    }

    # Stop only Quick Tunnels explicitly targeting this project's local port.
    Write-Host "[1/2] Stopping this project's Cloudflare Quick Tunnel..." -ForegroundColor Yellow

    $tunnels = Get-ProjectQuickTunnels
    foreach ($process in $tunnels) {
        Write-Host "Stopping cloudflared PID $($process.ProcessId)..."
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }

    if ($tunnels.Count -gt 0) {
        Start-Sleep -Seconds 2
    }

    $remaining = Get-ProjectQuickTunnels
    if ($remaining.Count -gt 0) {
        $ids = ($remaining | ForEach-Object { $_.ProcessId }) -join ", "
        throw "Could not stop all project Quick Tunnels. Remaining PID(s): $ids"
    }

    if ($tunnels.Count -eq 0) {
        Write-Host "No matching project tunnel is running." -ForegroundColor DarkGray
    }
    else {
        Write-Host "Project Cloudflare Tunnel stopped." -ForegroundColor Green
    }

    # Stop and remove Compose containers/network, but preserve named volumes.
    Write-Host "[2/2] Stopping Docker Compose services..." -ForegroundColor Yellow

    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) {
        throw "Docker CLI was not found. The Cloudflare Tunnel was stopped, but Docker services may still be running."
    }

    docker compose down --remove-orphans --timeout 20
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed. Docker services may still be running."
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "       CONFIGURATION STOPPED" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Cloudflare Quick Tunnel: stopped" -ForegroundColor Green
    Write-Host "Compose containers: removed" -ForegroundColor Green
    Write-Host "Compose network: removed" -ForegroundColor Green
    Write-Host "Docker volumes: preserved" -ForegroundColor Green
    Write-Host ".env: unchanged" -ForegroundColor Green
    Write-Host ""
    Write-Host "Start everything again with:" -ForegroundColor Cyan
    Write-Host ".\scripts\start-tunnel.ps1" -ForegroundColor White
    Write-Host ""
}
catch {
    Write-Host ""
    Write-Host "STOP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    exit 1
}
finally {
    Pop-Location
}