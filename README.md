# lct_a8 — Предиктивный ML-сервис аварий и отказов оборудования коллекторов

Веб-сервис прогнозирования отказов датчиков и аварий инженерных коллекторов АО «Москоллектор» (hackathon/технологическое соревнование). Стек: Python 3.12, FastAPI (бэкенд), PostgreSQL, LightGBM/CatBoost (ML), Jupyter (research).

## Структура репозитория

```
lct_a8/
├── STATUS.md            # сводка готовности (метрики, компоненты, блокеры)
├── research/            # ML Research Team: EDA, feature pipeline, модели, Jupyter
│   ├── .venv/           # venv Python 3.12 (ядро Jupyter: lct-a8-research)
│   ├── dataset/         # исходные .7z, распакованные CSV (extracted/), панели, справочники,
│   │                    #   _external/ (кэш внешних выгрузок: maintenance_plan)
│   ├── notebooks/       # 00..07 (данные/EDA), 08..12 (wear/TTE), 19..33 (fire/sensor/access,
│   │                    #   калибровка, RBAM/L2, интеграция, плановые ТО/ППР)
│   ├── nb_build/        # текстовые исходники ноутбуков (+ build.py)
│   ├── docs/            # DATA_REPORT, ML_PLAN, DATA_MATRIX, OPEN_QUESTIONS, MVP_PIVOT,
│   │                    #   RISK_PIVOT_REPORT, TZ_COMPLIANCE_REPORT, API_CONTRACT, ADAPTERS_README
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
    ├── Dockerfile, docker-compose.yml, .env.example
    ├── README.md        # быстрый старт, API, реплей, тесты
    ├── SERVICE_PLAN.md  # план сервиса (уточнён по итогам встречи с экспертами)
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

- `research/docs/ML_PLAN.md` — план ML (раздел 0 — итоги встречи с экспертами 16.09).
- `research/docs/DATA_MATRIX.md` — матрица «задача → данные → связи (joins)».
- `research/docs/OPEN_QUESTIONS.md` — вопросы организаторам и ответы экспертов.
- `research/docs/DATA_REPORT.md` — отчёт по данным (EDA, недельный анализ, кампании).
- `research/docs/PLAN_LAYER2_TTE.md` — план/статус улучшения прогноза «через сколько дней» (слой 2, ноутбук 11).
- `research/docs/PLAN_OTHER_TASKS.md` — план/статус задач fire/sensor/access (в т.ч. итоги P0 в §21, 20.09.2026).
- `research/docs/MVP_PIVOT.md` — ядро MVP в канве индустриальных стандартов (CBM/RBAM/RUL) + резервный сценарий «буква ТЗ» (20.09.2026).
- `research/docs/SEVERITY_MAP.md` — веса последствий для RBAM-приоритета (эвристика, заменится реестром).
- `research/docs/RISK_PIVOT_REPORT.md` — риск-портфель RBAM и план ТО (генерируется notebook 30).
- `research/docs/API_CONTRACT.md` — API-контракт ядра MVP для backend-команды (top-risks / maintenance-plan / forecasts / decision).
- `research/docs/TZ_COMPLIANCE_REPORT.md` — fallback-отчёт «буква ТЗ» (генерируется `research/report_tz_compliance.py`).
- `research/docs/ADAPTERS_README.md` — интерфейсы адаптеров внешних данных (АРМ/ОДС/СКУД/реестр, P2).
- `research/docs/REPRODUCE_DATASETS.md` — как из `.7z` пересобрать все датасеты (`rebuild_all_datasets.py`).

## Текущий статус

Сводная таблица готовности (метрики, компоненты, блокеры) — в **[STATUS.md](STATUS.md)**.

- [x] Окружение: два venv Python 3.12, ядро Jupyter
- [x] Распаковка всех `.7z`
- [x] EDA: объёмы, схема, тревоги по типам, словарь статусов, структура тегов
- [x] EDA в Jupyter: ноутбуки `research/notebooks/01..06` + исходники `nb_build/src`
- [x] Подготовка данных: пайплайн `00_data_pipeline` + ноутбук `07_data_prep` (панели, нейтрализация кампаний)
- [x] Календарь кампаний проверок (`data_utils.CAMPAIGN_WEEKS`)
- [x] Feature pipeline: `features.py` (признаки каналов/объектов, горизонты 6–48ч)
- [x] Basline и горизонты: ноутбуки `08_wear_baseline`, `09_wear_horizons`, `10_wear_series` (событие = старт серии)
- [x] Слой 2 «через сколько дней»: survival-апгрейд `11_wear_tte` (discrete hazard, цензура, holdout 2025H2+2026)
- [x] Задачи fire/sensor/access + wear на дефолтах: итоги P0 — `research/docs/PLAN_OTHER_TASKS.md` §21 (notebooks 27/28/29)
- [x] Risk-портфель RBAM (ядро MVP) + fallback «буква ТЗ»: `MVP_PIVOT.md`, `RISK_PIVOT_REPORT.md`, `TZ_COMPLIANCE_REPORT.md`
- [x] Инференс-контракт для backend: `inference_contract.py` (модель + калибровка + top-K + план ТО)
- [x] Календарь плановых ТО/ППР заказчика (2026): `planned_work.py`, `notebooks/33_planned_work_2026.ipynb`
- [x] **FastAPI-сервис, БД, frontend, JWT/RBAC, audit, реплей 2026** (тесты: 19 passed) — см. `services/README.md`
- [~] Прод-обвязка (PostgreSQL/TLS/LDAP) и внешние адаптеры (АРМ/ОДС/СКУД) — интерфейсы готовы, данные не поставлены

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