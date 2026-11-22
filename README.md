# VK → Spotify

Django-приложение для переноса плейлистов VK в Spotify.

## Возможности
- Получение ID композиций VK через batch.call и метаданных через audio.getById.
- Сохранение исходного порядка.
- Spotify OAuth Authorization Code с проверкой state и обновлением токена.
- Сопоставление по названию, исполнителю и длительности.
- Создание приватного плейлиста или добавление в существующий плейлист подключённого владельца.
- CSV-отчёт по результатам.

## Локальный запуск
1. Скопируйте .env.example в .env и заполните ключи.
2. Создайте Spotify app и добавьте redirect URI из SPOTIFY_REDIRECT_URI.
3. Установите зависимости requirements.txt.
4. Выполните python manage.py migrate и python manage.py runserver 127.0.0.1:8000.

## Docker
Заполните .env, задайте уникальные DJANGO_SECRET_KEY и POSTGRES_PASSWORD, затем docker compose up --build. Интерфейс опубликован только на localhost.

## Security
Секреты читаются из окружения; OAuth-токены хранятся в серверной БД-сессии; включены CSRF middleware, безопасные cookie, OAuth state, allowlist доменов VK, таймауты HTTP, проверка владельца целевого плейлиста и приватное создание нового плейлиста. Не используйте браузерные Cookie VK.

CI: pytest, Ruff, Django checks, Bandit и Semgrep (SAST), pip-audit (SCA), Gitleaks, Trivy image scan, Hadolint и OWASP ZAP baseline (DAST). Успешный скан не доказывает отсутствие уязвимостей.

## Ограничение текущей итерации
Перенос синхронный. Для крупных плейлистов следующей задачей будет фоновая очередь с прогрессом и повторными попытками. VK audio API может изменяться, так как используется методика взаимодействия веб-клиента.
