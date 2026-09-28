# -*- coding: utf-8 -*-
"""Экран «Алерты»: серверный журнал алертов (MOBILE_PLAN §6.1, §4.6).

Основной источник — таблица ``alert_log`` (её наполняет воркер ``workers/alerts.py``).
Если журнал пуст (воркер ещё не запускался / свежая БД), ручка отдаёт «живых»
кандидатов по текущему бакету и помечает ответ ``fallback=true`` — экран алертов
работает всегда.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles, scoped_object_ids
from ..services import audit_service, prediction_service as ps

router = APIRouter(tags=["alerts"])


def _aware(d: dt.datetime | None) -> dt.datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


@router.get("/alerts")
def alerts(since: str | None = Query(None, description="ISO-время: только новее"),
           task: str | None = Query(None),
           limit: int = Query(100, ge=1, le=500),
           min_p7d: float = Query(None, ge=0.0, le=1.0),
           db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    if task and task not in task_cfg.ALL_TASKS:
        task = None
    allowed = scoped_object_ids(user, db)

    q = (db.query(dbm.AlertLog, dbm.ObjectRef, dbm.ChannelRef)
         .outerjoin(dbm.ObjectRef, dbm.ObjectRef.object_id == dbm.AlertLog.object_id)
         .outerjoin(dbm.ChannelRef, dbm.ChannelRef.channel_id == dbm.AlertLog.channel_id))
    if task:
        q = q.filter(dbm.AlertLog.task == task)
    if allowed is not None:
        q = q.filter(dbm.AlertLog.object_id.in_(allowed))
    if since:
        try:
            q = q.filter(dbm.AlertLog.sent_at >= dt.datetime.fromisoformat(since.replace("Z", "+00:00")))
        except ValueError:
            pass
    rows = q.order_by(dbm.AlertLog.sent_at.desc()).limit(limit).all()

    items = []
    for a, obj, ch in rows:
        items.append({
            "id": a.id, "task": a.task,
            "task_desc": task_cfg.TASKS.get(a.task, {}).get("desc", a.task),
            "channel_id": a.channel_id, "object_id": a.object_id,
            "object_name": getattr(obj, "name", None),
            "district": getattr(obj, "district", None),
            "sensor_type": getattr(ch, "sensor_type", None),
            "sensor_name": getattr(ch, "sensor_name", None),
            "p7d": a.risk_value, "risk_used": a.risk_value,
            "kind": a.kind, "sent_at": a.sent_at.isoformat() if a.sent_at else None,
        })
    if items:
        return {"items": items, "total": len(items), "fallback": False,
                "min_p7d": config.ALERTS_MIN_P7D}

    # --- fallback: текущие кандидаты по последнему бакету ---
    lo = min_p7d if min_p7d is not None else config.ALERTS_MIN_P7D
    live = []
    for t in (task_cfg.ALL_TASKS if not task else [task]):
        last = ps.latest_bucket_ts(db, t)
        if last is None:
            continue
        qq = (db.query(dbm.Prediction, dbm.ChannelRef.sensor_type, dbm.ChannelRef.sensor_name,
                       dbm.ObjectRef)
              .outerjoin(dbm.ChannelRef, dbm.ChannelRef.channel_id == dbm.Prediction.channel_id)
              .outerjoin(dbm.ObjectRef, dbm.ObjectRef.object_id == dbm.Prediction.object_id)
              .filter(dbm.Prediction.task == t, dbm.Prediction.bucket_ts == last,
                      dbm.current_only()))
        if allowed is not None:
            qq = qq.filter(dbm.Prediction.object_id.in_(allowed))
        for p, st, sn, obj in qq.all():
            p7 = ps._p7d(p.surv_points)
            if p7 is None or p7 < lo:
                continue
            it = ps._pred_to_item(p, st, sn, obj=obj)
            # нормализуем ключи: fallback должен отдавать те же имена, что и журнал алертов
            it.setdefault("object_name", it.get("название_объекта"))
            it.setdefault("channel_id", it.get("ид_канала_данных"))
            it.setdefault("sensor_type", it.get("тип_датчика"))
            it.setdefault("sensor_name", it.get("название_датчика"))
            it.setdefault("district", it.get("район"))
            it.update({"task": t,
                       "task_desc": task_cfg.TASKS.get(t, {}).get("desc", t),
                       "p7d": p7, "kind": "live", "sent_at": None})
            live.append(it)
    live.sort(key=lambda x: -(x.get("p7d") or 0))
    return {"items": live[:limit], "total": len(live[:limit]), "fallback": True,
            "min_p7d": lo}


@router.post("/admin/alerts/run")
def run_alerts(force: bool = Query(True, description="игнорировать окно тишины (демо/приёмка)"),
               db: Session = Depends(get_db),
               user: dbm.User = Depends(require_roles("central"))):
    """Ручной запуск серверного правила алертов (MOBILE_PLAN §6.2)."""
    from ..workers import alerts as alerts_worker
    res = alerts_worker.run(db, force=force)
    audit_service.record(db, "alert.push", user_id=user.id, entity_type="alert",
                         entity_id="manual",
                         detail={"source": "admin", "force": force, **res})
    return {"ok": True, **res}
