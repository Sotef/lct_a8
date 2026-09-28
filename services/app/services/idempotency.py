# -*- coding: utf-8 -*-
"""Идемпотентность офлайн-действий (MOBILE_PLAN §4.5).

Клиент PWA шлёт заголовок ``X-Client-Id: <uuid>`` на каждую изменяющую операцию.
Сервер хранит ``processed_actions`` и на повтор возвращает сохранённый ответ,
не применяя действие второй раз. Без этого ретраи из подземки создали бы дубли
решений/смен статуса заявок.
"""
from __future__ import annotations

import logging

from fastapi import Header
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models_db as dbm

log = logging.getLogger("idempotency")


def client_id_header(x_client_id: str | None = Header(default=None, alias="X-Client-Id")) -> str | None:
    """Заголовок X-Client-Id (None для десктопных запросов — поведение не меняется)."""
    cid = (x_client_id or "").strip()
    return cid[:64] or None


def get_processed(db: Session, client_id: str | None) -> dbm.ProcessedAction | None:
    if not client_id:
        return None
    return db.get(dbm.ProcessedAction, client_id)


def begin(db: Session, client_id: str | None, user_id: int | None,
          path: str) -> tuple[bool, dict | None]:
    """Резервирует client_id ДО применения действия (защита от гонки ретраев).

    -> (already_done, saved_response). Если already_done=True — действие уже
    выполнялось, повторять нельзя; saved_response — сохранённый ответ (или None,
    если ответ ещё не записан параллельным запросом).
    """
    if not client_id:
        return False, None
    existing = db.get(dbm.ProcessedAction, client_id)
    if existing is not None:
        return True, existing.response
    db.add(dbm.ProcessedAction(client_id=client_id, user_id=user_id,
                               path=path[:200], response=None))
    try:
        db.commit()
    except IntegrityError:          # параллельный ретрай успел первым
        db.rollback()
        existing = db.get(dbm.ProcessedAction, client_id)
        return True, (existing.response if existing else None)
    return False, None


def finish(db: Session, client_id: str | None, response: dict) -> None:
    """Сохраняет ответ успешного действия (повтор его вернёт)."""
    if not client_id:
        return
    row = db.get(dbm.ProcessedAction, client_id)
    if row is not None:
        row.response = response
        db.commit()


def cancel(db: Session, client_id: str | None) -> None:
    """Снимает резерв, если действие не удалось — ретрай сможет его повторить."""
    if not client_id:
        return
    row = db.get(dbm.ProcessedAction, client_id)
    if row is not None and row.response is None:
        db.delete(row)
        db.commit()


def remember(db: Session, client_id: str | None, user_id: int | None,
             path: str, response: dict, commit: bool = True) -> None:
    """Разовая запись (для ручек, которым не нужен резерв через begin())."""
    if not client_id:
        return
    row = dbm.ProcessedAction(client_id=client_id, user_id=user_id,
                              path=path[:200], response=response)
    db.add(row)
    if commit:
        try:
            db.commit()
        except IntegrityError:      # параллельный ретрай записал первым — это нормально
            db.rollback()
            log.info("processed_action race for %s", client_id)
