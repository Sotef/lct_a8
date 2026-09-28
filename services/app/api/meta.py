# -*- coding: utf-8 -*-
"""Мета-ручки для веб-интерфейса: доступные бакеты, задачи, настройки фильтров."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import config
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles
from ..services import prediction_service as ps

router = APIRouter(tags=["meta"])


@router.get("/meta/tasks")
def list_tasks(user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    out = []
    order = {"fire": 0, "access": 1, "sensor": 2, "wear": 3}
    for t in sorted(task_cfg.TASKS, key=lambda x: order.get(x, 9)):
        cfg = task_cfg.TASKS[t]
        out.append({"task": t, "desc": cfg["desc"], "event_col": cfg["event_col"],
                    "calibrated": cfg["calibrated"]})
    return {"tasks": out}


@router.get("/meta/buckets")
def list_buckets(task: str | None = Query(None),
                 db: Session = Depends(get_db),
                 user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Доступные бакеты прогнозов (для слайдера «as-of»)."""
    q = db.query(dbm.Prediction.task,
                 func.min(dbm.Prediction.bucket_ts).label("first"),
                 func.max(dbm.Prediction.bucket_ts).label("last"),
                 func.count(dbm.Prediction.id).label("n")).filter(dbm.current_only())
    if task:
        q = q.filter(dbm.Prediction.task == task)
    rows = q.group_by(dbm.Prediction.task).all()
    return {"buckets": [{"task": r.task, "first": r.first.isoformat(),
                         "last": r.last.isoformat(), "n": r.n} for r in rows]}


@router.get("/meta/bucket-dates")
def bucket_dates(task: str = Query(...),
                 db: Session = Depends(get_db),
                 user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Отсортированный список bucket_ts + bucket-int задачи (для слайдера)."""
    rows = (db.query(dbm.Prediction.bucket_ts)
            .filter(dbm.Prediction.task == task, dbm.current_only())
            .distinct().order_by(dbm.Prediction.bucket_ts.asc()).all())
    epoch = __import__("datetime").datetime(1970, 1, 1)
    out = []
    for (r,) in rows:
        if r.tzinfo:
            r = r.replace(tzinfo=None)
        bucket = int((r - epoch).total_seconds() // (6 * 3600))
        out.append({"ts": r.isoformat(), "bucket": bucket})
    return {"task": task, "dates": out}
MEASURES = {"risk30": "риск 30 дней", "p24": "P(событие ≤ 24 ч)", "p72": "P(≤ 72 ч)",
            "p7d": "P(≤ 7 дней)"}


def _hist_window(db: Session, task: str, n: int):
    """Нижняя граница окна для тренда: последние n 6ч-бакетов.

    Без этого запрос группировал бы ВСЮ историю задачи (в реплее — сотни тысяч строк),
    из-за чего ответ «тренда» мог задерживаться и приходить в UI с опозданием.
    Возвращает None, если прогнозов по задаче ещё нет.
    """
    last = (db.query(func.max(dbm.Prediction.bucket_ts))
            .filter(dbm.Prediction.task == task, dbm.current_only()).scalar())
    if last is None:
        return None
    return last - dt.timedelta(hours=6 * max(1, int(n)))      # окно с запасом; срез rows[-n:]


@router.get("/meta/risk-history")
def risk_history(task: str = Query(...), n: int = Query(40, ge=1, le=300),
                 measure: str = Query("risk30", pattern="^(risk30|p24|p72|p7d)$"),
                 db: Session = Depends(get_db),
                 user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Агрегат риска по бакетам (тренд для дашборда).

    measure: risk30 (по умолчанию) | p24 (1 день) | p72 (3 дня) | p7d (7 дней из S(t)).
    Сканируются только последние n бакетов (см. _hist_window) — ответ быстрый и
    не «догоняет» пользователя при длинном реплее.
    """
    if task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    lo = _hist_window(db, task, n)
    if lo is None:
        return {"task": task, "measure": measure, "measure_ru": MEASURES[measure], "rows": []}
    if measure == "p7d":
        return _history_p7d(db, task, n, lo)
    col = {"p24": dbm.Prediction.p24, "p72": dbm.Prediction.p72}.get(
        measure, dbm.Prediction.risk30)
    rows = (db.query(dbm.Prediction.bucket_ts,
                     func.avg(col).label("avg"), func.max(col).label("mx"),
                     func.count(dbm.Prediction.id).label("cnt"))
            .filter(dbm.Prediction.task == task, dbm.current_only(),
                    dbm.Prediction.bucket_ts >= lo)
            .group_by(dbm.Prediction.bucket_ts)
            .order_by(dbm.Prediction.bucket_ts.asc()).all())
    out = [{"bucket_ts": r[0].isoformat(),
            "avg_risk": round(float(r[1]), 4) if r[1] is not None else None,
            "max_risk": round(float(r[2]), 4) if r[2] is not None else None,
            "n": int(r[3])} for r in rows[-n:]]
    return {"task": task, "measure": measure, "measure_ru": MEASURES[measure], "rows": out}


def _history_p7d(db: Session, task: str, n: int, lo=None) -> dict:
    """P(≤7 дней) по бакетам — колонка predictions.p7d (считается на тике)."""
    q = (db.query(dbm.Prediction.bucket_ts,
                  func.avg(dbm.Prediction.p7d).label("avg"),
                  func.max(dbm.Prediction.p7d).label("mx"),
                  func.count(dbm.Prediction.id).label("cnt"))
         .filter(dbm.Prediction.task == task, dbm.Prediction.p7d.isnot(None),
                 dbm.current_only()))
    if lo is not None:
        q = q.filter(dbm.Prediction.bucket_ts >= lo)
    rows = (q.group_by(dbm.Prediction.bucket_ts)
            .order_by(dbm.Prediction.bucket_ts.asc()).all())
    out = [{"bucket_ts": r[0].isoformat(),
            "avg_risk": round(float(r[1]), 4), "max_risk": round(float(r[2]), 4),
            "n": int(r[3])} for r in rows[-n:]]
    return {"task": task, "measure": "p7d", "measure_ru": MEASURES["p7d"], "rows": out}


@router.get("/meta/channel-history")
def channel_history(task: str = Query(...), channel_id: str = Query(...),
                    n: int = Query(30, ge=1, le=200),
                    db: Session = Depends(get_db),
                    user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """История риска канала по бакетам (спарклайн на карточке)."""
    rows = (db.query(dbm.Prediction.bucket_ts, dbm.Prediction.risk30,
                     dbm.Prediction.p24, dbm.Prediction.exp_days)
            .filter(dbm.Prediction.task == task,
                    dbm.Prediction.channel_id == channel_id,
                    dbm.current_only())
            .order_by(dbm.Prediction.bucket_ts.asc()).all())
    out = []
    for b, r30, p24, ed in rows[-n:]:
        out.append({"bucket_ts": b.isoformat(),
                    "risk30": round(float(r30), 4) if r30 is not None else None,
                    "p24": round(float(p24), 5) if p24 is not None else None,
                    "exp_days": round(float(ed), 2) if ed is not None else None})
    return {"task": task, "channel_id": channel_id, "rows": out}


@router.get("/meta/clock")
def clock(user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Симулируемое «сейчас» сервиса (режим реплея данных 2026 года)."""
    from ..workers import simclock
    return simclock.clock_status()


@router.get("/meta/alerts")
def alerts(min_p7d: float = Query(0.2, ge=0.0, le=1.0, description="порог P(событие ≤ 7 дней)"),
           k: int = Query(50, ge=1, le=500),
           db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Кандидаты на уведомление диспетчера: P(событие ≤ 7 дней) ≥ порога.

    Берётся актуальный бакет каждой задачи; сортировка по вероятности за неделю.
    Повторные уведомления по одному датчику ограничивает клиент (интервал 12 ч).
    """
    from ..deps import scoped_object_ids
    allowed = scoped_object_ids(user, db)
    items = []
    for task in task_cfg.ALL_TASKS:
        last = ps.latest_bucket_ts(db, task)
        if last is None:
            continue
        q = (db.query(dbm.Prediction, dbm.ChannelRef.sensor_type, dbm.ChannelRef.sensor_name,
                      dbm.ObjectRef)
             .outerjoin(dbm.ChannelRef,
                        dbm.ChannelRef.channel_id == dbm.Prediction.channel_id)
             .outerjoin(dbm.ObjectRef, dbm.ObjectRef.object_id == dbm.Prediction.object_id)
             .filter(dbm.Prediction.task == task, dbm.Prediction.bucket_ts == last,
                     dbm.current_only()))
        if allowed is not None:
            q = q.filter(dbm.Prediction.object_id.in_(allowed))
        for p, st, sn, obj in q.all():
            p7 = ps._p7d(p.surv_points)
            if p7 is None or p7 < min_p7d:
                continue
            it = ps._pred_to_item(p, st, sn, obj=obj)
            it["task"] = task
            it["task_desc"] = task_cfg.TASKS[task]["desc"]
            items.append(it)
    items.sort(key=lambda x: -(x.get("p7d") or 0))
    return {"min_p7d": min_p7d, "k": len(items[:k]), "total": len(items), "items": items[:k]}


@router.get("/meta/summary")
def summary(db: Session = Depends(get_db),
            user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Сводка для KPI-карточек (последний бакет по каждой задаче)."""
    out = {}
    for task in task_cfg.ALL_TASKS:
        last = ps.latest_bucket_ts(db, task)
        if last is None:
            out[task] = {"bucket": None, "n": 0, "high": 0, "critical": 0,
                         "avg_risk": None, "avg_p24": None, "active": 0}
            continue
        p = db.query(dbm.Prediction).filter(
            dbm.Prediction.task == task, dbm.Prediction.bucket_ts == last,
            dbm.current_only())
        meta = db.query(func.count(dbm.Prediction.id),
                        func.avg(dbm.Prediction.risk30),
                        func.avg(dbm.Prediction.p24),
                        func.max(dbm.Prediction.score)).filter(
            dbm.Prediction.task == task, dbm.Prediction.bucket_ts == last,
            dbm.current_only()).one()
        high = p.filter(dbm.Prediction.risk30 >= 0.5).count()
        crit = p.filter(dbm.Prediction.risk30 >= 0.8).count()
        active = p.filter(dbm.Prediction.event_flag == 1).count()
        out[task] = {"bucket": last.isoformat(),
                     "n": meta[0], "high": high, "critical": crit,
                     "avg_risk": round(meta[1], 4) if meta[1] else None,
                     "avg_p24": round(meta[2], 5) if meta[2] else None,
                     "max_score": round(meta[3], 4) if meta[3] else None,
                     "active": active}
    return out


@router.get("/meta/client-config")
def client_config(user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Настройки мобильного профиля для веб-клиента (MOBILE_PLAN §6.1).

    Секреты здесь не отдаются: только пороги, TTL сессии и фиче-флаги.
    """
    return {
        "role": user.role,
        "pwa": bool(config.PWA),
        "alerts": {
            "min_p7d": config.ALERTS_MIN_P7D,
            "silence_hours": config.ALERTS_SILENCE_HOURS,
            "push_enabled": bool(config.ALERTS_PUSH),
            "top_k": config.ALERTS_TOP_K,
        },
        "session": {
            "access_minutes": config.ACCESS_TOKEN_MINUTES,
            "refresh_days": config.MOBILE_REFRESH_DAYS,
        },
        "attachments": {"max_mb": config.ATTACH_MAX_MB,
                        "mime": ["image/jpeg", "image/png", "image/webp"]},
        "features": {"offline_queue": True, "push": bool(config.ALERTS_PUSH),
                     "mobile_bottom_nav": True},
    }