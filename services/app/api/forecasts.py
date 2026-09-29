# -*- coding: utf-8 -*-
"""Прогнозы/карточки/решения (BACKEND_SPEC §5.2, §6.2)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import schemas
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles, scoped_object_ids
from ..services import audit_service, decision_service, forecast_card, prediction_service as ps
from ..services import idempotency as idem

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
    card = forecast_card.build_card(db, p)
    ticket = (db.query(dbm.MaintenanceTask)
              .filter(dbm.MaintenanceTask.task == p.task,
                      dbm.MaintenanceTask.channel_id == p.channel_id)
              .order_by(dbm.MaintenanceTask.id.desc()).first())
    card["ticket"] = None if ticket is None else {
        "id": ticket.id, "status": ticket.status, "priority": ticket.priority,
        "source": ticket.source,
        "due_to": ticket.due_to.isoformat() if ticket.due_to else None}
    audit_service.record(db, "forecast.view", user_id=user.id, entity_type="prediction",
                         entity_id=p.id, level=logging.DEBUG,
                         detail={"task": p.task, "channel_id": p.channel_id})
    return card


@router.get("/{prediction_id}/factors")
def factors(prediction_id: int, compute: bool = Query(False, description="посчитать SHAP, если не сохранены"),
            db: Session = Depends(get_db),
            user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    p = _get_pred(db, prediction_id)
    _check_scope(user, db, p)
    fac = p.factors
    if not fac and compute:
        fac = ps.compute_factors_for_prediction(db, p)
    return {"factors": fac or [], "features": p.features_json or {},
            "computed": bool(fac)}


@router.get("/{prediction_id}/facts")
def forecast_facts(prediction_id: int, lookback: int = Query(4, ge=1, le=20),
                   n: int = Query(8, ge=1, le=50),
                   threshold: float | None = Query(None, ge=0.0, le=1.0),
                   alert_q: float | None = Query(None, ge=0.5, le=0.9999),
                   db: Session = Depends(get_db),
                   user: dbm.User = Depends(
                       require_roles("dispatcher", "central", "tech"))):
    """«Предсказано / произошло» по каналу прогноза.

    Факты — реальные происшествия из журнала СМВУ (`event_flag = 1` в 6ч-бакете канала);
    для каждого факта указано, когда и с какой вероятностью его предсказали (или что пропустили).
    Плюс — что модель ожидает от текущего прогноза: окно `horizon_h` от бакета прогноза.
    """
    import datetime as _dt

    from ..services import object_service
    p = _get_pred(db, prediction_id)
    _check_scope(user, db, p)
    data = object_service.events_vs_forecast(db, p.task, channel_id=p.channel_id, n=n,
                                             lookback=lookback, threshold=threshold,
                                             alert_q=alert_q)
    p24 = object_service._p24(p)
    thr = data["threshold"]
    issued = p.bucket_ts
    return {
        "prediction_id": p.id,
        "task": p.task,
        "channel_id": p.channel_id,
        "выдано": issued.strftime("%d.%m %H:%M") if issued else None,
        "p24": round(p24, 4) if p24 is not None else None,
        "risk30": p.risk30,
        "ожидается_событие": bool(p24 is not None and p24 >= thr),
        "окно_до": (issued + _dt.timedelta(hours=data["horizon_h"])).strftime("%d.%m %H:%M")
                   if issued else None,
        "событие_в_этом_бакете": bool(p.event_flag == 1),
        "threshold": thr,
        "summary": data["summary"],
        "items": data["items"][:n],
        "note": data["note"],
    }


@router.post("/{prediction_id}/decision")
def decide(prediction_id: int, req: schemas.DecisionRequest,
           db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("dispatcher", "central")),
           client_id: str | None = Depends(idem.client_id_header)):
    path = f"/api/v1/forecasts/{prediction_id}/decision"
    already, saved = idem.begin(db, client_id, user.id, path)
    if already and saved is not None:
        return saved                       # повтор офлайн-решения: без второй записи
    try:
        p = _get_pred(db, prediction_id)
        dec = decision_service.create_decision(
            db, prediction_id, req.decision, user_id=user.id,
            username=user.username, responsible=req.responsible, comment=req.comment,
            scheduled_at=req.scheduled_at, client_id=client_id, offline_ts=req.offline_ts)
        res = {"ok": True, "prediction_id": prediction_id,
               "decision_id": dec.id, "ticket_id": getattr(dec, "ticket_id", None)}
    except HTTPException:
        idem.cancel(db, client_id)
        raise
    idem.finish(db, client_id, res)
    return res