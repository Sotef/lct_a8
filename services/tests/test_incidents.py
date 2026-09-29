# -*- coding: utf-8 -*-
"""Происшествия журнала: логирование в аудит/системный лог и «свежесть» (24 ч).

Проверяем:
  * `incident_log.log_bucket` пишет происшествия (event_flag=1) в audit_log и
    дедуплицирует повторный пересчёт того же бакета;
  * `/meta/events` помечает недавние происшествия (`свежее`) и считает `summary.recent`,
    а недавние всегда попадают в выдачу.

Запуск: services\\.venv\\Scripts\\python.exe -m pytest tests/test_incidents.py -q
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import models_db as dbm  # noqa: E402
from app.database import Base  # noqa: E402
from app.services import incident_log  # noqa: E402
from app.services import object_service as osvc  # noqa: E402

B0 = dt.datetime(2026, 1, 1, 0, 0)
B1 = dt.datetime(2026, 1, 1, 6, 0)
B2 = dt.datetime(2026, 1, 1, 12, 0)
B3 = dt.datetime(2026, 1, 3, 12, 0)          # вне окна 24 ч (старше)


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(dbm.ObjectRef(object_id="OBJ1", hierarchy_level=2, name="Камера 1",
                        object_type="guardObject", district="OBJ1"))
    s.add(dbm.ChannelRef(channel_id="CHI", object_id="OBJ1",
                         sensor_type="Состояние насоса", sensor_name="Насос I"))
    def pred(bucket, cnt, flag, p24=0.2, risk=0.6):
        return dbm.Prediction(task="wear", channel_id="CHI", object_id="OBJ1",
                              bucket_ts=bucket, p24=p24, risk30=risk, risk30_cal=risk,
                              exp_days=10.0, score=0.5, severity=0.8, scale=1.0,
                              plan="следующий квартал", features_json={"неисправностей": cnt},
                              event_flag=flag, model_version="test")
    s.add_all([pred(B0, 0, 0), pred(B1, 0, 0, p24=0.7), pred(B2, 2, 1), pred(B3, 1, 1)])
    s.commit()
    return s


def test_incident_log_writes_and_dedups():
    db = _db()
    bucket2 = int((B2 - dt.datetime(1970, 1, 1)).total_seconds() // 21600)
    facts = db.query(dbm.Prediction).filter(
        dbm.Prediction.task == "wear", dbm.Prediction.bucket_ts == B2).all()
    n1 = incident_log.log_bucket(db, "wear", bucket2, facts)
    n2 = incident_log.log_bucket(db, "wear", bucket2, facts)     # повтор — дублей нет
    assert n1 == 1 and n2 == 0
    rows = (db.query(dbm.AuditLog)
            .filter(dbm.AuditLog.action == incident_log.ACTION).all())
    assert len(rows) == 1
    assert rows[0].detail["channel_id"] == "CHI" and rows[0].detail["bucket"] == bucket2
    db.close()


def test_events_marks_recent_and_keeps_them():
    """«Свежее» = последние recent_h часов от новейшего бакета (в демо — от сим-«сейчас»)."""
    db = _db()
    res = osvc.events_vs_forecast(db, "wear", n=1, recent_h=24)
    assert res["recent_h"] == 24
    # факты: B2 (старый) и B3 (свежий — в пределах 24 ч от новейшего бакета)
    assert res["summary"]["events"] == 2
    assert res["summary"]["recent"] == 1
    # недавнее происшествие обязано попасть в выдачу даже при n=1
    assert res["items"] and res["items"][0]["свежее"] is True
    assert res["items"][0]["bucket_ts"].startswith("2026-01-03T12")
    # старый факт помечен как несвежий (виден при большем n)
    allit = osvc.events_vs_forecast(db, "wear", n=60, recent_h=24)["items"]
    assert {x["свежее"] for x in allit} == {True, False}
    db.close()
