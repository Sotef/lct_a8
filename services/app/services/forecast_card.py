# -*- coding: utf-8 -*-
"""Карточка прогноза GET /forecasts/{id} (обязательный сценарий, BACKEND_SPEC §6.2)."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import task_cfg
from ..adapters.journal import bucket_to_timestamp
from . import decision_service
from . import object_service
from .alarm_service import alarm_class, is_security


def build_card(db: Session, prediction: dbm.Prediction) -> dict:
    """Полная карточка: объект/система/канал, риск, горизонт, факторы, история."""
    obj = db.query(dbm.ObjectRef).filter(
        dbm.ObjectRef.object_id == prediction.object_id).first()
    ch = db.query(dbm.ChannelRef).filter(
        dbm.ChannelRef.channel_id == prediction.channel_id).first()
    tasks = dbm.Decision.__table__.columns.keys()  # noqa: F841
    _ac = alarm_class(ch.sensor_type if ch else None)      # класс по ответам заказчика

    risk_level = _risk_level(prediction)
    horizon = {
        "exp_days": prediction.exp_days,
        "surv_points": prediction.surv_points,   # [6ч,12ч,24ч,48ч,3д,7д,14д,30д]
        "labels": ["6ч", "12ч", "24ч", "48ч", "3д", "7д", "14д", "30д"],
    }
    season = _season_from_features(prediction.features_json)
    actions = _recommended_actions(prediction)
    return {
        "id": prediction.id,
        "task": prediction.task,
        "task_desc": task_cfg.TASKS[prediction.task]["desc"],
        "channel_id": prediction.channel_id,
        "channel_name": ch.sensor_name if ch else None,
        "sensor_type": ch.sensor_type if ch else None,
        "system_type": ch.system_type if ch else None,
        "tag": ch.tag if ch else None,
        # класс тревожного сообщения: авария (пожар/наводнение/газ/террор/аном. темп.)
        # или инцидент (электроснабжение/связь → «слепые зоны», косвенно допускает аварию)
        "класс_события": _ac["класс"],
        "группа_события": _ac["группа"],
        "косвенно_авария": _ac["косвенно_авария"],
        "охранный": is_security(ch.sensor_type if ch else None),
        "object": {
            "object_id": prediction.object_id,
            "name": obj.name if obj else None,
            "type": obj.object_type if obj else None,
            "district": obj.district if obj else None,
        },
        "probabilities": {
            "p24": prediction.p24,
            "p72": prediction.p72,
            "risk30": prediction.risk30,
            "risk30_cal": prediction.risk30_cal,
            "risk_used": prediction.risk30_cal if prediction.risk30_cal is not None
                         else prediction.risk30,
        },
        "risk_level": risk_level,
        "horizon": horizon,
        "rbam": {
            "severity": prediction.severity,
            "scale": prediction.scale,
            "score": prediction.score,
            "plan": prediction.plan,
        },
        "factors": prediction.factors,
        "features": prediction.features_json,
        "season": season,
        "last_events": object_service.channel_last_events(db, prediction.channel_id),
        "recommended_action": actions["action"],
        "preventive_order": actions["preventive_order"],
        "history": decision_service.decision_history(db, prediction.id),
        "model_version": prediction.model_version,
        "bucket_ts": prediction.bucket_ts.isoformat() if prediction.bucket_ts else None,
    }


def _risk_level(p: dbm.Prediction) -> str:
    risk = p.risk30_cal if p.risk30_cal is not None else p.risk30
    if risk is None:
        return "не определён"
    if risk >= 0.5:
        return "высокий"
    if risk >= 0.2:
        return "средний"
    return "низкий"


def _season_from_features(features: dict | None) -> dict | None:
    if not features:
        return None
    months = {1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май",
              6: "июнь", 7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь",
              11: "ноябрь", 12: "декабрь"}
    m = features.get("месяц")
    hour = features.get("час_бакета")
    dow = features.get("день_недели")
    return {
        "месяц": months.get(int(m)) if m is not None else None,
        "час_бакета": int(hour) if hour is not None else None,
        "день_недели": int(dow) if dow is not None else None,
        "доля_горизонта": features.get("доля_горизонта"),
    }


def _recommended_actions(p: dbm.Prediction) -> dict:
    plan = p.plan or "плановый"
    risk = p.risk30_cal if p.risk30_cal is not None else p.risk30
    if p.task == "fire":
        action = "Направить бригаду на осмотр, проверить дымовые/тепловые каналы и график горячих работ"
    elif p.task == "access":
        action = "Проверить СКУД/двери/объёмники, сверить журнал допусков на смену"
    elif p.task == "sensor":
        action = "Проверить работоспособность датчика, возможность замены/чистки"
    else:
        action = "Осмотр агрегата, внеплановый ТО по регламенту"
    if risk is not None and risk >= 0.5:
        action += " (высокий приоритет)"
    order = f"Превентивная заявка: {plan}, канал {p.channel_id}, object {p.object_id}"
    return {"action": action, "preventive_order": order}