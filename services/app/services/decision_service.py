# -*- coding: utf-8 -*-
"""Решения диспетчера + аудит (обратная петля ground-truth).

POST /forecasts/{id}/decision §6.2: подтвердить/отклонить/профилактика.
Все решения пишутся в audit_log и накапливаются как датасет для дообучения.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models_db as dbm


def create_decision(db: Session, prediction_id: int, decision: str,
                    user_id: int | None = None, username: str | None = None,
                    responsible: str | None = None,
                    comment: str | None = None,
                    scheduled_at=None,
                    client_id: str | None = None,
                    offline_ts: str | None = None) -> dbm.Decision:
    pred = db.get(dbm.Prediction, prediction_id)
    if pred is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"прогноз {prediction_id} не найден")
    from . import audit_service, maintenance_service
    dec = dbm.Decision(prediction_id=prediction_id, decision=decision,
                       responsible_id=user_id, comment=comment)
    db.add(dec)
    db.flush()
    ticket_id = None
    # «профилактика» -> заявка в maintenance_tasks (видна технику района);
    # если по каналу уже есть открытая авто-заявка — она назначается, дубль не создаётся
    if decision == "preventive":
        t, _ = maintenance_service.create_from_prediction(
            db, pred, source="decision", status="assigned", user_id=user_id,
            comment=comment, scheduled_at=scheduled_at, commit=False)
        ticket_id = t.id
    # «отклонить» закрывает предложенную авто-заявку по этому каналу
    elif decision == "reject":
        open_t = maintenance_service._find_open(db, pred.task, pred.channel_id)
        if open_t is not None and open_t.status == "suggested":
            open_t.status = "cancelled"
            ticket_id = open_t.id
    audit_service.record(
        db, "forecast.decision", user_id=user_id, entity_type="prediction",
        entity_id=prediction_id, commit=False,
        detail={"decision": decision, "responsible": responsible,
                "comment": comment, "username": username,
                "task": pred.task, "channel_id": pred.channel_id,
                "object_id": pred.object_id, "ticket_id": ticket_id,
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "source": "mobile-offline" if offline_ts else "web",
                **({"client_id": client_id} if client_id else {}),
                **({"offline_ts": offline_ts} if offline_ts else {}),
                "risk30": pred.risk30, "p24": pred.p24})
    db.commit()
    db.refresh(dec)
    dec.ticket_id = ticket_id  # не колонка — для ответа API
    return dec


def decision_history(db: Session, prediction_id: int) -> list[dict]:
    rows = (db.query(dbm.Decision, dbm.User.username)
            .outerjoin(dbm.User, dbm.User.id == dbm.Decision.responsible_id)
            .filter(dbm.Decision.prediction_id == prediction_id)
            .order_by(dbm.Decision.created_at.desc()).all())
    return [{"decision": d.decision,
             "responsible": u if u else d.responsible_id,
             "comment": d.comment,
             "created_at": d.created_at.isoformat()} for d, u in rows]