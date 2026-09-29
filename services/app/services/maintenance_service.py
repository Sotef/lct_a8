# -*- coding: utf-8 -*-
"""Модуль превентивных заявок (maintenance_tasks).

Источники заявок:
- auto     — автоформирование из прогнозов актуального бакета: топ-K по RBAM-score
             среди каналов с risk30(cal) >= AUTO_TICKETS_MIN_RISK (каждый сим-тик);
- decision — решение диспетчера «профилактика» в карточке прогноза;
- manual   — ручное создание по прогнозу (POST /maintenance/tickets).

Дедупликация: на канал × задачу не больше одной открытой заявки
(suggested/assigned/in_progress). Срок: due_to = бакет + clamp(exp_days, 1, 30) дней.
Модель только предлагает заявку — назначение/закрытие делает человек.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm
from .. import task_cfg
from ..logging_setup import log_event
from . import audit_service
from . import prediction_service as ps

log = logging.getLogger("maintenance")

OPEN = ("suggested", "assigned", "in_progress")
STATUSES = ("suggested", "assigned", "in_progress", "done", "cancelled")
STATUS_RU = {"suggested": "предложена", "assigned": "назначена",
             "in_progress": "в работе", "done": "выполнена", "cancelled": "отменена"}
# допустимые переходы; tech — только исполнение
TRANSITIONS = {
    "suggested": {"assigned", "cancelled", "in_progress"},
    "assigned": {"in_progress", "cancelled", "suggested", "done"},
    "in_progress": {"done", "assigned", "cancelled"},
    "done": {"in_progress"},
    "cancelled": {"suggested"},
}
TECH_ALLOWED = {("assigned", "in_progress"), ("in_progress", "done"),
                ("in_progress", "assigned")}


def _risk(p: dbm.Prediction) -> float:
    r = p.risk30_cal if p.risk30_cal is not None else p.risk30
    return float(r or 0.0)


def _priority(p: dbm.Prediction) -> str:
    r = _risk(p)
    if r >= 0.8 or (p.p72 or 0) >= 0.5:
        return "high"
    return "medium" if r >= 0.5 else "low"


def _naive(d):
    return d.replace(tzinfo=None) if d is not None and d.tzinfo else d


def _find_open(db: Session, task: str, channel_id: str):
    return (db.query(dbm.MaintenanceTask)
            .filter(dbm.MaintenanceTask.task == task,
                    dbm.MaintenanceTask.channel_id == channel_id,
                    dbm.MaintenanceTask.status.in_(OPEN)).first())


def create_from_prediction(db: Session, pred: dbm.Prediction, source: str,
                           status: str = "suggested", user_id: int | None = None,
                           comment: str | None = None,
                           scheduled_at: dt.datetime | None = None,
                           commit: bool = True) -> tuple[dbm.MaintenanceTask, bool]:
    """Создаёт заявку (или возвращает уже открытую). -> (ticket, created)."""
    existing = _find_open(db, pred.task, pred.channel_id)
    if existing is not None:
        if status == "assigned" and existing.status == "suggested":
            existing.status = "assigned"
            existing.assigned_to = existing.assigned_to or user_id
            existing.updated_at = dt.datetime.now(dt.timezone.utc)
            existing.prediction_id = pred.id
        if scheduled_at is not None:
            existing.scheduled_at = scheduled_at
            existing.updated_at = dt.datetime.now(dt.timezone.utc)
            if commit:
                db.commit()
        elif commit:
            db.commit()
        return existing, False
    start = _naive(pred.bucket_ts) or dt.datetime.utcnow()
    days = min(30.0, max(1.0, float(pred.exp_days or 7.0)))
    t = dbm.MaintenanceTask(
        task=pred.task, channel_id=pred.channel_id, object_id=pred.object_id,
        plan_bucket=pred.plan, score=pred.score, status=status,
        due_from=start, due_to=start + dt.timedelta(days=days),
        scheduled_at=scheduled_at,
        assigned_to=user_id if status == "assigned" else None,
        prediction_id=pred.id, source=source, priority=_priority(pred),
        comment=comment, updated_at=dt.datetime.now(dt.timezone.utc))
    db.add(t)
    db.flush()
    if commit:
        db.commit()
    return t, True


def auto_generate(db: Session, tasks=None, min_risk: float | None = None,
                  top_k: int | None = None, user_id: int | None = None) -> dict:
    """Автоформирование заявок по актуальному бакету каждой задачи."""
    min_risk = config.AUTO_TICKETS_MIN_RISK if min_risk is None else min_risk
    top_k = config.AUTO_TICKETS_TOP_K if top_k is None else top_k
    out = {}
    for task in (tasks or task_cfg.ALL_TASKS):
        last = ps.latest_bucket_ts(db, task)
        if last is None:
            out[task] = {"created": 0, "skipped": 0}
            continue
        risk_col = func.coalesce(dbm.Prediction.risk30_cal, dbm.Prediction.risk30)
        preds = (db.query(dbm.Prediction)
                 .filter(dbm.Prediction.task == task,
                         dbm.Prediction.bucket_ts == last,
                         risk_col >= min_risk)
                 .order_by(dbm.Prediction.score.desc().nulls_last())
                 .limit(top_k).all())
        created = skipped = 0
        for p in preds:
            _, is_new = create_from_prediction(db, p, source="auto", commit=False)
            created += int(is_new)
            skipped += int(not is_new)
        db.commit()
        out[task] = {"created": created, "skipped": skipped}
    total = sum(v["created"] for v in out.values())
    if total or user_id is not None:
        audit_service.record(db, "ticket.auto_generate", user_id=user_id,
                             entity_type="maintenance", entity_id="batch",
                             detail={"result": out, "min_risk": min_risk, "top_k": top_k})
    log_event(log, logging.INFO, f"auto tickets: +{total}", result=out)
    return {"created": total, "by_task": out, "min_risk": min_risk, "top_k": top_k}


def service_now() -> dt.datetime:
    """«Сейчас» сервиса: сим-время в режиме реплея, иначе UTC."""
    try:
        from ..workers import simclock
        st = simclock.clock_status()
        if config.SIM_CLOCK and st.get("sim_now"):
            return dt.datetime.fromisoformat(st["sim_now"])
    except Exception:  # noqa: BLE001
        pass
    return dt.datetime.utcnow()


def ticket_detail(db: Session, t: dbm.MaintenanceTask) -> dict:
    """Одна заявка в том же формате, что элементы списка (для карточки объекта и мобильного)."""
    obj = db.get(dbm.ObjectRef, t.object_id)
    ch = db.get(dbm.ChannelRef, t.channel_id)
    assignee = None
    if t.assigned_to:
        u = db.get(dbm.User, t.assigned_to)
        assignee = u.username if u else None
    pred = db.get(dbm.Prediction, t.prediction_id) if t.prediction_id else None
    return _ticket_out(t, obj, ch, assignee, pred)


def _ticket_out(t: dbm.MaintenanceTask, obj=None, ch=None, assignee=None,
                pred: dbm.Prediction | None = None,
                now: dt.datetime | None = None) -> dict:
    now = now or service_now()
    due = _naive(t.due_to)
    return {
        "id": t.id, "task": t.task,
        "task_desc": task_cfg.TASKS.get(t.task, {}).get("desc", t.task),
        "channel_id": t.channel_id, "object_id": t.object_id,
        "object_name": getattr(obj, "name", None),
        "district": getattr(obj, "district", None),
        "sensor_type": getattr(ch, "sensor_type", None),
        "sensor_name": getattr(ch, "sensor_name", None),
        "plan": t.plan_bucket, "score": t.score,
        "status": t.status, "status_ru": STATUS_RU.get(t.status, t.status),
        "priority": t.priority or "medium", "source": t.source or "manual",
        "prediction_id": t.prediction_id,
        "risk": _risk(pred) if pred is not None else None,
        "p24": pred.p24 if pred is not None else None,
        "exp_days": pred.exp_days if pred is not None else None,
        "assigned_to": t.assigned_to, "assignee": assignee,
        "comment": t.comment,
        "due_from": t.due_from.isoformat() if t.due_from else None,
        "due_to": t.due_to.isoformat() if t.due_to else None,
        "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
        "plan_at": (t.scheduled_at or t.due_to).isoformat() if (t.scheduled_at or t.due_to) else None,
        "overdue": bool(due and t.status in OPEN and due < now),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def list_tickets(db: Session, task: str | None = None, status: str | None = None,
                 object_ids: list[str] | None = None, object_id: str | None = None,
                 q: str | None = None,
                 order: str = "new", limit: int = 500,
                 mine_user_id: int | None = None, scope: str | None = None,
                 cursor: str | None = None) -> dict:
    Assignee = dbm.User
    qry = (db.query(dbm.MaintenanceTask, dbm.ObjectRef, dbm.ChannelRef,
                    Assignee.username, dbm.Prediction)
           .outerjoin(dbm.ObjectRef, dbm.ObjectRef.object_id == dbm.MaintenanceTask.object_id)
           .outerjoin(dbm.ChannelRef,
                      dbm.ChannelRef.channel_id == dbm.MaintenanceTask.channel_id)
           .outerjoin(Assignee, Assignee.id == dbm.MaintenanceTask.assigned_to)
           .outerjoin(dbm.Prediction,
                      dbm.Prediction.id == dbm.MaintenanceTask.prediction_id))
    if task:
        qry = qry.filter(dbm.MaintenanceTask.task == task)
    if object_id:
        qry = qry.filter(dbm.MaintenanceTask.object_id == object_id)
    if status:
        qry = qry.filter(dbm.MaintenanceTask.status.in_(status.split(",")))
    if scope == "active":
        qry = qry.filter(dbm.MaintenanceTask.status.in_(OPEN))
    if mine_user_id is not None:
        qry = qry.filter(dbm.MaintenanceTask.assigned_to == mine_user_id)
    if object_ids is not None:
        qry = qry.filter(dbm.MaintenanceTask.object_id.in_(object_ids))
    if q:
        like = f"%{q}%"
        qry = qry.filter(dbm.ObjectRef.name.like(like) |
                         dbm.MaintenanceTask.channel_id.like(like) |
                         dbm.ChannelRef.sensor_name.like(like))
    # срок выезда: назначенная дата, иначе расчётный срок (due_to)
    plan_expr = func.coalesce(dbm.MaintenanceTask.scheduled_at, dbm.MaintenanceTask.due_to)
    if order == "due":
        if cursor:
            try:
                cur_dt = dt.datetime.fromisoformat(cursor.replace("Z", "+00:00"))
                qry = qry.filter(plan_expr > _naive(cur_dt))
            except ValueError:
                pass
        # график обслуживания: сначала то, что запланировано/наступит раньше
        qry = qry.order_by(plan_expr.asc(), dbm.MaintenanceTask.id.asc())
    else:
        if cursor:
            try:
                qry = qry.filter(dbm.MaintenanceTask.id < int(cursor))
            except ValueError:
                pass
        qry = qry.order_by(dbm.MaintenanceTask.id.desc())
    rows = qry.limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    now = service_now()
    items = [_ticket_out(t, o, c, u, p, now=now) for t, o, c, u, p in rows]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = (last["plan_at"] or "") if order == "due" else str(last["id"])
    return {"items": items, "total": len(items), "has_more": has_more,
            "next_cursor": next_cursor}


def summary(db: Session, object_ids: list[str] | None = None) -> dict:
    qry = db.query(dbm.MaintenanceTask.status, dbm.MaintenanceTask.task,
                   func.count(dbm.MaintenanceTask.id))
    if object_ids is not None:
        qry = qry.filter(dbm.MaintenanceTask.object_id.in_(object_ids))
    rows = qry.group_by(dbm.MaintenanceTask.status, dbm.MaintenanceTask.task).all()
    by_status = {s: 0 for s in STATUSES}
    by_task: dict = {}
    for s, t, n in rows:
        by_status[s] = by_status.get(s, 0) + n
        by_task.setdefault(t, {}).setdefault(s, 0)
        by_task[t][s] += n
    return {"by_status": by_status, "by_task": by_task,
            "open": sum(by_status.get(s, 0) for s in OPEN)}


def update_status(db: Session, ticket_id: int, new_status: str, user: dbm.User,
                  comment: str | None = None, assign_to_me: bool = False,
                  scheduled_at: dt.datetime | None = None,
                  object_ids: list[str] | None = None,
                  client_id: str | None = None, offline_ts: str | None = None) -> dict:
    t = db.get(dbm.MaintenanceTask, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    if object_ids is not None and t.object_id not in object_ids:
        raise HTTPException(status_code=403, detail="объект вне вашего района")
    if new_status not in STATUSES:
        raise HTTPException(status_code=400, detail="неизвестный статус")
    old = t.status
    if new_status != old:
        if new_status not in TRANSITIONS.get(old, set()):
            raise HTTPException(status_code=409,
                                detail=f"переход «{STATUS_RU.get(old, old)}» → "
                                       f"«{STATUS_RU[new_status]}» недопустим")
        if user.role == "tech" and (old, new_status) not in TECH_ALLOWED:
            raise HTTPException(status_code=403,
                                detail="техник может только брать в работу и закрывать заявки")
    t.status = new_status
    if scheduled_at is not None:
        t.scheduled_at = _naive(scheduled_at)
    if assign_to_me or (new_status in ("assigned", "in_progress") and not t.assigned_to):
        t.assigned_to = user.id
    if comment:
        stamp = dt.datetime.now().strftime("%d.%m %H:%M")
        t.comment = ((t.comment + "\n") if t.comment else "") + \
            f"[{stamp} {user.username}] {comment}"
    t.updated_at = dt.datetime.now(dt.timezone.utc)
    audit_service.record(db, "ticket.status", user_id=user.id, entity_type="maintenance",
                         entity_id=t.id, commit=False,
                         detail={"from": old, "to": new_status, "comment": comment,
                                 "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
                                 "task": t.task, "channel_id": t.channel_id,
                                 "object_id": t.object_id,
                                 "source": "mobile-offline" if offline_ts else "web",
                                 **({"client_id": client_id} if client_id else {}),
                                 **({"offline_ts": offline_ts,
                                     "synced_at": dt.datetime.now(dt.timezone.utc).isoformat()}
                                    if offline_ts else {})})
    db.commit()
    return {"ok": True, "id": t.id, "status": t.status, "from": old,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None}

