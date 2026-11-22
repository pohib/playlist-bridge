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

Создай приложения в Spotify Developer Dashboard и VK ID Developer Dashboard. В обоих приложениях зарегистрируй точные callback URL:
- http://127.0.0.1:8000/spotify/callback/
- http://127.0.0.1:8000/vk/callback/

Для публичного развёртывания используй HTTPS и соответствующие публичные redirect URI.

## Запуск через Docker Compose

1. Скопируй .env.example в .env.
2. Заполни секреты приложения, инфраструктуры и developer OAuth app credentials.
3. Сгенерируй TOKEN_ENCRYPTION_KEY.
4. Запусти:

    docker compose up --build -d

Открой http://127.0.0.1:8000, подключи VK и Spotify и запускай перенос.

Логи:

    docker compose logs -f web worker

Остановка:

    docker compose down

Не удаляй volume postgres_data, если нужно сохранить OAuth-подключения и историю задач. Потеря TOKEN_ENCRYPTION_KEY сделает зашифрованные токены невосстановимыми — храни ключ в менеджере секретов и делай защищённую резервную копию.

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

- pytest, Ruff, Django checks;
- Bandit и Semgrep с SARIF публикацией в GitHub Code Scanning;
- pip-audit, Gitleaks, Trivy filesystem/image, Hadolint;
- OWASP ZAP baseline DAST против запущенного приложения;
- Dependabot для pip, Docker и GitHub Actions: ежедневная проверка с cooldown 7 дней;
- Dependabot PR автоматически сливаются после успешного завершения tests, SAST/SCA/secrets, container и DAST jobs; автоматизация охватывает patch/minor/major обновления.
- Cooldown 7 дней относится к обычным version updates; security updates GitHub может предлагать сразу, без ожидания cooldown.

Для auto-merge включи Allow auto-merge в Settings → General. В Settings → Branches настрой защиту main и обязательные checks tests, sast-sca-secrets, container, dast: без обязательных checks GitHub не сможет гарантировать, что merge ждёт завершения всех проверок.

SARIF загружается на push/workflow_dispatch; GitHub Code Scanning может требовать доступность Code Security для репозитория. Для private repository проверь доступность этой функции на текущем плане.

## Ограничения

- Доступность методов VK Audio зависит от разрешений и типа VK ID приложения; реальную выдачу прав на audio.getPlaylistById необходимо проверить на подключённом аккаунте.
- Spotify rate limits могут замедлять перенос.
- DAST baseline выполняется без OAuth-аутентификации и не покрывает авторизованные пользовательские сценарии.
- Повторная отправка пакетов Spotify автоматически не включена, чтобы не создавать дубликаты при неопределённом результате сетевого запроса.
