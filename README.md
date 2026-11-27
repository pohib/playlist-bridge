# Playlist Bridge

Django-приложение для сбора плейлистов и треков из VK, Spotify и SoundCloud в единую библиотеку и переноса коллекций между поддерживаемыми сервисами.

## Пользовательская авторизация

Пользователь подключает доступные сервисы кнопками на главной странице:
- Spotify — OAuth Authorization Code.
- VK — публичные плейлисты и отдельные треки импортируются по ссылке через анонимный API-токен веб-клиента VK; вход в VK и создание собственного VK-приложения не требуются.
- SoundCloud — OAuth 2.1 Authorization Code с PKCE S256 и одноразовыми refresh tokens.

Пользовательские access/refresh tokens не задаются в .env, не сохраняются в браузерной сессии и не передаются в Celery arguments. Они шифруются Fernet и сохраняются в PostgreSQL в модели OAuthCredential. Worker получает токены из БД по HMAC-отпечатку сессии, расшифровывает их только в памяти и обновляет через refresh token. В Redis передаётся только UUID фоновой задачи.

При отключении провайдера соответствующая запись токенов удаляется. Сессионные cookie HttpOnly и SameSite=Lax.

## Архитектура приложения

Это модульный Django-монолит, не набор микросервисов. Сервисы запускаются через Docker Compose: Nginx принимает HTTP-трафик как локальный reverse proxy, Gunicorn обслуживает Django, отдельно работают PostgreSQL, Redis и Celery worker. Cloudflare Quick Tunnel подключается к опубликованному локальному порту Nginx (127.0.0.1:8000); URL туннеля и OAuth callback flow не зависят от внутреннего адреса Gunicorn.

Разделение view-слоя библиотеки завершено: **library_views.py — compatibility facade**, который только реэкспортирует обработчики специализированных модулей. Новые обработчики следует размещать в соответствующих модулях, не возвращая бизнес-логику в фасад.

Основные границы ответственности:

- config/ — Django settings, URL root, WSGI/ASGI, Celery app, security headers и storage;
- transfer/site_views.py — страницы dashboard, библиотеки, профиля и подключений;
- transfer/auth_views.py — регистрация, вход, выход и смена пароля;
- transfer/oauth_views.py — OAuth state/PKCE, callback, привязка сессии, подключение/отключение Spotify и SoundCloud;
- transfer/api_views.py — versioned API переноса, статусы и отчёты;
- transfer/library_views.py — тонкий compatibility facade с реэкспортом обработчиков;
- transfer/library_import_views.py — compatibility facade импорта;\n- transfer/library_vk_import_views.py — импорт VK-плейлистов/треков и обновление обложек;\n- transfer/library_spotify_import_views.py — импорт Spotify-плейлистов, треков и библиотеки;\n- transfer/library_soundcloud_import_views.py — импорт SoundCloud-плейлистов, треков и библиотеки;
- transfer/library_management_views.py — CRUD библиотеки, объединение плейлистов, локальная загрузка треков и обновление профиля;
- transfer/library_playback_views.py — локальное и VK-воспроизведение/потоковая выдача;
- transfer/library_provider_upload_views.py — загрузка треков в SoundCloud;
- transfer/library_search_views.py — поиск источников для плейлистов и треков;
- transfer/library_media_views.py — защищённая выдача обложек с allowlist доменов и проверкой владельца трека;
- transfer/library_transfer_views.py — compatibility facade переноса;\n- transfer/library_transfer_create_views.py — создание переноса библиотеки между провайдерами;\n- transfer/library_transfer_review_views.py — ручной поиск, выбор и пропуск совпадений при переносе;
- transfer/library_support.py — общие функции доступа к профилю и токенам провайдеров;
- nginx/default.conf — конфигурация локального reverse proxy;
- transfer/services/ — provider clients, общие ошибки и структуры, нормализация/сопоставление и orchestration;
- transfer/tasks.py — Celery task для старого прямого VK → Spotify workflow;
- transfer/domain_models/ — фактические Django-модели, сгруппированные по доменам;
- transfer/models.py и transfer/core.py — compatibility facades; сохраняйте их, пока не проверены все старые импорты;
- transfer/views.py — compatibility facade для прежних view imports; новые URL подключают специализированные view-модули напрямую;
- transfer/templates/transfer/ — HTML-шаблоны;
- transfer/static/transfer/js/app.js — клиентская логика переноса, глобального плеера, очереди и внутренней навигации;
- transfer/static/transfer/styles/main.css — основные стили сайта и плеера.

### Карта Python-модулей

| Путь | Ответственность / важные детали |
|---|---|
| config/settings.py | Переменные окружения, БД, cookies, security settings, logging, Celery |
| config/security.py | Security headers и CSP/COEP; не ослаблять политики ради обхода ошибок воспроизведения без диагностики |
| config/storage.py | Static files storage |
| transfer/domain_models/credentials.py | OAuthCredential |
| transfer/domain_models/jobs.py | TransferJob |
| transfer/domain_models/library.py | LibraryProfile, LibraryPlaylist, LibraryTrack, LibraryTransfer, LibraryTransferItem, cleanup audio files signal |
| transfer/credentials.py | HMAC session fingerprint, Fernet encryption, token persistence/refresh |
| transfer/services/common.py | TransferError, ReauthorizationRequired, VKTrack, VK URL parsers, shared normalization |
| transfer/services/vk_client.py | Анонимный токен VK, получение плейлиста/трека и stream metadata |
| transfer/services/spotify_client.py | Spotify OAuth/API, поиск, playlist operations, batching и проверка владельца |
| transfer/services/soundcloud_client.py | SoundCloud OAuth PKCE/API, pagination, поиск, playlists и upload |
| transfer/services/track_matcher.py | normalize_track_text, score_candidate |
| transfer/services/transfer_service.py | execute_transfer: прямой VK → Spotify workflow |
| transfer/api_views.py + transfer/tasks.py | API → очередь Celery → job claim/progress/result |
| transfer/library_views.py | Compatibility facade; новые маршруты используют специализированные модули напрямую |
| transfer/site_views.py | Page rendering, ownership-filtered querysets, playback payload, artwork proxy |

### Основные бизнес-процессы

1. **Импорт в библиотеку.** HTTP handlers в library_import_views.py валидируют ссылку, получают credentials через credentials.py, вызывают provider clients и сохраняют локальную копию метаданных в LibraryPlaylist/LibraryTrack. Для VK используется анонимный web-client token, для Spotify/SoundCloud — OAuth пользователя.
2. **Перенос библиотечного плейлиста.** Handler в library_transfer_views.py ищет совпадения в Spotify или SoundCloud, создаёт целевой плейлист из найденных треков, сохраняет локальное зеркало и создаёт LibraryTransfer/LibraryTransferItem. Ненайденные и неоднозначные элементы остаются в review.
3. **Ручная проверка.** search_transfer_item, select_transfer_candidate, skip_transfer_item реализуют последовательный workflow: нельзя обработать более поздний трек раньше текущего. Выбранный candidate ID должен быть среди сохранённых сервером вариантов.
4. **Прямой VK → Spotify перенос через API v1.** api_create_transfer создаёт TransferJob и отправляет UUID в Celery; run_transfer атомарно claim-ит queued job; execute_transfer получает VK playlist, ищет совпадения и пишет в Spotify; API отдаёт progress и JSON report. Это отдельный workflow от LibraryTransfer/review.
5. **Плеер.** site_views.py формирует playback payload, app.js управляет очередью и воспроизведением. Локальные аудиофайлы и VK воспроизводятся через HTMLAudioElement; Spotify и SoundCloud — через их embed iframe. Плеер не получает аудио Spotify/SoundCloud напрямую.

### Важные правила изменения архитектуры

- Сохраняйте Django app label transfer, имена моделей, таблицы и текущие миграции. Не переносить модели в другое Django app без отдельного плана миграций и проверки FK/admin/signals/Celery.
- При добавлении новых library endpoints подключайте специализированные view-модули напрямую в transfer/urls.py. Не возвращайте обработчики в compatibility facade library_views.py; бизнес-логику при необходимости выносите в transfer/services/ после фиксации контрактов тестами.
- Не удаляйте compatibility facades models.py, core.py, views.py, пока не проверены все места импорта.
- Внешние API в тестах только mock-ать. Не использовать реальные OAuth tokens и не вызывать live VK/Spotify/SoundCloud из CI.
- Не менять URL names, JSON contract, ownership filtering и очередность ручного review без явной причины и регрессионных тестов.

## Поддерживаемые направления

Единая библиотека хранит коллекции и метаданные, а импорт и экспорт выполняются через API-адаптеры провайдеров. Один и тот же плейлист из библиотеки можно отправить в доступный целевой сервис; сопоставление выполняется по названию, исполнителю и длительности.

| Сервис | Импорт плейлистов | Импорт отдельных треков | Создание целевого плейлиста | Загрузка аудиофайла |
|---|---:|---:|---:|---:|
| VK | Да, по ссылке | Да, по ссылке | Пока нет | Пока нет |
| Spotify | Да, своя библиотека или ссылка | Да, по ссылке | Да | Нет — Spotify API не предоставляет загрузку аудио |
| SoundCloud | Да, своя библиотека или ссылка | Да, по ссылке | Да | Да, из пользовательского файла до 100 МБ |

Перенос между Spotify и SoundCloud, а также из VK в Spotify/SoundCloud выполняется через библиотеку. В SoundCloud создаётся плейлист из найденных существующих треков; отдельная загрузка аудио возможна только из файла, который пользователь сам предоставил и имеет право загружать. Приложение не скачивает и не рипает аудио из Spotify или SoundCloud. Для Spotify сохраняются ссылки и метаданные, а не аудиофайлы.

Импорт VK использует обнаруженные внутренние методы веб-клиента (`audio.getIdsBySource` и `audio.getById`) и анонимную выдачу токена через `get_anonym_token`. Это не документированный публичный контракт VK: методы, ограничения и формат ответов могут измениться без предупреждения. Создание плейлистов в VK не включено. YouTube Music и Apple Music отображаются как будущие провайдеры и пока не участвуют в импорте/переносе.

SoundCloud использует OAuth 2.1 Authorization Code с PKCE S256; refresh tokens одноразовые и обновляются с сохранением нового значения. Для регистрации SoundCloud API app актуальная документация описывает путь через Artist Pro.


## Аккаунты, страницы и личная библиотека

- Главная страница `/` — публичная презентация приложения с адаптивной анимацией музыкальных сервисов.
- Регистрация и вход — Django Authentication с хешированием паролей штатными password hasher Django, проверкой паролей и фиксированным перенаправлением после входа в личный кабинет (параметр `next` не используется).
- После регистрации гостевая библиотека и подключения текущей сессии привязываются к аккаунту. Для авторизованного пользователя HMAC fingerprint вычисляется от внутреннего ID пользователя, поэтому библиотека и OAuth credentials сохраняются между браузерными сессиями и устройствами.
- Spotify и SoundCloud подключаются отдельно через OAuth. VK импортируется по публичной ссылке через анонимный API: вход в VK и пользовательская VK-авторизация не используются.
- Разделы приложения: `/app/` — обзор, `/library/` — импорт, добавление треков и перенос коллекций, `/connections/` — подключения Spotify/SoundCloud, `/profile/` — настройки аккаунта и статистика библиотеки, `/transfers/` — история и ручная проверка. 
- Доступ к библиотеке, плейлистам и transfer review ограничен владельцем профиля. Вьюхи получают записи через фильтр `profile`; UUID сам по себе не считается контролем доступа.
- Не найденные треки сохраняются как элементы review. Пользователь может выполнить повторный поиск по целевому сервису, выбрать конкретный результат либо пропустить трек. Сопоставление обрабатывается последовательно, чтобы сохранять исходный порядок. Выбранный ID должен присутствовать в сохранённом сервером списке кандидатов.
- Spotify получает композиции через официальные playlist items API с вставкой в исходную позицию; SoundCloud обновляет список треков плейлиста через документированный `PUT /playlists/{playlist_id}`.
- HTML-шаблоны используют автоэкранирование Django. Ссылки кандидатов проверяются по HTTPS и allowlist доменов провайдеров; POST-формы используют CSRF-токены.

## Глобальный музыкальный плеер

Плеер показывается авторизованным пользователям на всех внутренних страницах и не должен размонтироваться при переходах внутри приложения. Свернутое состояние использует отдельную геометрию и FLIP-анимацию, не подменяя базовое центрирование через transform.

- Playback payload формируется в site_views.py; состояние очереди/режимов хранится в браузерном localStorage под ключом playlist-bridge-player-v2.
- Поддерживаются play/pause, предыдущий/следующий трек, очередь, перестановка/удаление треков, очистка очереди, shuffle, repeat off/all/one, громкость/mute, сворачивание/разворачивание.
- Внутренняя навигация использует fetch + замену .page-content и History API, чтобы сохранять активный плеер и iframe между страницами; при несовместимом ответе выполняется обычная навигация.
- Локальный файл проигрывается через same-origin /library/tracks/<uuid>/stream/; VK — через /library/tracks/<uuid>/vk-audio/ с отдельным endpoint разрешения потока /api/v1/library/tracks/<uuid>/vk-stream/.
- Spotify track и SoundCloud track проигрываются через embed iframe. Приложение не скачивает и не проксирует их аудио.
- Поиск текущей композиции отправляется в POST /api/v1/library/tracks/search/. Spotify/SoundCloud возвращают найденные треки; YouTube Music и Apple Music пока дают только внешнюю ссылку на поиск. Анонимный VK API не поддерживает используемый поиск каталога, поэтому VK не предлагается как поисковый провайдер.
- Обложки выдаются через /library/cover/ с allowlist доменов, проверкой redirect target, MIME signature и лимитом размера. Не подменять прокси на произвольный внешний URL.
- DOM IDs плеера определены в base.html и используются в app.js; изменение ID требует синхронного изменения JS. После изменения CSS/JS обновлять cache-busting query параметр в base template.


## Структура страниц

| URL | Назначение |
|---|---|
| `/` | Публичная главная |
| `/accounts/register/` | Создание аккаунта |
| `/accounts/login/` | Вход |
| `/app/` | Личный dashboard |
| `/library/` | Импорт и коллекции |
| `/library/<uuid>/` | Состав плейлиста и запуск переноса |
| `/connections/` | Подключение и отключение Spotify/SoundCloud |
| `/profile/` | Профиль, статистика библиотеки и настройки аккаунта |
| `/transfers/` | История переносов |
| `/transfers/<uuid>/review/` | Ручное сопоставление пропусков |
| `/api/docs/` | Справочник API и правила безопасной работы |

## Логирование

Django и приложение пишут логи в stdout и в `reports/application.log`. Используется межпроцессная безопасная ротация файла: 5 МБ на файл, до 5 архивных копий. В `compose.yaml` каталог `reports` подключён к web и worker, поэтому журналы доступны в локальном репозитории. В логах запрещено сохранять OAuth access/refresh tokens, client secrets, пароли, полные HTTP-заголовки авторизации и содержимое пользовательских аудиофайлов.
## Что хранится в .env

В .env хранятся только конфигурация приложения, секреты разработчика и инфраструктуры:
- DJANGO_SECRET_KEY, TOKEN_ENCRYPTION_KEY, пароль PostgreSQL;
- Spotify Developer App: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, Redirect URI;

- SoundCloud Developer App: SOUNDCLOUD_CLIENT_ID, SOUNDCLOUD_CLIENT_SECRET и Redirect URI;
- версия VK API и адрес Redis.

Пользовательские VK/Spotify/SoundCloud access token и refresh token не следует помещать в `.env`.

Для подключения провайдеров зарегистрируйте приложения в [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) и [SoundCloud Developers](https://developers.soundcloud.com/). Для получения API credentials SoundCloud актуальная документация описывает регистрацию приложения с Artist Pro. VK подключать не нужно: импорт использует анонимный доступ публичного веб-клиента VK. В режиме Development Mode тестовые аккаунты необходимо добавить в Users Management приложения Spotify.

## Запуск локально с публичным HTTPS через Cloudflare Quick Tunnel

Домен, VPS и платная подписка Cloudflare для Quick Tunnel не нужны. Туннель временно публикует локальный порт Django по HTTPS. Адрес *.trycloudflare.com временный и может измениться при следующем запуске; при смене адреса обнови Redirect URL в кабинетах Spotify и SoundCloud.

### 1. Подготовь проект и .env

В PowerShell:

    git clone https://github.com/pohib/vk-to-spotify.git
    cd vk-to-spotify
    Copy-Item .env.example .env
    notepad .env

Если репозиторий уже скачан, вместо clone перейди в его каталог и выполни:

    git switch main
    git pull --ff-only origin main

Сгенерируйте три независимых значения командами ниже и укажите результаты в соответствующих переменных `.env`:

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
- SOUNDCLOUD_CLIENT_ID и SOUNDCLOUD_CLIENT_SECRET — из зарегистрированного SoundCloud Developer App.

VK не требует регистрации приложения и отдельных значений в `.env`: сервер получает анонимный токен публичного веб-клиента.

При первом запуске остальные значения можно оставить такими, как указано в `.env.example`. Переменная `DATABASE_URL` не требуется: Compose формирует её из `POSTGRES_PASSWORD`. Пользовательские access/refresh tokens не следует хранить в `.env`.

### 2. Установи Cloudflare Tunnel

Установите Docker Desktop и дождитесь запуска Docker Engine. Затем установите cloudflared:

    winget install --id Cloudflare.cloudflared -e

Закройте и повторно откройте PowerShell для обновления PATH. Затем выполните проверку:

    cloudflared --version

### 3. Запусти приложение и HTTPS-туннель

Из корня проекта:

    Set-ExecutionPolicy -Scope Process Bypass
    .\scripts\start-tunnel.ps1

Скрипт не запускает pytest, Ruff или другие тесты: он предназначен для запуска уже подготовленного Docker Compose окружения и публикации его через Quick Tunnel. Новые Python test-файлы не нужно добавлять в start-tunnel.ps1; тесты запускаются отдельными командами из корня проекта до запуска приложения.

Скрипт:
1. Проверяет обязательные секреты в .env;
2. собирает контейнеры и запускает Nginx reverse proxy, Django/Gunicorn, PostgreSQL, Redis и Celery worker;
3. ждёт успешного ответа /healthz/;
4. запускает Cloudflare Quick Tunnel;
5. получает временный HTTPS URL;
6. обновляет в .env домен, CSRF origin, Secure cookies, HTTPS redirect и callback URI Spotify/SoundCloud;
7. пересоздаёт web и worker с новыми настройками; Nginx продолжает принимать трафик на прежнем локальном порту 8000 и передаёт его в web:8000.

После завершения скрипт покажет URL и точные callback URI. Не закрывай процесс cloudflared: туннель должен оставаться запущенным, пока используешь приложение. Чтобы остановить его, выполни команду с PID, который напечатал скрипт:

    Stop-Process -Id <PID>

### 4. Зарегистрируй OAuth callback URI Spotify и SoundCloud

Скопируй callback URL из вывода скрипта без изменений.

В настройках приложения Spotify укажите Redirect URI:

    https://<текущий-домен>.trycloudflare.com/spotify/callback/

В кабинете SoundCloud также зарегистрируй:

    https://<текущий-домен>.trycloudflare.com/soundcloud/callback/

Вместо <текущий-домен> подставь фактический адрес из вывода скрипта. Callback в .env и в кабинете провайдера должны совпадать посимвольно, включая завершающий слеш.

### 5. Проверка приложения

Откройте HTTPS URL, выведенный скриптом, и проверьте health endpoint:

    Invoke-WebRequest https://<текущий-домен>.trycloudflare.com/healthz/

Проверьте состояние контейнеров:

    docker compose ps

Логи приложения и фонового worker:

    docker compose logs -f web worker

Подключите Spotify. VK подключать не требуется: для проверки импорта достаточно ссылки на публичный плейлист VK. Для добавления треков в существующий Spotify playlist используйте ссылку на плейлист, принадлежащий подключённому аккаунту.

### 6. Повторный запуск

Quick Tunnel не гарантирует постоянный адрес. При новом запуске:
1. Останови старый cloudflared процесс, если он ещё работает;
2. Запусти scripts/start-tunnel.ps1 снова;
3. Обнови callback URI в кабинетах Spotify и SoundCloud, если домен изменился;
4. При изменении Redirect URI переподключите OAuth-аккаунт провайдера.

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

TOKEN_ENCRYPTION_KEY необходимо сохранить: без него восстановить зашифрованные токены невозможно. Храните ключ отдельно в менеджере секретов и создавайте защищённую резервную копию.


## Локальные тесты и проверки

Для запуска тестов на Windows установи Python 3.12 и выполни из корня проекта в отдельном PowerShell:

    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt -r requirements-dev.txt
    python manage.py check
    python manage.py makemigrations --check --dry-run
    ruff check .
    pytest -q
    pytest -q transfer/tests/test_fuzzing.py
    pytest -q --cov=transfer --cov-report=term-missing

Тесты используют SQLite, если DATABASE_URL не задан в окружении; PostgreSQL из Compose для локального запуска pytest не требуется. Не добавляйте DATABASE_URL в `.env` только ради тестов.

CI запускается автоматически при push в main и pull request. В workflow входят pytest, Ruff, Django checks, Bandit, Semgrep, pip-audit, Gitleaks, Trivy, Hadolint, CodeQL и OWASP ZAP baseline DAST. Результат проверки смотри во вкладке Actions соответствующего коммита.



### Быстрые команды разработчика

```powershell
# Windows: локальные Python checks (не требует поднятого Docker stack)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q --cov=transfer --cov-report=term-missing

# Только property-based fuzz tests
pytest -q transfer/tests/test_fuzzing.py

# Контейнеры / приложение / логи
docker compose ps
docker compose logs -f web worker
docker compose exec web python manage.py check

# Запуск локального HTTPS Quick Tunnel
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start-tunnel.ps1

# Остановка туннеля и Compose (volume БД сохраняется)
.\scripts\stop-tunnel.ps1
```

### Карта тестов

| Файл | Что защищает |
|---|---|
| transfer/tests/test_legacy.py | Ранние регрессионные сценарии: URL validation, API contracts, credentials, concurrency и исходные workflows |
| transfer/tests/test_contracts.py | URL names/paths, HTTP methods и внешние контракты |
| transfer/tests/test_oauth_flows.py | OAuth state, PKCE, callback, credential persistence/disconnect |
| transfer/tests/test_provider_clients.py | HTTP/API contracts провайдеров, pagination, redirects, ID validation, upload |
| transfer/tests/test_service_orchestration.py | Прямой VK → Spotify orchestration и matching decisions |
| transfer/tests/test_playback.py | Playback endpoints, local audio, cover proxy и VK stream behavior |
| transfer/tests/test_library_workflows.py | CRUD, provider imports, ownership и review state machine |
| transfer/tests/test_bulk_import_regressions.py | Массовый импорт библиотек, batch limit и частичные ошибки |
| transfer/tests/test_fuzzing.py | Hypothesis fuzzing входных URL/JSON и provider metadata |
| transfer/tests/test_profile_and_api_docs.py | Профиль, сервисы, API docs и статические UI-регрессии плеера |

### Границы покрытия и незакрытые зоны

- Coverage в CI считается через pytest-cov только для Python-пакета transfer; migrations и тестовые модули исключены через .coveragerc. Это **не процент покрытия всего репозитория**: JS, CSS, HTML templates, PowerShell, Docker/Compose и ручные пользовательские сценарии в этот процент не входят.
- Последний подтверждённый успешный tests job на commit `8ab7b24689e590726fe51a0915cc46faf11055b6`: **176 passed**, **26 subtests passed**, **76.46%** coverage для `transfer`. Это результат тестового job; после изменений Nginx и URL routing требуется дождаться нового полного CI.
- Mock provider API проверяют логику и контракты, но не подтверждают, что реальные VK/Spotify/SoundCloud API доступны или не изменились.
- Для плеера нет полноценного browser-based E2E набора, проверяющего реальное воспроизведение и анимации во всех браузерах.
- OWASP ZAP baseline DAST не авторизуется и не проверяет всю библиотеку/плеер за логином.
- Fuzz tests ограничены по длине и числу примеров; это не бесконечный fuzz campaign и не замена security review.

## Защита Spotify API от SSRF

Spotify-клиент не принимает произвольные URL или HTTP-методы: вызываются только заранее определённые операции API. Для операций с плейлистом отдельно проверяется ID, а автоматическое следование HTTP-редиректам отключено. Эти меры ограничивают сетевое назначение фиксированным API Spotify и не позволяют передать пользовательский URL в HTTP-клиент. Регрессионные тесты проверяют подмену адреса, некорректные ID и редиректы. Статус CodeQL подтверждается только после успешного завершения нового анализа на актуальном commit SHA.

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

Автоматическое слияние выполняет workflow через GITHUB_TOKEN только после успешного завершения всего CI, включая CodeQL; включать Allow auto-merge не требуется. Для дополнительной защиты включите ruleset/branch protection для main и сделайте обязательными checks tests, sast-sca-secrets, container, dast и codeql.

SARIF Bandit/Semgrep/Trivy загружается на push/workflow_dispatch, а CodeQL также анализирует pull request. GitHub Code Scanning может требовать доступность Code Security для репозитория. Для private repository проверьте доступность этой функции на текущем плане.

## Ограничения

- Импорт публичного аудио зависит от доступности внутренних VK web API и анонимной выдачи токена; VK может менять этот механизм или ограничивать его. Сейчас список ID запрашивается одним вызовом `audio.getIdsBySource`; пагинация этого метода не установлена, поэтому очень большие плейлисты могут быть ограничены самим VK. Метаданные загружаются пакетами по 50 записей. Название коллекции пока сохраняется как `VK playlist`, поскольку исследованный ответ со списком ID не содержал названия.
- Spotify access token обновляется через refresh token; refresh token Spotify истекает через 6 месяцев после исходной авторизации, после чего пользователь должен подключить аккаунт заново.
- Spotify rate limits и отдельная Development Mode quota могут замедлять или временно блокировать перенос.
- DAST baseline выполняется без OAuth-аутентификации и не покрывает авторизованные пользовательские сценарии.
- В Spotify Development Mode владелец приложения должен иметь Premium; максимум 5 авторизованных пользователей, каждый тестировщик должен быть добавлен в Users Management allowlist. Для публичного сервиса действует отдельная процедура Extended Quota Mode.
- Локальные настройки `SESSION_COOKIE_SECURE=false` и `CSRF_COOKIE_SECURE=false` допустимы только для loopback HTTP-разработки; на публичном HTTPS-хосте включите обе.
- Повторная отправка пакетов Spotify автоматически не включена, чтобы не создавать дубликаты при неопределённом результате сетевого запроса.

## Текущий статус и ближайшие задачи

### Уже реализовано

- Регистрация, вход, профиль пользователя и личная библиотека с привязкой данных к аккаунту.
- OAuth Spotify и SoundCloud; SoundCloud использует PKCE S256. Пользовательские credentials шифруются Fernet в PostgreSQL, поиск credentials привязан к HMAC fingerprint.
- Импорт публичных плейлистов и отдельных треков VK, Spotify и SoundCloud.
- Импорт доступной библиотеки плейлистов Spotify и SoundCloud с ограничением до 30 плейлистов за один запуск.
- Перенос библиотечных плейлистов в Spotify или SoundCloud: подбор существующих композиций, создание целевого плейлиста из совпадений, локальное зеркало и ручной review пропусков.
- Отдельный асинхронный workflow VK → Spotify через API v1, Celery, Redis, статусы, прогресс и JSON-отчёт.
- Проверка доступа к существующему Spotify playlist в прямом VK → Spotify workflow; добавление композиций в заданную позицию.
- Локальная загрузка и воспроизведение аудио; загрузка пользовательского файла в SoundCloud. Ограничение файла — 100 МБ.
- Глобальный плеер: очередь, shuffle/repeat, управление громкостью, сворачивание/разворачивание с FLIP-анимацией, поиск альтернативных источников и сохранение состояния.
- Docker Compose для Nginx reverse proxy, Django/Gunicorn web, Celery worker, PostgreSQL и Redis; health checks, логи и Cloudflare Quick Tunnel для локального OAuth.
- CI с pytest/coverage, Ruff, Django checks, SAST/SCA/secrets, container scan, CodeQL и OWASP ZAP baseline DAST.
- Последний подтверждённый тестовый job: 176 passed, 26 subtests passed; coverage пакета transfer — 76.46%.

### Ближайшие задачи

- Провести аудит оставшихся view-модулей и сервисного слоя на циклические импорты и лишнюю связанность; не дробить уже специализированные модули без практической причины.
- Ввести единый интерфейс провайдера там, где это уменьшит связанность; не создавать абстракции ради абстракций.
- Улучшить matching: пороги уверенности, неоднозначные совпадения, версии/ремастеры/featuring и причины отклонения кандидатов.
- Усилить отчёт переноса: объяснение ошибок и пропусков, экспорт CSV; JSON report уже доступен через API прямого переноса.
- Реализовать retry/resume для частично завершённых библиотечных переносов и защиту от дубликатов при неопределённом результате API-запроса.
- Расширить обработку больших коллекций, rate limits и временных ошибок API с корректным Retry-After/backoff.
- Добавить отмену активных Celery jobs, подробный мониторинг и correlation ID.
- Добавить browser-based E2E для плеера: реальное воспроизведение, очередь, навигация, адаптивность и анимации. Текущий Python coverage не измеряет JS/CSS/templates.
- Добавить нагрузочные тесты, резервное копирование PostgreSQL и проверку восстановления.
- Подготовить постоянный production-домен, TLS-конфигурацию для Nginx/Cloudflare, отдельные окружения и управляемые секреты.
- Реализовать полноценные интеграции YouTube Music и Apple Music, если будет выбран поддерживаемый и разрешённый API.
- Добавить понятные процедуры экспорта и удаления пользовательских данных.

> Лимиты и поведение сторонних API могут меняться. Перед изменением интеграции сверяйтесь с текущими ответами API и документацией провайдера; не обходите ограничения доступа или DRM.


## Документация API

В приложении доступен справочник по API: `/api/docs/`. Машиночитаемая схема OpenAPI 3.1 находится по адресу `/api/v1/openapi.json`. Документация описывает методы, форматы запросов и ответов, CSRF и коды ошибок. API использует браузерную сессию; OAuth-токены провайдеров не передаются в теле запросов и не публикуются в документации.
