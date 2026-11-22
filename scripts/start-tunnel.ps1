$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
$tunnel = $null

try {
    if (-not (Test-Path ".env")) {
        throw "Missing .env file. Copy .env.example to .env and configure the secrets first."
    }

    $envPath = Join-Path $repoRoot ".env"
    $envLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
        $envLines.Add($line)
    }

    foreach ($required in @("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "TOKEN_ENCRYPTION_KEY")) {
        $found = $false
        foreach ($line in $envLines) {
            if ($line.StartsWith($required + "=")) {
                $value = $line.Substring($required.Length + 1).Trim()
                if ([string]::IsNullOrWhiteSpace($value) -or $value.StartsWith("replace-")) {
                    throw "Set a value for $required."
                }
                $found = $true
                break
            }
        }
        if (-not $found) {
            throw "Missing .env parameter $required."
        }
    }

    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cloudflared) {
        throw "cloudflared was not found. Install it with: winget install --id Cloudflare.cloudflared -e"
    }

    Write-Host "[1/4] Building and starting containers..."
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed."
    }

    Write-Host "[2/4] Checking Django..."
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -Headers @{ "X-Forwarded-Proto" = "https" } -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $healthy) {
        docker compose ps
        docker compose logs --tail=80 web
        throw "Django did not become available at the local health endpoint."
    }

    Write-Host "[3/4] Starting Cloudflare Quick Tunnel..."
    $stdout = Join-Path $env:TEMP "vk-to-spotify-cloudflared-out.log"
    $stderr = Join-Path $env:TEMP "vk-to-spotify-cloudflared-err.log"
    Remove-Item $stdout -Force -ErrorAction SilentlyContinue
    Remove-Item $stderr -Force -ErrorAction SilentlyContinue

    $tunnel = Start-Process -FilePath $cloudflared.Source -ArgumentList @(
        "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000"
    ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr

    $publicUrl = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        $logs = ""
        if (Test-Path $stdout) {
            $logs += [System.IO.File]::ReadAllText($stdout)
        }
        if (Test-Path $stderr) {
            $logs += [System.IO.File]::ReadAllText($stderr)
        }

        $match = [regex]::Match($logs, "https://[a-z0-9-]+\.trycloudflare\.com")
        if ($match.Success) {
            $publicUrl = $match.Value
            break
        }
        if ($tunnel.HasExited) {
            throw "cloudflared exited. Check log $stderr."
        }
    }

    if (-not $publicUrl) {
        throw "Could not obtain the Cloudflare HTTPS URL. Check log $stderr."
    }

    $hostName = ([uri]$publicUrl).Host
    $origin = $publicUrl.TrimEnd("/")
    $settings = [ordered]@{
        "DJANGO_ALLOWED_HOSTS" = "$hostName,127.0.0.1,localhost,web"
        "DJANGO_CSRF_TRUSTED_ORIGINS" = $origin
        "SESSION_COOKIE_SECURE" = "true"
        "CSRF_COOKIE_SECURE" = "true"
        "SECURE_SSL_REDIRECT" = "true"
        "SPOTIFY_REDIRECT_URI" = "$origin/spotify/callback/"
        "VK_ID_REDIRECT_URI" = "$origin/vk/callback/"
    }

    foreach ($key in $settings.Keys) {
        $newLine = $key + "=" + $settings[$key]
        $replaced = $false
        for ($i = 0; $i -lt $envLines.Count; $i++) {
            if ($envLines[$i].StartsWith($key + "=")) {
                $envLines[$i] = $newLine
                $replaced = $true
                break
            }
        }
        if (-not $replaced) {
            $envLines.Add($newLine)
        }
    }

    [System.IO.File]::WriteAllLines($envPath, $envLines.ToArray(), [System.Text.UTF8Encoding]::new($false))

    Write-Host "[4/4] Restarting web and worker with HTTPS..."
    docker compose up -d --force-recreate web worker
    if ($LASTEXITCODE -ne 0) {
        throw "Could not restart web and worker."
    }

    $healthy = $false
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -Headers @{ "X-Forwarded-Proto" = "https" } -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $healthy = $true
                break
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $healthy) {
        docker compose logs --tail=80 web
        throw "Django health check failed after enabling HTTPS."
    }

    Write-Host ""
    Write-Host "HTTPS URL: $origin" -ForegroundColor Green
    Write-Host "VK ID callback: $origin/vk/callback/"
    Write-Host "Spotify callback: $origin/spotify/callback/"
    Write-Host "Tunnel PID: $($tunnel.Id)"
    Write-Host "Update callback URLs in the VK ID and Spotify dashboards."
    Write-Host "Keep cloudflared running while using the application."
    Write-Host "To stop the tunnel: Stop-Process -Id $($tunnel.Id)"
    Write-Host "The Quick Tunnel URL may change when restarted."
}
catch {
    if ($null -ne $tunnel -and -not $tunnel.HasExited) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    Pop-Location
}
