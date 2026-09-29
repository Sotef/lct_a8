# -*- coding: utf-8 -*-
"""План ТО: возраст оборудования, нормативный срок, дата плана и анти-прыжок.

Проверяем чистые функции (to_norm / channel_meta) и интеграционно — гистерезис
срока в maintenance_service (открытая «предложенная» заявка не «прыгает» от
мелких пересчётов, а назначенную человеком дату модель не трогает).

Запуск: services\\.venv\\Scripts\\python.exe -m pytest tests/test_plan_norm.py -q
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="mc_plannorm_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SIM_CLOCK"] = "0"
os.environ["RUN_SCHEDULER"] = "0"
os.environ["AUTO_TICKETS"] = "0"
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["PLAN_HYSTERESIS_DAYS"] = "5"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app import config  # noqa: E402
from app import database as dbmod  # noqa: E402
from app import models_db as dbm  # noqa: E402
from app.services import channel_meta as cm  # noqa: E402
from app.services import maintenance_service as ms  # noqa: E402
from app.services import to_norm  # noqa: E402

NOW = dt.datetime(2026, 1, 10, 0, 0)


# --- чистые функции: периодичность и сроки ---------------------------------
def test_norm_period_by_type_and_task():
    assert to_norm.norm_period_days("fire", "Датчик дыма") == 180
    assert to_norm.norm_period_days("access", "КД Дверь") == 365
    assert to_norm.norm_period_days("wear", "Состояние насоса") == 180
    # неизвестный тип → откат на направление, затем на дефолт
    assert to_norm.norm_period_days("fire", "Нечто") == to_norm.NORM_PERIOD_DAYS_BY_TASK["fire"]
    assert to_norm.norm_period_days("nope", None) == to_norm.NORM_PERIOD_DEFAULT_DAYS


def test_norm_due_is_next_slot_from_first_seen():
    fs = dt.datetime(2021, 1, 1)
    d = to_norm.norm_due(fs, NOW, 180)
    assert d >= NOW and (d - fs).days % 180 == 0
    # без первой записи — считаем от «сейчас»
    d2 = to_norm.norm_due(None, NOW, 365)
    assert d2 == NOW + dt.timedelta(days=365)


def test_forecast_due_clamps():
    assert to_norm.forecast_due(NOW, 0) == NOW + dt.timedelta(days=1)
    assert to_norm.forecast_due(NOW, 1000, cap_days=90) == NOW + dt.timedelta(days=90)
    assert to_norm.forecast_due(NOW, float("nan")) is None


def test_plan_date_is_min_of_forecast_and_norm():
    norm = NOW + dt.timedelta(days=180)
    assert to_norm.plan_date(NOW, 10, norm) == NOW + dt.timedelta(days=10)   # прогноз раньше
    assert to_norm.plan_date(NOW, 60, norm) == NOW + dt.timedelta(days=60)
    assert to_norm.plan_date(NOW, None, norm) == norm                        # только норматив


def test_horizon_labels():
    assert to_norm.horizon_label(3) == "текущий квартал"
    assert to_norm.horizon_label(10) == "следующий квартал"
    assert to_norm.horizon_label(60) == "плановый год"
    assert to_norm.horizon_label(None) == "плановый"


def test_age_days_uses_first_seen(monkeypatch):
    monkeypatch.setattr(cm, "_first_seen_map",
                        lambda: {"CHX": dt.datetime(2020, 1, 1)})
    assert cm.age_days("CHX", dt.datetime(2025, 1, 1)) == pytest.approx(1827.0, abs=1.0)
    assert cm.age_days("UNKNOWN", NOW) is None


# --- интеграционно: гистерезис срока --------------------------------------
@pytest.fixture(scope="module")
def db():
    engine = create_engine(f"sqlite:///{(_TMP / 'test.db').as_posix()}",
                           connect_args={"check_same_thread": False}, future=True)
    dbmod.engine = engine
    dbmod.SessionLocal.configure(bind=engine)
    config.SIM_CLOCK = False
    config.AUTO_TICKETS = False
    dbmod.init_db()
    s = dbmod.SessionLocal()
    s.add(dbm.ObjectRef(object_id="OBJ1", hierarchy_level=2, name="Камера 1",
                        object_type="guardObject", district="OBJ1"))
    s.add(dbm.ChannelRef(channel_id="CHH", object_id="OBJ1",
                         sensor_type="Состояние насоса", sensor_name="Насос H"))
    s.commit()
    yield s
    s.close()


def _pred(db, bucket, plan_dt, age_days=3650.0):
    p = dbm.Prediction(task="wear", channel_id="CHH", object_id="OBJ1",
                       bucket_ts=bucket, p24=0.3, p72=0.5, risk30=0.7,
                       risk30_cal=0.7, exp_days=20.0, score=0.42, severity=0.8,
                       scale=1.0, plan="плановый год", age_days=age_days,
                       norm_due=plan_dt, plan_date=plan_dt, campaign=0,
                       model_version="test")
    db.add(p)
    db.commit()
    return p


def test_plan_date_and_hysteresis(db):
    b0 = dt.datetime(2026, 1, 10)
    work = db.query(dbm.MaintenanceTask).filter(
        dbm.MaintenanceTask.channel_id == "CHH").delete()
    db.commit()
    assert work == 0

    t0 = b0 + dt.timedelta(days=10)
    ticket, created = ms.create_from_prediction(db, _pred(db, b0, t0), source="auto")
    assert created and ticket.due_to == t0
    assert ticket.age_days == 3650.0 and ticket.norm_due == t0
    assert ticket.rationale and "дата_плана" in ticket.rationale

    # небольшой сдвиг (+2 дн) — срок НЕ меняется (гистерезис 5 дней)
    _, created2 = ms.create_from_prediction(db, _pred(db, b0 + dt.timedelta(hours=6), t0),
                                            source="auto")
    assert not created2 and ticket.due_to == t0

    # большой сдвиг (+15 дн) — срок обновляется
    t2 = t0 + dt.timedelta(days=15)
    ms.create_from_prediction(db, _pred(db, b0 + dt.timedelta(hours=12), t2), source="auto")
    assert ticket.due_to == t2

    # назначенную человеком дату модель не трогает
    ticket.scheduled_at = t2
    ticket.status = "assigned"
    db.commit()
    t3 = t2 + dt.timedelta(days=30)
    ms.create_from_prediction(db, _pred(db, b0 + dt.timedelta(hours=18), t3), source="auto")
    assert ticket.due_to == t2                       # срок заморожен
