# Playlist Bridge

Playlist Bridge — Django-приложение для импорта музыкальных коллекций в личную библиотеку, сопоставления треков и переноса плейлистов между VK, Spotify и SoundCloud.

Проект построен как модульный Django-монолит, а не набор микросервисов.

## Возможности

| Возможность | VK | Spotify | SoundCloud |
|---|---:|---:|---:|
| Импорт публичного плейлиста по ссылке | Да | Да | Да |
| Импорт отдельного трека по ссылке | Да | Да | Да |
| Импорт собственной библиотеки | — | Да | Да |
| Поиск кандидатов для ручного сопоставления | Ограниченно | Да | Да |
| Создание целевого плейлиста | Нет | Да | Да |
| Загрузка аудиофайла, предоставленного пользователем | Нет | Нет | Да |

- Коллекции сохраняются в личной библиотеке. Доступ к плейлистам, трекам и задачам ограничивается владельцем.
- При переносе приложение ищет существующие треки, создаёт целевой плейлист и предлагает вручную разобрать неоднозначные или ненайденные композиции.
- Импорт VK использует методы публичного веб-клиента. Это не стабильный публичный API: методы, анонимный токен и ограничения могут измениться.
- Spotify и SoundCloud подключаются через OAuth. SoundCloud использует Authorization Code с PKCE S256.
- Пользовательские access/refresh tokens шифруются Fernet и хранятся в PostgreSQL. Они не помещаются в .env, браузерную сессию или аргументы Celery.
- Встроенный плеер поддерживает очередь, shuffle/repeat, громкость и локальное воспроизведение. Spotify и SoundCloud воспроизводятся через embed-плееры; приложение не извлекает и не скачивает их аудио.

YouTube Music и Apple Music пока не являются полноценными провайдерами импорта или переноса. Некоторые экраны могут предоставлять внешние ссылки на поиск.

## Архитектура

~~~text
config/                  Django settings, URL root, ASGI/WSGI, Celery
transfer/
  api/                   HTTP API, сериализация, OpenAPI
  domain_models/         Django-модели по доменам
  oauth/                 OAuth workflows провайдеров
  services/              бизнес-логика, клиенты API, matching, dispatch
  templates/             Django templates
  static/                CSS, JavaScript, изображения
  tests/                 тесты приложения
nginx/                   локальный reverse proxy
scripts/                 PowerShell запуск, остановка, backup/restore
compose*.yaml            Docker Compose конфигурации
~~~

Основные компоненты:

- **Django + Gunicorn** — веб-приложение и серверные endpoints.
- **PostgreSQL** — пользователи, библиотека, OAuth credentials, история переносов и административные события.
- **Redis + Celery** — фоновые задачи и доставка заданий.
- **Celery beat** — периодическая доставка ожидающих заданий и обслуживание задач.
- **Nginx** — reverse proxy перед Django.
- **Cloudflare Quick Tunnel** — временный HTTPS-доступ к локальному Nginx; не заменяет production-домен и полноценную инфраструктуру.

Старые модули views.py, core.py, models.py, api_views.py и отдельные *_views.py могут содержать compatibility exports. Новые обработчики подключайте к URL из профильных модулей, а бизнес-логику размещайте в transfer/services/. Не удаляйте compatibility facade без поиска всех импортов и регрессионных тестов.

## Требования

- Windows 10/11 + PowerShell и Docker Desktop — для описанных ниже сценариев разработки.
- Docker Engine с поддержкой Docker Compose v2.
- Python 3.12+ — для локального запуска тестов и инструментов.
- cloudflared — только если нужен публичный Quick Tunnel.
- Spotify Developer App и SoundCloud Developer App — для соответствующих OAuth-интеграций. VK OAuth-приложение для публичного импорта не требуется.

## Быстрый запуск

### 1. Получить проект и подготовить .env

PowerShell:

~~~powershell
git clone https://github.com/pohib/playlist-bridge.git
cd playlist-bridge
Copy-Item .env.example .env
notepad .env
~~~

Если проект уже клонирован:

~~~powershell
git switch main
git pull --ff-only origin main
~~~

Сгенерируйте отдельные секреты:

~~~powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
~~~

Укажите значения соответственно в DJANGO_SECRET_KEY, POSTGRES_PASSWORD и TOKEN_ENCRYPTION_KEY. Не используйте одно значение для нескольких параметров и не публикуйте .env.

Заполните OAuth credentials: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SOUNDCLOUD_CLIENT_ID и SOUNDCLOUD_CLIENT_SECRET. DATABASE_URL формируется Compose из POSTGRES_PASSWORD; вручную задавать его в .env не нужно. Полный список переменных находится в .env.example.

### 2. Локальная разработка

Dev overlay включает Django DEBUG, autoreload и bind mount исходников. Он использует отдельное имя Compose-проекта и отдельные volumes, поэтому данные dev-окружения не смешиваются с обычным compose.yaml.

~~~powershell
docker compose -f compose.yaml -f compose.dev.yaml up --build -d
docker compose -f compose.yaml -f compose.dev.yaml ps
docker compose -f compose.yaml -f compose.dev.yaml logs -f web worker celery-beat
~~~

Адреса:
- Django напрямую: http://127.0.0.1:8002/
- Через Nginx: http://127.0.0.1:8000/

После изменения Python-кода Django web перезагружается автоматически. Worker и beat — отдельные процессы; перезапускайте их после изменения задач или кода, который они импортируют:

~~~powershell
docker compose -f compose.yaml -f compose.dev.yaml restart worker celery-beat
~~~

Изменения зависимостей требуют пересборки соответствующих образов. После изменения моделей создайте и примените миграции:

~~~powershell
docker compose -f compose.yaml -f compose.dev.yaml exec web python manage.py makemigrations
docker compose -f compose.yaml -f compose.dev.yaml exec web python manage.py migrate
~~~

Для CSS/JS при необходимости обновите cache-busting параметр в шаблоне и выполните жёсткое обновление страницы (Ctrl+F5).

Остановка dev-стека с сохранением volumes:

~~~powershell
docker compose -f compose.yaml -f compose.dev.yaml down
~~~

Не используйте down -v, если не хотите удалить dev-базу и Redis volume.

### 3. Временный публичный HTTPS-доступ

Установите Docker Desktop и cloudflared:

~~~powershell
winget install --id Cloudflare.cloudflared -e
cloudflared --version
~~~

Для временной отладки с DEBUG:

~~~powershell
.\scripts\start-tunnel.ps1
~~~

Скрипт использует dev overlay и требует явного подтверждения публикации DEBUG-окружения. **Не оставляйте DEBUG-версию публично доступной.**

Для production-like проверки с Gunicorn и DEBUG=False:

~~~powershell
.\scripts\start-tunnel-prod.ps1
~~~

Этот сценарий использует основной compose.yaml и не является полноценным production deployment: Quick Tunnel выдаёт временный адрес, а локальная машина остаётся хостом приложения. После запуска скрипт печатает URL и callback URI. Зарегистрируйте точные callback URI в настройках Spotify и SoundCloud.

Остановить туннель и Compose-окружения:

~~~powershell
.\scripts\stop-tunnel.ps1
~~~

Команда остановки удаляет контейнеры и сети обоих Compose-проектов, но сохраняет именованные volumes. Для обычного применения изменений не запускайте stop/start скрипты: пересоздавайте только изменённые сервисы через Compose. Если пересоздаётся web, учитывайте зависимость Nginx proxy от адреса web-контейнера.

## API

- /api/docs/ — интерактивная документация.
- /api/v1/openapi.json — OpenAPI 3.1 schema.
- GET /api/v1/status/ — статус подключений и конфигурации провайдеров.
- POST /api/v1/transfers/ — создание фоновой задачи переноса.
- GET /api/v1/transfers/{job_id}/ — статус и прогресс задачи.
- GET /api/v1/transfers/{job_id}/report/ — JSON-отчёт.
- GET /healthz/ — health check.

API использует браузерную сессию и CSRF-защиту. OAuth-токены провайдеров не передаются клиентом в теле API-запросов.

## Панель управления

Кастомная панель расположена по адресу /control/. Она предназначена для staff-пользователей с соответствующими Django permissions; наличие аккаунта само по себе не даёт доступ к панели. /admin/ перенаправляет на кастомную панель.

В зависимости от прав доступны управление пользователями и ролями, библиотеками, фоновыми задачами, аудитом и системной диагностикой. Чувствительные сведения безопасности — IP-адреса, User-Agent и глобальные security events — ограничены superuser. Панель поддерживает историю IP-блокировок и блокировок аккаунтов; временная блокировка аккаунта не меняет is_active, поэтому доступ восстанавливается после истечения срока или отзыва блокировки.

Секреты OAuth, расшифрованные credentials и session fingerprints в интерфейсе не показываются. Административные действия должны оставаться permission-protected и попадать в аудит.

## Безопасность

- OAuth state/PKCE и серверное хранение зашифрованных пользовательских credentials.
- CSRF-защита форм и session-bound API; ownership checks для пользовательских объектов.
- Ограничения входных URL и доменов, SSRF-защита provider clients и media proxy.
- Защищённые cookie и security headers на HTTPS-конфигурации.
- Ограничение частоты неудачных попыток входа и журналирование security events без записи паролей, токенов и cookies.
- Разделение staff permissions и superuser-only security data.
- Nginx блокирует доступ к служебным файлам и каталогам репозитория.

Для постоянного публичного хоста используйте HTTPS, корректные DJANGO_ALLOWED_HOSTS и DJANGO_CSRF_TRUSTED_ORIGINS, SESSION_COOKIE_SECURE=true, CSRF_COOKIE_SECURE=true, SECURE_SSL_REDIRECT=true, доверенный reverse proxy и отдельное хранилище секретов. Не публикуйте DEBUG-окружение.

## Фоновые задачи и восстановление

Новая задача переноса сохраняется в PostgreSQL, а в Redis передаётся идентификатор. Периодический dispatch восстанавливает доставку ожидающих задач, если Redis временно был недоступен. Worker атомарно захватывает задачу, обновляет heartbeat и сохраняет checkpoints.

Для проверки зависших задач без изменений:

~~~powershell
docker compose exec web python manage.py fail_stale_transfers --older-than-minutes 60 --dry-run
~~~

Для выполнения проверки:

~~~powershell
docker compose exec web python manage.py fail_stale_transfers --older-than-minutes 60
~~~

Команда dispatch:

~~~powershell
docker compose exec web python manage.py dispatch_queued_transfers --dry-run
docker compose exec web python manage.py dispatch_queued_transfers
~~~

Перед ручным повтором или изменением статуса проверьте фактическое содержимое целевого плейлиста. Внешний API мог принять запись до сбоя worker. Не включайте слепые retries для внешних POST-запросов: это может создать дубликаты.

## Backup и restore

PowerShell-скрипты работают с production-like Compose:

~~~powershell
.\scripts\backup.ps1
.\scripts\backup.ps1 -OutputRoot 'E:\PlaylistBridgeBackups' -RetentionDays 14
.\scripts\restore.ps1 -BackupPath '.\backups\<backup-folder>'
~~~

Backup включает PostgreSQL dump, архив media/ и SHA-256 manifest. Скрипты не архивируют .env и не шифруют backup. Для восстановления OAuth credentials необходим исходный TOKEN_ENCRYPTION_KEY. Храните резервные копии вне рабочей машины в защищённом хранилище и регулярно проверяйте restore на отдельном окружении. Runtime restore drill не следует считать подтверждённым только по факту наличия скриптов.

## Разработка и тестирование

Установить зависимости:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
~~~

Основные проверки:

~~~bash
ruff check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q
pytest -q --cov=transfer --cov-report=term-missing
~~~

Дополнительные инструкции, структура тестов, fuzzing и требования к покрытию описаны в TESTING.md.

CI workflow включает тесты, Ruff/Django checks, SAST/SCA/secrets, container scan и DAST; CodeQL запускается отдельным workflow. Результаты CI и CodeQL нужно проверять для конкретного commit в GitHub Actions — README намеренно не фиксирует меняющиеся номера тестов, coverage и статус проверок.

## Известные ограничения

- VK audio import опирается на внутренние методы публичного веб-клиента, которые могут измениться или стать недоступными.
- Spotify API может ограничивать запросы по тарифу, Development Mode, квотам и rate limits. Client Credentials не обходят ограничения Spotify.
- SoundCloud и Spotify могут менять API и OAuth требования.
- Импорт и перенос с реальными аккаунтами требуют отдельной интеграционной проверки; CI использует mock-ответы и не выполняет реальные операции с пользовательскими плейлистами.
- Плеер не предоставляет прямое аудио Spotify/SoundCloud и зависит от embed-возможностей провайдеров.
- Quick Tunnel — временный механизм доступа, не замена постоянному домену и production-инфраструктуре.
- Backup/restore требует практического тестового восстановления; наличие CI проверки синтаксиса скриптов не подтверждает восстановление реальной базы.

## План дальнейшей работы

- Завершить аудит разрешений и административных действий, включая журналирование чувствительных операций.
- Расширить аналитику пользовательской активности и операционных ошибок без раскрытия сетевых данных обычному staff.
- Добавить browser-based E2E для плеера, внутренней навигации и адаптивного интерфейса.
- Улучшить отчёты переноса, matching неоднозначных версий и обработку rate limits.
- Провести регулярный backup/restore drill и настроить зашифрованное off-site хранение.
- Подготовить отдельное production окружение с постоянным доменом, управляемыми секретами и мониторингом.
- Реализовать экспорт и удаление пользовательских данных.

---

## Ссылки

- [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
- [SoundCloud Developers](https://developers.soundcloud.com/)
- [Django documentation](https://docs.djangoproject.com/)
- [Celery documentation](https://docs.celeryq.dev/)
