# -*- coding: utf-8 -*-
"""Прогнозы/карточки/решения (BACKEND_SPEC §5.2, §6.2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import schemas
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles, scoped_object_ids
from ..services import decision_service, forecast_card, prediction_service as ps

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


def _get_pred(db: Session, prediction_id: int) -> dbm.Prediction:
    p = db.get(dbm.Prediction, prediction_id)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="прогноз не найден")
    return p


def _check_scope(user: dbm.User, db: Session, p: dbm.Prediction) -> None:
    """tech видит карточки только объектов своего района (dispatcher/central — все)."""
    allowed = scoped_object_ids(user, db)
    if allowed is not None and p.object_id not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="объект вне вашего района")


@router.get("")
def list_forecasts(task: str = Query(...),
                   object_id: str | None = Query(None),
                   status_q: str | None = Query(None, alias="status"),
                   page: int = Query(1, ge=1),
                   size: int = Query(50, ge=1, le=200),
                   bucket: int | None = Query(None),
                   horizon: str = Query("30d", pattern="^(24h|72h|30d)$"),
                   db: Session = Depends(get_db),
                   user: dbm.User = Depends(
                       require_roles("dispatcher", "central", "tech"))):
    if task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    allowed = scoped_object_ids(user, db)
    if allowed is not None and object_id and object_id not in allowed:
        raise HTTPException(status_code=403, detail="объект вне вашего района")
    return ps.forecasts_list(task=task, object_id=object_id, status=status_q,
                             page=page, size=size, bucket=bucket, db=db,
                             object_ids=allowed, horizon=horizon)


@router.get("/{prediction_id}")
def get_forecast_card(prediction_id: int, db: Session = Depends(get_db),
                      user: dbm.User = Depends(
                          require_roles("dispatcher", "central", "tech"))):
    p = _get_pred(db, prediction_id)
    _check_scope(user, db, p)
    return forecast_card.build_card(db, p)


@router.get("/{prediction_id}/factors")
def factors(prediction_id: int, db: Session = Depends(get_db),
            user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    p = _get_pred(db, prediction_id)
    _check_scope(user, db, p)
    return {"factors": p.factors or [],
            "features": p.features_json or {}}


@router.post("/{prediction_id}/decision")
def decide(prediction_id: int, req: schemas.DecisionRequest,
           db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("dispatcher", "central"))):
    p = _get_pred(db, prediction_id)
    dec = decision_service.create_decision(
        db, prediction_id, req.decision, user_id=user.id,
        username=user.username, responsible=req.responsible, comment=req.comment)
    return {"ok": True, "prediction_id": prediction_id,
            "decision_id": dec.id}