# -*- coding: utf-8 -*-
"""Серверное правило алертов (MOBILE_PLAN §4.6).

Вызывается после каждого тика прогноза. Правило «P(событие ≤ 7 дней) ≥ порога»
и 12-часовая тишина по датчику перенесены с клиента (localStorage notify.js) на
сервер: так push приходит при закрытом приложении, а два устройства одного
пользователя не создают два уведомления по одному датчику.

Журнал ``alert_log`` — источник для экрана «Алерты» и фолбэк-поллинга.
"""
from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import func

from .. import config
from .. import models_db as dbm
from .. import task_cfg
from ..database import SessionLocal
from ..services import prediction_service as ps
from ..services import push_service

log = logging.getLogger("alerts")


def _aware(d: dt.datetime | None) -> dt.datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def run(db=None, force: bool = False) -> dict:
    """Один проход правила. force=True — игнорировать окно «тишины» (приёмка/демо)."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        return _run(db, force)
    finally:
        if own:
            db.close()


def _run(db, force: bool) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    min_p7 = config.ALERTS_MIN_P7D
    silence = dt.timedelta(hours=config.ALERTS_SILENCE_HOURS)

    candidates: list[tuple] = []
    for task in task_cfg.ALL_TASKS:
        last = ps.latest_bucket_ts(db, task)
        if last is None:
            continue
        q = (db.query(dbm.Prediction, dbm.ChannelRef.sensor_type,
                      dbm.ChannelRef.sensor_name, dbm.ObjectRef)
             .outerjoin(dbm.ChannelRef,
                        dbm.ChannelRef.channel_id == dbm.Prediction.channel_id)
             .outerjoin(dbm.ObjectRef, dbm.ObjectRef.object_id == dbm.Prediction.object_id)
             .filter(dbm.Prediction.task == task, dbm.Prediction.bucket_ts == last,
                     dbm.current_only()))
        for p, st, sn, obj in q.all():
            p7 = ps._p7d(p.surv_points)
            if p7 is None or p7 < min_p7:
                continue
            candidates.append((task, float(p7), p, st, sn, obj))

    candidates.sort(key=lambda x: -x[1])
    candidates = candidates[:config.ALERTS_TOP_K]

    kind = "push" if (config.ALERTS_PUSH and push_service.vapid_configured()) else "inapp"
    fired: list[dict] = []
    for task, p7, p, st, sn, obj in candidates:
        last_sent = (db.query(func.max(dbm.AlertLog.sent_at))
                     .filter(dbm.AlertLog.task == task,
                             dbm.AlertLog.channel_id == p.channel_id).scalar())
        if not force and _aware(last_sent) and _aware(last_sent) > now - silence:
            continue
        db.add(dbm.AlertLog(task=task, channel_id=p.channel_id, object_id=p.object_id,
                            risk_value=p7, kind=kind))
        fired.append({"task": task, "p7d": p7, "id": p.id, "channel_id": p.channel_id,
                      "object_id": p.object_id,
                      "object_name": getattr(obj, "name", None), "sensor": st or sn})
    db.commit()

    pushed = 0
    if config.ALERTS_PUSH and fired:
        pushed = _push(db, fired)

    log.info("alerts run: candidates=%s fired=%s pushed=%s kind=%s",
             len(candidates), len(fired), pushed, kind)
    return {"candidates": len(candidates), "fired": len(fired), "pushed": pushed,
            "kind": kind, "min_p7d": min_p7}


def _push(db, fired: list[dict]) -> int:
    """Рассылка по подписчикам с учётом RBAC-скоупа (район пользователя)."""
    from ..deps import scoped_object_ids
    subs = db.query(dbm.PushSubscription).all()
    by_user: dict[int, list] = {}
    for s in subs:
        by_user.setdefault(s.user_id, []).append(s)
    total = 0
    for uid in by_user:
        user = db.get(dbm.User, uid)
        if user is None or not user.active:
            continue
        allowed = scoped_object_ids(user, db)
        mine = [a for a in fired
                if allowed is None or a["object_id"] in allowed]
        for a in mine[:3]:                       # не больше 3 push на пользователя за проход
            tm = API_META.get(a["task"], {})
            title = f"{tm.get('short', a['task'])}: риск на неделю {a['p7d'] * 100:.0f}%"
            body = f"{a['object_name'] or ('объект ' + str(a['object_id']))} · {a['sensor'] or a['channel_id']}"
            total += push_service.send(db, uid, title, body,
                                       url=f"/#/forecasts?id={a['id']}",
                                       tag=f"{a['task']}:{a['channel_id']}")
    return total


API_META = {"fire": {"short": "Пожарный риск"}, "access": {"short": "Несанкц. доступ"},
            "sensor": {"short": "Отказ датчика"}, "wear": {"short": "Износ инфраструктуры"}}
