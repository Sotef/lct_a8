# Предиктивный сервис АО «Москоллектор» — Backend & Web Service Team

MVP-сервис предиктивной аналитики: потоковые/исторические данные журнала СМВУ →
6-часовые панели → признаки моделей (идентичные обучению) → прогнозы
(fire/access/sensor/wear) → диспетчерский REST API + карточка риска, план ТО,
решения (обратная петля ground-truth) и аудит.

ML-логика не пишется в эндпоинтах: она инкапсулирована в `research`
(`features.py`, `tte_pipeline.py`, `inference_contract.py`) и подключается
как библиотека (см. `app/research_bridge.py`).

## Самый простой запуск (Docker, 3 команды)

Сервис целиком (PostgreSQL 12+ + API + SPA/PWA) поднимается в Docker — Python,
venv и локальная БД не нужны:

```powershell
cd services
copy .env.docker.example .env        # bash: cp .env.docker.example .env
docker compose up -d --build
```

Готово, когда `docker compose ps` показывает `api ... (healthy)`:

| Что | Адрес |
|---|---|
| SPA (диспетчер/техник) | http://127.0.0.1:8000/ |
| Swagger | http://127.0.0.1:8000/docs |
| HTTPS (профиль `tls`, TLS 1.2+) | https://127.0.0.1:8443/ |

Вход: `central.operator` / `central123` (центральный диспетчер),
`dispatcher.alpha` / `alpha123`, `tech.alpha` / `tech123`.

Проверка развёртывания (API по ролям + PWA-раздача) —
`docker compose exec -T api python scripts/verify_deploy.py`.
Остановить: `docker compose down`; «с нуля»: `docker compose down -v && docker compose up -d --build`.

Из клона всё нужное для прогнозов уже есть (~33 МБ в git): модели
(`research/models/tte_*_discrete_hazard.cbm`, `calib30_access.pkl`), справочники
(`research/dataset/справочник_*.csv`) и raw-кэш (`services/data/raw/buckets_2026.parquet`).
Панели 6ч в git не хранятся — они пересобираются из raw-кэша на первом запуске
(`feature_pipeline.build_subjects`). Тяжёлые исходные журналы СМВУ (~16 ГБ) нужны только
для `POST /admin/data/load` (загрузка новых данных) или переобучения.

Полный разбор (переменные, тома, TLS, эксплуатация) — раздел
[«Docker: развёртывание всего сервиса»](#docker-развёртывание-всего-сервиса-postgresql-12--api-spa--tls) ниже.

## Тест на мобильных (телефон/планшет)

| Что проверяем | Как |
|---|---|
| Вёрстка и сценарии на реальном телефоне | `ipconfig` → на телефоне в той же сети открыть `http://<IP>:8000`; при необходимости разрешить порт: `netsh advfirewall firewall add rule name="LCT 8000" dir=in action=allow protocol=TCP localport=8000` |
| Установка PWA, офлайн-очередь, Web Push | нужен *secure context*: `http://127.0.0.1:8000` + DevTools device mode (localhost безопасен) **или** `https://<IP>:8443` с **доверенным** сертификатом |
| Автотест мобильного профиля | `docker compose cp app/web/__mprobe.html api:/workspace/services/app/web/__mprobe.html` → открыть `http://127.0.0.1:8000/__mprobe.html?stub=1` (отчёт `MPROBE OK`) |
| Приёмка по экранам (26 пунктов) | `MOBILE_PLAN.md` → Приложение C |

По `http://<IP>` включится только сам UI: origin небезопасный, поэтому service worker,
установка приложения, офлайн-очередь и push выключены. Уведомления запрашиваются в
«Ещё» → «Включить уведомления» (нужны `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`; без них
алерты приходят через фолбэк-поллинг `GET /alerts`).


## Живая подача из журнала (SIM_FEED=1) — «как в реальной работе»

По умолчанию демо идёт по предзагруженной панели: данные 2026 один раз переработаны в
`data/raw/buckets_2026.parquet` + `data/panels/*.csv`, а сим-клок лишь двигает «сейчас».
Чтобы сервис **сам читал грязный журнал и считал всё на лету**, включите подачу:

```bash
# services/.env  (или переменная окружения в контейнере)
SIM_FEED=1
docker compose up -d api        # Docker; локально — как обычно
```

Цикл одного тика в этом режиме:

```
ext-journal-<год>.csv ──ленивое чтение порциями (SIM_FEED_CHUNK)──► только «наступившие»
 6ч-бакеты ──► data/stream/raw/buckets_<год>.parquet ──► пересборка признаков задач
 (research features.make_subdaily_panel + z по train-статистикам + серии) ──►
 CatBoost.predict_proba на текущем бакете ──► авто-заявки ──► алерты (журнал/push)
```

Что видно в логах и в API:
- `stream feed: бакет … — прочитано N строк, принято M, кэш K строк, max_ts …` — сколько
  «сырых» строк пришло и превратилось в агрегаты за тик;
- `GET /api/v1/meta/clock` → блок `feed`: `enabled`, `source`, `cache_dir`, `panel_dir`,
  `rows_due`, `cache_rows`, `max_ts`, `eof`, `chunksize`.

Параметры и особенности:
- `SIM_FEED_CHUNK` (200 000) — размер порции чтения. Файл читается **один раз
  последовательно** (`pd.read_csv(chunksize=…)`), «будущие» строки буферизуются и отдаются
  на следующих тиках — то есть данные приходят как поток, а пейсинг задают сим-часы;
- `SIM_FEED_WARMUP=1` — перед первым прогнозом догружает журнал до `SIM_START`, чтобы
  признаки были «тёплыми»; данные после `SIM_START` не берутся (никакого заглядывания вперёд);
- `SIM_FEED_END` — конец периода подачи; пусто → определяется по последней строке журнала;
- `SIM_FEED_REBUILD=1` — признаки пересобираются на каждом тике (в подаче обязательно);
- состояние подачи изолировано от демо-кэша: `services/data/stream/{raw,panels}` (в git не попадает);
- «холодные» бакеты — норма: если у задачи ещё нет событий/типов каналов, панель не
  строится (в логе `признаки пока не собираются (мало данных)`), прогноз появится, когда
  данных накопится достаточно (например, задача `access` в самом начале периода);
- стоимость тика: агрегация 6ч-хвоста ≈0,2–0,3 с; пересборка панелей растёт вместе с
  историей (единицы–десятки секунд), поэтому тик может занимать до ~1–2 минут — SLA
  «пачка данных/инференс ≤ 300 с» соблюдён. Сим-часы ждут окончания расчёта
  (`effective_tick_sec` в `/meta/clock`);
- при `SIM_LOOP=1` новый круг стартует «с чистого листа»: кэш подачи и панели сбрасываются.

Режим реального времени (без реплея): `SIM_CLOCK=0`, `RUN_SCHEDULER=1`, `SIM_FEED=1` —
каждые 6 часов сервис дочитывает хвост журнала (инкрементально, по чекпоинту `max_ts`) и
пересчитывает прогнозы.

> Требуется исходный журнал `research/dataset/extracted/ext-journal-<SIM_YEAR>.csv`
> (в git его нет — ~16 ГБ всех лет). В Docker он приходит из read-only тома
> `../research:/workspace/research`.

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

### Доступ из локальной сети (другая машина в той же сети)

SPA и API отдаются **одним origin**, поэтому отдельный домен не нужен — достаточно
адреса сервера. По умолчанию uvicorn слушает только `127.0.0.1`, с других машин он
недоступен; запускайте через `scripts/serve.py` (слушает `0.0.0.0` и печатает адреса):

```powershell
services\.venv\Scripts\python.exe scripts\serve.py            # 0.0.0.0:8000 + список адресов
services\.venv\Scripts\python.exe scripts\serve.py --port 8080
services\.venv\Scripts\python.exe scripts\serve.py --firewall  # добавить правило (нужны права админа)
```

Адрес для коллег: `http://<IP-сервера>:8000` (например `http://192.168.31.217:8000`) или,
если в сети разрешаются имена, `http://<имя-машины>:8000`. `HOST`/`PORT` можно задать и
в `.env`. Если с других машин не открывается — откройте порт (PowerShell от админа):

```powershell
netsh advfirewall firewall add rule name="LCT Predictive 8000" dir=in action=allow protocol=TCP localport=8000
```

Настоящий «домен» потребует внутреннего DNS (A-запись на IP сервера) и, для HTTPS,
сертификата (TLS-терминация на reverse-proxy); для локальной сети это не обязательно.

### Режим реплея (симулируемые часы)
По умолчанию сервис живёт в режиме **реплея данных 2026 года**: симулируемое
«сейчас» стартует **01.01.2026 00:00** и продвигается шагами по 6 ч — все 4 задачи
пересчитываются, KPI/тренд/журнал/заявки растут в реальном времени. Текущее
сим-время — чип `⏱` в шапке UI и `GET /api/v1/meta/clock`.

**Скорость прокрута управляется из UI** (раздел «Система → Обзор», карточка часов):

| Уровень | Интервал тика | Полный проход (янв→июн) |
|---|---|---|
| 1× | 75 с | ~15 ч (с SHAP) |
| 2× | 40 с | ~8 ч |
| 4× | 20 с | ~4 ч |
| 8× | 10 с | ~2 ч |

- тумблер **«быстрый расчёт: без SHAP-факторов»** — главный ускоритель: SHAP
  занимает ≈99.5% времени тика (≈43 с на задачу), без него тик идёт **0.6 с**
  (замер: `tests/bench_tick.py`, 16 ядер). Факторы при этом считаются **по
  запросу** для конкретной карточки (кнопка «Рассчитать факторы», ≈1 с) и
  сохраняются в прогнозе;
- тумблер «параллельный расчёт задач» — обычно не помогает (SHAP и так грузит
  все ядра), полезен только в быстром режиме;
- период реплея конечен (01.01–30.06.2026, ~724 бакета), поэтому `SIM_LOOP=1`
  (по умолчанию) — дойдя до конца, реплей начинается заново с 01.01.2026
  (прогнозы/решения/заявки круга сбрасываются, событие пишется в лог и аудит);
- ручное управление: `POST /admin/clock/reset` (заново с января),
  `/admin/clock/pause`, `/admin/clock/resume`, `/admin/clock/step?n=1` («+6 ч»),
  `/admin/clock/speed` (`level`, `fast`, `parallel`), `GET /admin/clock/speed` —
  только роль `central`, все действия в аудите;
- первый тик после рестарта «холодный» (модели, панели, субъекты) — до минуты,
  дальше тики идут в темпе режима.

`SHAP_TOP_K` (по умолчанию 400) ограничивает, для скольких каналов на задачу
считаются факторы на тике: уменьшение ускоряет прокрут, но карточки каналов ниже
топ-N будут без факторов (досчитываются по запросу).

Отключение реплея: `SIM_CLOCK=0` (+ `RUN_SCHEDULER=1` для 6ч-цикла по реальному времени).
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

`tests/test_schedule_features.py` — дата выезда в заявках (создание/перенос),
график обслуживания (`order=due`, фильтр `object_id`), поле `p7d`
(P(событие ≤ 7 дней), колонка + откат на S(t)), `risk7d` в `GET /objects`/`/objects/graph`
и сохранность человеческих данных при перезапуске реплея.
`tests/check_new_features.py` — то же на живом сервере (быстрая приёмочная проверка
после деплоя). `tests/check_replay_safety.py` — живая проверка инварианта
«перезапуск круга не теряет решения и заявки». `tests/backfill_p7d.py` — разовый
бэкфилл `predictions.p7d` для прогнозов, посчитанных до появления колонки.
`tests/inspect_audit_tickets.py` и `tests/restore_tickets_from_audit.py [--apply]` —
разовый анализ журнала аудита и восстановление заявок, потерянных прежней версией
перезапуска реплея.

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
без сборки и без CDN). Подробно — `FRONTEND.md`. Кратко:

| Раздел | Роль | Что внутри |
|---|---|---|
| Пульт | все | KPI по 4 направлениям с count-up, тренд риска (**горизонт 1/3/7/30 дней** + тумблер «максимум»), топ-риски (объекты/датчики, горизонт 24 ч/72 ч/30 дн), донат заявок, лента аудита |
| Объекты | все | список с сортировкой/фильтрами + карта-радар (SVG, зум/пан, пульс высокого риска); риск = **максимум P(событие ≤ 7 дней)** по каналам (L2 risk30 — в подсказках) |
| Граф систем | диспетчер, central | force-layout объектов ↔ пикетов, подсветка соседей, зум |
| Журнал прогнозов | все | фильтры, сортировка по столбцам, CSV, карточка прогноза (gauge, S(t), «когда ожидать», SHAP, решения, заявка) |
| План ТО | все | «горизонт × тип канала», фильтр по кварталу, автоформирование заявок |
| Заявки | все | канбан с **drag&drop** смены статуса, карточка заявки, комментарии, аудит |
| Аудит | диспетчер, central | журнал действий с фильтрами, деталями (request_id, ip), статистикой, CSV |
| Система | central | состояние сервиса, модели, источники, live-хвост системного лога, скачивание лог-файла, **управление реплеем** (заново с января / пауза / шаг +6 ч), **«Фон и анимации»** (скорость частиц/выключение, импульсы) |
| Пользователи | central | создание, роли, блокировка (всё в аудите) |

> **Планируется:** мобильная версия (адаптив + PWA: офлайн-очередь действий, фото, Web Push) —
> подробный план реализации, оценки и чек-лист приёмки: `services/MOBILE_PLAN.md`.

Возможности интерфейса: палитра команд `Ctrl+K` (разделы, направления, объекты,
заявки, темы, фон, действия), центр уведомлений о высоком **недельном** риске
(`P(≤7д) ≥ 0.2`, повтор не чаще 1 раза в 12 ч на датчик) — **клик по уведомлению
открывает сам объект**; симулируемые часы с прогрессом до следующего тика,
`prefers-reduced-motion`, смена темы с круговым reveal. Кнопка «Сформировать заявки»
перед запуском показывает, какие каналы попадут в план, порог риска и лимит за
запуск (данные из `GET /maintenance/summary`), после — число созданных заявок.
В канбане при снятии галочки «показывать отменённые» оставшиеся колонки занимают
освободившуюся ширину.

**Обновления без перезагрузки страницы.** Разделы собираются offscreen и попадают
на экран одним вызовом: при переключении направлений/фильтров пустого кадра нет,
а тик сим-часов обновляет **только изменившиеся поля** (числа мягко подсвечиваются,
карточки не пересобираются, фокус и скролл сохраняются). Регулировка фона («сеть
коллекторов» за интерфейсом) — в «Системе» или через `Ctrl+K`: Выкл / 0.35× / 1× / 2×
и тумблер бегущих импульсов; выбор хранится в браузере.

**Три оформления** (переключатель в шапке/на логине, сохраняется в браузере):
`Obsidian` (тёмный глассморфизм, живой canvas-фон «сеть коллекторов»),
`Editorial` (светлый журнальный), `Terminal` (пульт диспетчера, моно, сканлайны).

> Координат объектов в данных нет — карта **схематичная** (секторы районов,
> позиция по хешу id, цвет = риск, размер = каналы); в UI есть пометка. Внешних
> библиотек и CDN нет вообще — контур полностью офлайн.

## Логирование

Структурное логирование: `app/logging_setup.py` + `app/middleware.py`.

- **Консоль** — человекочитаемо; **файл** `services/logs/app.log` — JSON lines с
  ротацией (`LOG_FILE_MAX_MB` × `LOG_FILE_BACKUPS`);
- **Кольцевой буфер в памяти** (`LOG_BUFFER_SIZE`) — live-просмотр в UI
  (`GET /admin/logs?after_id=`, инкрементально) и выгрузка файла
  (`GET /admin/logs/file`);
- каждый HTTP-запрос: `method path -> status (ms)` + `request_id` (заголовок
  `X-Request-ID` в ответе), пользователь из JWT, ip; медленные (> `SLOW_REQUEST_MS`)
  и 4xx (401/403/429) — WARNING, 5xx — ERROR с трассировкой;
- **журнал аудита** (`audit_log`) — входы/неудачные входы, выходы, решения по
  прогнозам, создание/смена статуса заявок, админ-действия, ошибки веб-интерфейса;
  каждая запись дополняется `ip` и `request_id`;
- **ошибки фронтенда** уходят в `POST /logs/client` (window.onerror,
  unhandledrejection, 5xx API) и видны в разделе «Система → Системный лог»
  (логгер `client`).

## Модуль превентивных заявок

`app/services/maintenance_service.py` + `app/api/maintenance.py`.

- **Источники заявок**: `auto` — каждые 6 ч сим-времени из прогнозов актуального
  бакета (`risk30 ≥ AUTO_TICKETS_MIN_RISK`, не больше `AUTO_TICKETS_TOP_K` на
  направление); `decision` — решение диспетчера «профилактика» в карточке;
  `manual` — `POST /maintenance/tickets`;
- **дедупликация**: одна открытая заявка на канал × направление;
- **жизненный цикл**: предложена → назначена → в работе → выполнена (либо
  отменена); переходы проверяются на сервере (409 при недопустимом), техник
  может только брать в работу и закрывать назначенные ему заявки;
- срок: `due_to = бакет + clamp(exp_days, 1, 30) дней`, приоритет по risk30/p72;
- `GET /maintenance/tickets|summary`, `POST /maintenance/tickets`,
  `PATCH /maintenance/tickets/{id}`, `POST /maintenance/auto-generate`.

## Проверка фронтенда

```powershell
cd services
node tests\front_static_check.mjs      # иконки, классы CSS, API-пути vs OpenAPI, экспорты модулей
.\.venv\Scripts\python.exe tests\dump_routes.py        # обновить tests/_routes.json (после правки API)
.\tests\ui_contract_check.py           # все разделы × 3 роли + закрытые ручки (нужен запущенный сервис)
.\tests\smoke_new_api.py               # аудит, логи, заявки, решения, система
powershell -File tests\web_smoke.ps1    # headless Edge/Chrome: все разделы, карточки, DnD, палитра, карта
powershell -File tests\web_smoke.ps1 -WithTimers   # то же с живыми сим-часами и поллингом

# развёртывание (Docker или локальный сервис): API по ролям + PWA-раздача
.\.venv\Scripts\python.exe scripts\verify_deploy.py
docker compose exec -T api python scripts/verify_deploy.py    # то же изнутри контейнера

# мобильный профиль: служебная страница не входит в образ — копируем в контейнер
docker compose cp app/web/__mprobe.html api:/workspace/services/app/web/__mprobe.html
#   затем откройте http://127.0.0.1:8000/__mprobe.html?stub=1  (отчёт MPROBE OK)
```

`tests/front_contract_check.py` — контракт фронт↔бэкенд (summary, risk-history,
top-risks с полями объекта, карточка с S(t)/factors, graph, decision).
Служебные страницы `app/web/__probe.html` и `app/web/__mprobe.html` — для headless-прогонов
(`web_smoke.ps1` и мобильного профиля); в образ они не попадают (`.dockerignore`),
для запуска в Docker их копируют `docker compose cp`.


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

## Docker: развёртывание всего сервиса (PostgreSQL 12+ + API/SPA + TLS)

Стек: `postgres` (14-alpine) + `api` (FastAPI/uvicorn + SPA + PWA) + опциональный
`proxy` (nginx с TLS ≥ 1.2). ML-артефакты и справочники `research/` подключаются
**read-only** и в образ не копируются (десятки ГБ исторических выгрузок СМВУ).

```bash
cd services
cp .env.docker.example .env          # Windows: copy .env.docker.example .env
docker compose up -d --build          # сборка образа + запуск postgres и api
# SPA:      http://127.0.0.1:8000/        Swagger: http://127.0.0.1:8000/docs
# проверка развёртывания (API по ролям + PWA-раздача):
docker compose exec -T api python scripts/verify_deploy.py
```

Что происходит при старте контейнера `api` (см. `scripts/docker-entrypoint.sh`):
1) ожидание `PostgreSQL` (`scripts/wait_for_db.py`, до `DB_WAIT_RETRIES`×2 с);
2) `scripts/seed.py` — схема (`init_db`) + демо-пользователи + реестр моделей (идемпотентно);
3) при `RUN_MIGRATIONS=1` — `alembic upgrade head`;
4) запуск `uvicorn` (CMD), образ имеет HEALTHCHECK на `/api/v1/health`.

### TLS 1.2+ (профиль `tls`)

```bash
# сертификат: положите tls.crt/tls.key в services/deploy/certs (см. README там же)
docker compose --profile tls up -d --build
# https://127.0.0.1:8443/   (HTTP :8080 -> 301 на HTTPS)
```
nginx ограничивает `ssl_protocols TLSv1.2 TLSv1.3`, отдаёт security-заголовки и
таймауты 300 с (SLA инференса/пакетов данных). Сертификаты в git не коммитятся.

### Переменные и тома
- Все настройки — `.env` (шаблон `.env.docker.example`) → подстановка `${VAR}` в `docker-compose.yml`.
  Compose намеренно **не** подмешивает dev-`services/.env` целиком (там Windows-пути).
- Тома: `pgdata` (БД), `../research` (ro, модели+справочники+журналы), `./data` (панели/raw/z-stats, вложения), `./logs`.
- Мобильный профиль/PWA настраивается `PWA`, `ALERTS_*`, `VAPID_*`, `ATTACH_MAX_MB` (см. MOBILE_PLAN.md, Приложение F).

### Эксплуатация

```bash
docker compose ps                     # статусы и healthcheck
docker compose logs -f api            # логи сервиса
docker compose restart api            # перезапуск API
docker compose down                   # остановить (данные в volumes сохраняются)
docker compose down -v                # остановить и удалить БД (демо «с нуля»)
docker compose build api && docker compose up -d api   # пересборка после правок кода
```

Замечания по окружению:
- Порт `8000` должен быть свободен: локальный (не-Docker) `uvicorn` на `0.0.0.0:8000`
  перехватывает запросы — остановите его перед `docker compose up`.
- `SIM_CLOCK=1` держите с `--workers 1` (один сим-часовой планировщик на процесс);
  для масштабирования воркеров переведите демо на реальное время (`SIM_CLOCK=0`).
- Версии зависимостей: `sqlalchemy>=2.0,<2.1` (в 2.1 меняется драйвер по умолчанию для `postgresql://`).

Локальная разработка без Docker — SQLite (default `DATABASE_URL`), прод — PostgreSQL 12+,
TLS 1.2+ на reverse-proxy, секреты в `.env`, журнал действий пользователей — `audit_log`.


## Метрики (research/final_metrics_v0.csv, holdout ≥ 2025-07, включая H1-2026)

Precision>0.7 и Recall>0.5 на топ-K по p24 (см. отчёты `research/models/tte_*_report.txt`);
прогноз на 6ч-сетке 30д (горизонт ≥ 24ч), время инференса одного бакета «канал×модель»
< 1 с на готовой панели (SLA ≤ 300 с).