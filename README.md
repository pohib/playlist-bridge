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

Полный пофайловый справочник см. в [FILES.md](FILES.md).

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
deploy/                   Пример Caddy TLS reverse proxy
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

### 3. Production без Cloudflare Tunnel (Linux + собственный домен + Caddy)

Для постоянного публичного запуска используйте Linux-сервер с публичным IP, DNS-доменом и TLS reverse proxy. В этом сценарии Cloudflare Tunnel и `cloudflared` не нужны: Caddy работает непосредственно на сервере, получает сертификат Let's Encrypt и проксирует HTTPS в локальный Nginx контейнер.

**Схема:** Интернет → Caddy (80/443, TLS) → Nginx в Docker (127.0.0.1:8000) → Django/Gunicorn → PostgreSQL/Redis.

1. Подготовьте Ubuntu Server (рекомендуется актуальный LTS), установите Docker Engine + Compose plugin и Caddy из официального репозитория Caddy. Настройте DNS A-запись домена на публичный IPv4 сервера; если публикуете AAAA, он тоже должен вести на этот сервер.
2. Откройте входящие TCP 80 и 443 в firewall/security group. Не открывайте наружу 8000, 5432 или 6379. Compose публикует Nginx только на `127.0.0.1:8000`; PostgreSQL и Redis наружу не публикуются.
3. Разместите проект на сервере и подготовьте окружение:

~~~bash
git clone https://github.com/pohib/playlist-bridge.git
cd playlist-bridge
cp .env.example .env
chmod 600 .env
nano .env
~~~

4. Установите production значения в `.env` (замените `music.example.com` своим доменом):

~~~dotenv
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=music.example.com,localhost,127.0.0.1,web
DJANGO_CSRF_TRUSTED_ORIGINS=https://music.example.com
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SECURE_SSL_REDIRECT=true
SPOTIFY_REDIRECT_URI=https://music.example.com/spotify/callback/
SOUNDCLOUD_REDIRECT_URI=https://music.example.com/soundcloud/callback/
~~~

Сгенерируйте отдельные случайные значения для `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` и `TOKEN_ENCRYPTION_KEY`. Для Fernet-ключа используйте:

~~~bash
python3 -c 'import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
~~~

Также заполните OAuth client credentials Spotify/SoundCloud, если планируете эти интеграции. Не меняйте `TOKEN_ENCRYPTION_KEY` после сохранения пользовательских OAuth credentials: без прежнего ключа уже сохранённые токены не расшифровать. Храните резервную копию ключа отдельно и безопасно.

5. Проверьте конфигурацию и запустите стек:

~~~bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 web proxy worker celery-beat
docker compose exec web python manage.py createsuperuser
~~~

Команда запуска web выполняет `collectstatic` и миграции перед стартом Gunicorn. Не запускайте параллельно отдельную миграцию в то же время, когда стартует web. После запуска проверьте локальный health endpoint:

~~~bash
curl -fsS http://127.0.0.1:8000/healthz/
~~~

6. Настройте Caddy. Скопируйте пример из репозитория в системный конфиг, замените домен и проверьте его:

~~~bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo sed -i 's/example.com/music.example.com/g' /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
~~~

Caddy должен иметь возможность слушать порты 80/443 и обращаться к `127.0.0.1:8000`. При корректных DNS и открытых портах Caddy автоматически получит и будет продлевать TLS-сертификат. Проверьте:

~~~bash
curl -fsS https://music.example.com/healthz/
~~~

7. Зарегистрируйте точные HTTPS callback URI в Spotify/SoundCloud Developer Dashboard:
   - `https://music.example.com/spotify/callback/`
   - `https://music.example.com/soundcloud/callback/`

   Перезапустите web/worker после изменения переменных окружения: `docker compose up -d --force-recreate web worker`. Nginx использует динамическое разрешение Docker DNS, поэтому после пересоздания web обычно не требует ручной перенастройки.

**Обновление приложения:**

~~~bash
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 web worker celery-beat
~~~

**Эксплуатация:** регулярно выполняйте backup PostgreSQL и `media/`, храните копии вне сервера, сохраняйте `TOKEN_ENCRYPTION_KEY` отдельно и проверяйте восстановление. Не используйте `docker compose down -v` для обычного обновления — команда удалит persistent volumes. Настройте системный мониторинг диска, RAM, контейнеров, логов и срока действия домена. Ограничьте SSH доступ, обновляйте ОС/Docker и используйте отдельного непривилегированного системного пользователя.

**Важно:** текущий Compose рассчитан на один сервер и один экземпляр web/worker. Это production-oriented single-host deployment, но не отказоустойчивый кластер: нет managed database, внешнего object storage, multi-host failover или встроенного централизованного мониторинга. Перед реальным публичным запуском проведите security review, проверьте восстановление backup на отдельной среде и настройте внешние уведомления об ошибках.

### 4. Временный Cloudflare Tunnel (только для разработки и тестов)

Эти скрипты оставлены для прежнего локального сценария. Для постоянного production-домена используйте шаг 3 с Caddy; Quick Tunnel не нужен.

~~~powershell
winget install --id Cloudflare.cloudflared -e
.\scripts\start-tunnel.ps1
~~~

Для production-like проверки через временный URL (не постоянный production deployment):

~~~powershell
.\scripts\start-tunnel-prod.ps1
~~~

Остановка временного туннеля и связанных Compose-контейнеров:

~~~powershell
.\scripts\stop-tunnel.ps1
~~~

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
