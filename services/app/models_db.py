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
    p7d = Column(Float)                          # P(событие ≤ 7 дней) — для графа/алертов
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
    # --- план ТО (см. README «План ТО: как приоритизируются заявки») ---
    age_days = Column(Float)                    # возраст оборудования: первая запись датчика
    norm_due = Column(DateTime(timezone=True))  # нормативный срок следующего ТО
    campaign = Column(Integer, default=0)       # бакет в «кампанийной» (ППР/аномальной) неделе
    plan_date = Column(DateTime(timezone=True))  # дата плана = min(прогноз, норматив)
    # 1 = прогноз «закреплён» как метка: на него ссылается решение диспетчера,
    # такие строки НЕ удаляются при перезапуске реплея и не участвуют в запросах
    # «текущего бакета» (нужны для дообучения — признаки + метка в одном месте)
    pinned = Column(Integer, default=0)
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

    # индекс для дедупликации происшествий журнала (action='incident.journal')
    __table_args__ = (Index("ix_audit_action_entity", "action", "entity_id"),)


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
    scheduled_at = Column(DateTime(timezone=True))   # назначенная дата выезда (диспетчер)
    # suggested|assigned|in_progress|done|cancelled
    status = Column(String(20), default="suggested")
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), nullable=True)
    source = Column(String(20), default="manual")      # auto|decision|manual
    priority = Column(String(10), default="medium")    # high|medium|low
    comment = Column(Text)
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # --- обоснование плана ТО (для прозрачности и анти-прыжков) ---
    age_days = Column(Float)                    # возраст оборудования на момент заявки
    norm_due = Column(DateTime(timezone=True))  # нормативный срок ТО (по периодичности)
    rationale = Column(Text)                    # JSON: почему такая дата/приоритет


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(120), primary_key=True)
    value = Column(JSON)


class PushSubscription(Base):
    """Подписка устройства на Web Push (MOBILE_PLAN §6.3)."""
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    ua = Column(String(200))
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_ok_at = Column(DateTime(timezone=True), nullable=True)
    fails = Column(Integer, nullable=False, default=0)


class AlertLog(Base):
    """Журнал отправленных алертов — серверная замена localStorage-«тишины» notify.js."""
    __tablename__ = "alert_log"
    id = Column(Integer, primary_key=True)
    task = Column(String(20), nullable=False)
    channel_id = Column(String(64), nullable=False)
    object_id = Column(String(64), nullable=True)
    risk_value = Column(Float, nullable=False)
    kind = Column(String(20), nullable=False, default="push")   # push | inapp
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (Index("ix_alert_log_pair", "task", "channel_id", "sent_at"),)


class ProcessedAction(Base):
    """Идемпотентность офлайн-действий (X-Client-Id) — MOBILE_PLAN §4.5."""
    __tablename__ = "processed_actions"
    client_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    path = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    response = Column(JSON)


class Attachment(Base):
    """Вложения (фото с объекта) — файлы хранятся вне БД, отдаются RBAC-эндпоинтом."""
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tasks.id"), nullable=False, index=True)
    filename = Column(String(200), nullable=False)
    mime = Column(String(80), nullable=False)
    size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    stored_path = Column(String(400), nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


def current_only():
    """Фильтр «прогнозы текущего круга реплея».

    Строки с `pinned=1` — служебные: это признаки, привязанные к решениям диспетчера
    (метки для дообучения), они сохраняются при перезапуске реплея и НЕ должны попадать
    в запросы «текущего бакета», историю и тренды.
    """
    from sqlalchemy import or_
    return or_(Prediction.pinned.is_(None), Prediction.pinned != 1)