# Роль

Ты — Backend & Web Service Team, мультиагентная команда, отвечающая за создание веб-сервиса предиктивной аналитики ЖКХ.

# Цель

Создать работающий сервис, который:

* получает данные от внешних систем;
* хранит и обрабатывает данные;
* вызывает ML-модели;
* формирует прогнозы и уровни риска;
* предоставляет REST API;
* отображает результаты через web-интерфейс;
* поддерживает работу диспетчера;
* сохраняет решения и результаты обработки.

Сервис должен интегрироваться с данными СМВУ, ОДС, реестром оборудования и другими источниками.

# Внутренние агенты

Работай как команда:

* Tech Lead — архитектура и координация;
* Backend Engineer — бизнес-логика и API;
* Database Engineer — PostgreSQL и модели данных;
* Integration Engineer — внешние системы;
* ML Integration Engineer — подключение inference;
* Frontend Engineer — web-интерфейс;
* Security Engineer — authentication, RBAC и audit;
* QA Engineer — тестирование;
* DevOps Engineer — Docker, deployment и monitoring.

# Правила

1. Сначала определить архитектуру и API-контракты.
2. Разделять frontend, backend, ML и integrations.
3. Использовать REST API и версионирование API.
4. Использовать PostgreSQL 12+.
5. Внутренние системы подключать в режиме read-only.
6. Поддерживать RBAC и интеграцию с LDAP/AD.
7. Использовать TLS 1.2+.
8. Логировать действия пользователей.
9. Все внешние интеграции реализовывать через отдельные adapters.
10. Не переносить ML-логику непосредственно в API endpoints.

Требования по PostgreSQL, TLS, LDAP/AD, RBAC и журналированию заданы в исходном ТЗ.

# Обязательный пользовательский сценарий

Система должна поддерживать цикл:

данные → ML-прогноз → alert → просмотр диспетчером → верификация → решение → сохранение результата.

Диспетчер принимает окончательное решение, а не ML-модель.

# Производительность

Целевые ограничения:

* inference одного объекта — не более 300 секунд;
* задержка обработки потоковых данных — не более 300 секунд;
* не менее 20 одновременных пользователей.

# Результат

На выходе команда должна предоставить:

# BACKEND SPEC — интеграционная спецификация предиктивного сервиса

Версия: 0.1 · Дата: 20.09.2026 · Backend & Web Service Team · (ядро: ML_PLAN.md (Часть III), API_CONTRACT.md, SERVICE_PLAN.md)

> Этот файл — «вход» для backend: куда брать данные, как их превращать в признаки,
> где модели, какие ручки и какая БД. ML-логика НЕ пишется в эндпоинтах —
> она инкапсулирована в `research/inference_contract.py` (импортируется как библиотека).

## 0. Стек

- Python 3.12, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 12+,
  asyncpg; auth: JWT (python-jose) + RBAC; CDN: файловая система (models/parquet).
- venv: `services/.venv` (requirements в `services/requirements.txt`).
- Research-модули подключаются через путь: `sys.path.insert(0, r"d:\Downloads_D\lct_a8\research")`.

## 1. Поток данных (общая картина)

```
СМВУ-журналы (ext-journal-*.csv) ─► adapters (read-only)
   │
   ▼  features.make_subdaily_panel (6ч панель «канал × бакет»)
subdaily_panel_{task}6h.csv (+ справочник каналов: ид_канала_данных, тип_датчика, ид_объект)
   │
   ▼  series context (tte.add_series_context): серия_старт, дни_с_посл_*
   │  + z_событий по train-статистикам (реестр канальных median/IQR)
   ▼  субъекты (строки текущего бакета) → subject_features (фичи модели)
   │
   ▼  inference_contract.predict_risk(model, subjects)
  {p24, risk30, risk30_cal, exp_days, S(t)}  →  прогнозы → БД
   │
   ▼  RBAM: score = risk30 × severity(тип) × scale(объект) → топ-риски/план ТО
   │
   ▼  REST API /top-risks /maintenance-plan /forecasts/{id} /decision → UI диспетчера
```

## 2. Источники данных и адаптеры

| Источник | Файл/эндпоинт | Структура (колонки) | Примечание |
|---|---|---|---|
| Журнал СМВУ (2019–2026) | `research/dataset/extracted/ext-journal-{год}.csv` | ид_события, ид_канала_данных, дата, время, тревожное('t'/'f'), значение_датчика | ~15 ГБ; читать адаптером по годам/инкрементально |
| Справочник каналов | `research/dataset/справочник_каналов_датчиков.csv` | ид_канала_данных, тип_датчика, ид_объект, … | ключ join канал→объект |
| Справочник объектов | `research/dataset/справочник_объектов_диспетчер.csv` | иерархия (district/controlHouse/…) | для карты/группировок |
| 6ч-панели (готовые) | `research/dataset/subdaily_panel_{fire,access,sensor}6h.csv`, `subdaily_panel_wear_6h.csv` | событий, тревог, неисправностей, шума + окна `_сум_*` + объектные `_об_б_*` + seasonality | source of truth для инференса |
| Подтверждения диспетчера | таблица `decisions` (БД) | обратная петля ground-truth (дообучение) |
| P2 (ждать): АРМ-Контроль, журнал ОДС, СКУД, реестр ремонтов | интерфейсы — `research/docs/ADAPTERS_README.md` | ключи: ид_объект + интервал дат |

Адаптеры — отдельные классы `services/app/adapters/*.py` (read-only, кэш в `research/dataset/_external/`).

## 3. Преобразование данных → признаки для модели (ОБЯЗАТЕЛЬНЫЙ формат)

Панель автоматически содержит все фичи, которыми обучалась модель, ЕСЛИ собирается
`features.make_subdaily_panel(types=<task>, recompute=False)` с теми же параметрами
(для wear — штатно; fire/access/sensor — с extra_cols, см. `rebuild_task_panels.py`).

Дальше — **цепочка инференса (5 шагов)**:

1. `features.make_subdaily_panel(types=..., recompute=False/True, out_csv=...)` →
   DataFrame (ид_канала_данных, бакет, дата, событий, тревог, неисправностей, шума,
   все `_сум_*`/объектные `_об_б_*`, час_бакета, день_недели, месяц, день_года,
   z_событий, цели*, год_неделя, аномально).
2. **z_событий** — пер-канальный z-скор. В панели он посчитан по всем годам; для
   честного инференса применяются **train-статистики** (ячейка `tte.refit_z_train_only`):
   `z = (событий - median_chan(train≤2024, вне кампаний)) / (iqr_chan + 1e-6)`.
   → вынести реестр `{ид_канала_данных: (median, iqr)}` в файл (см. §3.1).
3. `tte.add_series_context(panel, event_col=<task>)` → серия_старт, дни_до_серии,
   дни_с_посл_неиспр, дни_с_посл_старта, в_серии_прокси, цель_серии_*.
4. Отобрать строки для прогноза: каналы на **текущий бакет** (бакет = int(now / 6ч)) —
   это субъекты. Список фич модели: `X_cols = tte.subject_features(субъекты)` —
   **все числовые колонки МИНУС** `DROP_COLS` (см. `tte_pipeline.DROP_COLS`):
   ид_канала_данных, бакет, дата, год_неделя, аномально, ид_объект, тип_датчика,
   серия_старт, дни_до_серии, дни_класс, event_flag, obs_buckets, obs_days,
   event_time_days, _next_start_bucket, цель_6ч/12ч/24ч/48ч, цель_серии_*.
5. Инференс:
   `pr = inference_contract.predict_risk(model, subjects)` —
   внутри: `expand_person_time(subjects, X_cols, 120, fixed_horizon=True)` (добавляет
   шаг, час_шага, день_недели_шага, месяц_шага, доля_горизонта), `predict_proba` →
   S(t) (120 бакетов), `p24 = 1-S[3]`, `risk30 = 1-S[-1]`, `exp_days = S.sum()/4`.

### 3.1 Реестр z-статистик (СДЕЛАТЬ при обвязке)
Файл `services/data/z_stats_<task>.parquet`: пер-канальные (median, iqr) по
train (≤2024-12-31, вне кампаний) — пересчитывается скриптом research при релизе
модели и кладётся рядом с моделью. Применять на этапе шага 2 сервисом.

### 3.2 Требования к «сырому» инференсу (без переобучения)
- Число/имена колонок на инференсе должны совпадать с обучением (CatBoost строг).
- Окна (событий_сум_* и др.) — только «прошлое + текущий бакет» (уже так в панели).
- Кампанийные недели (аномально=True) в прод-прогнозе помечать, но не выбрасывать
  строки (алерт диспетчеру без ML-подтверждения).

## 4. Модели: где лежат, как загружать

| Задача | Модель (CatBoost .cbm) | Калибровка risk30 | Фичи (панель 6ч) |
|---|---|---|---|
| fire | `research/models/tte_fire_discrete_hazard.cbm` | **нет (raw)** | 137+5 шаговых |
| access | `research/models/tte_access_discrete_hazard.cbm` | **да** — `research/models/calib30_access.pkl` | ~все числовые panel |
| sensor | `research/models/tte_sensor_discrete_hazard.cbm` (панель с пр_разрывов/неисправн_дым, 20.09.2026) | **нет (raw, §21.9)** | 95+5 |
| wear | `research/models/tte_wear_discrete_hazard.cbm` (дефолты 1000/0.03/10, GPU) | **нет (raw)** | 64+5 |

Загрузка через `inference_contract`:
```python
import inference_contract as ic
m = ic.load_model("fire")            # CatBoost(task_type="CPU"), load_model(*.cbm)
cal = ic.load_calibration("access")  # (bin_edges, rates) | None
risk30_cal = ic.calibrated_risk("access", risk30)  # per-bin (только access)
```

Holdout-предсказания и отчёты (для сверки/тестов, не в рантайме):
`research/models/tte_{task}_holdout.parquet`, `tte_{task}_report.txt`,
`verify_inference_{task}.txt`; финальная таблица метрик — `research/dataset/final_metrics_v0.csv`.

### 4.1 Реестр моделей (БД)
`models_registry` (см. §6.1): task, version, model_path, calib_path, z_stats_path,
trained_on, metrics_json, active. Новая модель → новый параметр записи, `active=1`
переключает инференс (поднимается через `/admin/models/reload` без рестарта).

## 5. REST API — ручки

Все пути под `/api/v1`, JSON (UTF-8), ошибки `{detail: ...}`.

### 5.1 Auth
| Метод | Путь | Тело/параметры | Ответ | Роли |
|---|---|---|---|---|
| POST | /auth/login | {username, password} | {access_token, refresh_token, user} | public |
| POST | /auth/refresh | {refresh_token} | {access_token} | public |
| GET | /auth/me | — | {id, username, role} | любой аутентиф. |
| POST | /auth/admin/create-user | {username, role} | user | central |

JWT Bearer, access 30 мин / refresh 7 сут. LDAP/AD — адаптер `adapters/ldap.py`;
на MVP — локальная имитация (демо-роли из SERVICE_PLAN).

### 5.2 Риск/прогнозы
| Метод | Путь | Параметры | Ответ | Роли |
|---|---|---|---|---|
| GET | /top-risks | task∈{fire,access,sensor,wear}, k=200, active_only | {task,k,items[]} | dispatcher, central |
| GET | /forecasts/{id} | — | карточка (§6.2) | dispatcher, central |
| GET | /forecasts | task, object_id?, status?, page | список | dispatcher, central |
| GET | /objects | — | L2-риск объектов | dispatcher, central |
| GET | /objects/{id}/risks | task? | риски каналов объекта | dispatcher, central |
| GET | /maintenance-plan | task?, quarter? | план ТО (plan×тип) | dispatcher, central, tech |
| GET | /forecasts/{id}/factors | — | топ-фичи «почему» | dispatcher |
| POST | /forecasts/{id}/decision | {decision, responsible, comment} | {ok} + audit | dispatcher, central |

`/top-risks` и `/maintenance-plan` — прямой JSON из `inference_contract.top_risks()` /
`maintenance_plan()`: score = risk30(cal где есть) × severity(тип) × scale(объект);
severity — `inference_contract.SEVERITY_BY_TYPE`, scale — по числу активных каналов объекта.

### 5.3 Администрирование/данные/модели
| Метод | Путь | Назначение | Роль |
|---|---|---|---|
| POST | /admin/data/load | запустить адаптер журнала (инкрементально) | central |
| GET | /admin/data/status | статусы загрузок (data_sources) | central, dispatcher |
| POST | /admin/models/reload | перечитать активные модели/калибровки | central |
| GET | /admin/models | реестр models_registry | central |
| GET | /admin/drift?task= | процентили p24/risk30 + O/E (`risk_drift_by_quarter`) | central |
| GET | /health | {status:"ok", model_version} | public |

## 6. БД (PostgreSQL 12+)

### 6.1 Таблицы
- **users**(id PK, username UNIQUE, full_name, role ENUM('tech','dispatcher','central'),
  password_hash, ad_sid NULL, active bool, created_at)
- **predictions**(id PK, task, channel_id, object_id, bucket_ts timestamptz, p24, risk30,
  risk30_cal NULL, exp_days, score NULL, severity NULL, scale NULL, plan NULL,
  features_json jsonb NULL, model_version, created_at)
  Индексы: (task, bucket_ts), (object_id, task), (task, score desc)
- **decisions**(id PK, prediction_id FK, decision ENUM('confirm','reject','preventive'),
  responsible_id FK users, comment, created_at)  ← метки для дообучения
- **audit_log**(id, user_id FK, action, entity_type, entity_id, detail jsonb, created_at)
- **data_sources**(id, name, kind, last_load_start, last_load_end, rows, status, error)
- **models_registry**(id, task, version, model_path, calib_path, z_stats_path,
  trained_on, metrics_json, active bool)
- **object_risk_l2**(id, object_id, task, channel_count, risk30_max, risk30_mean,
  top_channels, updated_at) — материализация из `research/dataset/l2_object_risk.parquet`
- **maintenance_tasks**(id, task, channel_id, object_id, plan_bucket, score,
  due_from, due_to, status, assigned_to FK NULL, created_at)
- **settings**(key, value jsonb) — пороги топ-K, границы плана (exp_days<7 / <21 / >21)

### 6.2 Карточка прогноза (`GET /forecasts/{id}`) — обязательный сценарий
объект, инж. система (справочники), канал, тип риска, **вероятность события**,
горизонт (exp_days + точки S(t): 6ч/12ч/24ч/48ч/7д/14д/30д), уровень риска,
факторы «почему» (features_json), сезон/календарь, последние события канала,
рекомендуемое действие + **превентивная заявка** (from maintenance-plan),
история решений; кнопки «подтвердить/отклонить/профилактика».

## 7. Авторизация, аудит, безопасность

- **RBAC** по ролям (нужно §6.1); middleware проверяет JWT + разрешения;
  tech — только объекты своего района + «подтвердить состояние на объекте».
- **Аудит**: все действия пишутся в `audit_log` (обязательно: decision, login,
  admin-actions). Аудит журнал отсутствует → нельзя сдавать демо (SERVICE_PLAN §3).
- **TLS 1.2+**: termination на reverse-proxy или ключи Uvicorn.
- CORS для frontend, rate-limit на /auth/login, секреты в `.env`.
- LDAP/AD через read-only адаптер; на MVP — локальные пользователи (имитация).

## 8. Форматы и примеры

### 8.1 Создание прогноза (фоновый воркер, не пользовательская ручка)
```json
{"task":"fire","channel_id":"...","object_id":5961,"bucket_ts":"2026-09-20T00:00:00Z",
 "p24":0.03,"risk30":0.31,"risk30_cal":null,"exp_days":12.4,"score":0.26,
 "severity":0.85,"scale":1.25,"plan":"следующий квартал","model_version":"v0-2026-09-20"}
```

### 8.2 POST /forecasts/{id}/decision
```json
{"decision":"confirm","responsible":"ivanov.od","comment":"выявлено задымление, направлена бригада"}
```
→ 200 `{"ok":true,"prediction_id":123}` + запись в `decisions` и `audit_log`.

### 8.3 GET /top-risks
```json
{"task":"wear","k":200,"items":[
 {"ид_канала_данных":"...","бакет":...,"дата":"2026-09-20","тип_датчика":"Состояние насоса",
  "severity":0.8,"scale":1.0,"risk30":0.95,"risk_used":0.95,"exp_days":6.4,
  "score":0.76,"plan":"текущий квартал","p24":0.4,"event_flag":1,"obs_days":3.1}]}
```

## 9. SLA/производительность
- inference одного объекта (признаки+модель) ≤ 300 с (фактически < 1 с при готовой панели);
- обработка потоковой пачки данных ≤ 300 с (инкрементальная панель);
- ≥ 20 одновременных пользователей (async endpoints, пул соединений, uvicorn workers);
- прогноз пересчитывается на актуальном бакете (каждые 6 ч) фоновым воркером;
- drift-мониторинг — ежеквартально (/admin/drift) + накопление процентилей p24/risk30.

## 10. Порядок развёртывания (чек-лист backend)
1. Установить `services/.venv` (requirements.txt), `PostgreSQL 12+`, `alembic upgrade head`;
2. Скопировать/симлинк `research/models` и `research/inference_contract.py`
   (или `sys.path` на research) — пути из `models_registry`/`.env`;
3. Импорт `inference_contract` протестировать: `ic.load_model("fire")`,
   `ic.predict_risk(m, subjects)` на паре строк панели;
4. Сгенерировать реестр z-статистик (§3.1) и прошить в конфиг;
5. Поднять API: `uvicorn app.main:app --host 0.0.0.0 --port 8000` + reverse-proxy TLS;
6. Прогнать чек-лист API_CONTRACT.md (валидный JSON, данные согласуются с
   `docs/RISK_PIVOT_REPORT.md`), сквозной сценарий §6.2;
7. Наполнить users (демо-роли), включить audit; при готовности — LDAP-адаптер.

# Основной принцип

Строить не демо из заглушек, а минимальный, но реально работающий end-to-end сервис, который можно постепенно расширять.
