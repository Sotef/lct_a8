# -*- coding: utf-8 -*-
"""ORM-модели (BACKEND_SPEC §6.1). JSON — портабельный тип (SQLite/PostgreSQL)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String,
    Text, UniqueConstraint,
)

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False, default="dispatcher")  # tech|dispatcher|central
    password_hash = Column(String(255), nullable=False)
    ad_sid = Column(String(255), nullable=True)
    district = Column(String(120), nullable=True)   # для RBAC «объекты своего района»
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True)
    task = Column(String(20), nullable=False, index=True)
    channel_id = Column(String(64), nullable=False, index=True)
    object_id = Column(String(64), nullable=False, index=True)
    bucket_ts = Column(DateTime(timezone=True), nullable=False, index=True)
    p24 = Column(Float)
    p72 = Column(Float)                          # P(событие ≤ 72 ч) — короткий горизонт
    risk30 = Column(Float)
    risk30_cal = Column(Float)
    exp_days = Column(Float)
    score = Column(Float)
    severity = Column(Float)
    scale = Column(Float)
    plan = Column(String(40))
    surv_points = Column(JSON)                  # [6ч,12ч,24ч,48ч,7д,14д,30д]
    factors = Column(JSON)                      # топ-фичи «почему»
    features_json = Column(JSON)                # полный срез фич канала
    event_flag = Column(Integer, default=0)     # активное событие на бакете
    obs_days = Column(Float)                    # дней с последнего события
    model_version = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_predictions_task_bucket", "task", "bucket_ts"),
        Index("ix_predictions_object_task", "object_id", "task"),
        Index("ix_predictions_task_score", "task", "score"),
    )


class Decision(Base):
    __tablename__ = "decisions"
    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=False, index=True)
    decision = Column(String(20), nullable=False)   # confirm|reject|preventive
    responsible_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(80), nullable=False, index=True)
    entity_type = Column(String(60), nullable=True)
    entity_id = Column(String(120), nullable=True)
    detail = Column(JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    kind = Column(String(40), nullable=False)     # journal|panel|drift
    last_load_start = Column(DateTime(timezone=True))
    last_load_end = Column(DateTime(timezone=True))
    rows = Column(Integer)
    status = Column(String(20), default="unknown")  # idle|running|ok|error
    error = Column(Text)
    checkpoint = Column(JSON)                     # chk: {"ид_события": max}


class ModelRegistry(Base):
    __tablename__ = "models_registry"
    id = Column(Integer, primary_key=True)
    task = Column(String(20), nullable=False, unique=True, index=True)
    version = Column(String(64), nullable=False)
    model_path = Column(String(400), nullable=False)
    calib_path = Column(String(400))
    z_stats_path = Column(String(400))
    trained_on = Column(String(40))
    metrics_json = Column(JSON)
    active = Column(Boolean, nullable=False, default=True)


class ObjectRef(Base):
    __tablename__ = "objects_ref"
    id = Column(Integer, primary_key=True)
    object_id = Column(String(64), unique=True, nullable=False, index=True)
    hierarchy_level = Column(Integer, nullable=False)
    parent_id = Column(String(64), nullable=True)
    object_type = Column(String(60))            # district|controlHouse|guardObject
    name = Column(String(255))
    district = Column(String(120), nullable=True)  # корневой район (для RBAC/карты)


class ChannelRef(Base):
    __tablename__ = "channels_ref"
    id = Column(Integer, primary_key=True)
    channel_id = Column(String(64), unique=True, nullable=False, index=True)
    system_type = Column(String(120))
    sensor_type = Column(String(120))
    tag = Column(String(255))
    sensor_name = Column(String(255))
    object_id = Column(String(64), nullable=False, index=True)


class ObjectRiskL2(Base):
    __tablename__ = "object_risk_l2"
    id = Column(Integer, primary_key=True)
    object_id = Column(String(64), nullable=False, index=True)
    task = Column(String(20), nullable=False, index=True)
    channel_count = Column(Integer)
    risk30_max = Column(Float)
    risk30_mean = Column(Float)
    top_channels = Column(JSON)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (UniqueConstraint("object_id", "task", name="uq_obj_task"),)


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"
    id = Column(Integer, primary_key=True)
    task = Column(String(20), nullable=False, index=True)
    channel_id = Column(String(64), nullable=False)
    object_id = Column(String(64), nullable=False, index=True)
    plan_bucket = Column(String(40))
    score = Column(Float)
    due_from = Column(DateTime(timezone=True))
    due_to = Column(DateTime(timezone=True))
    status = Column(String(20), default="suggested")  # suggested|assigned|done|cancelled
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(120), primary_key=True)
    value = Column(JSON)