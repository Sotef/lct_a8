# Архитектура и использование (lct_a8)

Предиктивный сервис аварий/отказов оборудования коллекторов АО «Москоллектор».
Стек: Python 3.12 · FastAPI + SQLAlchemy/PostgreSQL · CatBoost · vanilla-JS SPA.
Сводка готовности и метрик — `STATUS.md`; ML-дизайн/статус — `research/docs/ML_PLAN.md`;
сервис — `services/BACKEND_SPEC.md`, `services/README.md`.

## 1. Общая картина

```
Журнал СМВУ (ext-journal-*.csv) + справочники (каналы, объекты)
        │
        ▼  features.make_subdaily_panel  ── 6ч панель «канал × бакет»
6ч-панели (subdaily_panel_{fire,access,sensor}6h.csv, subdaily_panel_wear_6h.csv)
        │
        ▼  tte.add_series_context: серии событий, «дни с последнего …», признак аномальных недель
        │  + z_событий по train-статистикам (реестр median/IQR на канал)
        ▼  субъекты = строки текущего бакета → subject_features (X_cols модели)
        │
        ▼  inference_contract.predict_risk(model, subjects) → {p24, risk30, exp_days, S(t)}
        │
        ▼  RBAM: score = risk30 × severity(тип) × scale(объект) → топ-риски / план ТО
        │
        ▼  REST API /api/v1 (JWT + RBAC) → SPA диспетчера: дашборд, объекты, журнал, план ТО, решение
        │
        ▼  POST /decision → журнал прогнозов + audit (обратная петля ground-truth)
```

Два контура: **research** (обучение/оценка, Jupyter + `.py`-модули) и **services**
(FastAPI-сервис, который переиспользует research-модули как библиотеку).

## 2. Структура репозитория

```
lct_a8/
├── STATUS.md                 # сводка готовности (метрики, компоненты, блокеры)
├── ARCHITECTURE.md           # этот документ
├── research/                 # ML: данные, фичи, модели, контракт
│   ├── dataset/              # .7z + extracted/, панели, справочники, _external/ (внешние выгрузки)
│   ├── notebooks/            # 00..07 EDA/prep, 08..12 wear/TTE, 13..33 fire/sensor/access, RBAM
│   ├── models/               # *.cbm (4 задачи), holdout-предсказания, отчёты, калибровки
│   ├── docs/                 # ML_PLAN, ARCHITECTURE-инфо, DATA_*, OPEN_QUESTIONS, BACKLOG, API_CONTRACT
│   ├── data_utils.py         # чтение журналов, справочники, календарь кампаний
│   ├── features.py           # панели (суточные/6ч), признаки, цели
│   ├── tte_pipeline.py       # survival: серии, цензура, сплиты, person-time, subject_features
│   ├── tte_experiments.py    # обучение/оценка discrete hazard + бенчмарки
│   ├── inference_contract.py # ЕДИНАЯ точка инференса для backend
│   ├── planned_work.py       # парсер графиков ТО/ППР 2026 → календарь ISO-недель
│   └── rebuild_task_panels.py / rebuild_all_datasets.py
└── services/                 # Backend & Web
    ├── app/api/              # роутеры (auth, risks, forecasts, objects, admin, meta, health)
    ├── app/services/         # бизнес-логика (prediction, inference, feature_pipeline, ml_registry…)
    ├── app/adapters/         # read-only адаптеры (journal, ldap)
    ├── app/workers/          # ingestion, scheduler, simclock (реплей 2026)
    ├── app/web/              # SPA (vanilla JS), раздаётся FastAPI
    ├── alembic/              # миграции БД (PostgreSQL 12+)
    ├── scripts/              # seed, run_demo, replay_history, validate_2026
    └── tests/                # unit + front-contract + сверка с research
```

## 3. Research-модули (ответственности)

| Модуль | Что делает | Ключевые функции |
|---|---|---|
| `data_utils.py` | чтение журналов чанками, справочники, календарь кампаний | `read_chunks`, `load_ref_channels/_objects`, `CAMPAIGN_WEEKS`, `week_is_campaign` |
| `features.py` | панели «канал×бакет(6ч)», счётчики событий/тревог/неисправностей/шума, окна, z-скор, сезонность, объектный контекст, цели | `make_subdaily_panel`, `make_daily_panel` |
| `tte_pipeline.py` | серии событий, цензура, временные сплиты, person-time, список фич | `add_series_context`, `subject_features`, `HORIZONS`, `DROP_COLS` |
| `tte_experiments.py` | discrete-hazard обучение/оценка, якоря, бенчмарки | `fit_discrete_hazard`, метрики Uno-C/IBS/PR-AUC |
| `inference_contract.py` | единый API инференса (модель+калибровка+RBAM+план) | `load_model`, `predict_risk`, `calibrated_risk`, `top_risks`, `maintenance_plan`, `final_metrics`, `risk_drift_by_quarter` |
| `planned_work.py` | графики ТО/ППР заказчика → ISO-недели | `parse_ppr`, `parse_to`, `planned_work_weeks` |
| `rebuild_task_panels.py` | пересборка 6ч-панелей задач с семантическими колонками | `build_fire/sensor/access` |

**Контракт «сырого» инференса:** имена/порядок колонок == обучению; окна — только «прошлое+текущий бакет»;
`z_событий` — по train-статистикам; кампанийные недели помечаются, но не выбрасываются.
Список фич фиксируется в `research/_features_schema.json` (и `services/data/_features_schema.json`).

## 4. Модели и артефакты

| Задача | Событие | Модель (CatBoost) | Калибровка risk30 | Ключевой артефакт |
|---|---|---|---|---|
| `fire` | «серьёзная тревога» (подтв. дым ≥2 / ручной ИПР, окно 6ч) | `tte_fire_discrete_hazard.cbm` | raw | `tte_fire_report.txt` |
| `access` | серия охранных тревог (proxy) | `tte_access_discrete_hazard.cbm` | per-bin (`calib30_access.pkl`) | `tte_access_report.txt` |
| `sensor` | серия неисправностей (любой статус) | `tte_sensor_discrete_hazard.cbm` | raw | `tte_sensor_report.txt` |
| `wear` | старт серии неисправностей насосов/вент/фаз | `tte_wear_discrete_hazard.cbm` | raw | `tte_wear_report.txt` |

Holdout-предсказания — `tte_{task}_holdout.parquet`; финальные метрики — `research/dataset/final_metrics_v0.csv`;
риск-портфель — `research/docs/RISK_PIVOT_REPORT.md`. Калибровка p24 — не применяется (raw) везде.

## 5. Сервис (services)

- **ML как библиотека:** эндпоинты не содержат ML-логики; research-модули подключаются через
  `app/research_bridge.py` (`sys.path` на `research/`). Роутеры вызывают `app/services/inference.py`,
  который оборачивает `inference_contract`.
- **feature_pipeline в сервисе:** инкрементальный ingestion журнала (6ч-бакеты, checkpoint по времени) →
  панель → z-stats (train-only, `services/data/z_stats_<task>.csv`) → серии → субъекты → прогноз.
- **Хранение:** `app/models_db.py` (SQLAlchemy 2) + Alembic. Основные таблицы: `users`, `predictions`,
  `decisions`, `audit_log`, `data_sources`, `models_registry`, `object_risk_l2`, `maintenance_tasks`, `settings`.
- **Авторизация/RBAC:** JWT (access 30 мин / refresh 7 сут), 3 роли — `tech` (только свой район),
  `dispatcher`, `central`; LDAP-адаптер read-only (MVP — локальная имитация); все действия → `audit_log`.
- **Workers:** `ingestion` (потоковое чтение, бакеты 6ч), `scheduler` (6ч-цикл), `simclock`
  (режим реплея 2026: сим-время стартует 01.01.2026, шаг 6ч каждые `SIM_TICK_REAL_SEC`).
- **Frontend:** SPA (vanilla JS, без сборки) раздаётся тем же FastAPI: дашборд рисков, объекты/карта,
  граф пикетов, журнал прогнозов (карточка: S(t), SHAP-факторы, решения+audit), план ТО, 3 темы.

## 6. REST API (под `/api/v1`)

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/auth/login`, `/auth/refresh`, `/auth/admin/create-user` | вход / токен / создание пользователя |
| GET | `/auth/me` | текущий пользователь |
| GET | `/top-risks?task=&k=&horizon=` | топ-K RBAM (score = risk30 × severity × scale) |
| GET | `/maintenance-plan?task=` | план ТО (горизонты по `exp_days`) |
| GET | `/forecasts`, `/forecasts/{id}`, `/forecasts/{id}/factors` | журнал / карточка / факторы «почему» |
| POST | `/forecasts/{id}/decision` | решение диспетчера (+audit, метки для дообучения) |
| GET | `/objects`, `/objects/{id}`, `/objects/{id}/risks`, `/objects/graph` | объекты/риски/схема связности |
| GET | `/meta/*` | мета для UI (задачи, даты бакетов, summary, тренд, история канала) |
| POST | `/admin/data/load`, `/admin/replay`, `/admin/models/reload` | ingestion / пересчёт истории / перечитать модели |
| GET | `/admin/data/status`, `/admin/models`, `/admin/drift`, `/health` | статусы / реестр / drift / здоровье |

Полный контракт ядра MVP — `research/docs/API_CONTRACT.md`; расширенный — `services/BACKEND_SPEC.md`.

## 7. Использование

### 7.1 Окружение (два venv, Python 3.12)

```powershell
D:\python312\python.exe -m venv research\.venv
research\.venv\Scripts\python.exe -m pip install -r research\requirements.txt
research\.venv\Scripts\python.exe -m ipykernel install --user --name lct-a8-research --display-name "Python 3.12 (research)"

D:\python312\python.exe -m venv services\.venv
services\.venv\Scripts\python.exe -m pip install -r services\requirements.txt
```

### 7.2 Research (данные/модели/инференс-контракт)

```powershell
# пересборка датасетов и панелей (из .7z — см. research/docs/REPRODUCE_DATASETS.md)
research\.venv\Scripts\python.exe research\rebuild_all_datasets.py
research\.venv\Scripts\python.exe research\rebuild_task_panels.py

# инференс-контракт: финальная таблица метрик / топ-K
research\.venv\Scripts\python.exe research\inference_contract.py --table
research\.venv\Scripts\python.exe research\inference_contract.py --topk

# графики ТО/ППР заказчика → календарь недель + артефакты
research\.venv\Scripts\python.exe research\planned_work.py

# Jupyter
research\.venv\Scripts\python.exe -m jupyter lab
```

### 7.3 Сервис (демо, локально на SQLite)

```powershell
cd services
.venv\Scripts\python.exe scripts\seed.py                    # таблицы + демо-пользователи + реестр моделей
.venv\Scripts\python.exe scripts\run_demo.py --limit 5000000 # ingestion (быстро) + прогнозный цикл
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# UI: http://127.0.0.1:8000/   ·   API: http://127.0.0.1:8000/docs
```

Демо-пользователи (`scripts/seed.py`): `central.operator/central123`, `dispatcher.alpha/alpha123`,
`dispatcher.beta/beta123`, `tech.alpha/tech123`.

### 7.4 Тесты

```powershell
cd services
.venv\Scripts\python.exe -m pytest tests -q                 # unit + front-contract + сверка с research
.venv\Scripts\python.exe tests\pipeline_smoke.py wear       # сквозной на реальных данных
```

## 8. Развёртывание и запуск (Docker — самый простой способ)

Весь сервис (PostgreSQL 12+ + API + SPA/PWA) поднимается в Docker; Python, venv и
локальная БД не нужны:

```bash
cd services
cp .env.docker.example .env          # Windows: copy .env.docker.example .env
docker compose up -d --build         # первая сборка 2–3 минуты
# SPA http://127.0.0.1:8000/  ·  Swagger /docs  ·  HTTPS (профиль tls) https://127.0.0.1:8443/
# Профиль tls требует сертификаты: python scripts/make_dev_certs.py (см. deploy/certs/README.md)
docker compose exec -T api python scripts/verify_deploy.py   # проверка API по ролям + PWA-раздачи
```

Демо-пользователи: `central.operator/central123`, `dispatcher.alpha/alpha123`,
`dispatcher.beta/beta123`, `tech.alpha/tech123`. Остановить — `docker compose down`
(данные БД сохраняются; `docker compose down -v` — сброс демо).

> Демо-данные (6ч-панели ~319 МБ и артефакты) контейнер скачает сам при первом старте:
> в `.env.docker.example` задан `DEMO_DATA_HF=sotef/lct`, entrypoint делает
> `fetch_demo_data.py --check` → при нехватке `--hf sotef/lct` (без токена) и распаковывает
> в `services/data/`, не перезаписывая существующее. `git lfs pull` нужен только для
> локального запуска без Docker; отключить сеть на старте — `SKIP_DEMO_FETCH=1`.

### Тест на мобильных (телефон/планшет)

1. В той же сети откройте на телефоне `http://<IP компьютера>:8000` — адаптивный UI
   (нижнее меню, карточки вместо таблиц/канбана, «Ещё», фото с камеры). Порт при
   необходимости: `netsh advfirewall firewall add rule name="LCT 8000" dir=in action=allow protocol=TCP localport=8000`.
2. Установка PWA, офлайн-очередь и Web Push требуют *secure context*: на компьютере —
   `http://127.0.0.1:8000` + DevTools device mode; на телефоне — HTTPS с **доверенным**
   сертификатом (`docker compose --profile tls up -d --build` → `https://<IP>:8443`).
3. Автотест мобильного профиля:
   `docker compose cp app/web/__mprobe.html api:/workspace/services/app/web/__mprobe.html`
   → `http://127.0.0.1:8000/__mprobe.html?stub=1` (отчёт `MPROBE OK`).

Локально без Docker — SQLite (default `DATABASE_URL`); прод — PostgreSQL 12+,
TLS 1.2+ на reverse-proxy, секреты в `.env`, журнал действий — `audit_log`.
Детали — `services/README.md`, мобильная версия — `services/MOBILE_PLAN.md`.

## 9. Карта документации

| Документ | Назначение |
|---|---|
| `README.md` (корень) | обзор, структура, быстрый старт |
| `STATUS.md` (корень) | готовность, метрики, блокеры |
| `ARCHITECTURE.md` (этот) | архитектура и использование |
| `research/docs/ML_PLAN.md` | ML: архитектура, план, статус задач, продуктовая рамка |
| `research/docs/BACKLOG.md` | нереализованное/отложенное + блокеры данных |
| `research/docs/OPEN_QUESTIONS.md` | вопросы заказчику и ответы экспертов |
| `research/docs/DATA_REPORT.md`, `DATA_MATRIX.md` | EDA и матрица данных/joins |
| `research/docs/API_CONTRACT.md`, `SEVERITY_MAP.md` | API ядра MVP, веса severity |
| `research/docs/RISK_PIVOT_REPORT.md`, `TZ_COMPLIANCE_REPORT.md` | отчёты (генерятся скриптами) |
| `research/docs/ADAPTERS_README.md`, `REPRODUCE_DATASETS.md` | адаптеры внешних данных, пересборка датасетов |
| `services/README.md`, `services/BACKEND_SPEC.md`, `services/SERVICE_PLAN.md` | сервис: запуск, интеграционная спека, план |

