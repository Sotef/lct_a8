# -*- coding: utf-8 -*-
"""Журналы: аудит действий пользователей, системный лог (live), ошибки фронта."""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..logging_setup import buffer, log_event
from ..services import audit_service

router = APIRouter(tags=["logs"])
client_log = logging.getLogger("client")


@router.get("/audit")
def audit(action: str | None = Query(None, description="точное имя или префикс с *"),
          user_id: int | None = Query(None), entity_type: str | None = Query(None),
          entity_id: str | None = Query(None), q: str | None = Query(None),
          hours: int | None = Query(None, ge=1, le=24 * 365),
          page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=500),
          db: Session = Depends(get_db),
          user: dbm.User = Depends(require_roles("central", "dispatcher"))):
    """Журнал действий. dispatcher видит только свои действия, central — все."""
    if user.role != "central":
        user_id = user.id
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)) if hours else None
    return audit_service.query(db, action=action, user_id=user_id,
                               entity_type=entity_type, entity_id=entity_id,
                               q=q, since=since, page=page, size=size)


@router.get("/audit/stats")
def audit_stats(hours: int = Query(24, ge=1, le=24 * 90), db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("central"))):
    return audit_service.stats(db, hours=hours)


@router.get("/audit/actions")
def audit_actions(user: dbm.User = Depends(require_roles("central", "dispatcher"))):
    return {"actions": [{"action": k, "action_ru": v}
                        for k, v in audit_service.ACTION_RU.items()]}


@router.get("/admin/logs")
def system_logs(after_id: int = Query(0, ge=0), level: str | None = Query(None),
                logger: str | None = Query(None), q: str | None = Query(None),
                limit: int = Query(300, ge=1, le=2000),
                user: dbm.User = Depends(require_roles("central"))):
    """Live-хвост системного лога из памяти (инкрементально по after_id)."""
    return buffer().query(after_id=after_id, level=level, logger=logger, q=q, limit=limit)


@router.get("/admin/logs/file")
def system_log_file(user: dbm.User = Depends(require_roles("central"))):
    fp = config.LOG_DIR / "app.log"
    if not fp.exists():
        return JSONResponse({"detail": "лог-файл ещё не создан"}, status_code=404)
    return FileResponse(str(fp), media_type="text/plain; charset=utf-8",
                        filename=f"app-{dt.date.today().isoformat()}.log")


class ClientLog(BaseModel):
    level: str = Field("error", pattern="^(debug|info|warning|error)$")
    message: str = Field(..., max_length=2000)
    url: str | None = Field(None, max_length=500)
    stack: str | None = Field(None, max_length=6000)
    context: dict | None = None


@router.post("/logs/client")
def client_logs(req: ClientLog, db: Session = Depends(get_db),
                user: dbm.User = Depends(get_current_user)):
    """Ошибки/события веб-интерфейса -> системный лог (+ audit для error)."""
    lv = {"debug": 10, "info": 20, "warning": 30, "error": 40}[req.level]
    log_event(client_log, lv, f"[ui] {req.message}", url=req.url,
              stack=(req.stack or "")[:3000], context=req.context,
              username=user.username)
    if lv >= 40:
        audit_service.record(db, "client.error", user_id=user.id, entity_type="ui",
                             entity_id=(req.url or "")[:100],
                             detail={"message": req.message[:500]},
                             level=logging.WARNING)
    return {"ok": True}
