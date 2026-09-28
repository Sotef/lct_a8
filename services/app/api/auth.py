# -*- coding: utf-8 -*-
"""Auth-ручки (BACKEND_SPEC §5.1)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models_db as dbm
from .. import schemas
from .. import security as sec
from ..database import get_db
from ..deps import require_roles
from ..services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(u: dbm.User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name,
            "role": u.role, "district": u.district}


@router.post("/login", response_model=schemas.LoginResponse)
def login(req: schemas.LoginRequest, request: Request,
          db: Session = Depends(get_db)):
    client = request.client.host if request.client else "unknown"
    sec.check_login_rate_limit(client)
    user = db.query(dbm.User).filter(dbm.User.username == req.username).first()
    if user is None or not sec.verify_password(req.password, user.password_hash):
        audit_service.record(db, "auth.login_failed",
                             user_id=user.id if user else None,
                             entity_type="user", entity_id=req.username[:120],
                             detail={"username": req.username[:120],
                                     "reason": "bad_credentials"},
                             level=logging.WARNING)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="неверный логин или пароль")
    if not user.active:
        audit_service.record(db, "auth.login_failed", user_id=user.id,
                             entity_type="user", entity_id=str(user.id),
                             detail={"username": user.username, "reason": "disabled"},
                             level=logging.WARNING)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="пользователь отключён")
    audit_service.record(db, "auth.login", user_id=user.id, entity_type="user",
                         entity_id=user.id, detail={"username": user.username,
                                                    "role": user.role})
    return {"access_token": sec.create_access_token(user.id),
            "refresh_token": sec.create_refresh_token(user.id),
            "user": _user_out(user)}


@router.post("/refresh")
def refresh(req: schemas.RefreshRequest, db: Session = Depends(get_db)):
    payload = sec.decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="ожидался refresh-токен")
    user = db.get(dbm.User, int(payload["sub"], ))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="пользователь не найден")
    return {"access_token": sec.create_access_token(user.id)}


@router.get("/me")
def me(user: dbm.User = Depends(require_roles("tech", "dispatcher", "central"))):
    return _user_out(user)


@router.get("/admin/users")
def list_users(admin: dbm.User = Depends(require_roles("central")),
               db: Session = Depends(get_db)):
    """Список пользователей (только central)."""
    rows = db.query(dbm.User).order_by(dbm.User.id.asc()).all()
    return {"users": [{"id": u.id, "username": u.username,
                       "full_name": u.full_name, "role": u.role,
                       "district": u.district, "active": u.active} for u in rows]}


@router.post("/admin/create-user")
def create_user(req: schemas.CreateUserRequest,
                db: Session = Depends(get_db),
                admin: dbm.User = Depends(require_roles("central"))):
    exists = db.query(dbm.User).filter(dbm.User.username == req.username).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="пользователь уже существует")
    user = dbm.User(username=req.username, full_name=req.full_name,
                    role=req.role, district=req.district,
                    password_hash=sec.hash_password(req.password))
    db.add(user)
    db.flush()
    audit_service.record(db, "admin.create_user", user_id=admin.id, entity_type="user",
                         entity_id=user.id, commit=False,
                         detail={"username": req.username, "role": req.role,
                                 "district": req.district})
    db.commit()
    return _user_out(user)


@router.post("/logout")
def logout(db: Session = Depends(get_db),
           user: dbm.User = Depends(require_roles("tech", "dispatcher", "central"))):
    audit_service.record(db, "auth.logout", user_id=user.id, entity_type="user",
                         entity_id=user.id, detail={"username": user.username})
    return {"ok": True}


class _ActiveReq(BaseModel):
    active: bool


@router.post("/admin/users/{user_id}/active")
def set_user_active(user_id: int, req: _ActiveReq, db: Session = Depends(get_db),
                    admin: dbm.User = Depends(require_roles("central"))):
    u = db.get(dbm.User, user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="пользователь не найден")
    if u.id == admin.id and not req.active:
        raise HTTPException(status_code=400, detail="нельзя заблокировать самого себя")
    u.active = req.active
    audit_service.record(db, "admin.set_user_active", user_id=admin.id,
                         entity_type="user", entity_id=u.id, commit=False,
                         detail={"username": u.username, "active": req.active})
    db.commit()
    return {"ok": True, "id": u.id, "active": u.active}