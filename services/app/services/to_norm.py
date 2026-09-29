# -*- coding: utf-8 -*-
"""Нормативная периодичность ТО/ППР и расчёт даты планового выезда.

Что здесь и почему:

* **Периодичность ТО** задаётся по типу датчика (с откатом на направление задачи).
  Значения — эвристика v1, согласованная с типовой практикой ППР (пожарная
  автоматика и механика — ТО 2 раза/год, СКУД/КИП/люки — 1 раз/год). Это
  единственный доступный вариант: реестр оборудования и нормативный справочник
  заказчик не даёт, а график плановых работ приходит с анонимизированными
  объектами («Объект N») без маппинга на `ид_объект` (см. research/planned_work.py).
  Всё настраивается через `NORM_PERIOD_DAYS_*`.

* **Нормативный срок** `norm_due` = ближайшая дата ТО по периодичности, отсчитанная
  от **первой записи датчика** (возраст оборудования, см. `channel_meta`).

* **Дата плана** `plan_date = min(прогнозный срок, нормативный срок)`:
  - если модель ждёт деградацию раньше планового ТО — идём раньше (внеплановый выезд);
  - иначе едем в штатное окно ТО.
  Это гарантирует «не позже любого из двух сроков».

* **Горизонт** (`plan`) — те же ярлыки, что и раньше (контракт UI/тестов):
  «текущий квартал» (<7 дн), «следующий квартал» (<21 дн), иначе «плановый год».
"""
from __future__ import annotations

import datetime as dt

# --- периодичность (дни) ---------------------------------------------------
# по типу датчика (приоритет), иначе по направлению задачи
NORM_PERIOD_DAYS_BY_TYPE: dict[str, int] = {
    # пожарная автоматика — ТО 2 раза/год
    "Датчик дыма": 180, "Ручной извещатель": 180, "Тепловой датчик": 180,
    # КИП / СКУД / прочее — 1 раз/год
    "Датчик температуры": 365, "Газовый датчик": 365, "Датчик затопления": 365,
    "КД Дверь": 365, "Датчик движения": 365, "КД АВ": 365, "КД Люк": 365,
    "9-секционный люк": 365, "Стекло": 365,
    # механика / износ — ТО 2 раза/год
    "Состояние насоса": 180, "Состояние вентилятора": 180, "Состояние фазы": 180,
}
NORM_PERIOD_DAYS_BY_TASK: dict[str, int] = {
    "fire": 180, "access": 365, "sensor": 365, "wear": 180,
}
NORM_PERIOD_DEFAULT_DAYS = 365

# границы ярлыков горизонта (дней до плановой даты)
HORIZON_CURRENT_DAYS = 7
HORIZON_NEXT_DAYS = 21


def norm_period_days(task: str | None, sensor_type: str | None) -> int:
    if sensor_type and str(sensor_type) in NORM_PERIOD_DAYS_BY_TYPE:
        return int(NORM_PERIOD_DAYS_BY_TYPE[str(sensor_type)])
    if task and str(task) in NORM_PERIOD_DAYS_BY_TASK:
        return int(NORM_PERIOD_DAYS_BY_TASK[str(task)])
    return NORM_PERIOD_DEFAULT_DAYS


def _naive(when) -> dt.datetime | None:
    if when is None:
        return None
    if hasattr(when, "to_pydatetime"):
        when = when.to_pydatetime()
    if getattr(when, "tzinfo", None) is not None:
        when = when.replace(tzinfo=None)
    return when


def norm_due(first_seen, now, period_days: int) -> dt.datetime:
    """Ближайшая (не раньше `now`) дата планового ТО по периодичности от первой записи."""
    now = _naive(now) or dt.datetime.utcnow()
    fs = _naive(first_seen)
    period = max(1, int(period_days))
    if fs is None or fs > now:
        return now + dt.timedelta(days=period)      # возраст неизвестен → считаем от «сейчас»
    k = int((now - fs).total_seconds() // (period * 86400)) + 1
    due = fs + dt.timedelta(days=k * period)
    while due < now:                                 # защита от краевых округлений
        due += dt.timedelta(days=period)
    return due


def forecast_due(now, exp_days, cap_days: int = 90) -> dt.datetime | None:
    """Прогнозный срок: `now + clamp(exp_days, 1, cap)`. None, если exp_days неизвестен."""
    now = _naive(now) or dt.datetime.utcnow()
    try:
        e = float(exp_days)
    except (TypeError, ValueError):
        return None
    if e != e:                                       # NaN
        return None
    due = now + dt.timedelta(days=min(float(cap_days), max(1.0, e)))
    return due.replace(minute=0, second=0, microsecond=0)   # до часа — tidy в UI


def plan_date(now, exp_days=None, norm=None, cap_days: int = 90) -> dt.datetime | None:
    """Плановая дата выезда = min(прогнозный срок, нормативный срок)."""
    now = _naive(now) or dt.datetime.utcnow()
    norm = _naive(norm)
    fc = forecast_due(now, exp_days, cap_days=cap_days)
    if fc is None:
        return norm
    if norm is None:
        return fc
    return min(fc, norm)


def horizon_label(days_left) -> str:
    """Ярлык горизонта по числу дней до плановой даты (контракт UI/тестов)."""
    if days_left is None:
        return "плановый"
    try:
        d = float(days_left)
    except (TypeError, ValueError):
        return "плановый"
    if d < HORIZON_CURRENT_DAYS:
        return "текущий квартал"
    if d < HORIZON_NEXT_DAYS:
        return "следующий квартал"
    return "плановый год"


def horizon_of(now, plan_dt) -> str:
    plan_dt = _naive(plan_dt)
    if plan_dt is None:
        return "плановый"
    now = _naive(now) or dt.datetime.utcnow()
    return horizon_label((plan_dt - now).total_seconds() / 86400.0)
