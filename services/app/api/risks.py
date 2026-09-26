# -*- coding: utf-8 -*-
"""Ручки риска: топ-риски, план ТО (BACKEND_SPEC §5.2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles, scoped_object_ids
from ..services import prediction_service as ps

router = APIRouter(tags=["risks"])


def _check_task(task: str):
    if task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail=f"неизвестная задача: {task}")


@router.get("/top-risks")
def top_risks(task: str = Query(...), k: int = Query(200, ge=1, le=1000),
              active_only: bool = Query(False),
              bucket: int | None = Query(None, description="бакет (опционально)"),
              horizon: str = Query("30d", pattern="^(24h|72h|30d)$",
                                   description="горизонт сортировки: 24ч/72ч/30д"),
              db: Session = Depends(get_db),
              user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    _check_task(task)
    object_ids = scoped_object_ids(user, db)
    return ps.top_risks(task, k=k, active_only=active_only, db=db,
                        bucket=bucket, object_ids=object_ids, horizon=horizon)


@router.get("/top-objects")
def top_objects(task: str = Query(...), k: int = Query(50, ge=1, le=200),
                horizon: str = Query("72h", pattern="^(24h|72h|30d)$"),
                db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Топ объектов: сумма (вес датчика × вероятность события на горизонте)."""
    _check_task(task)
    object_ids = scoped_object_ids(user, db)
    return ps.top_objects(task, db, k=k, horizon=horizon, object_ids=object_ids)


@router.get("/maintenance-plan")
def maintenance_plan(task: str = Query(...),
                     bucket: int | None = Query(None),
                     db: Session = Depends(get_db),
                     user: dbm.User = Depends(
                         require_roles("dispatcher", "central", "tech"))):
    _check_task(task)
    allowed = scoped_object_ids(user, db)
    return ps.maintenance_plan(task, db, bucket=bucket, object_ids=allowed)