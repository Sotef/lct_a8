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
                    comment: str | None = None) -> dbm.Decision:
    pred = db.get(dbm.Prediction, prediction_id)
    if pred is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"прогноз {prediction_id} не найден")
    dec = dbm.Decision(prediction_id=prediction_id, decision=decision,
                       responsible_id=user_id, comment=comment)
    db.add(dec)
    db.flush()
    # «профилактика» -> конкретная заявка в maintenance_tasks (видна технику района)
    if decision == "preventive":
        db.add(dbm.MaintenanceTask(
            task=pred.task, channel_id=pred.channel_id,
            object_id=pred.object_id, plan_bucket=pred.plan,
            score=pred.score, status="assigned"))
    db.add(dbm.AuditLog(
        user_id=user_id,
        action="forecast.decision",
        entity_type="prediction",
        entity_id=str(prediction_id),
        detail={"decision": decision, "responsible": responsible,
                "comment": comment, "username": username,
                "task": pred.task, "channel_id": pred.channel_id,
                "object_id": pred.object_id}))
    db.commit()
    db.refresh(dec)
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