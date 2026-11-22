$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
$tunnel = $null
$tunnelLogPath = $null

function Read-SharedLog {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $stream = $null
    $reader = $null
    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $reader = [System.IO.StreamReader]::new($stream)
        return $reader.ReadToEnd()
    }
    catch { return "" }
    finally {
        if ($null -ne $reader) { $reader.Dispose() }
        elseif ($null -ne $stream) { $stream.Dispose() }
    }
}

function Stop-ProjectQuickTunnels {
    Write-Host "Searching for existing Quick Tunnels targeting this project..."
    $targets = @(
        Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object {
            $_.CommandLine -match '(?i)\btunnel\b' -and
            $_.CommandLine -match '(?i)--url\s+["'']?https?://(127\.0\.0\.1|localhost):8000(?:/)?(?:["'']|\s|$)'
        }
    )
    foreach ($process in $targets) {
        Write-Host "Stopping project tunnel PID $($process.ProcessId)..."
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
    if ($targets.Count -gt 0) { Start-Sleep -Seconds 2 }

    $remaining = @(
        Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object {
            $_.CommandLine -match '(?i)\btunnel\b' -and
            $_.CommandLine -match '(?i)--url\s+["'']?https?://(127\.0\.0\.1|localhost):8000(?:/)?(?:["'']|\s|$)'
        }
    )
    if ($remaining.Count -gt 0) {
        $ids = ($remaining | ForEach-Object { $_.ProcessId }) -join ", "
        throw "Could not stop all existing project Quick Tunnels. Remaining PID(s): $ids"
    }
    Write-Host "Existing project Quick Tunnels stopped." -ForegroundColor Green
}

function Test-HttpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$ExpectedStatus = 200,
        [string]$ExpectedBodyPattern = "",
        [switch]$ForwardedProtoHttps
    )
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) { throw "curl.exe was not found." }

    $bodyPath = Join-Path $env:TEMP ("vktospotify-http-" + [guid]::NewGuid().ToString("N") + ".tmp")
    try {
        $curlArgs = @("--silent", "--show-error", "--max-time", "10", "--output", $bodyPath, "--write-out", "%{http_code}", "--stderr", "NUL")
        if ($ForwardedProtoHttps) {
            $curlArgs += @("--header", "X-Forwarded-Proto: https")
        }
        $curlArgs += $Url
        $statusOutput = & $curl.Source @curlArgs
        $curlExitCode = $LASTEXITCODE
        $statusText = ($statusOutput -join "").Trim()
        if ($curlExitCode -ne 0 -or $statusText -ne [string]$ExpectedStatus) { return $false }

        if ($ExpectedBodyPattern) {
            if (-not (Test-Path -LiteralPath $bodyPath)) { return $false }
            $body = [System.IO.File]::ReadAllText($bodyPath)
            if ($body -notmatch $ExpectedBodyPattern) { return $false }
        }
        return $true
    }
    finally {
        Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
    }
}

try {
    if (-not (Test-Path ".env")) {
        throw "Missing .env file. Copy .env.example to .env and configure the secrets first."
    }

    $envPath = Join-Path $repoRoot ".env"
    $envLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in [System.IO.File]::ReadAllLines($envPath)) { $envLines.Add($line) }

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
        if (-not $found) { throw "Missing .env parameter $required." }
    }

    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cloudflared) {
        throw "cloudflared was not found. Install it with: winget install --id Cloudflare.cloudflared -e"
    }

    Write-Host "[0/5] Cleaning up existing project Quick Tunnels..."
    Stop-ProjectQuickTunnels

    Write-Host "[1/5] Building and starting containers..."
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed." }

    Write-Host "[2/5] Checking local Django health..."
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-HttpEndpoint -Url "http://127.0.0.1:8000/healthz/" -ExpectedStatus 200 -ExpectedBodyPattern '"status"\s*:\s*"ok"' -ForwardedProtoHttps) {
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        docker compose ps
        docker compose logs --tail=100 web
        throw "Django did not return a valid local HTTP 200 health response."
    }
    Write-Host "Local Django health check passed." -ForegroundColor Green

    Write-Host "[3/5] Starting one Cloudflare Quick Tunnel..."
    $tunnelLogPath = Join-Path $env:TEMP ("vktospotify-cloudflared-" + [guid]::NewGuid().ToString("N") + ".log")
    $tunnelArguments = 'tunnel --no-autoupdate --loglevel info --logfile "{0}" --url http://127.0.0.1:8000' -f $tunnelLogPath
    $tunnel = Start-Process -FilePath $cloudflared.Source -ArgumentList $tunnelArguments -PassThru -WindowStyle Hidden

    $publicUrl = $null
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        $logText = Read-SharedLog -Path $tunnelLogPath
        $match = [regex]::Match($logText, 'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($match.Success) { $publicUrl = $match.Value }

        $tunnel.Refresh()
        if ($tunnel.HasExited) {
            throw ("cloudflared exited before the tunnel became ready. Exit code: " + $tunnel.ExitCode + ". Log: " + $tunnelLogPath + [Environment]::NewLine + $logText)
        }
        if ($publicUrl) { break }
    }
    if (-not $publicUrl) {
        $logText = Read-SharedLog -Path $tunnelLogPath
        throw ("No Cloudflare HTTPS URL was received within 90 seconds. Log: " + $tunnelLogPath + [Environment]::NewLine + $logText)
    }
    Write-Host "Quick Tunnel URL received: $publicUrl" -ForegroundColor Green

    $hostName = ([uri]$publicUrl).Host
    $origin = $publicUrl.TrimEnd("/")
    $settings = [ordered]@{
        "DJANGO_ALLOWED_HOSTS" = "$hostName,127.0.0.1,localhost,web"
        "DJANGO_CSRF_TRUSTED_ORIGINS" = $origin
        "SESSION_COOKIE_SECURE" = "true"
        "CSRF_COOKIE_SECURE" = "true"
        "SECURE_SSL_REDIRECT" = "true"
        "SPOTIFY_REDIRECT_URI" = "$origin/spotify/callback/"
        "SOUNDCLOUD_REDIRECT_URI" = "$origin/soundcloud/callback/"
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
        if (-not $replaced) { $envLines.Add($newLine) }
    }
    [System.IO.File]::WriteAllLines($envPath, $envLines.ToArray(), [System.Text.UTF8Encoding]::new($false))

    Write-Host "[4/5] Recreating web and worker with HTTPS settings..."
    docker compose up -d --force-recreate web worker
    if ($LASTEXITCODE -ne 0) { throw "Could not restart web and worker." }

    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        $tunnel.Refresh()
        if ($tunnel.HasExited) {
            throw ("cloudflared stopped while the application was restarting. Exit code: " + $tunnel.ExitCode + ". Log: " + $tunnelLogPath + [Environment]::NewLine + (Read-SharedLog -Path $tunnelLogPath))
        }
        if (Test-HttpEndpoint -Url "http://127.0.0.1:8000/healthz/" -ExpectedStatus 200 -ExpectedBodyPattern '"status"\s*:\s*"ok"' -ForwardedProtoHttps) {
            $healthy = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        docker compose logs --tail=100 web
        throw "Local Django health check failed after applying HTTPS settings."
    }

    Write-Host "[5/5] Verifying the public HTTPS endpoint..."
    $publicHealthy = $false
    for ($i = 0; $i -lt 45; $i++) {
        $tunnel.Refresh()
        if ($tunnel.HasExited) {
            throw ("cloudflared exited during the public health check. Exit code: " + $tunnel.ExitCode + ". Log: " + $tunnelLogPath + [Environment]::NewLine + (Read-SharedLog -Path $tunnelLogPath))
        }
        if (Test-HttpEndpoint -Url "$origin/healthz/" -ExpectedStatus 200 -ExpectedBodyPattern '"status"\s*:\s*"ok"') {
            $publicHealthy = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $publicHealthy) {
        docker compose logs --tail=100 web
        throw ("The public HTTPS health check did not return HTTP 200. URL: $origin. Check Cloudflare connectivity and Django logs.")
    }

    if (-not (Test-HttpEndpoint -Url "$origin/" -ExpectedStatus 200)) {
        docker compose logs --tail=100 web
        throw "The public health endpoint works, but the homepage did not return HTTP 200."
    }

    Write-Host ""
    Write-Host "Application is available: $origin" -ForegroundColor Green
    Write-Host "Spotify callback: $origin/spotify/callback/"
    Write-Host "SoundCloud callback: $origin/soundcloud/callback/"
    Write-Host "Tunnel PID: $($tunnel.Id)"
    Write-Host "Keep this tunnel process running while using the application."
    Write-Host "Stop this project's tunnel with: Stop-Process -Id $($tunnel.Id) -Force"
    Write-Host "Quick Tunnel URL may change after restart."
}
catch {
    $originalError = $_
    if ($null -ne $tunnel) {
        try {
            $tunnel.Refresh()
            if (-not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
        }
        catch { }
    }

    if ($tunnelLogPath) {
        $diagnosticLog = Read-SharedLog -Path $tunnelLogPath
        if ($diagnosticLog) {
            Write-Host ""
            Write-Host "cloudflared log ($tunnelLogPath):" -ForegroundColor Yellow
            $diagnosticLog -split '\r?\n' | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
        }
    }
    throw $originalError
}
finally {
    Pop-Location
}
