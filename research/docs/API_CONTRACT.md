# API-контракт ядра MVP (Фаза B, вход для backend-команды)

Версия: 0.1 · Дата: 20.09.2026 · Источник данных: `research/inference_contract.py`
(модели + калибровка + RBAM-слой, уже проверены на holdout 20k субъектов)

Принцип: backend оборачивает готовые функции в FastAPI-эндпоинты **без
ML-логики в роутерах** (ML инкапсулирован в `inference_contract`).

## Эндпоинты

### GET /api/v1/top-risks?task={fire|access|sensor|wear}&k=200
- Описание: топ-K каналов по RBAM-score = risk30(cal/raw) × severity(тип) × scale(объект).
- Реализация: `inference_contract.top_risks(task, k)` → JSON `{task, k, items[]}`.
- `items[]` элемент: `{ид_канала_данных, бакет, дата, тип_датчика, severity, scale,
  p24, risk30, risk_used, exp_days, score, plan, event_flag, obs_days}`.

### GET /api/v1/maintenance-plan?task=wear&k=1000
- Агрегат «план ТО × тип канала»: `{task, rows[{plan, тип_датчика, каналов,
  риск_средний, score_сумма, exp_days_медиана}]}`.
- `plan` ∈ {текущий квартал, следующий квартал, плановый год} (мягкие границы по exp_days).

### GET /api/v1/forecasts/{id}  (карточка, Фаза B)
- Поля: риск, горизонт, S(t) кривая (6ч-сетка 30д — из `predict_risk`),
  exp_days, факторы (топ-фичи модели — добавить на шаге обвязки), рекомендуемое
  действие (по `plan`/«превентивная заявка»), история последних событий канала.

### POST /api/v1/forecasts/{id}/decision
- Body: `{decision: "подтвердить"|"отклонить"|"профилактика", responsible, comment}`.
- Записывает в журнал прогнозов + audit (RBAC). **Собирает метки для дообучения** (обязательное поле).

## Сопутствующие
- Калибровка: `risk30_cal` применять только у access (per-bin `calib30_access.pkl`);
  у sensor/fire/wear — raw (§21.9).
- k=200 default; ответы ≤ ~50 КБ; время < 1 с на запрос (данные в памяти/parquet).
- Модели перечитываются при старте; процентили p24/risk30 для drift — `risk_drift_by_quarter`.

## Пример ответа (top-risks, fire)
```json
{"task":"fire","k":5,"items":[
 {"ид_канала_данных":"...","бакет":...,"дата":"2025-09-24","тип_датчика":"Датчик дыма",
  "severity":0.85,"scale":1.0,"p24":0.9,"risk30":1.0,"risk_used":1.0,"exp_days":0.22,
  "score":0.85,"plan":"текущий квартал","event_flag":1,"obs_days":0.5}
]}
```

## Чек-лист приёма (backend)
1. `/top-risks` возвращает валидный JSON для всех 4 задач.
2. `/maintenance-plan` согласуется с `docs/RISK_PIVOT_REPORT.md` (те же числа).
3. Значения score/exp_days не NaN; task неизвестный → 400.
4. Запись decision → журнал прогнозов + audit накопительно (дообучение).