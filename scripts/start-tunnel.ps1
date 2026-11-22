$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    if (-not (Test-Path ".env")) {
        throw "Файл .env не найден. Сначала скопируй .env.example в .env и заполни секреты."
    }

    $envText = [System.IO.File]::ReadAllText((Join-Path $repoRoot ".env"))
    foreach ($required in @("DJANGO_SECRET_KEY", "POSTGRES_PASSWORD", "TOKEN_ENCRYPTION_KEY")) {
        $match = [regex]::Match($envText, "(?m)^" + [regex]::Escape($required) + "=(.*)$")
        if (-not $match.Success -or [string]::IsNullOrWhiteSpace($match.Groups[1].Value) -or $match.Groups[1].Value -match "^replace-") {
            throw "В .env необходимо задать непустое уникальное значение $required."
        }
    }

    $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cloudflared) {
        throw "cloudflared не найден. Установи его командой: winget install --id Cloudflare.cloudflared -e"
    }

    Write-Host "[1/4] Сборка и запуск Django, PostgreSQL и Redis..."
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up завершился с ошибкой." }

    Write-Host "[2/4] Ожидание готовности Django..."
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/healthz/" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $healthy = $true; break }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        docker compose ps
        docker compose logs --tail=80 web
        throw "Django не стал доступен на http://127.0.0.1:8000/healthz/."
    }

    Write-Host "[3/4] Запуск временного HTTPS-туннеля Cloudflare..."
    $stdout = Join-Path $env:TEMP "vk-to-spotify-cloudflared-out.log"
    $stderr = Join-Path $env:TEMP "vk-to-spotify-cloudflared-err.log"
    Remove-Item $stdout, $stderr -Force -ErrorAction SilentlyContinue
    $tunnel = Start-Process -FilePath $cloudflared.Source -ArgumentList @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8000") -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr

    $publicUrl = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        $logs = ""
        if (Test-Path $stdout) { $logs += [System.IO.File]::ReadAllText($stdout) }
        if (Test-Path $stderr) { $logs += [System.IO.File]::ReadAllText($stderr) }
        $found = [regex]::Match($logs, "https://[a-z0-9-]+\.trycloudflare\.com")
        if ($found.Success) { $publicUrl = $found.Value; break }
        if ($tunnel.HasExited) { throw "cloudflared завершился. Логи: $stderr" }
    }
    if (-not $publicUrl) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
        throw "Не удалось получить HTTPS URL Cloudflare. Проверь доступ к сети и лог $stderr."
    }

    $hostName = ([uri]$publicUrl).Host
    $origin = $publicUrl.TrimEnd("/")
    $values = [ordered]@{
        "DJANGO_ALLOWED_HOSTS" = "$hostName,127.0.0.1,localhost,web"
        "DJANGO_CSRF_TRUSTED_ORIGINS" = $origin
        "SESSION_COOKIE_SECURE" = "true"
        "CSRF_COOKIE_SECURE" = "true"
        "SECURE_SSL_REDIRECT" = "true"
        "SPOTIFY_REDIRECT_URI" = "$origin/spotify/callback/"
        "VK_ID_REDIRECT_URI" = "$origin/vk/callback/"
    }

    foreach ($entry in $values.GetEnumerator()) {
        $line = "$($entry.Key)=$($entry.Value)"
        $pattern = "(?m)^" + [regex]::Escape($entry.Key) + "=.*$"
        if ([regex]::IsMatch($envText, $pattern)) {
            $envText = [regex]::Replace($envText, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line })
        } else {
            $envText = $envText.TrimEnd() + [Environment]::NewLine + $line + [Environment]::NewLine
        }
    }
    [System.IO.File]::WriteAllText((Join-Path $repoRoot ".env"), $envText, [System.Text.UTF8Encoding]::new($false))

    Write-Host "[4/4] Применение HTTPS-настроек..."
    docker compose up -d --force-recreate web worker
    if ($LASTEXITCODE -ne 0) {
        Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
        throw "Не удалось перезапустить web/worker с HTTPS-настройками."
    }

    Write-Host ""
    Write-Host "HTTPS URL: $origin" -ForegroundColor Green
    Write-Host "VK ID callback: $origin/vk/callback/"
    Write-Host "Spotify callback: $origin/spotify/callback/"
    Write-Host "Tunnel PID: $($tunnel.Id)"
    Write-Host "Открой кабинеты VK ID и Spotify и укажи соответствующие callback URL ТОЧНО."
    Write-Host "Пока процесс cloudflared работает, URL доступен. Для остановки: Stop-Process -Id $($tunnel.Id)"
    Write-Host "При следующем запуске Quick Tunnel URL изменится; запусти этот скрипт снова и обнови callback URL в кабинетах."
}
finally {
    Pop-Location
}
