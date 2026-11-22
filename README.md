# VK → Spotify

Django-приложение для переноса плейлистов VK в Spotify с фоновой обработкой больших списков.

## Возможности
- Получение ID композиций VK через batch.call и метаданных через audio.getById.
- Сохранение исходного порядка композиций.
- Spotify OAuth Authorization Code с проверкой state и обновлением access token.
- Сопоставление по названию, исполнителю и длительности; неоднозначные совпадения пропускаются.
- Создание приватного плейлиста или добавление в существующий плейлист подключённого владельца.
- Фоновая очередь Celery + Redis, прогресс выполнения и JSON-отчёт.
- Версионированный JSON API и OpenAPI schema.
- CSV-экспорт в legacy UI path для старого синхронного маршрута.

## Настройка интеграций

1. Скопируйте .env.example в .env.
2. Создайте приложение в Spotify Developer Dashboard.
3. В настройках Spotify app добавьте Redirect URI, который в точности совпадает со значением SPOTIFY_REDIRECT_URI, по умолчанию: http://127.0.0.1:8000/spotify/callback/
4. Заполните SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET.
5. Заполните VK_API_TOKEN. Используйте отдельный токен с минимально необходимыми разрешениями; не используйте браузерные Cookie.
6. Сгенерируйте TOKEN_ENCRYPTION_KEY командой:

   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

7. Сгенерируйте уникальные DJANGO_SECRET_KEY и POSTGRES_PASSWORD. Не используйте тестовые значения в рабочем окружении.

Все секреты хранятся только в .env и не должны попадать в Git, логи или сообщения.

## Запуск через Docker Compose

    docker compose up --build -d

Откройте http://127.0.0.1:8000. Compose поднимает Django/Gunicorn, PostgreSQL, Redis и отдельный Celery worker. Порт приложения привязан к loopback-интерфейсу. Worker и Redis не публикуют порты наружу.

Для просмотра логов:

    docker compose logs -f web worker

Для остановки:

    docker compose down

Не удаляйте volume postgres_data, если хотите сохранить данные приложения.

## API v1

Все API-маршруты используют ту же браузерную Django-сессию. POST-запросы защищены CSRF; для них передавай CSRF-токен в заголовке X-CSRFToken. Идентификаторы задач привязаны к HMAC-отпечатку сессии, поэтому другая сессия не может получить чужую задачу.

- GET /api/v1/status/ — состояние конфигурации и подключений.
- POST /api/v1/transfers/ — поставить перенос в очередь.
- GET /api/v1/transfers/{job_id}/ — состояние и прогресс.
- GET /api/v1/transfers/{job_id}/report/ — JSON-отчёт после завершения.
- GET /api/v1/openapi.json — OpenAPI 3.1 schema.
- GET /healthz/ — health check для оркестратора.

Пример POST body:

    {
      "source_url": "https://vk.ru/music/playlist/241688629_5_b8781ccec850436700",
      "target_playlist": ""
    }

Пустой target_playlist означает создание нового приватного плейлиста. API возвращает HTTP 202 и объект job; клиент опрашивает endpoint задачи до статуса succeeded или failed.

## Локальная разработка

Установите зависимости и запустите миграции:

    pip install -r requirements.txt -r requirements-dev.txt
    python manage.py migrate
    python manage.py runserver 127.0.0.1:8000

Для фоновой обработки отдельно запустите Redis и Celery worker:

    celery -A config worker --loglevel=INFO

## Проверки безопасности в CI

- pytest и Django system checks;
- Ruff;
- Bandit и Semgrep (SAST);
- pip-audit (SCA);
- Gitleaks (поиск секретов);
- Trivy filesystem и container image scan;
- Hadolint;
- OWASP ZAP baseline DAST на поднятом приложении.

CI — это набор автоматизированных проверок, а не доказательство отсутствия уязвимостей. DAST выполняется без авторизации и не покрывает все пользовательские сценарии.

## Важные ограничения

VK audio API может меняться, так как для получения содержимого плейлиста используется API веб-клиента. Spotify rate limits могут влиять на скорость больших переносов. Фоновая задача не повторяет автоматически неидемпотентную операцию добавления треков, чтобы избежать дублирования при неизвестном результате сетевого запроса.
