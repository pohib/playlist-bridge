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

    # Stop only stale Quick Tunnels that target this project's local Django port.
    # Do not terminate named tunnels or cloudflared processes for other local services.
    Write-Host "[0/4] Cleaning up stale Quick Tunnel processes..."
    $staleTunnels = @(
        Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object {
            $_.CommandLine -match '(?i)cloudflared(?:\.exe)?\s+tunnel' -and
            $_.CommandLine -match '(?i)--url\s+http://127\.0\.0\.1:8000(?:\s|$)'
        }
    )
    foreach ($stale in $staleTunnels) {
        Write-Host "Stopping stale cloudflared PID $($stale.ProcessId)..."
        Stop-Process -Id $stale.ProcessId -Force -ErrorAction Stop
    }
    if ($staleTunnels.Count -gt 0) {
        Start-Sleep -Seconds 2
    }

    Write-Host "[1/4] Building and starting containers..."
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed."
    }

    
    Write-Host "[2/4] Checking Django..."

    $healthy = $false
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue

    if (-not $curl) {
        throw "curl.exe was not found."
    }

    $healthUrl = "http://127.0.0.1:8000/healthz/"

    for ($i = 0; $i -lt 60; $i++) {
        $healthBody = @(
            & $curl.Source `
                --silent `
                --fail `
                --max-time 3 `
                --stderr NUL `
                --header "X-Forwarded-Proto: https" `
                $healthUrl
        )

        $curlExitCode = $LASTEXITCODE

        if (
            $curlExitCode -eq 0 -and
            (($healthBody -join "`n") -match '"status"\s*:\s*"ok"')
        ) {
            $healthy = $true
            break
        }

        Start-Sleep -Seconds 2
    }

    if (-not $healthy) {
        Write-Host "Django health check failed." -ForegroundColor Red
        docker compose ps
        docker compose logs --tail=80 web

        throw "Django did not return a valid HTTP 200 health response."
    }

    Write-Host "Django is healthy." -ForegroundColor Green


    Write-Host "[3/4] Starting Cloudflare Quick Tunnel..."
    # Use cloudflared's own logfile instead of asynchronous .NET output events.
    # This avoids PowerShell 5.1 runspace/event-handler issues on Windows.
    $tunnelLogPath = Join-Path $env:TEMP ("vktospotify-cloudflared-" + [guid]::NewGuid().ToString("N") + ".log")
    $tunnelArguments = 'tunnel --no-autoupdate --loglevel info --logfile "{0}" --url http://127.0.0.1:8000' -f $tunnelLogPath
    $tunnel = Start-Process -FilePath $cloudflared.Source -ArgumentList $tunnelArguments -PassThru -WindowStyle Hidden

    $publicUrl = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1

        if (Test-Path -LiteralPath $tunnelLogPath) {
            try {
                $logText = [System.IO.File]::ReadAllText($tunnelLogPath)
                $match = [regex]::Match($logText, "https://[a-z0-9-]+\.trycloudflare\.com")
                if ($match.Success) {
                    $publicUrl = $match.Value
                    break
                }
            }
            catch {
                # The log may be momentarily unavailable while cloudflared writes it.
            }
        }

        $tunnel.Refresh()
        if ($tunnel.HasExited) {
            $details = ""
            if (Test-Path -LiteralPath $tunnelLogPath) {
                $details = [System.IO.File]::ReadAllText($tunnelLogPath)
            }
            throw ("cloudflared exited before a public URL was received. Log file: " + $tunnelLogPath + [Environment]::NewLine + $details)
        }
    }

    if (-not $publicUrl) {
        $details = ""
        if (Test-Path -LiteralPath $tunnelLogPath) {
            $details = [System.IO.File]::ReadAllText($tunnelLogPath)
        }
        throw ("Could not obtain the Cloudflare HTTPS URL within 60 seconds. Log file: " + $tunnelLogPath + [Environment]::NewLine + $details)
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

    Write-Host "[4/5] Restarting web and worker with HTTPS..."
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

    Write-Host "[5/5] Verifying the public HTTPS endpoint..."
    $publicHealthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $publicResponse = Invoke-WebRequest -Uri "$origin/healthz/" -UseBasicParsing -TimeoutSec 10
            if ($publicResponse.StatusCode -eq 200 -and $publicResponse.Content -match '"status"\s*:\s*"ok"') {
                $publicHealthy = $true
                break
            }
            Write-Host "Public health endpoint returned HTTP $($publicResponse.StatusCode). Retrying..."
        }
        catch {
            Write-Host "Waiting for public tunnel endpoint: $($_.Exception.Message)"
            Start-Sleep -Seconds 2
        }
    }

    if (-not $publicHealthy) {
        docker compose logs --tail=100 web
        throw "The tunnel started, but the public HTTPS health check did not return HTTP 200. Check DJANGO_ALLOWED_HOSTS and the web logs."
    }

    # Verify the homepage too, so a DisallowedHost/HTTP 400 is caught before
    # presenting the URL as ready for OAuth setup.
    try {
        $homeResponse = Invoke-WebRequest -Uri "$origin/" -UseBasicParsing -TimeoutSec 10
        if ($homeResponse.StatusCode -ne 200) {
            throw "Homepage returned HTTP $($homeResponse.StatusCode)."
        }
    }
    catch {
        docker compose logs --tail=100 web
        throw "The public health endpoint works, but the homepage is not ready: $($_.Exception.Message)"
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
    if ($null -ne $tunnel) {
        try {
            $tunnel.Refresh()
            if (-not $tunnel.HasExited) {
                Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
            }
        }
        catch {
            # Preserve the original script error.
        }
    }
    if ($tunnelLogPath -and (Test-Path -LiteralPath $tunnelLogPath)) {
        Write-Host ""
        Write-Host "cloudflared log ($tunnelLogPath):" -ForegroundColor Yellow
        Get-Content -LiteralPath $tunnelLogPath -Tail 40 -ErrorAction SilentlyContinue
    }
    throw
}
finally {
    Pop-Location
}
