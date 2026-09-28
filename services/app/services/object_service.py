# -*- coding: utf-8 -*-
"""Справочники объектов/каналов + риски объектов (карта диспетчера).

Диспетчер различает объекты: иерархия (district -> controlHouse/guardObject),
инж. системы и датчики на объекте (channels_ref). RBAC-фильтр по району — на
уровне депозитов (deps.scoped_object_ids).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import task_cfg
from ..research_bridge import module as _m


def load_references_into_db(db: Session) -> dict:
    """Загружает справочники research -> таблицы objects_ref/channels_ref (идемпотентно)."""
    if db.query(dbm.ObjectRef).count() > 0 and db.query(dbm.ChannelRef).count() > 0:
        return {"objects": db.query(dbm.ObjectRef).count(),
                "channels": db.query(dbm.ChannelRef).count()}
    du = _m("data_utils")
    objs = du.load_ref_objects()
    chs = du.load_ref_channels()
    # район (корень) для каждого объекта: первый уровень-дистрикт
    objs = objs.copy()
    objs["вид_объекта_clean"] = objs["вид_объекта"].astype(str).str.strip()
    cell = objs[(objs["иерархия_уровень"].astype(int) == 1)]
    if len(cell):
        root = cell.iloc[0]["ид_объект"]
    else:
        root = None
    level = objs["иерархия_уровень"].astype(int).to_dict()

    def district_of(oid: str) -> str | None:
        cur = str(oid)
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            lv = level.get(cur)
            if lv == 1:
                return cur
            parent = objs.loc[objs["ид_объект"] == cur, "родитель"]
            cur = str(parent.iloc[0]) if len(parent) and not pd.isna(parent.iloc[0]) else None
        return root

    district_of_cache = {o: district_of(o) for o in objs["ид_объект"]}

    db.query(dbm.ObjectRef).delete()
    db.query(dbm.ChannelRef).delete()
    for _, row in objs.iterrows():
        oid = str(row["ид_объект"])
        db.add(dbm.ObjectRef(
            object_id=oid,
            hierarchy_level=int(row["иерархия_уровень"]),
            parent_id=None if pd.isna(row["родитель"]) else str(row["родитель"]),
            object_type=str(row["вид_объекта_clean"]),
            name=str(row["диспетчерское_название_объекта"]),
            district=district_of_cache.get(oid)))
    ch_rows = [
        dbm.ChannelRef(
            channel_id=str(r["ид_канала_данных"]),
            system_type=None if pd.isna(r["тип_инж_системы"]) else str(r["тип_инж_системы"]),
            sensor_type=None if pd.isna(r["тип_датчика"]) else str(r["тип_датчика"]),
            tag=None if pd.isna(r["тег_инженерной_системы"]) else str(r["тег_инженерной_системы"]),
            sensor_name=None if pd.isna(r["название_датчика"]) else str(r["название_датчика"]),
            object_id=str(r["ид_объект"]))
        for _, r in chs.iterrows()
    ]
    db.add_all(ch_rows)
    db.commit()
    return {"objects": len(objs), "channels": len(chs)}


def object_tree(db: Session, object_ids: list[str] | None = None) -> dict:
    """Дерево объектов для карты (со скользящим риском L2).

    object_ids=None — все объекты; [] — пустое дерево (нет доступа).
    """
    q = db.query(dbm.ObjectRef)
    if object_ids is not None:
        q = q.filter(dbm.ObjectRef.object_id.in_(object_ids))
    objs = [{"object_id": o.object_id, "parent_id": o.parent_id,
             "name": o.name, "type": o.object_type, "level": o.hierarchy_level,
             "district": o.district} for o in q.all()]
    return {"tree": objs}


def object_risks(db: Session, object_ids: list[str] | None = None,
                 task: str | None = None) -> list[dict]:
    """L2-риск объектов (оценка по прогнозам текущего бакета + object_risk_l2)."""
    q = db.query(dbm.ObjectRiskL2)
    if object_ids is not None:
        q = q.filter(dbm.ObjectRiskL2.object_id.in_(object_ids))
    if task:
        q = q.filter(dbm.ObjectRiskL2.task == task)
    rows = [{"object_id": r.object_id, "task": r.task,
             "channel_count": r.channel_count,
             "risk30_max": r.risk30_max, "risk30_mean": r.risk30_mean,
             "top_channels": r.top_channels} for r in q.all()]
    return rows


def risk7d_by_object(db: Session, object_ids: list[str] | None = None,
                     buckets_back: int = 12) -> dict:
    """Максимальный P(событие ≤ 7 дней) по каналам объекта (колонка predictions.p7d).

    Берём последние `buckets_back` бакетов каждой задачи (по умолчанию 12 = 3 суток
    сим-времени), чтобы объект попадал в раскраску даже если в самом свежем бакете
    его каналы не были активны. Нужен графу систем и карточкам объектов.
    """
    from . import prediction_service as ps
    out: dict = {}
    for task in task_cfg.ALL_TASKS:
        last = ps.latest_bucket_ts(db, task)
        if last is None:
            continue
        since = last - dt.timedelta(hours=6 * max(1, buckets_back))
        q = (db.query(dbm.Prediction.object_id, func.max(dbm.Prediction.p7d))
             .filter(dbm.Prediction.task == task,
                     dbm.Prediction.bucket_ts >= since,
                     dbm.Prediction.p7d.isnot(None),
                     dbm.current_only())
             .group_by(dbm.Prediction.object_id))
        if object_ids is not None:
            q = q.filter(dbm.Prediction.object_id.in_(object_ids))
        for object_id, p7 in q.all():
            if p7 is None:
                continue
            d = out.setdefault(str(object_id), {})
            d[task] = max(d.get(task, 0.0), round(float(p7), 4))
    return out


def graph_data(db: Session, max_per_hub: int = 40) -> dict:
    """Схема связности: объекты ↔ «пикеты» (p3 из тега инж. системы).

    Хаб «ПК-пикет» связывает объекты, у которых есть каналы с одинаковым p3
    (схематично: контрольные пункты вдоль коллекторов). Данные — справочник.
    """
    import re
    from collections import defaultdict
    rows = db.query(dbm.ChannelRef.object_id, dbm.ChannelRef.tag).all()
    hub_objs = defaultdict(set)
    obj_hubs = defaultdict(set)
    for obj, tag in rows:
        if not tag:
            continue
        parts = [p for p in re.split(r"[.\-]+", tag.strip(".")) if p]
        p3 = parts[2] if len(parts) > 2 else None
        if not p3 or p3 in {"255", "4096", "4095", "0"}:
            continue
        hub_objs[p3].add(obj)
        obj_hubs[obj].add(p3)
    hubs = [{"id": "h_" + h, "label": "ПК-" + h, "count": len(o),
             "objects": sorted(o)[:max_per_hub]} for h, o in hub_objs.items()]
    nodes = []
    for o in db.query(dbm.ObjectRef).all():
        risk = {}
        for r in db.query(dbm.ObjectRiskL2).filter_by(object_id=o.object_id).all():
            risk[r.task] = round(r.risk30_max or 0, 3)
        nodes.append({"id": o.object_id, "name": o.name, "level": o.hierarchy_level,
                      "type": o.object_type, "district": o.district, "risk": risk,
                      "hubs": sorted(obj_hubs.get(o.object_id, ()))})
    links = []
    for hi, h in enumerate(hubs):
        hub_tag = h["id"].split("_", 1)[1]
        for oid in h["objects"]:
            if any(n["id"] == oid for n in nodes):
                links.append({"source": "h_" + hub_tag, "target": oid,
                              "weight": round(1.0 / (1 + h["count"]), 3)})
    return {"nodes": nodes, "hubs": hubs, "links": links}
    rows = [{"object_id": r.object_id, "task": r.task,
             "channel_count": r.channel_count,
             "risk30_max": r.risk30_max, "risk30_mean": r.risk30_mean,
             "top_channels": r.top_channels} for r in q.all()]
    return rows


def channel_last_events(db: Session, channel_id: str, n: int = 12) -> list[dict]:
    """Последние события канала за 30 дней относительно последнего бакета в БД."""
    from sqlalchemy import func
    last = db.query(func.max(dbm.Prediction.bucket_ts)).filter(
        dbm.Prediction.channel_id == channel_id, dbm.current_only()).scalar()
    since = last - dt.timedelta(days=30) if last is not None else None
    q = (db.query(dbm.Prediction)
         .filter(dbm.Prediction.channel_id == channel_id, dbm.current_only()))
    if since is not None:
        q = q.filter(dbm.Prediction.bucket_ts >= since)
    rows = (q.order_by(dbm.Prediction.bucket_ts.desc()).limit(n).all())
    return [{"bucket_ts": r.bucket_ts.isoformat(), "p24": r.p24,
             "risk30": r.risk30, "score": r.score} for r in rows]