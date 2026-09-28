# -*- coding: utf-8 -*-
"""Pydantic v2 схемы запросов/ответов."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    role: str
    district: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=120)
    role: str = Field(pattern="^(tech|dispatcher|central)$")
    full_name: str | None = None
    district: str | None = None
    password: str = Field(min_length=4)


class DecisionRequest(BaseModel):
    decision: str = Field(pattern="^(confirm|reject|preventive)$")
    responsible: str | None = None
    comment: str | None = None
    scheduled_at: datetime | None = None      # дата выезда для «профилактики»
    offline_ts: str | None = None             # ISO-время офлайн-решения (аудит, §4.5)


class DataLoadRequest(BaseModel):
    bucket: int | None = None
    tasks: list[str] | None = None


class ModelReloadRequest(BaseModel):
    tasks: list[str] | None = None