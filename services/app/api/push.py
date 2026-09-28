# -*- coding: utf-8 -*-
"""Ручки Web Push (MOBILE_PLAN §6.1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models_db as dbm
from ..database import get_db
from ..deps import require_roles
from ..services import push_service

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeReq(BaseModel):
    endpoint: str
    keys: dict = Field(default_factory=dict)


class UnsubscribeReq(BaseModel):
    endpoint: str | None = None


@router.get("/vapid-public-key")
def vapid_public_key(user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    """Публичный VAPID-ключ для PushManager.subscribe (секреты не раскрываются)."""
    return {"key": push_service.public_key(),
            "configured": push_service.vapid_configured(),
            "enabled": push_service.vapid_configured()}


@router.post("/subscribe")
def subscribe(req: SubscribeReq, db: Session = Depends(get_db),
              user: dbm.User = Depends(require_roles("dispatcher", "central", "tech")),
              user_agent: str | None = Header(default=None, alias="User-Agent")):
    keys = req.keys or {}
    return push_service.subscribe(db, user.id, req.endpoint,
                                  keys.get("p256dh") or "", keys.get("auth") or "",
                                  ua=user_agent)


@router.delete("/subscribe")
def unsubscribe(req: UnsubscribeReq, db: Session = Depends(get_db),
                user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    return push_service.unsubscribe(db, user.id, req.endpoint)


@router.post("/test")
def test(db: Session = Depends(get_db),
         user: dbm.User = Depends(require_roles("dispatcher", "central", "tech"))):
    return push_service.test(db, user.id)
