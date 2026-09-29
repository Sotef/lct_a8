# -*- coding: utf-8 -*-
"""Логирование реальных происшествий журнала СМВУ (срабатывания/неисправности).

Каждое происшествие бакета (строка прогноза с `event_flag = 1`) попадает:
  * в **системный лог** под логгером ``incident`` — видно во вкладке «Система» →
    «Системный лог» (фильтр логгеров), в live-буфере и в файле `app.log`;
  * в **audit_log** (действие ``incident.journal``) — durable, доступно через
    `/audit` и сохраняется после рестарта/сброса реплея.

Дедупликация: ключ (направление, бакет, канал) — повторный пересчёт того же бакета
(шаг/сброс/перерисовка) не создаёт дублей. Проверка — по уже записанным строкам
аудита, поэтому работает и в многопроцессной конфигурации.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models_db as dbm
from ..logging_setup import log_event
from . import audit_service

log = logging.getLogger("incident")

ACTION = "incident.journal"


def log_bucket(db: Session, task: str, bucket: int, preds,
               commit: bool = True) -> int:
    """Пишет происшествия бакета (event_flag=1) в лог и аудит. -> сколько записано."""
    facts = [p for p in (preds or []) if int(getattr(p, "event_flag", 0) or 0) == 1]
    if not facts:
        return 0
    prefix = f"{task}:{int(bucket)}:"
    existing = {
        r[0] for r in db.query(dbm.AuditLog.entity_id)
        .filter(dbm.AuditLog.action == ACTION,
                dbm.AuditLog.entity_id.like(prefix + "%")).all()
    }
    n = 0
    for p in facts:
        eid = prefix + str(p.channel_id)
        if eid in existing:
            continue
        detail = {
            "task": task,
            "bucket": int(bucket),
            "bucket_ts": p.bucket_ts.isoformat() if p.bucket_ts else None,
            "channel_id": str(p.channel_id),
            "object_id": str(p.object_id),
            "risk30": p.risk30,
            "p24": p.p24,
            "plan": p.plan,
            "кампания": int(p.campaign or 0),
        }
        log_event(log, logging.INFO,
                  f"[{task}] происшествие: канал {p.channel_id} "
                  f"(объект {p.object_id}, {detail['bucket_ts']})", **detail)
        audit_service.record(db, ACTION, entity_type="channel", entity_id=eid,
                             detail=detail, commit=False,
                             level=logging.DEBUG)   # в буфере не дублируем (см. incident)
        n += 1
    if commit and n:
        db.commit()
    return n
