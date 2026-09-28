# -*- coding: utf-8 -*-
"""Объекты: карта/дерево, риски объектов, датчики объекта (карта диспетчера)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import task_cfg
from ..database import get_db
from ..deps import require_roles, scoped_object_ids
from ..services import object_service

router = APIRouter(prefix="/objects", tags=["objects"])


@router.get("")
def objects(db: Session = Depends(get_db),
            user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Дерево объектов + риски.

    `risks` — материализация L2 (risk30 по каналам, история), `risk7d` — прогноз
    P(событие ≤ 7 дней) максимумом по каналам объекта за последние 3 суток прогнозов:
    именно его показывает карта/список, чтобы «не долбить» месячным risk30.
    """
    allowed = scoped_object_ids(user, db)
    tree = object_service.object_tree(db, object_ids=allowed)
    risks = object_service.object_risks(db, object_ids=allowed)
    risk_by_obj = {}
    for r in risks:
        risk_by_obj.setdefault(r["object_id"], {})[r["task"]] = {
            "risk30_max": r["risk30_max"], "risk30_mean": r["risk30_mean"],
            "channel_count": r["channel_count"], "top_channels": r["top_channels"]}
    r7 = object_service.risk7d_by_object(db, object_ids=allowed)
    for node in tree["tree"]:
        node["risks"] = risk_by_obj.get(node["object_id"], {})
        node["risk7d"] = r7.get(str(node["object_id"]), {})
    return tree


@router.get("/graph")
def objects_graph(db: Session = Depends(get_db),
                  user: dbm.User = Depends(
                      require_roles("dispatcher", "central", "tech"))):
    """Схема связности объектов и пикетов (для «Графа систем»).

    Каждому узлу добавляется `risk7d` — P(событие ≤ 7 дней) по направлениям
    (максимум по каналам объекта на актуальном бакете) для раскраски графа.
    """
    allowed = scoped_object_ids(user, db)
    data = object_service.graph_data(db)
    r7 = object_service.risk7d_by_object(db, object_ids=allowed)
    for node in data.get("nodes", []):
        node["risk7d"] = r7.get(str(node["id"]), {})
    if allowed is not None:
        keep = set(allowed)
        data["nodes"] = [n for n in data["nodes"] if n["id"] in keep]
        data["hubs"] = [h for h in data["hubs"] if set(h["objects"]) & keep]
        data["links"] = [l for l in data["links"]
                         if l["target"] in keep
                         and any(h["id"] == l["source"] for h in data["hubs"])]
    return data


@router.get("/{object_id}")
def object_detail(object_id: str, db: Session = Depends(get_db),
                  user: dbm.User = Depends(
                      require_roles("dispatcher", "central", "tech"))):
    allowed = scoped_object_ids(user, db)
    if allowed is not None and object_id not in allowed:
        raise HTTPException(status_code=403, detail="объект вне вашего района")
    obj = db.query(dbm.ObjectRef).filter_by(object_id=object_id).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="объект не найден")
    channels = (db.query(dbm.ChannelRef)
                .filter_by(object_id=object_id).all())
    return {"object": {"object_id": obj.object_id, "name": obj.name,
                       "type": obj.object_type, "district": obj.district,
                       "parent_id": obj.parent_id},
            "channels": [{"channel_id": c.channel_id, "sensor_type": c.sensor_type,
                          "system_type": c.system_type, "name": c.sensor_name,
                          "tag": c.tag} for c in channels],
            "risks": object_service.object_risks(db, object_ids=[object_id])}


@router.get("/{object_id}/risks")
def object_risks(object_id: str, task: str | None = Query(None),
                 db: Session = Depends(get_db),
                 user: dbm.User = Depends(
                     require_roles("dispatcher", "central", "tech"))):
    allowed = scoped_object_ids(user, db)
    if allowed is not None and object_id not in allowed:
        raise HTTPException(status_code=403, detail="объект вне вашего района")
    if task and task not in task_cfg.ALL_TASKS:
        raise HTTPException(status_code=400, detail="неизвестная задача")
    return {"object_id": object_id,
            "risks": object_service.object_risks(db, object_ids=[object_id], task=task)}