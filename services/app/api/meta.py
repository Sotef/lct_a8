# -*- coding: utf-8 -*-
"""Мета-ручки для веб-интерфейса: доступные бакеты, задачи, настройки фильтров."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models_db as dbm
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
                 func.count(dbm.Prediction.id).label("n"))
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
            .filter(dbm.Prediction.task == task)
            .distinct().order_by(dbm.Prediction.bucket_ts.asc()).all())
    epoch = __import__("datetime").datetime(1970, 1, 1)
    out = []
    for (r,) in rows:
        if r.tzinfo:
            r = r.replace(tzinfo=None)
        bucket = int((r - epoch).total_seconds() // (6 * 3600))
        out.append({"ts": r.isoformat(), "bucket": bucket})
    return {"task": task, "dates": out}
@router.get("/meta/risk-history")
def risk_history(task: str = Query(...), n: int = Query(40, ge=1, le=300),
                 db: Session = Depends(get_db),
                 user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Агрегат риска по бакетам (тренд для дашборда)."""
    if task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    rows = (db.query(dbm.Prediction.bucket_ts,
                     func.avg(dbm.Prediction.risk30).label("avg"),
                     func.max(dbm.Prediction.risk30).label("mx"),
                     func.count(dbm.Prediction.id).label("cnt"))
            .filter(dbm.Prediction.task == task)
            .group_by(dbm.Prediction.bucket_ts)
            .order_by(dbm.Prediction.bucket_ts.asc()).all())
    out = []
    for r in rows[-n:]:
        out.append({"bucket_ts": r[0].isoformat(),
                    "avg_risk": round(float(r[1]), 4),
                    "max_risk": round(float(r[2]), 4),
                    "n": int(r[3])})
    return {"task": task, "rows": out}


@router.get("/meta/channel-history")
def channel_history(task: str = Query(...), channel_id: str = Query(...),
                    n: int = Query(30, ge=1, le=200),
                    db: Session = Depends(get_db),
                    user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """История риска канала по бакетам (спарклайн на карточке)."""
    rows = (db.query(dbm.Prediction.bucket_ts, dbm.Prediction.risk30,
                     dbm.Prediction.p24, dbm.Prediction.exp_days)
            .filter(dbm.Prediction.task == task,
                    dbm.Prediction.channel_id == channel_id)
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
            dbm.Prediction.task == task, dbm.Prediction.bucket_ts == last)
        meta = db.query(func.count(dbm.Prediction.id),
                        func.avg(dbm.Prediction.risk30),
                        func.avg(dbm.Prediction.p24),
                        func.max(dbm.Prediction.score)).filter(
            dbm.Prediction.task == task, dbm.Prediction.bucket_ts == last).one()
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