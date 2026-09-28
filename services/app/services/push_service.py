# -*- coding: utf-8 -*-
"""Web Push: подписки устройств и рассылка уведомлений (MOBILE_PLAN §4.6).

Библиотека ``pywebpush`` опциональна: если она не установлена или VAPID-ключи
не заданы, рассылка становится no-op (``sent=0``), а клиент продолжает работать
на фолбэк-поллинге ``GET /alerts``. Это осознанно: сервис не должен падать из-за
отсутствия опциональной зависимости.
"""
from __future__ import annotations

import json
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm

log = logging.getLogger("push")

try:                                        # опциональная зависимость
    from pywebpush import WebPushException, webpush  # type: ignore
    _HAVE_WEBPUSH = True
except Exception:                           # noqa: BLE001
    webpush = None
    WebPushException = Exception            # type: ignore
    _HAVE_WEBPUSH = False


def vapid_configured() -> bool:
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY and _HAVE_WEBPUSH)


def public_key() -> str:
    return config.VAPID_PUBLIC_KEY or ""


def subscribe(db: Session, user_id: int, endpoint: str, p256dh: str,
              auth: str, ua: str | None = None) -> dict:
    endpoint = (endpoint or "").strip()
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="неполная push-подписка")
    row = db.query(dbm.PushSubscription).filter(
        dbm.PushSubscription.endpoint == endpoint).first()
    if row is None:
        row = dbm.PushSubscription(user_id=user_id, endpoint=endpoint,
                                   p256dh=p256dh, auth=auth, ua=(ua or "")[:200])
        db.add(row)
    else:
        row.user_id = user_id
        row.p256dh = p256dh
        row.auth = auth
        row.ua = (ua or row.ua or "")[:200]
        row.fails = 0
    db.commit()
    return {"ok": True, "id": row.id, "endpoint": endpoint}


def unsubscribe(db: Session, user_id: int, endpoint: str | None) -> dict:
    q = db.query(dbm.PushSubscription).filter(dbm.PushSubscription.user_id == user_id)
    if endpoint:
        q = q.filter(dbm.PushSubscription.endpoint == endpoint)
    n = 0
    for row in q.all():
        db.delete(row)
        n += 1
    db.commit()
    return {"ok": True, "removed": n}


def _subs_for(db: Session, user_id: int | None) -> list[dbm.PushSubscription]:
    q = db.query(dbm.PushSubscription)
    if user_id is not None:
        q = q.filter(dbm.PushSubscription.user_id == user_id)
    return q.all()


def _send_one(db: Session, sub: dbm.PushSubscription, payload: dict) -> bool:
    if not vapid_configured():
        return False
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint,
                               "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=config.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": config.VAPID_SUBJECT},
            timeout=8,
        )
        import datetime as dt
        sub.last_ok_at = dt.datetime.now(dt.timezone.utc)
        sub.fails = 0
        return True
    except WebPushException as exc:          # type: ignore[misc]
        code = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning("push failed endpoint=%s code=%s", sub.endpoint[:60], code)
        sub.fails = (sub.fails or 0) + 1
        if code in (404, 410):               # подписка мертва — удаляем
            db.delete(sub)
        return False
    except Exception as exc:                 # noqa: BLE001
        log.warning("push error: %s", exc)
        sub.fails = (sub.fails or 0) + 1
        return False


def send(db: Session, user_id: int | None, title: str, body: str,
         url: str = "/#/alerts", tag: str | None = None) -> int:
    """Отправляет уведомление на все устройства пользователя (или всем)."""
    if not _HAVE_WEBPUSH:
        log.info("push skipped: pywebpush не установлен")
        return 0
    if not vapid_configured():
        log.info("push skipped: VAPID-ключи не заданы")
        return 0
    subs = _subs_for(db, user_id)
    if not subs:
        return 0
    payload = {"title": title, "body": body, "url": url, "tag": tag}
    sent = sum(1 for s in subs if _send_one(db, s, payload))
    try:
        db.commit()
    except Exception:                        # noqa: BLE001
        db.rollback()
    return sent


def test(db: Session, user_id: int) -> dict:
    sent = send(db, user_id, "Москоллектор ОДС",
                "Тестовое уведомление: push настроен и работает.",
                url="/#/alerts", tag="push-test")
    if not _HAVE_WEBPUSH:
        return {"ok": False, "sent": 0,
                "detail": "pywebpush не установлен на сервере (фолбэк-поллинг активен)"}
    if not vapid_configured():
        return {"ok": False, "sent": 0,
                "detail": "VAPID-ключи не заданы (фолбэк-поллинг активен)"}
    return {"ok": sent > 0, "sent": sent}
