# Структура проекта Playlist Bridge

Документ описывает **каждый файл, отслеживаемый Git на ветке main** на момент обновления. Он предназначен для навигации разработчика и технического ревью. Сгенерированные файлы, локальные данные, содержимое .env, виртуальные окружения и пользовательские медиа не входят в список, если они не отслеживаются Git.

## Как читать структуру

- `config/` — конфигурация Django и инфраструктурных компонентов.
- `transfer/` — основное Django-приложение: HTTP handlers, API, модели, бизнес-сервисы, шаблоны, статика и тесты.
- `compose.yaml` — production-like контейнерный стек; `compose.dev.yaml` — overlay разработки.
- `scripts/` — эксплуатационные PowerShell и security automation.
- `nginx/` и `deploy/` — reverse proxy и TLS edge proxy configuration.
- `transfer/*_views.py`, `core.py`, `models.py`, `api_views.py` могут включать compatibility exports. Перед удалением проверяйте импорты и контрактные тесты.

**Важно:** наличие файла в репозитории не означает, что соответствующая внешняя интеграция гарантированно доступна в production. Реальный доступ к провайдерам зависит от их API, OAuth application permissions, квот и ограничений.

## Функциональная карта проекта

Ниже файлы сгруппированы не только по физическим папкам, но и по назначению. Это основной маршрут для поиска кода при работе над конкретной функцией. Полный каталог всех отслеживаемых файлов по папкам находится в разделе «Файлы» ниже.

### Музыкальный плеер и эквалайзер

| Уровень | Файлы | Роль |
|---|---|---|
| UI плеера | `transfer/templates/transfer/partials/global_player.html`, `transfer/templates/transfer/player_popout.html` | Общий встроенный плеер и отдельное pop-out окно. |
| Поведение | `transfer/static/transfer/js/app.js`, `transfer/static/transfer/js/player-popout.js` | Управление воспроизведением, очередью, состоянием плеера и отдельным окном. |
| Оформление | `transfer/static/transfer/styles/main.css`, `transfer/static/transfer/styles/player-popout.css` | Основной интерфейс и стили pop-out плеера. |
| Backend эквалайзера | `transfer/player_eq_views.py`, `transfer/domain_models/admin.py` (`UserEQPreset`) | API сохранения и загрузки пользовательских EQ-пресетов и модель их хранения. |
| Проверки | `transfer/tests/test_playback.py`, `transfer/tests/test_admin_console_player.py`, `transfer/tests/test_player_eq_presets.py` | Воспроизведение, работа плеера в админке и пользовательские пресеты. |

### API и документация API

| Уровень | Файлы | Роль |
|---|---|---|
| HTTP API | `transfer/api/common.py`, `transfer/api/serializers.py`, `transfer/api/status_views.py`, `transfer/api/transfer_views.py` | Общие ответы, сериализация, статус интеграций и endpoints переносов. |
| Документация | `transfer/api/docs_views.py`, `transfer/templates/transfer/api_docs.html` | OpenAPI schema и страница документации. |
| Маршруты и совместимость | `transfer/urls.py`, `transfer/api_views.py` | Регистрация URL и legacy facade для старых импортов. |
| Сервисный слой | `transfer/services/api_transfer_service.py`, `transfer/services/api_transfer_validation.py` | Создание задач API и проверка входных параметров. |
| Проверки | `transfer/tests/test_api_transfer_service.py`, `transfer/tests/test_api_transfer_validation.py`, `transfer/tests/test_api_module_boundaries.py`, `transfer/tests/test_profile_and_api_docs.py` | API-контракты, валидация, границы модулей и документация. |

### Журнал интеграций и фоновых ошибок

| Компонент | Файлы | Роль |
|---|---|---|
| Модель и миграция | `transfer/domain_models/admin.py`, `transfer/migrations/0022_providerintegrationevent.py` | Хранение безопасных событий ошибок провайдеров и фоновых задач. |
| Запись и классификация | `transfer/services/integration_event_recorder.py`, `transfer/tasks.py`, `transfer/services/transfer_dispatch.py` | Маскирование секретов, классификация ошибок переноса и Celery dispatch. |
| Панель | `transfer/admin_console_views.py`, `transfer/templates/transfer/admin_console/integrations.html`, `transfer/templates/transfer/admin_console/base.html`, `transfer/urls.py` | Superuser-only журнал с фильтрами по сервису, категории, датам и поиску. |
| Проверки | `transfer/tests/test_admin_console_integrations.py` | Доступы, фильтры, классификация и проверка отсутствия секретов в событиях. |

### Кастомная административная панель

| Раздел | Файлы | Роль |
|---|---|---|
| Backend и маршруты | `transfer/admin_console_views.py`, `transfer/urls.py` | Обзор, пользователи, роли, библиотеки, очередь задач, аудит, события, безопасность и системная диагностика. |
| Общий каркас | `transfer/templates/transfer/admin_console/base.html`, `pagination.html` | Навигация, общий layout и пагинация с сохранением фильтров. |
| Обзор и аккаунты | `dashboard.html`, `users.html`, `user_detail.html`, `groups.html`, `privileges.html` в `transfer/templates/transfer/admin_console/` | Сводка, карточки пользователей, роли/группы и привилегии. |
| Операции и аудит | `library.html`, `library_detail.html`, `jobs.html`, `job_detail.html`, `audit.html` в `transfer/templates/transfer/admin_console/` | Просмотр библиотек, переносов и административного журнала. |
| Безопасность и состояние | `security.html`, `ip_bans.html`, `events.html`, `system.html` в `transfer/templates/transfer/admin_console/` | События безопасности, IP/account bans, центр событий и диагностика сервисов. |
| Данные | `transfer/domain_models/admin.py`, `transfer/domain_models/jobs.py`, `transfer/domain_models/library.py` | Аудит, security telemetry, блокировки, EQ-пресеты, задачи и библиотечные сущности. |
| Стили | `transfer/static/transfer/styles/admin-console.css` | Отдельная визуальная система админ-панели. |
| Проверки | `transfer/tests/test_admin_console_*.py` | Доступы, роли, привилегии, аудит, блокировки, диагностика, задачи и плеер в панели. |

### Музыкальная библиотека, плейлисты и импорт

| Подсистема | Файлы | Роль |
|---|---|---|
| Страницы и HTTP handlers | `transfer/library_page_views.py`, `library_playlist_management_views.py`, `library_track_management_views.py`, `library_profile_management_views.py`, `library_search_views.py` | Страницы библиотеки, операции над плейлистами/треками/профилем и поиск. |
| Импорт провайдеров | `transfer/library_vk_import_views.py`, `library_spotify_import_views.py`, `library_soundcloud_import_views.py` | HTTP endpoints импорта из VK, Spotify и SoundCloud. |
| Загрузка и проигрывание | `transfer/library_provider_upload_views.py`, `library_local_playback_views.py`, `library_vk_playback_views.py`, `library_media_views.py` | Загрузка аудио, локальное/VK-воспроизведение и безопасная работа с обложками. |
| Перенос и ручная проверка | `transfer/library_transfer_create_views.py`, `library_transfer_review_views.py` | Создание переноса и ручное сопоставление нераспознанных треков. |
| Доменная логика | `transfer/services/library_*.py`, `transfer/domain_models/library.py` | Импорт, поиск, управление библиотекой, сопоставление и сохранение данных. |
| UI и модели | `transfer/templates/transfer/library.html`, `transfer/models.py` | Интерфейс библиотеки и совместимый фасад доменных моделей. |
| Проверки | `transfer/tests/test_library_*.py`, `test_playlist_editing.py`, `test_single_track_import_workflows.py` | Импорт, редактирование, поиск, переносы, загрузка и регрессии библиотеки. |

### OAuth и интеграции музыкальных сервисов

| Подсистема | Файлы | Роль |
|---|---|---|
| OAuth workflow | `transfer/oauth/clients.py`, `shared.py`, `spotify.py`, `soundcloud.py`, `transfer/oauth_views.py` | OAuth-клиенты, state/PKCE, callback и подключение Spotify/SoundCloud. |
| Клиенты API | `transfer/services/spotify_client.py`, `soundcloud_client.py`, `vk_client.py` | Запросы к API провайдеров. |
| Доступ и поиск | `transfer/services/provider_catalog_access.py`, `free_music_catalog_search.py`, `library_source_search.py`, `library_source_search_service.py` | Проверка доступности каталогов и поиск источников/треков. |
| VK audio | `transfer/services/vk_anonymous_token.py`, `vk_audio_metadata.py`, `library_vk_playback.py` | Получение анонимного токена, метаданные и подготовка потока VK. |
| Credentials | `transfer/domain_models/credentials.py`, `transfer/services/credential_service.py`, `oauth_session_service.py` | Хранение и обслуживание подключений; секреты не должны попадать в админский HTML или логи. |
| Проверки | `transfer/tests/test_oauth_flows.py`, `test_oauth_session_service.py`, `test_provider_clients.py`, `test_provider_catalog_access.py` | OAuth-сценарии, клиентские контракты и доступность каталогов. |

### Фоновые задачи и переносы

| Уровень | Файлы | Роль |
|---|---|---|
| Модель задачи | `transfer/domain_models/jobs.py` | Статус, прогресс, heartbeat, dispatch attempts, checkpoint и результат переноса. |
| Celery tasks | `transfer/tasks.py`, `config/celery.py` | Исполнение переноса, доставка ожидающих задач и очистка устаревшей security telemetry. |
| Оркестрация | `transfer/services/transfer_service.py`, `transfer/services/transfer_dispatch.py` | Перенос библиотеки, безопасная доставка задач и восстановление зависших задач. |
| CLI recovery | `transfer/management/commands/dispatch_queued_transfers.py`, `fail_stale_transfers.py` | Ручной/плановый запуск восстановления очереди и обработка зависших задач. |
| Админский мониторинг | `transfer/admin_console_views.py`, `jobs.html`, `job_detail.html` в `transfer/templates/transfer/admin_console/` | Статистика очереди, backlog dispatch, stale heartbeat и диагностика конкретной задачи без вывода checkpoint/result. |
| Проверки | `transfer/tests/test_transfer_dispatch.py`, `test_transfer_task_recovery.py`, `test_admin_console_details.py` | Защита от дублирования, восстановление и отображение диагностики. |

### Аутентификация, безопасность и аудит

| Подсистема | Файлы | Роль |
|---|---|---|
| Вход и аккаунты | `transfer/auth_views.py`, `transfer/services/login_throttle.py`, `transfer/services/auth_security_audit.py` | Регистрация/вход, ограничение перебора и аудит аутентификации. |
| Request telemetry | `transfer/security_activity_middleware.py`, `config/security.py` | IP/account bans, allowlist событий действий, security headers и CSP. |
| Security data | `transfer/domain_models/admin.py`, `transfer/services/security_event_retention.py`, `transfer/management/commands/purge_security_events.py` | Журнал событий, история блокировок и retention. |
| Проверки | `transfer/tests/test_login_throttle.py`, `test_security_activity_middleware.py`, `test_security_event_retention.py`, `test_admin_console_security.py`, `test_admin_console_ip_bans.py`, `test_admin_console_account_bans.py` | Регрессии аутентификации, телеметрии, retention и управления блокировками. |

### Инфраструктура, запуск и эксплуатация

| Область | Файлы | Роль |
|---|---|---|
| Django config | `config/settings.py`, `urls.py`, `wsgi.py`, `asgi.py`, `storage.py`, `celery.py` | Настройки, маршрутизация, entrypoints, статика и Celery. |
| Контейнеры | `Dockerfile`, `compose.yaml`, `compose.dev.yaml`, `requirements.txt`, `requirements-dev.txt` | Сборка и запуск приложения, БД, Redis, Nginx и worker. |
| Reverse proxy и TLS | `nginx/default.conf`, `nginx/errors/404.html`, `deploy/Caddyfile` | Внутренний reverse proxy, ошибка 404 и внешний HTTPS edge proxy. |
| Операционные скрипты | `scripts/start-tunnel.ps1`, `start-tunnel-prod.ps1`, `stop-tunnel.ps1`, `backup.ps1`, `restore.ps1` | Локальный запуск, временный tunnel, резервное копирование и восстановление. |
| Документация | `README.md`, `TESTING.md`, `FILES.md` | Запуск разработки/production, тестирование и карта исходников. |

### Тестирование и security automation

| Область | Файлы | Роль |
|---|---|---|
| CI workflows | `.github/workflows/ci.yml`, `codeql.yml`, `dependabot-automerge.yml`, `.github/dependabot.yml` | Тесты, SAST/SCA, secrets scan, container scan, CodeQL и обновления зависимостей. |
| DAST | `.zap/rules.tsv`, `scripts/security/dast_auth_check.sh`, `dast_bootstrap.py` | Настройка и подготовка авторизованного DAST. |
| Тестовая инфраструктура | `pytest.ini`, `pyproject.toml`, `.coveragerc`, `TESTING.md` | Конфигурация тестов, линтера, фаззинга и покрытия. |
| Тесты | `transfer/tests/` | Unit, integration, security, API, UI и regression tests. |

---

## Файлы

### Корень репозитория

| Файл | Назначение |
|---|---|
| `.coveragerc` | Правила включения и исключения файлов при измерении покрытия тестами. |
| `.env.example` | Шаблон переменных окружения; содержит только безопасные заглушки, не секреты. |
| `.gitignore` | Исключения Git для секретов, виртуальных окружений, кешей, логов, медиа и backup. |
| `.gitleaks.toml` | Конфигурация Gitleaks и допустимых исключений для поиска секретов. |
| `.trivyignore` | Список явно подавленных Trivy findings с привязкой к правилам/обоснованиям. |
| `Dockerfile` | Образ Django-приложения: Python runtime, зависимости, непривилегированный пользователь и Gunicorn. |
| `README.md` | Основная документация: возможности, запуск разработки, production deployment, API и эксплуатация. |
| `FILES.md` | Этот справочник: назначение всех отслеживаемых файлов проекта, включая сам документ. |
| `TESTING.md` | Инструкции по тестам, фаззингу, покрытию, CI и тестовым границам. |
| `compose.dev.yaml` | Development overlay: DEBUG, runserver, bind mounts и изолированный Compose project. |
| `compose.yaml` | Основной production-like Docker Compose стек: Django, Nginx, Celery, PostgreSQL и Redis. |
| `manage.py` | Командная точка входа Django management commands. |
| `pyproject.toml` | Настройки Ruff, pytest/Hypothesis и инструментов Python-проекта. |
| `pytest.ini` | Конфигурация обнаружения и запуска pytest/Django tests. |
| `requirements-dev.txt` | Зависимости разработки и тестирования поверх runtime requirements. |
| `requirements.txt` | Runtime Python-зависимости приложения. |

### .github

| Файл | Назначение |
|---|---|
| `dependabot.yml` | Настройки Dependabot для автоматического поиска обновлений зависимостей. |

### .github/workflows

| Файл | Назначение |
|---|---|
| `ci.yml` | Основной CI: проверки стиля, Django, тесты, анализ зависимостей/секретов, контейнера и DAST. |
| `codeql.yml` | Отдельный workflow GitHub CodeQL для статического анализа Python-кода. |
| `dependabot-automerge.yml` | Ограниченная автоматизация слияния подходящих Dependabot PR после проверок. |

### .zap

| Файл | Назначение |
|---|---|
| `rules.tsv` | Правила и исключения OWASP ZAP для DAST-проверок. |

### config

| Файл | Назначение |
|---|---|
| `__init__.py` | Маркер Python-пакета конфигурации. |
| `asgi.py` | ASGI entrypoint Django для ASGI-совместимого сервера. |
| `celery.py` | Создание и настройка Celery application с Django settings. |
| `security.py` | Пользовательское middleware security headers и CSP. |
| `settings.py` | Основные настройки Django, БД, сессий, статики, OAuth, Redis, Celery и логирования. |
| `storage.py` | Настройки backend хранения статических файлов с manifest compression. |
| `urls.py` | Корневые URL-маршруты Django и пользовательские обработчики ошибок. |
| `wsgi.py` | WSGI entrypoint Django для Gunicorn. |

### deploy

| Файл | Назначение |
|---|---|
| `Caddyfile` | Пример конфигурации Caddy для постоянного домена, автоматического HTTPS и передачи доверенных forwarded headers без Cloudflare Tunnel. |

### nginx

| Файл | Назначение |
|---|---|
| `default.conf` | Reverse proxy Nginx, безопасный Host для upstream, доверенные forwarded headers, access log и блокировка служебных путей. |

### nginx/errors

| Файл | Назначение |
|---|---|
| `404.html` | Пользовательская статическая страница 404 для Nginx. |

### reports

| Файл | Назначение |
|---|---|
| `.gitkeep` | Служебный файл проекта: .gitkeep. |

### scripts

| Файл | Назначение |
|---|---|
| `backup.ps1` | PowerShell backup PostgreSQL и media с проверкой архива, SHA-256 manifest и retention. |
| `restore.ps1` | Проверяемое восстановление PostgreSQL и media с обязательным pre-restore backup. |
| `start-tunnel-prod.ps1` | Локальный production-like запуск с Gunicorn и временным Cloudflare Quick Tunnel. |
| `start-tunnel.ps1` | Локальный dev запуск и временный Cloudflare Quick Tunnel с проверками готовности. |
| `stop-tunnel.ps1` | Остановка процессов Quick Tunnel и связанных Compose окружений проекта. |

### scripts/security

| Файл | Назначение |
|---|---|
| `dast_auth_check.sh` | Подготовка/проверка авторизованного DAST сценария. |
| `dast_bootstrap.py` | Bootstrap вспомогательных учётных данных/состояния для DAST. |

### transfer

| Файл | Назначение |
|---|---|
| `__init__.py` | Маркер Python-пакета Django-приложения transfer. |
| `account_page_views.py` | Страницы аккаунта: подключения, профиль, история переносов и popout плеер. |
| `admin.py` | Регистрация моделей в стандартной Django admin (основной интерфейс проекта — /control/). |
| `admin_console_views.py` | Staff-only кастомная админ-панель, разрешения, аудит, диагностика и управление. |
| `api_views.py` | Совместимый фасад API endpoints; новые endpoint handlers находятся в transfer/api/. |
| `apps.py` | Конфигурация Django-приложения transfer. |
| `auth_views.py` | Регистрация, вход, выход и пользовательские authentication flows. |
| `context_processors.py` | Глобальный контекст шаблонов для текущего рабочего пространства библиотеки. |
| `core.py` | Совместимый фасад legacy core/service функций. |
| `credentials.py` | Совместимый фасад функций шифрования и доступа к credentials. |
| `dashboard_views.py` | Главная рабочая панель авторизованного пользователя. |
| `error_views.py` | Русскоязычные пользовательские HTTP error pages. |
| `forms.py` | Модуль приложения transfer: forms. |
| `landing_views.py` | Публичная landing/home page. |
| `library_import_views.py` | Совместимый фасад обработчиков импорта библиотеки. |
| `library_local_playback_views.py` | Локальная потоковая отдача загруженных пользователем аудиофайлов. |
| `library_management_views.py` | Совместимый фасад операций управления библиотекой. |
| `library_media_views.py` | Безопасная отдача и проксирование изображений/обложек. |
| `library_page_views.py` | Страницы библиотеки и подробного просмотра плейлиста. |
| `library_playback_views.py` | Совместимый фасад обработчиков воспроизведения. |
| `library_playlist_management_views.py` | HTTP handlers операций над плейлистами. |
| `library_profile_management_views.py` | HTTP handlers редактирования профиля библиотеки. |
| `library_provider_upload_views.py` | HTTP handlers загрузки аудиотреков к провайдерам. |
| `library_search_views.py` | HTTP handlers поиска и открытия источников треков/плейлистов. |
| `library_soundcloud_import_views.py` | HTTP handlers импорта SoundCloud. |
| `library_spotify_import_views.py` | HTTP handlers импорта Spotify. |
| `library_support.py` | Совместимые вспомогательные функции library views. |
| `library_track_management_views.py` | HTTP handlers добавления, изменения и удаления треков. |
| `library_transfer_create_views.py` | HTTP handlers создания переноса библиотеки. |
| `library_transfer_review_views.py` | HTTP handlers ручного сопоставления элементов переноса. |
| `library_transfer_views.py` | Совместимый фасад HTTP handlers переноса. |
| `library_views.py` | Совместимый фасад старых library view imports. |
| `library_vk_import_views.py` | HTTP handlers импорта VK. |
| `library_vk_playback_views.py` | HTTP handlers воспроизведения аудио VK. |
| `models.py` | Совместимый публичный фасад экспорта доменных моделей. |
| `oauth_views.py` | Совместимый фасад OAuth views провайдеров. |
| `player_eq_views.py` | API и операции сохранения пользовательских пресетов эквалайзера. |
| `security_activity_middleware.py` | Проверка IP/account bans и запись allowlist пользовательских действий в security telemetry. |
| `site_views.py` | Совместимый фасад общих страниц сайта. |
| `system_views.py` | Health check и технические system endpoints. |
| `tasks.py` | Celery tasks для фонового переноса и обслуживания задач. |
| `urls.py` | Маршруты пользовательского сайта, библиотеки, OAuth, API и кастомной админки. |
| `views.py` | Совместимый фасад legacy view handlers, сохраняющий старые импорты. |

### transfer/api

| Файл | Назначение |
|---|---|
| `__init__.py` | Пакет HTTP API. |
| `common.py` | Общие API helpers и контракты. |
| `docs_views.py` | OpenAPI schema и endpoint интерактивной документации. |
| `serializers.py` | Сериализация и валидация входных/выходных API данных. |
| `status_views.py` | Endpoint статуса подключений и провайдеров. |
| `transfer_views.py` | API endpoints создания, статуса и отчётов переноса. |

### transfer/domain_models

| Файл | Назначение |
|---|---|
| `__init__.py` | Публичные экспорты доменных Django-моделей. |
| `admin.py` | Модели аудита, событий безопасности, EQ presets и блокировок. |
| `credentials.py` | Модели подключений и OAuth credentials. |
| `jobs.py` | Модели фоновых задач, прогресса и переноса. |
| `library.py` | Модели профилей, плейлистов и треков библиотеки. |

### transfer/management

| Файл | Назначение |
|---|---|
| `__init__.py` | Модуль приложения transfer:   init  . |

### transfer/management/commands

| Файл | Назначение |
|---|---|
| `__init__.py` | Пользовательская команда Django. |
| `dispatch_queued_transfers.py` | Management command доставки ожидающих задач в Celery. |
| `fail_stale_transfers.py` | Поиск и обработка зависших/просроченных задач переноса. |
| `purge_security_events.py` | Очистка событий безопасности старше retention периода. |

### transfer/migrations

| Файл | Назначение |
|---|---|
| `0001_initial.py` | Начальная схема моделей приложения. |
| `0002_oauthcredential.py` | Добавляет модель OAuth credentials. |
| `0003_one_active_transfer_per_session.py` | Ограничивает одновременные активные переносы в рамках сессии. |
| `0004_library_workspace.py` | Добавляет пользовательское рабочее пространство музыкальной библиотеки. |
| `0005_soundcloud_provider.py` | Добавляет поддержку SoundCloud в модели источников/переносов. |
| `0006_user_accounts.py` | Добавляет связи и данные пользовательских аккаунтов. |
| `0007_library_transfer_review.py` | Добавляет сущности ручной проверки сопоставления треков. |
| `0008_transfer_target_playlist.py` | Добавляет сведения о целевом плейлисте переноса. |
| `0009_librarytrack_cover_url.py` | Добавляет URL обложки трека. |
| `0010_librarytrack_source_provider.py` | Добавляет provider/source атрибут трека. |
| `0011_librarytrack_audio_file.py` | Добавляет поле локального аудиофайла. |
| `0012_transferjob_heartbeat_at.py` | Добавляет heartbeat timestamp фоновой задачи. |
| `0013_transferjob_dispatch_state.py` | Добавляет состояние доставки задачи в очередь. |
| `0014_transferjob_checkpoint.py` | Добавляет checkpoint данных для восстановления переноса. |
| `0015_adminauditevent.py` | Добавляет журнал привилегированных действий администраторов. |
| `0016_usersecurityevent.py` | Добавляет телеметрию событий безопасности пользователя. |
| `0017_usersecurityevent_activity_context.py` | Расширяет security events контекстом HTTP-запроса. |
| `0018_usereqpreset.py` | Добавляет пользовательские пресеты эквалайзера. |
| `0018_useripban.py` | Добавляет реестр блокировок IP. |
| `0019_merge_useripban_usereqpreset.py` | Объединяет параллельные migration branches. |
| `0020_allow_ip_ban_history.py` | Разрешает сохранять историю повторных блокировок IP. |
| `0021_useraccountban.py` | Добавляет историю временных и постоянных блокировок аккаунтов. |
| `__init__.py` | Изменение схемы базы данных Django. |

### transfer/oauth

| Файл | Назначение |
|---|---|
| `__init__.py` | Пакет OAuth workflow и клиентов. |
| `clients.py` | Общие HTTP/OAuth client helpers. |
| `shared.py` | Общие state, PKCE и redirect проверки OAuth. |
| `soundcloud.py` | OAuth workflow интеграции SoundCloud. |
| `spotify.py` | OAuth workflow интеграции Spotify. |

### transfer/services

| Файл | Назначение |
|---|---|
| `__init__.py` | Сервисный модуль доменной логики   init  . |
| `account_workspace.py` | Управление и разрешение пользовательских рабочих пространств библиотеки. |
| `api_transfer_service.py` | Сервисный слой создания и получения API задач переноса. |
| `api_transfer_validation.py` | Валидация API входных параметров и ограничений переноса. |
| `audio_file_validation.py` | Проверки типа, размера и допустимости загружаемых аудиофайлов. |
| `auth_security_audit.py` | Запись событий входа и связанных действий безопасности. |
| `common.py` | Общие функции и примитивы сервисного слоя. |
| `credential_service.py` | Шифрование, сохранение и получение OAuth credentials. |
| `free_music_catalog_search.py` | Бесплатный поиск кандидатов по внешним музыкальным каталогам. |
| `library_artwork_proxy.py` | Безопасное получение/проксирование обложек музыкальной библиотеки. |
| `library_import_soundcloud.py` | Импорт музыкальных данных из SoundCloud. |
| `library_import_spotify.py` | Импорт музыкальных данных из Spotify. |
| `library_import_vk.py` | Импорт публичных музыкальных данных VK. |
| `library_imports.py` | Общие orchestration helpers для сценариев импорта. |
| `library_management.py` | Операции управления пользовательской музыкальной библиотекой. |
| `library_management_errors.py` | Доменные исключения и нормализация ошибок библиотеки. |
| `library_playlist_management.py` | Создание, изменение, объединение и удаление плейлистов. |
| `library_presentation.py` | Подготовка библиотечных данных для отображения в UI. |
| `library_profile_management.py` | Управление профилем музыкальной библиотеки. |
| `library_request_context.py` | Получение безопасного контекста пользователя/библиотеки из запроса. |
| `library_soundcloud_upload.py` | Загрузка пользовательских треков в SoundCloud. |
| `library_source_links.py` | Разбор и нормализация ссылок на музыкальные источники. |
| `library_source_search.py` | Поиск музыкальных источников для элементов библиотеки. |
| `library_source_search_service.py` | Оркестрация поиска по поддерживаемым бесплатным каталогам. |
| `library_track_management.py` | Добавление, редактирование, перемещение и удаление треков. |
| `library_transfer_creation.py` | Создание и первичная валидация переноса плейлиста. |
| `library_transfer_matching.py` | Сопоставление исходных треков с кандидатами целевого сервиса. |
| `library_transfer_persistence.py` | Сохранение состояния, элементов и прогресса переноса. |
| `library_transfer_review.py` | Операции ручной проверки ненайденных/неоднозначных треков. |
| `library_transfer_review_provider.py` | Получение кандидатов от внешнего провайдера для ручной проверки. |
| `library_transfer_review_queries.py` | Построение запросов и выборок для review интерфейса. |
| `library_transfer_review_search.py` | Поиск дополнительных кандидатов в процессе review. |
| `library_transfer_search.py` | Поиск целевых треков при переносе. |
| `library_transfer_workflow.py` | Координация полного workflow переноса. |
| `library_upload_management.py` | Проверка и управление локальными загрузками. |
| `library_vk_playback.py` | Получение метаданных и потоков воспроизведения VK. |
| `login_throttle.py` | Ограничение частоты неудачных попыток аутентификации. |
| `oauth_session_service.py` | Управление безопасным OAuth state/session workflow. |
| `provider_catalog_access.py` | Общие механизмы доступа к каталогам музыкальных провайдеров. |
| `security_event_retention.py` | Очистка устаревших событий безопасности согласно retention policy. |
| `soundcloud_client.py` | HTTP-клиент API SoundCloud. |
| `spotify_client.py` | HTTP-клиент API Spotify. |
| `track_matcher.py` | Нормализация и алгоритмы сопоставления названий/исполнителей треков. |
| `transfer_dispatch.py` | Доставка ожидающих задач переноса в Celery. |
| `transfer_service.py` | Бизнес-операции выполнения переноса плейлистов. |
| `vk_anonymous_token.py` | Получение и кэширование анонимного токена VK web API. |
| `vk_audio_metadata.py` | Разбор и нормализация метаданных аудиозаписей VK. |
| `vk_client.py` | HTTP-клиент внутренних/публичных методов VK web API. |

### transfer/static/transfer/images

| Файл | Назначение |
|---|---|
| `brand.svg` | Векторный брендовый ресурс приложения. |

### transfer/static/transfer/js

| Файл | Назначение |
|---|---|
| `app.js` | JavaScript логика интерфейса. |
| `player-popout.js` | JavaScript логика интерфейса. |

### transfer/static/transfer/styles

| Файл | Назначение |
|---|---|
| `admin-console.css` | Таблица стилей интерфейса: admin console.css. |
| `error.css` | Таблица стилей интерфейса: error.css. |
| `main.css` | Таблица стилей интерфейса: main.css. |
| `player-popout.css` | Таблица стилей интерфейса: player popout.css. |

### transfer/templates/transfer/admin_console

| Файл | Назначение |
|---|---|
| `audit.html` | Шаблон административной панели: audit.html. |
| `base.html` | Шаблон административной панели: base.html. |
| `dashboard.html` | Шаблон административной панели: dashboard.html. |
| `events.html` | Шаблон административной панели: events.html. |
| `groups.html` | Шаблон административной панели: groups.html. |
| `ip_bans.html` | Шаблон административной панели: ip bans.html. |
| `job_detail.html` | Шаблон административной панели: job detail.html. |
| `jobs.html` | Шаблон административной панели: jobs.html. |
| `library.html` | Шаблон административной панели: library.html. |
| `library_detail.html` | Шаблон административной панели: library detail.html. |
| `pagination.html` | Шаблон административной панели: pagination.html. |
| `privileges.html` | Шаблон административной панели: privileges.html. |
| `security.html` | Шаблон административной панели: security.html. |
| `system.html` | Шаблон административной панели: system.html. |
| `user_detail.html` | Шаблон административной панели: user detail.html. |
| `users.html` | Шаблон административной панели: users.html. |

### transfer/templates/transfer

| Файл | Назначение |
|---|---|
| `api_docs.html` | Встроенная документация API. |
| `base.html` | Базовый пользовательский layout сайта и подключение общих ресурсов/плеера. |
| `connections.html` | Управление подключениями внешних музыкальных сервисов. |
| `dashboard.html` | Пользовательский dashboard. |
| `home.html` | Главная страница приложения. |
| `landing.html` | Публичная промо-страница. |
| `library.html` | Основной интерфейс музыкальной библиотеки. |
| `player_popout.html` | Отдельная страница/окно popout плеера. |
| `playlist_detail.html` | Детальная страница плейлиста и его треков. |
| `profile.html` | Страница профиля пользователя. |
| `transfer_review.html` | UI ручного сопоставления треков при переносе. |
| `transfers.html` | История и состояние переносов. |

### transfer/templates/transfer/auth

| Файл | Назначение |
|---|---|
| `login.html` | Форма входа. |
| `password_change.html` | Форма смены пароля. |
| `register.html` | Форма регистрации. |

### transfer/templates/transfer/errors

| Файл | Назначение |
|---|---|
| `error.html` | Общий пользовательский шаблон HTTP ошибки. |

### transfer/templates/transfer/partials

| Файл | Назначение |
|---|---|
| `global_player.html` | Общий markup музыкального плеера, сохраняемый между страницами. |

### transfer/tests

| Файл | Назначение |
|---|---|
| `__init__.py` | Автоматические тесты сценариев «  init  »: регрессии, контракты и проверки поведения. |
| `test_account_workspace_service.py` | Автоматические тесты сценариев «account workspace service»: регрессии, контракты и проверки поведения. |
| `test_admin_console_access.py` | Автоматические тесты сценариев «admin console access»: регрессии, контракты и проверки поведения. |
| `test_admin_console_account_bans.py` | Автоматические тесты сценариев «admin console account bans»: регрессии, контракты и проверки поведения. |
| `test_admin_console_details.py` | Автоматические тесты сценариев «admin console details»: регрессии, контракты и проверки поведения. |
| `test_admin_console_events.py` | Автоматические тесты сценариев «admin console events»: регрессии, контракты и проверки поведения. |
| `test_admin_console_ip_bans.py` | Автоматические тесты сценариев «admin console ip bans»: регрессии, контракты и проверки поведения. |
| `test_admin_console_player.py` | Автоматические тесты сценариев «admin console player»: регрессии, контракты и проверки поведения. |
| `test_admin_console_privileges.py` | Автоматические тесты сценариев «admin console privileges»: регрессии, контракты и проверки поведения. |
| `test_admin_console_roles.py` | Автоматические тесты сценариев «admin console roles»: регрессии, контракты и проверки поведения. |
| `test_admin_console_security.py` | Автоматические тесты сценариев «admin console security»: регрессии, контракты и проверки поведения. |
| `test_admin_console_system.py` | Автоматические тесты сценариев «admin console system»: регрессии, контракты и проверки поведения. |
| `test_api_module_boundaries.py` | Автоматические тесты сценариев «api module boundaries»: регрессии, контракты и проверки поведения. |
| `test_api_transfer_service.py` | Автоматические тесты сценариев «api transfer service»: регрессии, контракты и проверки поведения. |
| `test_api_transfer_validation.py` | Автоматические тесты сценариев «api transfer validation»: регрессии, контракты и проверки поведения. |
| `test_audio_file_validation.py` | Автоматические тесты сценариев «audio file validation»: регрессии, контракты и проверки поведения. |
| `test_bulk_import_regressions.py` | Автоматические тесты сценариев «bulk import regressions»: регрессии, контракты и проверки поведения. |
| `test_contracts.py` | Автоматические тесты сценариев «contracts»: регрессии, контракты и проверки поведения. |
| `test_error_pages.py` | Автоматические тесты сценариев «error pages»: регрессии, контракты и проверки поведения. |
| `test_free_music_catalog_search.py` | Автоматические тесты сценариев «free music catalog search»: регрессии, контракты и проверки поведения. |
| `test_fuzzing.py` | Автоматические тесты сценариев «fuzzing»: регрессии, контракты и проверки поведения. |
| `test_legacy.py` | Автоматические тесты сценариев «legacy»: регрессии, контракты и проверки поведения. |
| `test_library_artwork_proxy.py` | Автоматические тесты сценариев «library artwork proxy»: регрессии, контракты и проверки поведения. |
| `test_library_import_service.py` | Автоматические тесты сценариев «library import service»: регрессии, контракты и проверки поведения. |
| `test_library_management_service.py` | Автоматические тесты сценариев «library management service»: регрессии, контракты и проверки поведения. |
| `test_library_presentation_service.py` | Автоматические тесты сценариев «library presentation service»: регрессии, контракты и проверки поведения. |
| `test_library_soundcloud_upload.py` | Автоматические тесты сценариев «library soundcloud upload»: регрессии, контракты и проверки поведения. |
| `test_library_source_links.py` | Автоматические тесты сценариев «library source links»: регрессии, контракты и проверки поведения. |
| `test_library_source_search.py` | Автоматические тесты сценариев «library source search»: регрессии, контракты и проверки поведения. |
| `test_library_source_search_service.py` | Автоматические тесты сценариев «library source search service»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_creation.py` | Автоматические тесты сценариев «library transfer creation»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_matching.py` | Автоматические тесты сценариев «library transfer matching»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_persistence.py` | Автоматические тесты сценариев «library transfer persistence»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_review_provider.py` | Автоматические тесты сценариев «library transfer review provider»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_review_queries.py` | Автоматические тесты сценариев «library transfer review queries»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_review_search.py` | Автоматические тесты сценариев «library transfer review search»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_review_service.py` | Автоматические тесты сценариев «library transfer review service»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_search.py` | Автоматические тесты сценариев «library transfer search»: регрессии, контракты и проверки поведения. |
| `test_library_transfer_workflow.py` | Автоматические тесты сценариев «library transfer workflow»: регрессии, контракты и проверки поведения. |
| `test_library_workflows.py` | Автоматические тесты сценариев «library workflows»: регрессии, контракты и проверки поведения. |
| `test_login_throttle.py` | Автоматические тесты сценариев «login throttle»: регрессии, контракты и проверки поведения. |
| `test_oauth_flows.py` | Автоматические тесты сценариев «oauth flows»: регрессии, контракты и проверки поведения. |
| `test_oauth_session_service.py` | Автоматические тесты сценариев «oauth session service»: регрессии, контракты и проверки поведения. |
| `test_playback.py` | Автоматические тесты сценариев «playback»: регрессии, контракты и проверки поведения. |
| `test_player_eq_presets.py` | Автоматические тесты сценариев «player eq presets»: регрессии, контракты и проверки поведения. |
| `test_playlist_editing.py` | Автоматические тесты сценариев «playlist editing»: регрессии, контракты и проверки поведения. |
| `test_profile_and_api_docs.py` | Автоматические тесты сценариев «profile and api docs»: регрессии, контракты и проверки поведения. |
| `test_provider_catalog_access.py` | Автоматические тесты сценариев «provider catalog access»: регрессии, контракты и проверки поведения. |
| `test_provider_clients.py` | Автоматические тесты сценариев «provider clients»: регрессии, контракты и проверки поведения. |
| `test_security_activity_middleware.py` | Автоматические тесты сценариев «security activity middleware»: регрессии, контракты и проверки поведения. |
| `test_security_event_retention.py` | Автоматические тесты сценариев «security event retention»: регрессии, контракты и проверки поведения. |
| `test_service_orchestration.py` | Автоматические тесты сценариев «service orchestration»: регрессии, контракты и проверки поведения. |
| `test_single_track_import_workflows.py` | Автоматические тесты сценариев «single track import workflows»: регрессии, контракты и проверки поведения. |
| `test_site_module_boundaries.py` | Автоматические тесты сценариев «site module boundaries»: регрессии, контракты и проверки поведения. |
| `test_transfer_dispatch.py` | Автоматические тесты сценариев «transfer dispatch»: регрессии, контракты и проверки поведения. |
| `test_transfer_task_recovery.py` | Автоматические тесты сценариев «transfer task recovery»: регрессии, контракты и проверки поведения. |

## Правила изменения структуры

1. Новую бизнес-логику размещайте в профильном модуле `transfer/services/`, а HTTP orchestration — в узком view module.
2. API endpoints и сериализацию держите в `transfer/api/`; не расширяйте legacy facade без необходимости.
3. Изменения моделей сопровождайте миграциями и тестами.
4. Security-sensitive административные endpoints должны проверять права на сервере, использовать POST + CSRF для изменений и записывать привилегированные действия в аудит.
5. Не коммитьте .env, OAuth tokens, media uploads, logs, backups или runtime lock files.
6. При удалении compatibility modules сначала найдите все импорты и сохраните публичные contracts тестами.
