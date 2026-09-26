# -*- coding: utf-8 -*-
"""Авторизация: JWT (Bearer, access/refresh), пароли, RBAC-утилиты, rate-limit.

MVP — локальная имитация каталога (SERVICE_PLAN §2); LDAP/AD подключается
адаптером adapters/ldap.py без изменения контракта.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt

from . import config

ROLES = {"tech", "dispatcher", "central"}


def hash_password(password: str) -> str:
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode("utf-8"),
                             bcrypt.gensalt(rounds=12)).decode("utf-8")
    except Exception:  # noqa: BLE001
        salt = secrets.token_hex(16)
        digest = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"sha256${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("sha256$"):
        _, salt, digest = password_hash.split("$", 2)
        return hashlib.sha256((salt + password).encode()).hexdigest() == digest
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode("utf-8"),
                              password_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def _create_token(subject: str, expires_delta: timedelta, token_type: str) -> str:
    payload = {"sub": subject, "type": token_type,
               "exp": datetime.now(timezone.utc) + expires_delta,
               "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    return _create_token(str(user_id), timedelta(minutes=config.ACCESS_TOKEN_MINUTES),
                         "access")


def create_refresh_token(user_id: int) -> str:
    return _create_token(str(user_id), timedelta(days=config.REFRESH_TOKEN_DAYS),
                         "refresh")


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, config.JWT_SECRET,
                             algorithms=[config.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="невалидный или истёкший токен") from exc
    if payload.get("type") not in ("access", "refresh"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="токен неправильного типа")
    return payload


def require_role(user, roles: set[str]) -> None:
    if not user or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="пользователь не активен")
    if user.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"роль {user.role} не имеет доступа")
    if user.role == "tech":
        # техник: только диспетчерское название/объекты своего района — см. deps
        pass


def allowed_districts(user) -> list[str]:
    """Районы, доступные пользователю (для RBAC-фильтра по объектам)."""
    if user.role in ("central", "dispatcher"):
        return []                       # [] = без ограничения
    if user.role == "tech":
        return [user.district] if user.district else []
    return []


# --- rate-limit на /auth/login -------------------------------------------------
_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def check_login_rate_limit(client_key: str) -> None:
    now = time.time()
    with _login_lock:
        hist = [t for t in _login_attempts.get(client_key, []) if now - t < 300]
        if len(hist) >= config.LOGIN_RATE_LIMIT:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="слишком много попыток входа, подождите 5 минут")
        hist.append(now)
        _login_attempts[client_key] = hist
        if len(_login_attempts) > 10_000:
            _login_attempts.clear()