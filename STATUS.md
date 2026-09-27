# Статус проекта lct_a8 — сводка готовности

Дата: 26.09.2026
Источники: `research/docs/*`, `research/models/*`, `services/*`, `research/dataset/final_metrics_v0.csv`, тесты сервиса.

## 1. Общая картина

End-to-end MVP **собран и рабочий**: research (данные → фичи → модели → инференс-контракт)
+ сервис (FastAPI + БД + SPA + JWT/RBAC + audit). Модели обучены для всех 4 направлений.

| Контур | Готовность | Комментарий |
|---|---|---|
| Research (данные, EDA, фичи, модели, контракт) | ~90% | все 4 модели + отчёты; слабые места объективны (нет внешних данных) |
| Service (backend + frontend + БД) | ~85% | полный E2E, тесты зелёные; прод-обвязка и внешние источники — не готовы |
| Готовность к демо | ✅ | сквозной сценарий «данные → прогноз → alert → карточка → решение → audit» работает (реплей 2026) |
| Буква ТЗ по метрикам (P>0.7, R>0.5) | 🟡 | строго проходит только **wear**; fire — топ-K с оговоркой; access/sensor — заблокированы |

Тесты сервиса: `services/.venv\Scripts\python.exe -m pytest tests -q` → **19 passed**.

## 2. Направления прогнозирования (ТЗ), holdout ≥ 2025-07 (20 000 субъектов)

| Направление | Статус | Метрики 24ч | Вердикт по ТЗ |
|---|---|---|---|
| **Износ инфраструктуры** (wear) | ✅ готово | PR-AUC 0.890; prec@50/100 = 1.0; **K@prec≥0.7 = 3035, recall 0.83**; risk30 PR-AUC 0.973; ECE 0.020 | **Выполняется** (рабочая точка P≈0.7, R≈0.83) |
| **Пожарный риск** (fire) | 🟡 частично | PR-AUC 0.421; prec@50=1.0, prec@100=0.97; K@prec≥0.7=152, **recall 0.35**; risk30 PR-AUC 0.486 | Precision ок, **Recall 0.35 < 0.5**; это «продолжение подтверждённого задымления», а не первое событие (аудит §21.6) |
| **Отказ датчика** (sensor) | 🟡→🔴 | PR-AUC 24ч 0.012 (база 0.3%); risk30 0.105; подтип «Датчик дыма»: PR30 → 0.184, PR24 → 0.063 | На 24ч **недостижимо** без журнала ОДС/истории ремонтов |
| **Несанкц. доступ** (access) | 🔴 | PR-AUC 24ч 0.030 (база 1.0%), prec@50≈0; risk30 PR-AUC 0.619, ECE 0.015 (калиброван) | На 24ч **недостижимо** без СКУД/журналов допусков (нет ground-truth) |

Слой «через сколько дней» (survival / discrete hazard): Uno-C 0.72–0.79, `exp_days`, S(t) —
работают; риск-портфель RBAM (`score = risk30 × severity × scale`), план ТО — сгенерированы.

> Переосмысленное ядро MVP (см. `research/docs/ML_PLAN.md (Часть III)`): отвечаем не «что сломается
> через 24ч», а «где риск сейчас и что в план ТО» (CBM + RBAM + RUL). «Буква ТЗ» —
> fallback-сценарий (`research/docs/TZ_COMPLIANCE_REPORT.md`).

## 3. Компоненты сервиса

| Компонент | Статус | Где |
|---|---|---|
| FastAPI API под `/api/v1` (auth, top-risks, maintenance-plan, forecasts, decision, objects, meta, admin, health) | ✅ | `services/app/api/*` |
| JWT + RBAC (3 роли: tech / dispatcher / central), audit_log, обратная петля `POST /decision` | ✅ | `services/app/security.py`, `api/auth.py`, `services/decision_service.py` |
| Веб-SPA (дашборд, объекты/карта, граф пикетов, журнал прогнозов с S(t)/SHAP, план ТО, 3 темы) | ✅ | `services/app/web/*` |
| feature_pipeline в сервисе (панель → z-stats train-only → серии → субъекты), ML как библиотека | ✅ | `services/app/services/feature_pipeline.py`, `research_bridge.py` |
| Workers: ingestion (6ч-бакеты, checkpoint), scheduler, реплей 2026 (сим-диспетчер) | ✅ | `services/app/workers/*` |
| Календарь ТО/ППР заказчика (парсер + недельный календарь) | ✅ | `research/planned_work.py`, `notebooks/33_planned_work_2026.ipynb` |
| Тесты (unit + front-contract + сверка с research) | ✅ 19 passed | `services/tests/*` |
| Валидация на потоке H1-2026 (wear prec@1000 0.986 / recall 0.51; fire/sensor/access — оговорены) | ✅ | `services/data/validate_2026_report.txt` |
| Docker + PostgreSQL 12+ (прод-контур) | ✅ (локально SQLite) | `services/docker-compose.yml`, `Dockerfile` |
| Адаптеры внешних данных (АРМ-Контроль, ОДС, СКУД, реестр оборудования) | 🟡 интерфейсы готовы, **данные не поставлены** (P2) | `services/app/adapters/*`, `research/docs/ADAPTERS_README.md` |
| LDAP/AD | 🟡 мок-имитация (прод — read-only адаптер) | `services/app/adapters/ldap.py` |
| TLS 1.2+ | 🟡 конфиг/reverse-proxy (на локали не включён) | `services/.env.example` |

## 4. Блокеры и открытые вопросы

1. **Нет внешних данных** — корень почти всех ограничений:
   - СКУД / журналы допусков → нет ground-truth по **access**;
   - журнал ОДС / история ремонтов → слабая метка по **sensor**;
   - АРМ-Контроль (сварочные/горячие работы) → полный **fire**-сценарий невозможен;
   - реестр оборудования (возраст, ремонты) → усиление **wear**.
2. **Нет маппинга «Объект N» ↔ `ид_объект`** (графики ТО/ППР РЭК 2026) — блокирует
   per-object маскировку окон ППР и синхронизацию модуля превентивных заявок с регламентом.
3. **Нет гео-координат** — карта в UI схематичная (помечено в интерфейсе).
4. **Нет формального определения «отказ», горизонта и протокола оценки** (скрытый тест) —
   влияет на интерпретацию метрик.
5. Прод-обвязка (PostgreSQL/TLS/LDAP) — не «боевая», root `README.md` до этого
   обновления был устаревшим по статусу сервиса.

## 5. Карта ключевых артефактов

| Что | Файл |
|---|---|
| Инференс-контракт (модель + калибровка + top-K + план ТО) | `research/inference_contract.py` |
| Модели (4 задачи, CatBoost .cbm) | `research/models/tte_{fire,access,sensor,wear}_discrete_hazard.cbm` |
| Holdout-предсказания и отчёты | `research/models/tte_{task}_holdout.parquet`, `tte_{task}_report.txt` |
| Финальные метрики | `research/dataset/final_metrics_v0.csv` |
| Риск-портфель RBAM | `research/docs/RISK_PIVOT_REPORT.md` |
| Соответствие «букве ТЗ» | `research/docs/TZ_COMPLIANCE_REPORT.md` |
| ML-план/статус/продуктовая рамка | `research/docs/ML_PLAN.md` (Части I–III) |
| Бэклог (не сделанное/блокеры) | `research/docs/BACKLOG.md`, `research/docs/OPEN_QUESTIONS.md` |
| Архитектура и использование | `ARCHITECTURE.md` |
| API-контракт для backend | `research/docs/API_CONTRACT.md`, `services/BACKEND_SPEC.md` |
| Календарь ТО/ППР заказчика | `research/planned_work.py`, `research/notebooks/33_planned_work_2026.ipynb` |

## 6. Быстрый запуск (демо)

```powershell
# сервис (локально, SQLite)
cd services
.venv\Scripts\python.exe scripts\seed.py
.venv\Scripts\python.exe scripts\run_demo.py --limit 5000000
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# UI: http://127.0.0.1:8000/  ·  API: http://127.0.0.1:8000/docs
```

Демо-пользователи — `services/README.md` (central.operator / dispatcher.* / tech.alpha).

## 7. Предлагаемые следующие шаги

1. Запросить у заказчика **маппинг «Объект N» ↔ `ид_объект`** + внешние источники
   (СКУД, ОДС, АРМ-Контроль, реестр оборудования) и определение «отказа».
2. Прод-контур: PostgreSQL + TLS + реальный LDAP-адаптер.
3. После данных — переобучение access/sensor, полный fire (фактор горячих работ),
   усиление wear реестром.
4. Синхронизация `/maintenance-plan` с нормативным графиком ТО/ППР (модуль превентивных заявок).

