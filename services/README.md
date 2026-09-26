# Предиктивный сервис АО «Москоллектор» — Backend & Web Service Team

MVP-сервис предиктивной аналитики: потоковые/исторические данные журнала СМВУ →
6-часовые панели → признаки моделей (идентичные обучению) → прогнозы
(fire/access/sensor/wear) → диспетчерский REST API + карточка риска, план ТО,
решения (обратная петля ground-truth) и аудит.

ML-логика не пишется в эндпоинтах: она инкапсулирована в `research`
(`features.py`, `tte_pipeline.py`, `inference_contract.py`) и подключается
как библиотека (см. `app/research_bridge.py`).

## Поток данных

```
ext-journal-*.csv ─► adapters/journal.py (потоковое чтение, бакеты 6ч, checkpoint по времени)
        │  кэш: services/data/raw/buckets_2026.parquet  (+ extra_cols всех задач — один проход)
        ▼
feature_pipeline.build_subjects(task)
   1) 6ч-панель  = features.make_subdaily_panel(precomputed=...)
   2) z_событий  = train-статистики (services/data/z_stats_<task>.csv) — без «заглядывания» в 2026
   3) серии      = tte.add_series_context(event_col задачи)
   4) субъекты   = строки бакета; subject_features == research/_features_schema.json X_cols (assert)
        ▼
inference.predict_risk / predict_survival_curve → {p24, risk30(cal), exp_days, S(t)}
        ▼
RBAM: score = risk30_cal × severity(тип) × scale(объект) → заявки/план ТО
        ▼
REST API /api/v1 (JWT + RBAC) → диспетчер: /top-risks, /forecasts/{id}, /decision, /objects
```

## Быстрый старт (test engine: Windows, services/.venv)

```powershell
# 1) окружение
d:\python312\python.exe -m venv services\.venv
services\.venv\Scripts\python.exe -m pip install -r services\requirements.txt

# 2) наполнить БД (SQLite для локального запуска из .env по умолчанию;
#    прод — PostgreSQL 12+, см. .env.example / docker-compose.yml)
cd services
.venv\Scripts\python.exe scripts\seed.py          # таблицы + демо-пользователи + реестр моделей

# 3) ПОТОКОВЫЙ ТЕСТ НА РЕАЛЬНЫХ ДАННЫХ 2026 (не участвовали в обучении)
#    (а) быстро: первые ~5 млн строк
.venv\Scripts\python.exe scripts\run_demo.py --limit 5000000
#    (б) догрузить остаток инкрементально (checkpoint по max_ts)
.venv\Scripts\python.exe scripts\run_demo.py --no-ingest   # прогнозный цикл на последнем бакете
.venv\Scripts\python.exe scripts\run_demo.py               # = ингвест остатка + прогнозы

# 4) API
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
open http://127.0.0.1:8000/docs
```

### Режим реплея (симулируемые часы)
По умолчанию сервис живёт в режиме **реплея данных 2026 года**: симулируемое
«сейчас» стартует **01.01.2026 00:00** и каждые `SIM_TICK_REAL_SEC` (75 с)
продвигается на 6 ч — все 4 задачи пересчитываются, KPI/тренд/журнал растут
в реальном времени, прогнозы попадают в сезонность моделей. Текущее сим-время —
чип `⏱` в шапке UI и `GET /api/v1/meta/clock`. Первый запуск с пустым
`settings.sim_bucket` сбрасывает старый реплей и начинает с 01.01.2026.
Отключение: `SIM_CLOCK=0` (+ `RUN_SCHEDULER=1` для 6ч-цикла по реальному времени).
Горизонт сортировки топ-рисков и журнала: `?horizon=24h|72h|30d` (P≤24ч / P≤72ч / risk30).

Демо-пользователи (scripts/seed.py):
| username | password | роль |
|---|---|---|
| central.operator | central123 | центральный диспетчер |
| dispatcher.alpha | alpha123 | диспетчер |
| dispatcher.beta  | beta123  | диспетчер |
| tech.alpha       | tech123  | техник (видит только свой объект/район — RBAC) |

## REST API (все пути под /api/v1)

| Метод | Путь | Роли |
|---|---|---|
| POST | /auth/login, /auth/refresh, /auth/admin/create-user | public / public / central |
| GET  | /auth/me | любой аутент. |
| GET  | /top-risks?task=fire&k=200&active_only=&bucket= | dispatcher, central |
| GET  | /maintenance-plan?task=wear | dispatcher, central, tech |
| GET  | /forecasts?task=&object_id=&bucket= | dispatcher, central |
| GET  | /forecasts/{id} (карточка §6.2), /forecasts/{id}/factors | dispatcher, central / dispatcher |
| POST | /forecasts/{id}/decision {decision, responsible, comment} | dispatcher, central |
| GET  | /objects, /objects/{id}, /objects/{id}/risks | dispatcher, central, tech |
| POST | /admin/data/load (инкрементальный ингвест), /admin/models/reload | central |
| GET  | /admin/data/status, /admin/models, /admin/drift?task= | central (+dispatch) |
| GET  | /health | public |

`bucket` — 6-часовой интервал (int от эпохи, как в research). Без параметра —
последний бакет данных. Диспетчер различает объекты через `/objects` (дерево:
district → controlHouse/guardObject, с L2-рисками) и `object_id` в каждом прогнозе;
техник видит только поддерево своего `district`.

## Ключевые точки кода

- `app/adapters/journal.py` — потоковый адаптер журнала (чанки, 6ч-бакеты,
  checkpoint по max_ts; первый проход — полный, повторные — только новые строки).
- `app/services/feature_pipeline.py` — форматирование данных под модели
  (панель + z по train + серии + коды категорий + выравнивание X_cols).
- `app/services/inference.py`, `ml_registry.py` — инференс и RBAM.
- `app/services/prediction_service.py` — персист прогнозов в БД, топ-риски, план ТО.
- `app/workers/ingestion.py`, `scheduler.py` — воркеры (6ч пересчёт, RUN_SCHEDULER=1).
- `app/api/*` — FastAPI-ручки (без ML-логики).
- `services/data/*` — сгенерированные артефакты: z_stats_<task>.csv, cat_codes_<task>.json,
  _features_schema.json, l2_object_risk.parquet, raw/buckets_2026.parquet, panels/*.

## Проверка согласованности с обучением

`tests/test_against_research_2026.py` — **главный тест подачи данных**: потоковый
кэш сервиса (собранный адаптером из `ext-journal-2026.csv`) сверяется
ПОЭЛЕМЕНТНО с research-панелями (ground truth обучения) по счётчикам
«канал × 6ч-бакет» за H1-2026: базовые счётчики + все extra_cols задач
(задымлений, серьёзн_ручной, тревог_дым/тепло/дверь/движение, пр_разрывов,
неисправн_дым) и производное событие fire «серьёзных». wear/fire — полная
сверка всех ключей; access/sensor — на выборке 2000 ключей (большие панели).

`tests/pipeline_smoke.py wear|fire|access|sensor [limit]` — собирает субъекты из
реального журнала и проверяет, что `subject_features` совпадает с X_cols модели
(CatBoost строг к числу/порядку колонок). `tests/api_check.py` — сквозная
проверка API (auth, риски, карточка, решение, объекты, RBAC, rate-limit).

`scripts/validate_2026.py` — валидация качества на потоковых данных H1-2026
(модель их не видела при обучении): p24/risk30 vs фактические события,
precision/recall на топ-K, PR-AUC; отчёт — `services/data/validate_2026_report.txt`.

## Различение объектов у диспетчера

Все прогнозы в БД хранятся с `object_id` и `channel_id`; списки
`/top-risks` и `/forecasts` возвращают вместе с риском: `название_объекта`,
`тип_объекта`, `район`, `название_датчика`, `тип_датчика`, `тег_инж_системы`,
`инж_система` (join `objects_ref`/`channels_ref`). Дерево/карта — `/objects`
(+ риски L2 на узлах), схема пикетов — `/objects/graph`, карточка
`/forecasts/{id}` содержит полный контекст объекта и канала. RBAC: техник
видит только объекты своего района (проверяется в api_check).

> Заметка: в `research/features.py` внесены два защитных фикса (идентично
> обучению): (1) `drop(columns=...)` не вызывается при пустом списке extra_cols,
> (2) в `count_cols_ob` добавлен `каналов_активных_об_б` — обучающие панели
> содержали эти окна (текущая research-копия теряла их). Изменение не влияет на
> уже построенные кэши/субъекты research.

## Веб-интерфейс

SPA раздаётся тем же FastAPI: **http://127.0.0.1:8000/** (`app/web`, vanilla JS,
без сборки). Вид: Дашборд рисков (KPI + тренд + топ-риски), Объекты
(список / карта Москвы и области), Граф систем (объекты ↔ пикеты из
`/objects/graph`), Журнал прогнозов (карточка §6.2: S(t), SHAP-факторы,
решения с audit), План ТО.

**Три оформления** (переключатель в шапке/на логине, сохраняется в браузере):
`Obsidian` (тёмный глассморфизм), `Editorial` (светлый журнальный),
`Terminal` (пульт диспетчера, моно).

> Координат объектов в данных нет — позиции на карте **схематичные**
> (детерминированный разброс вокруг Москвы и области, цвет = риск, размер =
> каналы); в UI есть пометка. Leaflet грузится с CDN; офлайн — режим «Список».

Контракт фронт↔бэкенд проверяется `tests/front_contract_check.py` (summary,
risk-history, top-risks с полями объекта, карточка с S(t)/factors, graph,
decision).

| Метод | Путь | Назначение |
|---|---|---|
| POST | /auth/login, /auth/refresh, /auth/admin/create-user | вход / токен / создание пользователя |
| GET  | /auth/me | текущий пользователь |
| GET  | /top-risks?task=&k=&bucket= | топ-K RBAM (актуальный/выбранный бакет) |
| GET  | /maintenance-plan?task= | план ТО (горизонты по exp_days) |
| GET  | /forecasts?task=&object_id=&bucket= | журнал прогнозов |
| GET  | /forecasts/{id}, /forecasts/{id}/factors | карточка + факторы «почему» |
| POST | /forecasts/{id}/decision | решение диспетчера (+ audit + метки для дообучения) |
| GET  | /objects, /objects/{id}, /objects/{id}/risks, /objects/graph | объекты/риски/схема связности |
| GET  | /meta/tasks, /meta/bucket-dates, /meta/summary, /meta/risk-history, /meta/channel-history | мета-данные для UI |
| POST | /admin/data/load, /admin/replay | ингвест журнала / пересчёт истории прогнозов |
| GET  | /admin/data/status, /admin/models, /admin/drift | статусы / реестр моделей / drift |
| POST | /admin/models/reload | перечитать активные модели |
| GET  | /health | статус + версии моделей |

`bucket` — 6-часовой интервал (int от эпохи, как в research); без параметра —
последний бакет данных.

## Тесты

```powershell
.venv\Scripts\python.exe -m pytest tests -q   # unit: адаптер/панель/согласование
.venv\Scripts\python.exe tests\pipeline_smoke.py wear   # сквозной (реальные данные)
```

## Docker / PostgreSQL (прод-контур)

```bash
docker compose up -d postgres
docker compose run --rm api python scripts/seed.py
docker compose up -d api
```

Локальная разработка — SQLite (default `DATABASE_URL`), прод — PostgreSQL 12+
(`DATABASE_URL=postgresql://...`), TLS 1.2+ на reverse-proxy, секреты в `.env`,
журнал действий пользователей — `audit_log` (обязательный сценарий демо).

## Метрики (research/final_metrics_v0.csv, holdout ≥ 2025-07, включая H1-2026)

Precision>0.7 и Recall>0.5 на топ-K по p24 (см. отчёты `research/models/tte_*_report.txt`);
прогноз на 6ч-сетке 30д (горизонт ≥ 24ч), время инференса одного бакета «канал×модель»
< 1 с на готовой панели (SLA ≤ 300 с).