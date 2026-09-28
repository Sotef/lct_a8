# -*- coding: utf-8 -*-
"""Модуль превентивных заявок: список, создание, статусы, автоформирование."""
from __future__ import annotations

import pathlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles, scoped_object_ids
from ..services import audit_service, attachment_service
from ..services import idempotency as idem
from ..services import maintenance_service as ms

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


def _check_scope(db: Session, user: dbm.User, ticket: dbm.MaintenanceTask) -> None:
    allowed = scoped_object_ids(user, db)
    if allowed is not None and ticket.object_id not in allowed:
        raise HTTPException(status_code=403, detail="объект вне вашего района")


class TicketCreate(BaseModel):
    prediction_id: int
    comment: str | None = None
    assign: bool = True
    scheduled_at: datetime | None = None


class TicketStatus(BaseModel):
    status: str = Field(pattern="^(suggested|assigned|in_progress|done|cancelled)$")
    comment: str | None = Field(None, max_length=2000)
    assign_to_me: bool = False
    scheduled_at: datetime | None = None
    # оптимистичная блокировка (MOBILE_PLAN §4.5): если на сервере статус уже другой — 409
    base_status: str | None = Field(None, pattern="^(suggested|assigned|in_progress|done|cancelled)$")
    offline_ts: str | None = None          # ISO-время офлайн-действия (аудит «сделано в поле»)


class AutoGen(BaseModel):
    tasks: list[str] | None = None
    min_risk: float | None = Field(None, ge=0, le=1)
    top_k: int | None = Field(None, ge=1, le=200)


@router.get("/tickets")
def tickets(task: str | None = Query(None), status: str | None = Query(None),
            q: str | None = Query(None), object_id: str | None = Query(None),
            order: str = Query("new", pattern="^(new|due)$"),
            scope: str | None = Query(None, pattern="^(active)$"),
            mine: bool = Query(False, description="только заявки текущего пользователя"),
            cursor: str | None = Query(None, description="курсор следующей страницы"),
            limit: int = Query(500, ge=1, le=2000),
            db: Session = Depends(get_db),
            user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    if task and task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    return ms.list_tickets(db, task=task, status=status, q=q, limit=limit, order=order,
                           object_id=object_id, scope=scope, cursor=cursor,
                           mine_user_id=user.id if mine else None,
                           object_ids=scoped_object_ids(user, db))


@router.get("/summary")
def tickets_summary(db: Session = Depends(get_db),
                    user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Сводка по заявкам + параметры автоформирования (для пояснения кнопки в UI)."""
    out = ms.summary(db, object_ids=scoped_object_ids(user, db))
    out["auto"] = {"enabled": bool(config.AUTO_TICKETS),
                   "min_risk": config.AUTO_TICKETS_MIN_RISK,
                   "top_k": config.AUTO_TICKETS_TOP_K}
    return out


@router.post("/tickets")
def create_ticket(req: TicketCreate, db: Session = Depends(get_db),
                  user: dbm.User = Depends(require_roles("dispatcher", "central"))):
    pred = db.get(dbm.Prediction, req.prediction_id)
    if pred is None:
        raise HTTPException(status_code=404, detail="прогноз не найден")
    t, created = ms.create_from_prediction(
        db, pred, source="manual", status="assigned" if req.assign else "suggested",
        user_id=user.id, comment=req.comment, scheduled_at=req.scheduled_at, commit=False)
    audit_service.record(db, "ticket.create", user_id=user.id, entity_type="maintenance",
                         entity_id=t.id, commit=False,
                         detail={"prediction_id": pred.id, "created": created,
                                 "task": pred.task, "channel_id": pred.channel_id})
    db.commit()
    return {"ok": True, "id": t.id, "created": created, "status": t.status,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "plan_at": (t.scheduled_at or t.due_to).isoformat() if (t.scheduled_at or t.due_to) else None,
            "due_to": t.due_to.isoformat() if t.due_to else None}


@router.patch("/tickets/{ticket_id}")
def set_status(ticket_id: int, req: TicketStatus, db: Session = Depends(get_db),
               user: dbm.User = Depends(require_roles("dispatcher", "central", "tech")),
               client_id: str | None = Depends(idem.client_id_header)):
    path = f"/api/v1/maintenance/tickets/{ticket_id}"
    already, saved = idem.begin(db, client_id, user.id, path)
    if already and saved is not None:
        return saved                                     # повтор офлайн-действия: без дубля
    try:
        t = db.get(dbm.MaintenanceTask, ticket_id)
        if t is None:
            raise HTTPException(status_code=404, detail="заявка не найдена")
        _check_scope(db, user, t)
        if req.base_status and t.status != req.base_status:
            raise HTTPException(status_code=409, detail={
                "code": "conflict",
                "message": f"заявка изменена другим пользователем: сейчас "
                           f"«{ms.STATUS_RU.get(t.status, t.status)}»",
                "current": {"id": t.id, "status": t.status,
                            "status_ru": ms.STATUS_RU.get(t.status, t.status),
                            "updated_at": t.updated_at.isoformat() if t.updated_at else None},
            })
        res = ms.update_status(db, ticket_id, req.status, user, comment=req.comment,
                               assign_to_me=req.assign_to_me, scheduled_at=req.scheduled_at,
                               object_ids=scoped_object_ids(user, db),
                               client_id=client_id, offline_ts=req.offline_ts)
    except HTTPException:
        idem.cancel(db, client_id)
        raise
    idem.finish(db, client_id, res)
    return res


@router.post("/auto-generate")
def auto_generate(req: AutoGen, db: Session = Depends(get_db),
                  user: dbm.User = Depends(require_roles("dispatcher", "central"))):
    if req.tasks and any(t not in task_cfg.ALL_TASKS for t in req.tasks):
        raise HTTPException(status_code=400, detail="неизвестная задача")
    return ms.auto_generate(db, tasks=req.tasks, min_risk=req.min_risk,
                            top_k=req.top_k, user_id=user.id)


# --- Вложения (фото с объекта) — MOBILE_PLAN §6.1 ------------------------------

@router.get("/tickets/{ticket_id}/attachments")
def list_attachments(ticket_id: int, db: Session = Depends(get_db),
                     user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    t = db.get(dbm.MaintenanceTask, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    _check_scope(db, user, t)
    return {"ticket_id": ticket_id, "items": attachment_service.list_for(db, ticket_id)}


@router.post("/tickets/{ticket_id}/attachments")
async def upload_attachment(ticket_id: int, file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    t = db.get(dbm.MaintenanceTask, ticket_id)
    if t is None:
        raise HTTPException(status_code=404, detail="заявка не найдена")
    _check_scope(db, user, t)
    data = await file.read()
    row = attachment_service.save(db, t, user.id, file.filename, data)
    audit_service.record(db, "ticket.attachment", user_id=user.id, entity_type="maintenance",
                         entity_id=t.id, detail={"attachment_id": row.id, "size": row.size,
                                                 "mime": row.mime, "ticket_id": t.id})
    return {"ok": True, "attachment": attachment_service.out(row)}


@router.get("/attachments/{attach_id}")
def get_attachment(attach_id: int, db: Session = Depends(get_db),
                   user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    a = attachment_service.get(db, attach_id)
    t = db.get(dbm.MaintenanceTask, a.ticket_id)
    if t is not None:
        _check_scope(db, user, t)
    fp = pathlib.Path(a.stored_path)
    if not fp.exists():
        raise HTTPException(status_code=410, detail="файл вложения недоступен")
    return FileResponse(str(fp), media_type=a.mime, filename=a.filename,
                        content_disposition_type="inline")
