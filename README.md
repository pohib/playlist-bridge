# VK → Spotify

Django-приложение для переноса VK-плейлистов в Spotify с OAuth-подключением аккаунтов и фоновой обработкой.

## Пользовательская авторизация

Пользователь подключает оба сервиса кнопками на главной странице:
- Spotify — OAuth Authorization Code.
- VK — VK ID OAuth 2.1 Authorization Code с PKCE, state и device_id.

Пользовательские access/refresh tokens не задаются в .env, не сохраняются в браузерной сессии и не передаются в Celery arguments. Они шифруются Fernet и сохраняются в PostgreSQL в модели OAuthCredential. Worker получает токены из БД по HMAC-отпечатку сессии, расшифровывает их только в памяти и обновляет через refresh token. В Redis передаётся только UUID фоновой задачи.

При отключении провайдера соответствующая запись токенов удаляется. Сессионные cookie HttpOnly и SameSite=Lax.

## Что хранится в .env

В .env хранятся только конфигурация приложения, секреты разработчика и инфраструктуры:
- DJANGO_SECRET_KEY, TOKEN_ENCRYPTION_KEY, пароль PostgreSQL;
- Spotify Developer App: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, Redirect URI;
- VK ID Developer App: VK_ID_CLIENT_ID, Redirect URI и, если требуется типом приложения, серверный VK_ID_SERVICE_TOKEN;
- версия VK API и адрес Redis.

Не помещай пользовательские VK/Spotify access token или refresh token в .env.

Сгенерировать Fernet key:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Создай приложение Spotify в [Spotify Developer Dashboard](https://developer.spotify.com/dashboard), а VK ID — в [кабинете VK ID](https://id.vk.com/about/business/go). Для VK ID выбери платформу Web и зарегистрируй Redirect URL. Не используй локальный HTTP callback: VK требует публичный HTTPS-адрес. Точные callback URL появятся после запуска временного Cloudflare Tunnel по инструкции ниже. Для Spotify добавь свой аккаунт в Users Management, если приложение работает в Development Mode.

## Запуск локально с публичным HTTPS через Cloudflare Quick Tunnel

Домен, VPS и платная подписка Cloudflare для Quick Tunnel не нужны. Туннель временно публикует локальный порт Django по HTTPS. Адрес *.trycloudflare.com временный и может измениться при следующем запуске; при смене адреса обнови Redirect URL в кабинетах VK ID и Spotify.

### 1. Подготовь проект и .env

В PowerShell:

    git clone https://github.com/pohib/vk-to-spotify.git
    cd vk-to-spotify
    Copy-Item .env.example .env
    notepad .env

Если репозиторий уже скачан, вместо clone перейди в его каталог и выполни:

    git switch main
    git pull --ff-only origin main

Сгенерируй три независимых значения командами ниже и вставь результаты в соответствующие строки .env:

    python -c "import secrets; print(secrets.token_urlsafe(64))"
    python -c "import secrets; print(secrets.token_urlsafe(48))"
    python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

Результаты по порядку:
- первая команда → DJANGO_SECRET_KEY;
- вторая команда → POSTGRES_PASSWORD;
- третья команда → TOKEN_ENCRYPTION_KEY (Fernet key).

Не используй одно значение для нескольких параметров. Не публикуй .env и не отправляй его содержимое в чат.

Заполни OAuth-переменные:
- SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET — из Spotify Developer Dashboard;
- VK_ID_CLIENT_ID — ID приложения из кабинета VK ID;
- VK_ID_SERVICE_TOKEN — оставь пустым, если тип приложения и сценарий VK ID его не требуют.

Остальные значения на первом запуске оставь как в .env.example. Не добавляй DATABASE_URL: Compose формирует его из POSTGRES_PASSWORD. Не помещай в .env пользовательские access/refresh tokens.

### 2. Установи Cloudflare Tunnel

Установи Docker Desktop и дождись запуска Docker Engine. Затем установи cloudflared:

    winget install --id Cloudflare.cloudflared -e

Закрой и заново открой PowerShell, чтобы обновился PATH. Проверь:

    cloudflared --version

### 3. Запусти приложение и HTTPS-туннель

Из корня проекта:

    Set-ExecutionPolicy -Scope Process Bypass
    .\scripts\start-tunnel.ps1

Скрипт:
1. Проверяет обязательные секреты в .env;
2. собирает контейнеры и запускает Django, PostgreSQL и Redis;
3. ждёт успешного ответа /healthz/;
4. запускает Cloudflare Quick Tunnel;
5. получает временный HTTPS URL;
6. обновляет в .env домен, CSRF origin, Secure cookies, HTTPS redirect и оба OAuth callback URI;
7. пересоздаёт web и worker с новыми настройками.

После завершения скрипт покажет URL и точные callback URI. Не закрывай процесс cloudflared: туннель должен оставаться запущенным, пока используешь приложение. Чтобы остановить его, выполни команду с PID, который напечатал скрипт:

    Stop-Process -Id <PID>

### 4. Зарегистрируй OAuth callback URI

Скопируй callback URL из вывода скрипта без изменений.

В кабинете VK ID добавь в доверенные Redirect URL:

    https://<текущий-домен>.trycloudflare.com/vk/callback/

В Spotify Developer Dashboard добавь Redirect URI:

    https://<текущий-домен>.trycloudflare.com/spotify/callback/

Вместо <текущий-домен> подставь фактический адрес из вывода скрипта. Callback в .env и в кабинете провайдера должны совпадать посимвольно, включая завершающий слеш. После изменения Redirect URI перезапусти OAuth-подключение в браузере.

### 5. Проверь приложение

Открой HTTPS URL, который напечатал скрипт. Проверь health endpoint:

    Invoke-WebRequest https://<текущий-домен>.trycloudflare.com/healthz/

Проверь состояние контейнеров:

    docker compose ps

Логи приложения и фонового worker:

    docker compose logs -f web worker

Сначала подключи Spotify и VK, затем проверь перенос на небольшом плейлисте. Для добавления в существующий Spotify playlist используй ссылку на плейлист, принадлежащий подключённому аккаунту.

### 6. Повторный запуск

Quick Tunnel не гарантирует постоянный адрес. При новом запуске:
1. Останови старый cloudflared процесс, если он ещё работает;
2. Запусти scripts/start-tunnel.ps1 снова;
3. Обнови оба callback URI в кабинетах VK ID и Spotify, если домен изменился;
4. Переподключи OAuth, если провайдер использует новый Redirect URI.

Не публикуй приложение с Quick Tunnel как постоянный production-сервис: это временный туннель для разработки и проверки OAuth.

### Обычные команды Docker Compose

Проверить контейнеры:

    docker compose ps

Посмотреть логи:

    docker compose logs -f web worker

Выполнить Django checks:

    docker compose exec web python manage.py check

Остановить контейнеры, сохранив базу:

    docker compose down

Удаление базы и OAuth-подключений — только если осознанно хочешь начать с чистого состояния:

    docker compose down -v

Команда down -v удаляет PostgreSQL volume, включая сохранённые OAuth credentials и историю переносов. Не выполняй её для обычной остановки.

Не теряй TOKEN_ENCRYPTION_KEY: без него сохранённые зашифрованные токены восстановить нельзя. Храни ключ отдельно в менеджере секретов и делай защищённую резервную копию.

## API v1

API использует ту же браузерную сессию и CSRF:
- GET /api/v1/status/ — подключения и конфигурация.
- POST /api/v1/transfers/ — поставить перенос в очередь.
- GET /api/v1/transfers/{job_id}/ — прогресс.
- GET /api/v1/transfers/{job_id}/report/ — JSON-отчёт.
- GET /api/v1/openapi.json — OpenAPI 3.1.
- GET /healthz/ — health check.

Пример тела запроса:

    {
      "source_url": "https://vk.ru/music/playlist/241688629_5_b8781ccec850436700",
      "target_playlist": ""
    }

Пустой target_playlist создаёт новый приватный плейлист.

## Безопасность и CI

- pytest, Ruff, Django checks, негативные тесты изоляции сессий и защиты от повторной постановки/обработки задач;
- Bandit, Semgrep и CodeQL (security-extended) как обязательные jobs CI с SARIF публикацией в GitHub Code Scanning;
- pip-audit, Gitleaks со сканированием истории Git, Trivy filesystem/container (MEDIUM и выше), Hadolint;
- OWASP ZAP baseline DAST против запущенного приложения;
- Dependabot для pip, Docker и GitHub Actions: ежедневная проверка с cooldown 7 дней;
- Dependabot PR автоматически сливаются через squash после успешного завершения всех jobs workflow CI: tests, SAST/SCA/secrets, container и DAST. CodeQL запускается отдельно.
- Cooldown 7 дней относится к обычным version updates; security updates GitHub может предлагать сразу, без ожидания cooldown.

Автоматическое слияние выполняет workflow через GITHUB_TOKEN только после успешного завершения всего CI, включая CodeQL; включать Allow auto-merge не требуется. Для дополнительной защиты включи ruleset/branch protection для main и сделай обязательными checks tests, sast-sca-secrets, container, dast и codeql.

SARIF Bandit/Semgrep/Trivy загружается на push/workflow_dispatch, а CodeQL также анализирует pull request. GitHub Code Scanning может требовать доступность Code Security для репозитория. Для private repository проверь доступность этой функции на текущем плане.

## Ограничения

- Доступность методов VK Audio зависит от разрешений и типа VK ID приложения; реальную выдачу прав на audio.getPlaylistById необходимо проверить на подключённом аккаунте.
- Spotify access token обновляется через refresh token; refresh token Spotify истекает через 6 месяцев после исходной авторизации, после чего пользователь должен подключить аккаунт заново.
- Spotify rate limits и отдельная Development Mode quota могут замедлять или временно блокировать перенос.
- DAST baseline выполняется без OAuth-аутентификации и не покрывает авторизованные пользовательские сценарии.
- В Spotify Development Mode владелец приложения должен иметь Premium; максимум 5 авторизованных пользователей, каждый тестировщик должен быть добавлен в Users Management allowlist. Для публичного сервиса действует отдельная процедура Extended Quota Mode.
- Локальные настройки `SESSION_COOKIE_SECURE=false` и `CSRF_COOKIE_SECURE=false` допустимы только для loopback HTTP-разработки; на публичном HTTPS-хосте включи обе.
- Повторная отправка пакетов Spotify автоматически не включена, чтобы не создавать дубликаты при неопределённом результате сетевого запроса.
