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
from .alarm_service import alarm_class as _alarm_class

BUCKET_H = 6          # шаг прогноза/факта — 6 часов (как в research/features)

# «Факт» = в этом 6ч-бакете журнал зафиксировал тревожные сообщения/неисправности канала.
# Счётчики берём из features_json (панельные агрегаты журнала), а не из ML-метки event_flag:
# event_flag отвечает на другой вопрос («есть ли неисправность в бакете» — для износа это 87%
# бакетов), тогда как диспетчеру нужны именно тревожные сообщения.
FACT_COUNTERS = {
    "fire": ("задымлений", "серьёзн_ручной", "тревог_дым", "тревог_тепло", "тревог"),
    "access": ("тревог_дверь", "тревог_движение", "тревог"),
    "sensor": ("неисправностей",),
    "wear": ("неисправностей",),
}
FACT_KIND_RU = {
    "fire": "тревожное сообщение (пожарная система)",
    "access": "тревожное сообщение (охранная система)",
    "sensor": "неисправность датчика",
    "wear": "неисправность оборудования",
}

# Рабочие точки моделей: доля верхних прогнозов, где precision ≥ 0.7 на holdout
# (K@prec>=.7(24h) из research/dataset/final_metrics_v0.csv, n_holdout = 19999):
#   fire 152 → q = 1 − 152/19999 = 0.9924     wear 3035 → q = 1 − 3035/19999 = 0.8482
#   access/sensor — таких точек нет (модели слабые) → берём консервативные 0.98
ALERT_Q_BY_TASK = {"fire": 0.9924, "access": 0.98, "sensor": 0.98, "wear": 0.8482}
DEFAULT_ALERT_Q = 0.95


def _fact_count(p, task: str) -> int:
    """Сколько тревожных сообщений/неисправностей журнал зафиксировал в бакете канала."""
    fj = p.features_json
    if isinstance(fj, str):
        try:
            import json as _json
            fj = _json.loads(fj)
        except (ValueError, TypeError):
            fj = None
    if not isinstance(fj, dict):
        return 0
    out = 0
    for k in FACT_COUNTERS.get(task, ("тревог",)):
        try:
            out = max(out, int(fj.get(k) or 0))
        except (TypeError, ValueError):
            continue
    return out


def _p24(p) -> float | None:
    """P(событие ≤ 24 ч) строки прогноза: колонка p24, иначе 4-я точка S(t)."""
    if p.p24 is not None:
        return float(p.p24)
    sp = p.surv_points or []
    try:
        return max(0.0, 1.0 - float(sp[3]))
    except (TypeError, ValueError, IndexError):
        return None



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


def security_route(db: Session, object_id: str, hours: int = 72,
                   task: str | None = None) -> dict:
    """«Маршрут движения нарушителя» по сработкам охранной системы объекта.

    Заказчик (ответ 2): сработки охранной системы (люк, аварийный выход, дверь, движение,
    стекло) — авария категории «террор, проникновение нарушителя», по ним строится маршрут.
    Реальные координаты пикетов у нас не подтверждены, поэтому маршрут строится как
    упорядоченная по сим-времени цепочка сработавших охранных точек объекта
    (бакеты 6 ч, признак события — `predictions.event_flag`).
    """
    from .alarm_service import SECURITY_TYPES, alarm_class

    obj = db.get(dbm.ObjectRef, object_id)
    rows = (db.query(dbm.Prediction, dbm.ChannelRef.sensor_type, dbm.ChannelRef.sensor_name,
                     dbm.ChannelRef.tag)
            .outerjoin(dbm.ChannelRef, dbm.ChannelRef.channel_id == dbm.Prediction.channel_id)
            .filter(dbm.Prediction.object_id == object_id,
                    dbm.ChannelRef.sensor_type.in_(list(SECURITY_TYPES)),
                    dbm.current_only())
            .all())
    if task:
        rows = [r for r in rows if r[0].task == task]
    if not rows:
        return {"object_id": object_id,
                "object_name": getattr(obj, "name", None),
                "hours": hours, "points": [], "buckets": 0,
                "note": "по объекту нет охранных каналов в текущем круге прогнозов"}
    anchor = max((r[0].bucket_ts for r in rows if r[0].bucket_ts is not None), default=None)
    since = (anchor - dt.timedelta(hours=max(6, int(hours)))) if anchor else None
    points = []
    for p, st, sn, tag in rows:
        if p.event_flag != 1 or p.bucket_ts is None:
            continue
        if since is not None and p.bucket_ts < since:
            continue
        ac = alarm_class(st)
        points.append({"bucket_ts": p.bucket_ts.isoformat(),
                       "время": p.bucket_ts.strftime("%d.%m %H:%M"),
                       "channel_id": p.channel_id, "тип_датчика": st, "название_датчика": sn,
                       "тег_пикета": tag, "severity": p.severity,
                       "класс_события": ac["класс"], "группа_события": ac["группа"],
                       "task": p.task})
    points.sort(key=lambda x: (x["bucket_ts"], -(x["severity"] or 0)))
    return {"object_id": object_id, "object_name": getattr(obj, "name", None),
            "hours": int(hours), "buckets": len({p["bucket_ts"] for p in points}),
            "points": points,
            "note": ("цепочка сработок охранных каналов (люк, аварийный выход, дверь, движение, "
                     "стекло) по 6ч-бакетам сим-времени: разновидность аварии «террор, "
                     "проникновение нарушителя», диспетчер проводит дополнительную проверку")}


def events_vs_forecast(db: Session, task: str, object_id: str | None = None,
                       channel_id: str | None = None, n: int = 60,
                       threshold: float | None = None, alert_q: float | None = None,
                       lookback: int = 4, campaign_min: int = 15,
                       recent_h: int = 24) -> dict:
    """Реальные происшествия (из журнала) против прогнозов, которые их предсказывали.

    Факт — строка прогноза с `event_flag = 1` (в этом 6ч-бакете по каналу было
    зафиксировано событие: сработка/неисправность — как в журнале СМВУ).
    «Предсказано» — если в одном из `lookback` предыдущих бакетов того же канала
    P(событие ≤ 24 ч) была не ниже порога: тогда известны и дата прогноза, и упреждение.

    Возвращает: сводку (событий всего/предсказано/пропущено, алертов, попаданий,
    precision/recall, медианное упреждение) и список событий «что произошло + когда
    это предсказали».

    Порог по умолчанию — квантиль `alert_q` распределения p24 по текущему кругу задачи
    («алерт = попадание в верхние (1 − alert_q) прогнозов»): абсолютные вероятности у задач
    разные (дым ~1%, износ ~13%), а калибровка отличается от задачи к задаче — единый
    абсолютный порог был бы нечестным. Бакеты с массовыми сработками (≥ `campaign_min` каналов
    почти одновременно) помечаются как похожие на ППР/плановую проверку и исключаются из метрик.
    """
    from collections import defaultdict

    q = (db.query(dbm.Prediction, dbm.ChannelRef.sensor_type, dbm.ChannelRef.sensor_name,
                  dbm.ObjectRef.name)
         .outerjoin(dbm.ChannelRef, dbm.ChannelRef.channel_id == dbm.Prediction.channel_id)
         .outerjoin(dbm.ObjectRef, dbm.ObjectRef.object_id == dbm.Prediction.object_id)
         .filter(dbm.Prediction.task == task, dbm.current_only(),
                 dbm.Prediction.bucket_ts.isnot(None)))
    # «сим-сейчас»: без этого в панель могли попасть бакеты прошлого круга реплея
    # (в БД остаются закреплённые прогнозы) — тогда окно «свежих» 24 ч считалось бы от
    # будущей даты. Другие «актуальные» ручки (топ-риски, план ТО) делают так же.
    from . import prediction_service as _ps
    _last = _ps.latest_bucket_ts(db, task)
    if _last is not None:
        q = q.filter(dbm.Prediction.bucket_ts <= _last)
    if object_id:
        q = q.filter(dbm.Prediction.object_id == object_id)
    if channel_id:
        q = q.filter(dbm.Prediction.channel_id == channel_id)
    rows = q.order_by(dbm.Prediction.channel_id, dbm.Prediction.bucket_ts.asc()).all()

    facts_cnt = [_fact_count(p, task) for p, *_ in rows]
    base = (sum(1 for c in facts_cnt if c > 0) / len(facts_cnt)) if facts_cnt else 0.0
    q = float(alert_q) if alert_q is not None else ALERT_Q_BY_TASK.get(task, DEFAULT_ALERT_Q)
    p24_sorted = sorted((_p24(p) or 0.0) for p, *_ in rows)
    if threshold is not None:
        thr, auto_thr = float(threshold), False
    elif p24_sorted:
        idx = max(0, min(len(p24_sorted) - 1, int(round(q * len(p24_sorted))) - 1))
        thr, auto_thr = round(p24_sorted[idx], 5), True
    else:
        thr, auto_thr = 1.0, True

    per_bucket: dict = defaultdict(int)
    for c, (p, *_) in zip(facts_cnt, rows):
        if c > 0:
            per_bucket[p.bucket_ts] += 1
    campaigns = {b for b, c in per_bucket.items() if c >= max(2, int(campaign_min))}

    per_chan: dict = defaultdict(list)
    for c, (p, st, sn, obj_name) in zip(facts_cnt, rows):
        per_chan[p.channel_id].append((p, st, sn, obj_name, c))

    # «свежее» — происшествие за последние `recent_h` часов сим-времени (по последнему бакету)
    _last_ts = max((p.bucket_ts for p, *_ in rows if p.bucket_ts is not None), default=None)
    _cutoff = _last_ts - dt.timedelta(hours=max(1, int(recent_h))) if _last_ts else None
    items, leads = [], []
    events_total = planned_total = predicted_total = missed = alerts = hits = 0
    for seq in per_chan.values():
        p24 = [(_p24(x[0]) or 0.0) for x in seq]
        fact = [x[4] > 0 for x in seq]
        cnt = [x[4] for x in seq]
        camp = [seq[j][0].bucket_ts in campaigns for j in range(len(seq))]
        # алерт = прогноз выше порога вне кампании ППР; попадание — если в следующие
        # `lookback` бакетов по каналу действительно было событие (иначе ложная тревога)
        for i in range(len(seq)):
            if p24[i] >= thr and not camp[i]:
                alerts += 1
                if any(fact[j] and not camp[j]
                       for j in range(i + 1, min(len(seq), i + 1 + lookback))):
                    hits += 1
        for i, (p, st, sn, obj_name, c) in enumerate(seq):
            if not fact[i]:
                continue
            best = None                       # лучший прогноз среди предыдущих `lookback` бакетов
            for j in range(max(0, i - lookback), i):
                if best is None or p24[j] > p24[best]:
                    best = j
            predicted = best is not None and p24[best] >= thr
            lead_h = (i - best) * BUCKET_H if best is not None else None
            prev_ts = seq[best][0].bucket_ts if best is not None else None
            if camp[i]:
                planned_total += 1            # массовая сработка = ППР/плановая проверка
            else:
                events_total += 1
                if predicted:
                    predicted_total += 1
                    if lead_h:
                        leads.append(lead_h)
                else:
                    missed += 1
            ac = _alarm_class(st)
            items.append({
                "channel_id": p.channel_id,
                "object_id": p.object_id,
                "object_name": obj_name,
                "тип_датчика": st,
                "название_датчика": sn,
                "bucket_ts": p.bucket_ts.isoformat(),
                "произошло": p.bucket_ts.strftime("%d.%m %H:%M"),
                "предсказано": bool(predicted),
                "предсказано_за_ч": lead_h if predicted else None,
                "прогноз_бакет_ts": prev_ts.isoformat() if predicted and prev_ts else None,
                "прогноз_бакет": prev_ts.strftime("%d.%m %H:%M") if predicted and prev_ts else None,
                "прогноз_p24": round(p24[best], 4) if predicted else None,
                "risk30_на_факте": p.risk30,
                "класс_события": ac["класс"],
                "группа_события": ac["группа"],
                "prediction_id": p.id,
                "прогноз_prediction_id": seq[best][0].id if best is not None else None,
                "похоже_на_ППР": bool(camp[i]),
                "событий_в_бакете": int(c),
                "вид_факта": FACT_KIND_RU.get(task, "событие"),
                # свежесть: показывается постоянно в панели, не «пропадает» между тиками
                "свежее": bool(_cutoff is not None and p.bucket_ts is not None
                               and p.bucket_ts >= _cutoff),
            })
    items.sort(key=lambda x: x["bucket_ts"], reverse=True)
    leads.sort()
    # недавние (за `recent_h` ч) отдаём ВСЕГДА (не «пропадают»), старой историей добираем до n;
    # размер ответа ограничен, чтобы сотни свежих фактов не раздували payload
    _n = max(1, int(n))
    _recent = [x for x in items if x["свежее"]][:max(_n, 200)]
    _rest = [x for x in items if not x["свежее"]]
    _out = _recent + _rest[:max(0, _n - len(_recent))]
    return {
        "task": task,
        "task_desc": task_cfg.TASKS[task]["desc"],
        "fact_kind": FACT_KIND_RU.get(task, "событие"),
        "threshold": thr,
        "alert_q": q,
        "alert_q_by_task": ALERT_Q_BY_TASK,
        "base_rate": round(base, 5),
        "auto_threshold": auto_thr,
        "horizon_h": lookback * BUCKET_H,
        "campaign_min": int(campaign_min),
        "recent_h": max(1, int(recent_h)),
        "summary": {
            "events": events_total,
            "planned_ppr": planned_total,
            "predicted": predicted_total,
            "missed": missed,
            "alerts": alerts,
            "hits": hits,
            "recent": len(_recent),
            "precision": round(hits / alerts, 3) if alerts else None,
            "recall": round(predicted_total / events_total, 3) if events_total else None,
            "median_lead_h": leads[len(leads) // 2] if leads else None,
        },
        "items": _out,
        "note": ("факты — тревожные сообщения/неисправности журнала СМВУ в 6ч-бакете канала; "
                 "«предсказано» — модель давала P(событие ≤ 24 ч) не ниже порога в одном из "
                 "предыдущих бакетов того же канала. Порог = квантиль alert_q распределения p24 "
                 "задачи (верхние прогнозы); массовые сработки помечены как ППР и исключены "
                 "из метрик"),
    }


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