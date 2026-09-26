# -*- coding: utf-8 -*-
"""FastAPI-зависимости: текущий пользователь, RBAC, scoped-доступ по объектам."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models_db as dbm
from . import security as sec
from .database import get_db

_bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer),
                     db: Session = Depends(get_db)) -> dbm.User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="нет заголовка Authorization")
    payload = sec.decode_token(creds.credentials)
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="невалидный sub") from None
    user = db.get(dbm.User, user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="пользователь не найден или неактивен")
    return user


def require_roles(*roles: str):
    def dep(user: dbm.User = Depends(get_current_user)) -> dbm.User:
        sec.require_role(user, set(roles))
        return user
    return dep


def scoped_object_ids(user: dbm.User, db: Session) -> list[str] | None:
    """Список object_id, доступных пользователю (None = все объекты, [] = нет доступа).

    - central                -> None (все объекты);
    - dispatcher без района    -> None (по умолчанию видит предприятие);
    - dispatcher с районом     -> поддерево района (district/родитель-дети);
    - tech                    -> поддерево своего объекта/района.
    """
    if user.role == "central":
        return None
    if user.role == "dispatcher" and not user.district:
        return None
    d = user.district
    if not d:
        return []
    # расширение поддерева по parent_id (объектов всего ~100)
    rows = db.query(dbm.ObjectRef).all()
    by_parent: dict = {}
    for r in rows:
        by_parent.setdefault(r.parent_id, []).append(r.object_id)
    seen, stack = set(), [d]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(by_parent.get(cur, []))
    from sqlalchemy import or_
    q = db.query(dbm.ObjectRef.object_id).filter(
        or_(dbm.ObjectRef.district == d,
            dbm.ObjectRef.object_id.in_(seen)))
    return [o[0] for o in q.all()]