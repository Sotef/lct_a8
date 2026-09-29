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
| GET | /maintenance/tickets | task?, status?, object_id?, order=due\|new, q?, limit | заявки/график работ | dispatcher, central, tech |
| POST | /maintenance/tickets | {prediction_id, assign, comment, scheduled_at} | заявка (+дата выезда) | dispatcher, central |
| PATCH | /maintenance/tickets/{id} | {status, comment, scheduled_at} | смена статуса/даты | dispatcher, central, tech |
| GET | /forecasts/{id}/factors | — | топ-фичи «почему» | dispatcher |
| POST | /forecasts/{id}/decision | {decision, responsible, comment, scheduled_at} | {ok} + audit (дата выезда — для «профилактики») | dispatcher, central |

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
- **predictions**(id PK, task, channel_id, object_id, bucket_ts timestamptz, p24, p72,
  **p7d** NULL (P(событие ≤ 7 дней), §11.12), risk30,
  risk30_cal NULL, exp_days, score NULL, severity NULL, scale NULL, plan NULL,
  **age_days** NULL (возраст: первая запись датчика, §11.2), **norm_due** NULL
  (нормативный срок ТО), **plan_date** NULL (min(прогноз, норматив)), **campaign** 0/1
  (кампанийная неделя ППР/аномалии),
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
  due_from, due_to (**дата плана = min(прогноз, норматив)**, §11.2),
  **scheduled_at** NULL (дата выезда диспетчера, §11.13), status,
  assigned_to FK NULL, created_at, **age_days** / **norm_due** (обоснование плана),
  **rationale** TEXT (JSON: прогноз/норматив/возраст/severity/порог/кампания))
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
  admin-actions; также `incident.journal` — реальные происшествия журнала СМВУ,
  §11.2). Аудит журнал отсутствует → нельзя сдавать демо (SERVICE_PLAN §3).
- **Происшествия ↔ панель**: срабатывания/неисправности бакета логируются логгером
  `incident` (вкладка «Система») и в `audit_log`; `GET /meta/events?recent_h=24`
  отдаёт недавние факты постоянно (поле `свежее`, `summary.recent`) — панель не
  «пропадает» на тиках (см. §11.2).
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
   для доступа из локальной сети удобнее `scripts/serve.py` — слушает `0.0.0.0`, печатает
   адреса (IP и имя машины) и подсказку по брандмауэру. SPA и API — один origin, поэтому
   домен не нужен: коллеги открывают `http://<IP-сервера>:8000`. Если порт закрыт —
   `netsh advfirewall firewall add rule name="LCT Predictive 8000" dir=in action=allow protocol=TCP localport=8000`
   (от администратора). Реальный домен — только через внутренний DNS + TLS на reverse-proxy;
6. Прогнать чек-лист API_CONTRACT.md (валидный JSON, данные согласуются с
   `docs/RISK_PIVOT_REPORT.md`), сквозной сценарий §6.2;
7. Наполнить users (демо-роли), включить audit; при готовности — LDAP-адаптер.

---

## 11. Реализовано сверх §5 (журналирование, заявки, веб-интерфейс)

Раздел дописан по факту реализации (Backend & Web Service Team, 27.09.2026).

### 11.1 Логирование и наблюдаемость
- `app/logging_setup.py`: консоль + JSON-lines файл `services/logs/app.log`
  (ротация) + кольцевой буфер в памяти; контекст `request_id`/`user`/`ip` через contextvars.
- `app/middleware.py` (чистый ASGI): `X-Request-ID` в ответе, access-лог каждого
  `/api/*` (`method path -> status (ms)`, пользователь из JWT без обращения к БД),
  медленные запросы (> `SLOW_REQUEST_MS`) и 401/403/429 — WARNING, 5xx — ERROR с трейсбеком.
- `services/audit_service.py`: единая запись аудита (ip + request_id в `detail`),
  чтение с фильтрами и статистикой. Новые события: `auth.logout`,
  `auth.login_failed`, `forecast.view`, `ticket.create`, `ticket.status`,
  `ticket.auto_generate`, `client.error`, `admin.data_load|replay|models_reload|bootstrap|set_user_active`.
- Новые ручки: `GET /audit` (dispatcher — только свои действия), `GET /audit/actions`,
  `GET /audit/stats`, `GET /admin/logs?after_id=` (инкрементальный хвост),
  `GET /admin/logs/file`, `POST /logs/client` (ошибки веб-интерфейса),
  `GET /admin/system` (сводка состояния, модели, сим-часы, размер лога),
  `POST /auth/logout`, `POST /auth/admin/users/{id}/active`.

### 11.2 Модуль превентивных заявок (maintenance_tasks)
Полное изложение приоритизации и анти-прыжков — корневой `README.md` §8.

- `maintenance_service.py`: `auto` (на каждом тике сим-времени), `decision`
  (решение «профилактика»), `manual`. Дедупликация: одна открытая заявка на канал × направление.
- Статусы `suggested → assigned → in_progress → done` (+ `cancelled`), переходы
  валидируются на сервере (409), техник — только взять в работу / закрыть.
- **Дата плана**: `due_to = min(бакет + clamp(exp_days, 1, 90), norm_due)`, где `norm_due` —
  ближайшая дата ТО по периодичности (`to_norm.py`, 180/365 дней по типу датчика) от
  **первой записи датчика** (`channel_meta.py` + `data/channel_first_seen.csv`; реестр
  оборудования не используется). Приоритет — по risk30/p72 и горизонту плана.
- **Приоритизация auto**: порог вероятности свой на направление
  (`AUTO_TICKETS_MIN_RISK_BY_TASK`) и ослабляется по severity
  (`eff = base × AUTO_TICKETS_SEVERITY_REF / severity`); ёмкость — `AUTO_TICKETS_TOP_K`
  новых за тик + `AUTO_TICKETS_NEAR_CAP` открытых near-term на направление;
  бакеты `campaign=1` пропускаются.
- **Анти-прыжки**: гистерезис `PLAN_HYSTERESIS_DAYS` для `suggested`-заявок без
  `scheduled_at`; заявки с датой от диспетчера или статусом ≠ `suggested` модель не двигает.
- Ручки: `GET /maintenance/tickets|summary`, `POST /maintenance/tickets`,
  `PATCH /maintenance/tickets/{id}`, `POST /maintenance/auto-generate`; график
  (`order=due`) в UI группируется по «выездам» (объект × дата).
- Отказ диспетчера в карточке прогноза закрывает предложенную авто-заявку по каналу.

### 11.3 Веб-интерфейс
Полностью переработан (см. `FRONTEND.md`): 9 разделов с RBAC, палитра команд
`Ctrl+K`, уведомления о высоком недельном риске (`p7d ≥ 0.2`, тишина 12 ч на датчик),
канбан заявок с drag&drop и датой выезда, график обслуживания, журнал аудита,
live-хвост системного лога, карта-радар и граф систем (раскраска по выбранному
направлению за 7 дней), три темы, `prefers-reduced-motion`, живой canvas-фон
со регулировкой скорости/отключением. Внешних библиотек и CDN нет.

**Модель обновления страницы (важно для правок UI).** Разделы собираются в
offscreen-фрагмент (`UI.stage()`) и попадают в живой контейнер одним вызовом
`UI.mount(host, staged, {merge})`:
- `merge=false` — `replaceChildren` (атомарная замена, «пустого кадра» нет);
- `merge=true` — обход дерева с обновлением **только изменившихся узлов**
  (смена направления, фильтры, тик сим-часов), новые значения мягко подсвечиваются
  классом `.lv-flash`. Признак «раздел уже смонтирован» — `host.dataset.mounted`.
- узлы с атрибутом **`data-keep`** (график тренда, график обслуживания, лента
  действий) морфинг не трогает: асинхронная отрисовка не «пропадает» на время
  пересчёта, прошлые данные видны до прихода новых.

Что это даёт: при переключении ползунков и на каждом тике страница не «мигает»
целиком — обновляются только поля с данными, сохраняются фокус в полях фильтров,
скролл и позиции карточек. Требования к коду раздела: собирать DOM в `F = UI.stage()`,
не чистить `host.innerHTML`, менять состояние через module-level переменные и
перерисовываться молча (`render(main, state, true)`), а идентификаторы читать из
`dataset` в момент клика (иначе при морфинге останутся старые замыкания).
Исключения (пересобираются целиком, `merge:false`): граф систем (force-layout держит
ссылки на узлы), карта-радар в «Объектах», разделы «Система», «Аудит», «Пользователи».

### 11.4 Новые переменные окружения
`LOG_DIR`, `LOG_LEVEL`, `LOG_JSON`, `LOG_FILE_MAX_MB`, `LOG_FILE_BACKUPS`,
`LOG_BUFFER_SIZE`, `SLOW_REQUEST_MS`, `AUTO_TICKETS`, `AUTO_TICKETS_MIN_RISK`,
`AUTO_TICKETS_MIN_RISK_BY_TASK`, `AUTO_TICKETS_SEVERITY_REF`, `AUTO_TICKETS_TOP_K`,
`AUTO_TICKETS_NEAR_CAP`, `PLAN_HYSTERESIS_DAYS`, `PLAN_FORECAST_CAP_DAYS`
(см. `.env.example` и корневой `README.md` §8).

### 11.6 Реплей данных: цикл и управление
Период реплея конечен (01.01.2026…30.06.2026), поэтому добавлено:
- `SIM_LOOP=1` — по достижении конца периода реплей автоматически начинается заново
  с `SIM_START` (сброс прогнозов/решений/заявок, запись в лог и аудит);
- `simclock.reset()/pause()/resume()/step(n)` + ручки `POST /admin/clock/reset|pause|resume|step`
  (роль `central`), события `admin.clock_*` в аудите;
- `GET /meta/clock` дополнен полями `bucket_start`, `start_ts`, `progress`, `paused`, `loop`;
- в UI — карточка часов с прогрессом периода и кнопками «Заново с января / Пауза / Шаг +6 ч»,
  чип в шапке показывает «⏸» и процент пройденного периода.

### 11.7 Скорость демо-прокрута и SHAP «по запросу»
- `POST /admin/clock/speed` (`level` 1×/2×/4×/8× = 75/40/20/10 с, либо `tick_sec`,
  плюс `fast`, `parallel`), `GET /admin/clock/speed`; параметры хранятся в
  `settings.sim_options` и переживают рестарт; события `admin.clock_speed` в аудите.
- Замер (`tests/bench_tick.py`, 16 ядер, 4 задачи, ~540 каналов/бакет):
  с SHAP тик ≈114 с, без SHAP ≈0.6 с; параллельность выигрыша не даёт
  (SHAP сам грузит все ядра). Отсюда основной тумблер — «быстрый расчёт».
- В быстром режиме SHAP-факторы считаются по запросу для конкретного прогноза:
  `GET /forecasts/{id}/factors?compute=true` (≈1 с на один канал) с сохранением
  результата; в UI — кнопка «Рассчитать факторы» в карточке.
- `SHAP_TOP_K` (env, по умолчанию 400) — сколько каналов на задачу получают
  факторы на тике.

### 11.8 Проверки фич на лету (без утечки будущего)
`tests/test_replay_features.py`: окна панели и **признаки, подаваемые в модель**,
для бакета N идентичны при кэше ≤N и ≤N+130 бакетов; `z_событий` пересчитан строго
по train-статистикам; в X_cols нет future-колонок (цели, `дни_до_серии`,
`_next_start_bucket`); `subject_features` == схема обучения; `p24 = 1−S[3]`,
`risk30 = 1−S[−1]`, `exp_days = ΣS/4`, повторный расчёт детерминирован.
Плюс `tests/check_panel_coverage.py` — панели покрывают сырой кэш (иначе тик
пройдёт без субъектов; на этот случай в лог пишется предупреждение).

### 11.10 Правки по итогам приёмки интерфейса (27.09.2026)
- **Кнопки-«гиганты»**: класс `.ghost` (контейнер графа) совпадал с модификатором
  кнопок `.btn.ghost` — все ghost-кнопки получали `height: 660px`. Контейнер графа
  переименован в `.graph-host`. Проверено в браузере: кнопок выше нормы 0 во всех
  разделах (`/__probe.html?audit=1`).
- **«Тихое» обновление разделов** (live-обновления, ползунок направлений, кнопки
  горизонтов, обновление по тику сим-часов) **дописывало** содержимое вместо замены:
  разделы дублировались, из-за чего казалось, что переключатели не работают.
  Теперь контейнер всегда очищается, а анимации появления выключаются классом
  `.quiet`.
- **Роутер**: вставка контейнера раздела зависела от callback View Transitions —
  при быстрых переходах раздел мог не попасть в DOM, а поздний callback прошлой
  навигации вставлял устаревший раздел поверх текущего. Вставка сделана
  синхронной, устаревшие вставки отбрасываются, внешние триггеры (ползунок задач,
  сим-часы) используют явную ссылку на контейнер (`state.box`).
- **Модалка подтверждения** (выход из системы, перезапуск реплея): затемнение имело
  `z-index: 40` и перекрывало диалог (`z-index: 1`) — «размытая плитка, кнопки не
  нажимаются». Затемнение внутри оверлея опущено на `z-index: 0`.
- **Тренд риска**: `GET /meta/risk-history` получил параметр
  `measure=risk30|p24|p72|p7d` (30/1/3/7 дней; `p7d` считается из `surv_points`),
  в карточке появились переключатель горизонта, тумблер «максимум» (максимум по
  каналам часто «прибит» к 100% и зашумляет среднее), ось в процентах и текущее
  значение. Значения разных горизонтов проверяются в `tests/smoke_new_api.py`.
- **Устойчивость тренда (когорта)**: средний риск бакета считался «по всем» каналам, а их
  состав скачет (в демо 16…1146), причём «холодный» канал (появился впервые) даёт risk30 ≈ 1.0 —
  кривая «пилила» и на каждом тике выглядела новой. Теперь `avg_risk` — среднее по
  **«постоянной когорте»** (каналы, присутствующие в ≥ `cohort_share` бакетов окна, по умолчанию
  0,5), `avg_risk_all` — среднее по всем каналам бакета, добавлено поле `cohort_n`; параметр
  `cohort_share` настраивается. Средний шаг кривой падает в 2,5–4,6 раза
  (`tests/test_buttons_api.py::test_trend_cohort_ignores_cold_channels`).

### 11.11 Проверки
`pytest tests` (38 тестов, включая `test_logging_maintenance.py` и
`test_schedule_features.py`), `tests/check_new_features.py` (живая проверка даты
обслуживания, графика работ, `risk7d`/`p7d`), `tests/smoke_new_api.py`,
`tests/ui_contract_check.py` (3 роли × разделы + закрытые ручки),
`tests/front_contract_check.py`, `node tests/front_static_check.mjs`,
`powershell -File tests/web_smoke.ps1 [-WithTimers]` (headless-браузер: все разделы,
карточки, решения, drag&drop, карта, live-лог, 0 ошибок JS).

### 11.12 Горизонт 7 дней (`p7d`) — один источник для алертов, графа и тренда
- **Колонка БД** `predictions.p7d` = 1 − S(7 дней) (28-й шаг 6ч-сетки, индекс 27).
  Заполняется на тике вместе с `p24`/`p72`; читается SQL-агрегацией (быстро).
  Лёгкая миграция в `database._ensure_columns`, разовый бэкфилл старых строк —
  `tests/backfill_p7d.py` (считает из `surv_points`, если колонки ещё не было).
- **API-поля**: `p7d` в элементах `/top-risks`, `/forecasts`, `/forecasts/{id}`
  (и во всех списках, собранных `_pred_to_item`); `GET /meta/risk-history?measure=p7d`
  — тренд по недельному риску (avg/max по бакетам).
- **`risk7d` в графе**: `GET /objects/graph` дополнительно отдаёт по каждому объекту
  `risk7d: {task: max(p7d по каналам)}` за последние 12 бакетов (3 суток сим-времени) —
  чтобы объект попадал в раскраску, даже если в самом свежем бакете его каналы молчали.
  Объекты без прогнозов за 7 дней отдаются пустыми (`{}`) — UI рисует их «полой» точкой,
  чужой риск не подставляется.

### 11.13 Дата обслуживания и график работ (заявки)
- **`maintenance_tasks.scheduled_at`** — назначенная диспетчером дата выезда
  (лёгкая миграция в `_ensure_columns`). В API-представлении заявки — `scheduled_at`
  и `plan_at = coalesce(scheduled_at, due_to)` (по нему строится график).
- **`POST /maintenance/tickets`** принимает `scheduled_at` и возвращает его в ответе;
  **`PATCH /maintenance/tickets/{id}`** принимает `scheduled_at` (можно менять дату,
  не меняя статус), пишет `scheduled_at` в `audit_log`.
- **`GET /maintenance/tickets`**: новые параметры `object_id` (график работ объекта) и
  `order=due|new` (`due` — сортировка по `coalesce(scheduled_at, due_to)`, для графика
  обслуживания), лимит до 2000.
- **`POST /forecasts/{id}/decision`** принимает `scheduled_at`: для решения
  «профилактика» дата сразу проставляется в заявке (существующая открытая заявка
  обновляется, дубль не создаётся).

### 11.14 Политика уведомлений диспетчера
Всплывающее уведомление показывается **только** когда пересчитанный недельный риск
датчика `p7d ≥ 0.2` **и** по этому датчику не было уведомления последние 12 часов
(журнал тишины `mc_notify_log` в localStorage, ключ `task|channel_id`). Один тик — не
более 3 всплывающих, остальные копятся в панели. Первый опрос после входа только
расставляет отметки (чтобы не завалить диспетчера при открытии смены).
Клик по уведомлению открывает **карточку объекта** (`Cards.object.open`), для
приёмки есть `Notify.demo(n)`.

### 11.16 Перезапуск реплея НЕ удаляет человеческие данные
Ранее `simclock._fresh_start()` (используется автоперезапуском круга `SIM_LOOP=1` и
`POST /admin/clock/reset`) удалял `predictions` **вместе с** `decisions` и
`maintenance_tasks` — при демо-прогоне терялись решения диспетчера и заявки. Теперь:

| Что | Поведение при перезапуске круга |
|---|---|
| `predictions` | удаляются (воспроизводимы, пересчитываются с `SIM_START`) — кроме «закреплённых» |
| решения (`decisions`) | **сохраняются**; их прогнозы помечаются `predictions.pinned=1` и не удаляются |
| заявки, которых коснулся человек (назначены, в работе, выполнены, отменены, созданы вручную или решением «профилактика», с датой выезда/исполнителем/комментарием) | **сохраняются** (у них снимается ссылка `prediction_id`, риск/срок/план остаются в самой заявке) |
| необработанные предложения автоформирования (`source='auto'`, `status='suggested'`, без исполнителя/даты/комментария) | удаляются — модель формирует их заново (иначе дубли блокировали бы новые предложения по тем же каналам) |
| `audit_log` | никогда не удаляется |

`predictions.pinned` (лёгкая миграция, `INTEGER DEFAULT 0`) + `models_db.current_only()`
исключают строки-метки из всех запросов «текущего бакета»: `latest_bucket_ts`,
summary/KPI, топ-риски, история (`/meta/risk-history`, `/meta/channel-history`,
`/meta/bucket-dates`, `/meta/buckets`), `/forecasts`, `risk7d` объектов, последние
события канала. При пересчёте того же бакета закреплённые строки тоже не затираются.

Восстановление данных, потерянных прежней версией (журнал аудита цел):
`tests/inspect_audit_tickets.py` — что известно по заявкам/решениям;
`tests/restore_tickets_from_audit.py` — dry-run/`--apply` восстановление последнего
**зафиксированного в аудите** состояния заявок (статус, автор, комментарий, время;
неизвестные поля не выдумываются, восстановленные строки помечены в комментарии).
Живая проверка инварианта — `tests/check_replay_safety.py` (создать заявку →
`/admin/clock/reset` → заявка, статус и дата на месте; бакет снова январский).

`GET /objects` отдаёт по каждому объекту `risk7d: {task: P(событие ≤ 7 дней)}`
(максимум по каналам за 12 последних бакетов) — его используют список, карта-радар,
фильтры, сортировка и счётчик «с недельным риском ≥ 0.5»; `risk30` остаётся только
в подсказках как L2-ориентир. `GET /maintenance/summary` дополнительно отдаёт блок
`auto` (`enabled`, `min_risk`, `top_k`) — из него UI строит пояснение к кнопке
«Сформировать заявки». Статика UI (`/js/*`, `/css/*`, `/`) отдаётся с
`Cache-Control: no-cache`, чтобы после обновления сервиса браузер не держал старый JS.
