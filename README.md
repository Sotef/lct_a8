# lct_a8 — Предиктивный ML-сервис аварий и отказов оборудования коллекторов

Веб-сервис прогнозирования отказов датчиков и аварий инженерных коллекторов АО «Москоллектор» (hackathon/технологическое соревнование). Стек: Python 3.12, FastAPI (бэкенд), PostgreSQL, LightGBM/CatBoost (ML), Jupyter (research).

## Быстрый старт в Docker (самый простой способ)

Нужен только **Docker Desktop** — Python, venv и БД ставить не требуется.

```powershell
cd services
copy .env.docker.example .env        # bash: cp .env.docker.example .env
docker compose up -d --build
```

Через 2–3 минуты после первой сборки (скачивается образ Python и зависимости, затем
поднимается PostgreSQL, сервис сам создаёт схему, демо-пользователей, реестр моделей
и запускает прогнозы):

- SPA (диспетчер/техник): **http://127.0.0.1:8000/**
- Swagger: **http://127.0.0.1:8000/docs**
- Проверка развёртывания: `docker compose exec -T api python scripts/verify_deploy.py`
- HTTPS (TLS 1.2+, требование ТЗ): положите сертификат в `services/deploy/certs`
  и выполните `docker compose --profile tls up -d --build` → **https://127.0.0.1:8443/**

Демо-доступы:

| Логин | Пароль | Роль |
|---|---|---|
| `central.operator` | `central123` | центральный диспетчер |
| `dispatcher.alpha` | `alpha123` | диспетчер района |
| `tech.alpha` | `tech123` | техник (район 5122) |

```powershell
docker compose ps                 # статусы и healthcheck
docker compose logs -f api        # логи сервиса
docker compose down               # остановить (данные БД сохраняются)
docker compose down -v            # удалить БД (демо «с нуля»; затем up -d --build)
```

> Если порт `8000` занят локальным (не-Docker) `uvicorn` — остановите его: иначе
> запросы уходят мимо контейнера. Подробности (переменные, тома, эксплуатация) —
> в `services/README.md`; мобильная версия (PWA/офлайн/push) — в `services/MOBILE_PLAN.md`.

### Что уже есть в репозитории (запуск «из клона» работает сразу)

| В git | Размер | Зачем |
|---|---|---|
| `research/models/tte_{fire,access,sensor,wear}_discrete_hazard.cbm` + `calib30_access.pkl` | ~31 МБ | обученные модели (инференс) |
| `research/dataset/справочник_каналов_датчиков.csv`, `справочник_объектов_диспетчер.csv` | ~1,3 МБ | справочники → `objects_ref` / `channels_ref` (bootstrap) |
| `services/data/raw/buckets_2026.parquet` | 1,1 МБ | сырой 6ч-кэш 2026: панели собираются из него на первом запуске |
| `services/data/z_stats_*.csv`, `_features_schema.json`, `l2_object_risk.parquet`, `cat_codes_*.json` | <1 МБ | train-статистики z, схема фич, L2-риски |
| `research/*.py` (`features`, `tte_pipeline`, `inference_contract`, `data_utils`) | — | ML-ядро, подключается сервисом как библиотека |

**Итого ~33 МБ** → после `git clone` достаточно `docker compose up -d --build`: модели
загрузятся, справочники наполнятся, панели пересоберутся из raw-кэша, пойдут прогнозы,
алерты и превентивные заявки.

**Чего в git нет** (и для демо не требуется):
- `research/dataset/extracted/ext-journal-*.csv` (~16 ГБ) — исходные журналы СМВУ: нужны
  только для загрузки новых данных (`POST /admin/data/load`) или переобучения;
- `services/data/panels/*.csv` (~319 МБ) — пересобираются из raw-кэша автоматически
  (`feature_pipeline.build_subjects`, проверено: те же 64 признака в том же порядке,
  что и при обучении);
- `services/data/*.db`, логи, TLS-ключи — см. `.gitignore`.

## Тест на мобильных устройствах (телефон/планшет)

Тот же сайт имеет мобильный профиль: нижнее меню из 4 табов, bottom-sheet «Ещё»,
карточки вместо таблиц/канбана, офлайн-очередь действий, установка как PWA, push.
Способ проверки зависит от того, что нужно проверить.

### 1. Вёрстка и рабочие сценарии на реальном телефоне (быстро)
1. Узнайте IP компьютера с Docker: `ipconfig` (адрес вида `192.168.x.x`) или
   `Get-NetIPAddress -AddressFamily IPv4 | Where-Object AddressState -eq Preferred`.
2. На телефоне в той же Wi-Fi/сети откройте `http://<IP>:8000` — работает адаптивная
   вёрстка, все разделы, карточки, заявки, фото с камеры.
3. Если не открывается, разрешите порт (PowerShell **от администратора**):
   `netsh advfirewall firewall add rule name="LCT 8000" dir=in action=allow protocol=TCP localport=8000`
4. Приёмка по экранам — чек-лист `services/MOBILE_PLAN.md`, **Приложение C**.

> По `http://<IP>` origin считается **небезопасным**: service worker, установка PWA,
> офлайн-очередь и Web Push на телефоне не включатся. Для проверки вёрстки/логики
> и обычных запросов этого достаточно.

### 2. Полный PWA-сценарий (установка, офлайн, push)
Нужен *secure context* (HTTPS или localhost):
- **Проще всего — на компьютере**: откройте `http://127.0.0.1:8000`, включите в DevTools
  (F12) режим устройства (Pixel/iPhone). `localhost` безопасен, поэтому доступны SW,
  установка приложения и офлайн-очередь; офлайн удобно проверять в
  DevTools → Application → Service Workers (Offline).
- **На телефоне** — только по HTTPS с **доверенным** сертификатом (корпоративный CA):
  `docker compose --profile tls up -d --build` и `https://<IP>:8443`. Самоподписанный
  сертификат Chrome не примет для service worker.
- Уведомления: «Ещё» → «Включить уведомления» (нужны `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`
  в `.env`; без них работает фолбэк-поллинг `GET /alerts` — алерты видны в разделе «Алерты»).

### 3. Автоматическая проверка мобильного профиля (без телефона)
```powershell
# команды выполняются из папки services (там docker-compose.yml):
# служебная страница не входит в образ — копируем её в контейнер
docker compose cp app/web/__mprobe.html api:/workspace/services/app/web/__mprobe.html
# затем откройте в браузере (или headless-прогоном, см. services/MOBILE_PLAN.md):
#   http://127.0.0.1:8000/__mprobe.html?stub=1
```
Страница печатает отчёт (`MPROBE OK`/`FAIL`): 4 таба нижнего меню, тап-цели ≥44 px,
отсутствие горизонтального скролла, мобильные табы заявок, sheet «Ещё», карточки алертов.


## Структура репозитория

```
lct_a8/
├── STATUS.md            # сводка готовности (метрики, компоненты, блокеры)
├── ARCHITECTURE.md      # архитектура и использование (research + сервис)
├── research/            # ML Research Team: EDA, feature pipeline, модели, Jupyter
│   ├── .venv/           # venv Python 3.12 (ядро Jupyter: lct-a8-research)
│   ├── dataset/         # исходные .7z, распакованные CSV (extracted/), панели, справочники,
│   │                    #   _external/ (кэш внешних выгрузок: maintenance_plan)
│   ├── notebooks/       # 00..07 (данные/EDA), 08..12 (wear/TTE), 19..33 (fire/sensor/access,
│   │                    #   калибровка, RBAM/L2, интеграция, плановые ТО/ППР)
│   ├── docs/            # ML_PLAN (архитектура+статус), BACKLOG, DATA_REPORT, DATA_MATRIX,
│   │                    #   OPEN_QUESTIONS, RISK_PIVOT_REPORT, TZ_COMPLIANCE_REPORT, API_CONTRACT, ADAPTERS_README
│   ├── models/          # обученные модели (.cbm), holdout-предсказания, отчёты
│   ├── data_utils.py    # чтение журналов, календарь кампаний
│   ├── features.py      # feature pipeline: панели (суточные/6ч), признаки, цели
│   ├── tte_pipeline.py  # survival-пайплайн слоя 2 («дней до события»), subject_features
│   ├── tte_experiments.py  # обучение/оценка TTE (discrete hazard + бенчмарки)
│   ├── inference_contract.py  # инференс-контракт для backend (модель+калибровка+топ-K+план ТО)
│   ├── planned_work.py  # парсер графиков ТО/ППР заказчика → календарь ISO-недель
│   ├── rebuild_task_panels.py / rebuild_all_datasets.py  # пересборка панелей/датасетов
│   └── requirements.txt
└── services/            # Backend & Web Service Team: FastAPI-сервис
    ├── .venv/           # venv Python 3.12
    ├── app/             # api/ (роутеры), services/ (бизнес-логика), adapters/ (read-only),
    │                    #   workers/ (ingestion, scheduler, реплей), web/ (SPA), models_db.py
    ├── alembic/         # миграции БД (PostgreSQL 12+)
    ├── scripts/         # seed.py, run_demo.py, replay_history.py, validate_2026.py
    ├── tests/           # unit + front-contract + сверка с research (pytest)
    ├── data/            # SQLite (локально), 6ч-панели 2026, z-stats, кэш ингеста
    ├── Dockerfile, docker-compose.yml, .dockerignore, .env.docker.example
    ├── deploy/          # nginx (TLS 1.2+) + сертификаты (certs — не в git)
    ├── README.md        # быстрый старт (Docker), API, реплей, тесты, тест на мобильных
    ├── SERVICE_PLAN.md  # план сервиса (уточнён по итогам встречи с экспертами)
    ├── MOBILE_PLAN.md   # мобильная версия (PWA/офлайн/push): план, статус, проверка на телефоне
    └── BACKEND_SPEC.md  # интеграционная спецификация: ручки, БД, авторизация, пайплайн и модель
```

## Окружение

Два изолированных venv на Python 3.12:

```powershell
# research — анализ данных и ML
D:\python312\python.exe -m venv research\.venv
research\.venv\Scripts\python.exe -m pip install -r research\requirements.txt
research\.venv\Scripts\python.exe -m ipykernel install --user --name lct-a8-research --display-name "Python 3.12 (research)"

# services — бэкенд
D:\python312\python.exe -m venv services\.venv
services\.venv\Scripts\python.exe -m pip install -r services\requirements.txt
```

Запуск Jupyter с ядром research:

```powershell
research\.venv\Scripts\python.exe -m jupyter lab
```

## Данные

- Исходные архивы: `research/dataset/ext-journal-{2019..2026}.7z` (внутри каждого — 1 CSV, схема идентична).
- Распакованные: `research/dataset/extracted/ext-journal-{год}.csv` (~15.9 ГБ суммарно).
- Справочники: `справочник_каналов_датчиков.csv`, `справочник_объектов_диспетчер.csv`, `журнал_событий_пример.csv`.
- Полное описание данных и EDA — в `research/docs/DATA_REPORT.md`.

## Кампании проверок (важно для модели)

Периоды массовых проверок/ремонтов (например, пик 2021W17–W22 после вступления
в силу ППР №1479 и СП 484/485/486 МЧС) **не являются реальными авариями** —
шумы от них нужно исключать из сплитов. Календарь реализован в
`research/data_utils.py` (`CAMPAIGN_WEEKS`, `EXCLUDE_WEEKS_DEFAULT`,
`filter_clean_weeks`). Подробности — в `research/docs/DATA_REPORT.md` → раздел 13.

## Документы ML-команды

- `ARCHITECTURE.md` — архитектура и использование (research + сервис), карта API.
- `research/docs/ML_PLAN.md` — единый ML-документ: архитектура/план (Часть I) + статус задач fire/sensor/access/wear (Часть II) + продуктовая рамка MVP (Часть III).
- `research/docs/BACKLOG.md` — нереализованное/отложенное и блокеры данных.
- `research/docs/DATA_MATRIX.md` — матрица «задача → данные → связи (joins)».
- `research/docs/OPEN_QUESTIONS.md` — вопросы организаторам и ответы экспертов.
- `research/docs/DATA_REPORT.md` — отчёт по данным (EDA, недельный анализ, кампании).
- `research/docs/SEVERITY_MAP.md` — веса последствий для RBAM-приоритета.
- `research/docs/RISK_PIVOT_REPORT.md` — риск-портфель RBAM и план ТО (nb 30).
- `research/docs/API_CONTRACT.md` — API-контракт ядра MVP для backend.
- `research/docs/TZ_COMPLIANCE_REPORT.md` — отчёт «буква ТЗ» (генерируется `report_tz_compliance.py`).
- `research/docs/ADAPTERS_README.md` — интерфейсы адаптеров внешних данных (P2).
- `research/docs/REPRODUCE_DATASETS.md` — как из `.7z` пересобрать все датасеты.

## Текущий статус

Сводная таблица готовности (метрики, компоненты, блокеры) — в **[STATUS.md](STATUS.md)**.

- [x] Окружение: два venv Python 3.12, ядро Jupyter
- [x] Распаковка всех `.7z`
- [x] EDA: объёмы, схема, тревоги по типам, словарь статусов, структура тегов
- [x] EDA в Jupyter: ноутбуки `research/notebooks/01..07`
- [x] Подготовка данных: пайплайн `00_data_pipeline` + ноутбук `07_data_prep` (панели, нейтрализация кампаний)
- [x] Календарь кампаний проверок (`data_utils.CAMPAIGN_WEEKS`)
- [x] Feature pipeline: `features.py` (признаки каналов/объектов, горизонты 6–48ч)
- [x] Basline и горизонты: ноутбуки `08_wear_baseline`, `09_wear_horizons`, `10_wear_series` (событие = старт серии)
- [x] Слой 2 «через сколько дней»: survival-апгрейд `11_wear_tte` (discrete hazard, цензура, holdout 2025H2+2026)
- [x] Задачи fire/sensor/access + wear на дефолтах: итоги P0/P1 — `research/docs/ML_PLAN.md (Часть II)` (notebooks 27/28/29)
- [x] Risk-портфель RBAM (ядро MVP) + fallback «буква ТЗ»: `ML_PLAN.md (Часть III)`, `RISK_PIVOT_REPORT.md`, `TZ_COMPLIANCE_REPORT.md`
- [x] Инференс-контракт для backend: `inference_contract.py` (модель + калибровка + top-K + план ТО)
- [x] Календарь плановых ТО/ППР заказчика (2026): `planned_work.py`, `notebooks/33_planned_work_2026.ipynb`
- [x] **FastAPI-сервис, БД, frontend, JWT/RBAC, audit, реплей 2026** (тесты: 19 passed) — см. `services/README.md`
- [x] **Развёртывание в Docker**: PostgreSQL 12+ + API + SPA/PWA (+ TLS-профиль nginx), `docker compose up -d --build` — см. `services/README.md`
- [x] **Мобильная версия**: адаптивный mobile-first профиль + PWA (нижнее меню, офлайн-очередь действий, push, алерты) — см. `services/MOBILE_PLAN.md`
- [~] LDAP/AD (на MVP — локальные пользователи) и внешние адаптеры (АРМ/ОДС/СКУД) — интерфейсы готовы, данные не поставлены

## MCP: локальный поиск (free-search-mcp, без API-ключей)

Опциональный MCP-сервер веб-поиска (репо `sweetcornna/free-search-mcp`, пакет `free-search-mcp` 0.11.0) установлен в изолированный venv:

```text
.venv-mcp\Scripts\free-search-mcp.exe     # stdio-сервер (по умолчанию)
```

Зарегистрирован в:
- VS Code (нативная MCP): `.vscode/mcp.json` (workspace);
- универсальный формат: `.mcp.json` (workspace root, `mcpServers`);
- Cline: `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`.

Инструменты: `search / research / fetch / fetch_batch / read_doc / cache_search / engines / ...`
(движки: duckduckgo, mojeek, searx; опционально brave/bing/google/…). Проверено
хендшейком (stdio, `initialize` + `list_tools`) и реальным поиском.

Замечания (Windows):
- Для браузерных движков нужен Chromium: `.venv-mcp\Scripts\python.exe -m playwright install chromium`
  (без него HTTP-движки работают; mojeek может отдавать 403 на HTTP — квитируется другими движками);
- Python client должен выставлять `asyncio.WindowsSelectorEventLoopPolicy()` (anyio/stdio на Windows).