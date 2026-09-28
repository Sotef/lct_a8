# -*- coding: utf-8 -*-
"""Логирование, аудит и модуль заявок — изолированно от основной БД.

Тест создаёт **собственный** SQLite-движок и переводит на него `app.database`
(важно: при полном прогоне pytest другой модуль может импортировать `app.config`
раньше, поэтому одних env-переменных недостаточно), отключает сим-часы и
автоформирование заявок.

Запуск отдельно:  services\\.venv\\Scripts\\python.exe -m pytest tests/test_logging_maintenance.py -q
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="mc_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["SIM_CLOCK"] = "0"
os.environ["RUN_SCHEDULER"] = "0"
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["AUTO_TICKETS_MIN_RISK"] = "0.5"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app import config  # noqa: E402
from app import database as dbmod  # noqa: E402
from app import models_db as dbm  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402

B = "/api/v1"
DB_FILE = _TMP / "test.db"


def _isolate() -> None:
    """Свой движок/сессия для теста + выключенные фоновые процессы."""
    engine = create_engine(f"sqlite:///{DB_FILE.as_posix()}",
                           connect_args={"check_same_thread": False}, future=True)
    dbmod.engine = engine
    dbmod.SessionLocal.configure(bind=engine)
    config.SIM_CLOCK = False
    config.RUN_SCHEDULER = False
    config.AUTO_TICKETS = False
    config.DATABASE_URL = f"sqlite:///{DB_FILE.as_posix()}"


@pytest.fixture(scope="module")
def client():
    _isolate()
    dbmod.init_db()
    db = dbmod.SessionLocal()
    for u, p, r, d in [("central.t", "pass1234", "central", None),
                       ("disp.t", "pass1234", "dispatcher", None),
                       ("tech.t", "pass1234", "tech", "OBJ1")]:
        db.add(dbm.User(username=u, role=r, district=d, password_hash=hash_password(p)))
    db.add(dbm.ObjectRef(object_id="OBJ1", hierarchy_level=2, name="Камера 1",
                         object_type="guardObject", district="OBJ1"))
    # непустой channels_ref — иначе bootstrap в lifespan перезальёт справочники
    for i in range(3):
        db.add(dbm.ChannelRef(channel_id=f"CH{i}", object_id="OBJ1",
                              sensor_type="Состояние насоса", sensor_name=f"Насос {i}"))
    ts = dt.datetime(2026, 3, 1, 12)
    for i, (r30, sc) in enumerate([(0.9, 0.8), (0.6, 0.5), (0.1, 0.05)]):
        db.add(dbm.Prediction(task="wear", channel_id=f"CH{i}", object_id="OBJ1",
                              bucket_ts=ts, p24=r30 / 5, p72=r30 / 2, risk30=r30,
                              exp_days=5 + i, score=sc, severity=0.8, scale=1.0,
                              plan="текущий квартал", model_version="test"))
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


def _tok(c, u):
    r = c.post(B + "/auth/login", json={"username": u, "password": "pass1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_request_id_and_failed_login_audit(client):
    r = client.post(B + "/auth/login", json={"username": "central.t", "password": "bad"})
    assert r.status_code == 401
    assert r.headers.get("x-request-id")
    h = _tok(client, "central.t")
    a = client.get(B + "/audit?action=auth.*", headers=h).json()
    acts = [i["action"] for i in a["items"]]
    assert "auth.login_failed" in acts and "auth.login" in acts
    failed = next(i for i in a["items"] if i["action"] == "auth.login_failed")
    assert failed["detail"].get("request_id") and failed["detail"].get("ip")


def test_system_logs_buffer(client):
    h = _tok(client, "central.t")
    client.get(B + "/meta/tasks", headers=h)
    logs = client.get(B + "/admin/logs?logger=http", headers=h).json()
    assert logs["last_id"] > 0
    assert any("/meta/tasks" in i["msg"] for i in logs["items"])
    again = client.get(B + f"/admin/logs?after_id={logs['last_id']}&logger=http",
                       headers=h).json()
    assert all(i["id"] > logs["last_id"] for i in again["items"])
    assert client.get(B + "/admin/logs", headers=_tok(client, "disp.t")).status_code == 403


def test_client_log(client):
    h = _tok(client, "disp.t")
    r = client.post(B + "/logs/client", headers=h,
                    json={"level": "error", "message": "TypeError: x is undefined",
                          "url": "/#/dashboard"})
    assert r.status_code == 200
    a = client.get(B + "/audit?action=client.error", headers=h).json()
    assert a["total"] >= 1


def test_auto_tickets_and_lifecycle(client):
    hc, ht = _tok(client, "central.t"), _tok(client, "tech.t")
    r = client.post(B + "/maintenance/auto-generate", headers=hc,
                    json={"tasks": ["wear"]}).json()
    assert r["by_task"]["wear"]["created"] == 2          # risk >= 0.5: CH0, CH1
    r2 = client.post(B + "/maintenance/auto-generate", headers=hc,
                     json={"tasks": ["wear"]}).json()
    assert r2["created"] == 0                             # дедупликация
    lst = client.get(B + "/maintenance/tickets?task=wear", headers=hc).json()["items"]
    assert {t["channel_id"] for t in lst} == {"CH0", "CH1"}
    t0 = next(t for t in lst if t["channel_id"] == "CH0")
    assert t0["priority"] == "high" and t0["status"] == "suggested"
    url = B + f"/maintenance/tickets/{t0['id']}"
    assert client.patch(url, headers=ht, json={"status": "assigned"}).status_code == 403
    assert client.patch(url, headers=hc,
                        json={"status": "assigned", "comment": "бригада 3"}).status_code == 200
    rr = client.patch(url, headers=ht, json={"status": "in_progress"}); assert rr.status_code == 200, rr.text
    assert client.patch(url, headers=hc, json={"status": "suggested"}).status_code == 409
    assert client.patch(url, headers=ht,
                        json={"status": "done", "comment": "заменён подшипник"}).status_code == 200
    s = client.get(B + "/maintenance/summary", headers=hc).json()
    assert s["by_status"]["done"] == 1 and s["open"] == 1
    a = client.get(B + "/audit?action=ticket.status", headers=hc).json()
    assert a["total"] == 3


def test_decision_preventive_reuses_ticket(client):
    hc = _tok(client, "central.t")
    db = dbmod.SessionLocal()
    pid = db.query(dbm.Prediction).filter_by(channel_id="CH1").first().id
    db.close()
    r = client.post(B + f"/forecasts/{pid}/decision", headers=hc,
                    json={"decision": "preventive", "comment": "плановый выезд"}).json()
    assert r["ok"] and r["ticket_id"]
    lst = client.get(B + "/maintenance/tickets?task=wear", headers=hc).json()["items"]
    ch1 = [t for t in lst if t["channel_id"] == "CH1"]
    assert len(ch1) == 1 and ch1[0]["status"] == "assigned"
    card = client.get(B + f"/forecasts/{pid}", headers=hc).json()
    assert card["ticket"]["id"] == r["ticket_id"]


def test_user_block_and_system(client):
    hc = _tok(client, "central.t")
    users = client.get(B + "/auth/admin/users", headers=hc).json()["users"]
    disp = next(u for u in users if u["username"] == "disp.t")
    url = B + f"/auth/admin/users/{disp['id']}/active"
    assert client.post(url, headers=hc, json={"active": False}).status_code == 200
    r = client.post(B + "/auth/login", json={"username": "disp.t", "password": "pass1234"})
    assert r.status_code == 403
    client.post(url, headers=hc, json={"active": True})
    s = client.get(B + "/admin/system", headers=hc).json()
    assert s["counts"]["tickets"] >= 2 and "log" in s
    assert (config.LOG_DIR / "app.log").exists()
    assert (config.LOG_DIR / "app.log").stat().st_size > 0
    # JSON lines: запись вида {"ts": ..., "request_id": ...}
    first = (config.LOG_DIR / "app.log").read_text(encoding="utf-8").strip().splitlines()[0]
    assert first.startswith("{") and "request_id" in first


def test_simclock_controls(client):
    """Управление реплеем: состояние, пауза/возобновление, шаг и перезапуск с начала периода."""
    from app.workers import simclock
    start = simclock.bucket_of(dt.datetime.fromisoformat(config.SIM_START))
    st = simclock.clock_status()
    assert st["mode"] == "replay-2026"
    assert st["bucket_start"] == start and st["start_ts"].startswith("2026-01-01")
    assert st["paused"] is False and 0.0 <= st["progress"] <= 1.0
    assert simclock.pause()["paused"] is True
    # ручной шаг снимает паузу на время шага и возвращает её после
    stepped = simclock.step(1)
    assert stepped["paused"] is False
    simclock.resume()
    assert simclock.clock_status()["paused"] is False
    db = dbmod.SessionLocal()
    try:
        human_before = db.query(dbm.MaintenanceTask).count()
        dec_before = db.query(dbm.Decision).count()
        human_kept_before = (db.query(dbm.MaintenanceTask)
                             .filter(dbm.MaintenanceTask.status != "suggested").count())
    finally:
        db.close()
    out = simclock.reset()
    assert out["bucket"] == start and out["paused"] is False
    assert out["progress"] == 0.0
    db = dbmod.SessionLocal()
    try:
        # прогнозы пересчитываются с начала периода: остаются только «закреплённые» метки
        assert db.query(dbm.Prediction).filter(dbm.current_only()).count() == 0
        # человеческие данные перезапуск круга не трогает (BACKEND_SPEC §11.16)
        assert db.query(dbm.MaintenanceTask).count() >= human_kept_before > 0
        assert (db.query(dbm.MaintenanceTask)
                .filter(dbm.MaintenanceTask.status != "suggested").count()) == human_kept_before
        assert db.query(dbm.Decision).count() == dec_before >= 0
        # необработанные предложения автоформирования уходят (модель создаст их заново)
        assert (db.query(dbm.MaintenanceTask)
                .filter(dbm.MaintenanceTask.source == "auto",
                        dbm.MaintenanceTask.status == "suggested").count()) == 0
        assert human_before >= human_kept_before
    finally:
        db.close()


def test_simclock_speed(client):
    """Скорость демо-прокрута: уровни, тумблеры SHAP/параллельности, сохранение в settings."""
    from app.workers import simclock
    st = simclock.set_speed_level(4)
    assert st["tick_sec"] == simclock.SPEED_LEVELS[4] == 20
    assert st["speed"] == 4, "уровень скорости должен совпадать с выбранным"
    assert st["buckets_per_hour"] > 0 and st["full_pass_hours"] >= 0
    st = simclock.set_speed(fast=True, parallel=False)
    assert st["fast"] is True and st["parallel"] is False
    st = simclock.set_speed_level(1, fast=False)
    assert st["tick_sec"] == 75 and st["speed"] == 1 and st["fast"] is False
    # параметры переживают рестарт (пишутся в settings.sim_options)
    db = dbmod.SessionLocal()
    try:
        opts = db.get(dbm.Setting, "sim_options")
        assert opts is not None and opts.value["tick_sec"] == 75
    finally:
        db.close()
    simclock._state["tick_sec"] = 75
    simclock._state["fast"] = False
    assert simclock.clock_status()["shap_top_k"] == config.SHAP_TOP_K



