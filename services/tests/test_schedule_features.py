# -*- coding: utf-8 -*-
"""Дата обслуживания в заявках, график работ, p7d и раскраска графа (risk7d).

Изолированная SQLite-БД (как в test_logging_maintenance.py), чтобы полный прогон
pytest не зависел от основной базы.

Запуск отдельно:
  services\\.venv\\Scripts\\python.exe -m pytest tests/test_schedule_features.py -q
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="mc_sched_"))
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
TS = dt.datetime(2026, 3, 1, 12)
# S(t) = [6ч, 12ч, 24ч, 48ч, 3д, 7д, 14д, 30д] -> P(≤7д) = 1 - S[5]
S_PTS = [0.99, 0.97, 0.95, 0.9, 0.8, 0.55, 0.35, 0.2]


def _isolate() -> None:
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
    for u, p, r, d in [("central.s", "pass1234", "central", None),
                       ("disp.s", "pass1234", "dispatcher", None)]:
        db.add(dbm.User(username=u, role=r, district=d, password_hash=hash_password(p)))
    db.add(dbm.ObjectRef(object_id="OBJ1", hierarchy_level=2, name="Камера 1",
                         object_type="guardObject", district="OBJ1"))
    db.add(dbm.ObjectRef(object_id="OBJ2", hierarchy_level=2, name="Камера 2",
                         object_type="guardObject", district="OBJ1"))
    db.add(dbm.ChannelRef(channel_id="CH_other", object_id="OBJ2", tag="9.9.4096",
                          sensor_type="Состояние насоса", sensor_name="Насос изолированный"))
    for i, obj in enumerate(["OBJ1", "OBJ1", "OBJ2"]):
        db.add(dbm.ChannelRef(channel_id=f"CH{i}", object_id=obj, tag="1.2.55",
                              sensor_type="Состояние насоса", sensor_name=f"Насос {i}"))
    # CH0: p7d в колонке; CH1: колонки нет (старая запись) — считаем из S(t); CH2: без p7d
    for i, (ch, p7, sp) in enumerate([("CH0", 0.45, S_PTS),
                                      ("CH1", None, S_PTS),
                                      ("CH2", None, None)]):
        db.add(dbm.Prediction(task="wear", channel_id=ch,
                              object_id="OBJ1" if i < 2 else "OBJ2",
                              bucket_ts=TS, p24=0.1, p72=0.25, p7d=p7,
                              risk30=0.9 - i * 0.3, exp_days=5 + i, score=0.8 - i * 0.3,
                              severity=0.8, scale=1.0, plan="текущий квартал",
                              surv_points=sp, model_version="test"))
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


def _h(c, u):
    r = c.post(B + "/auth/login", json={"username": u, "password": "pass1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_p7d_in_forecasts(client):
    h = _h(client, "disp.s")
    items = client.get(B + "/top-risks?task=wear&k=10&horizon=30d", headers=h).json()["items"]
    by_ch = {i["ид_канала_данных"]: i for i in items}
    assert by_ch["CH0"]["p7d"] == pytest.approx(0.45, abs=1e-6)      # из колонки
    assert by_ch["CH1"]["p7d"] == pytest.approx(0.45, abs=1e-6)      # из S(t): 1 - 0.55
    assert by_ch["CH2"]["p7d"] is None                               # данных нет
    assert by_ch["CH0"]["p7d"] >= by_ch["CH0"]["p24"]


def test_graph_risk7d(client):
    h = _h(client, "disp.s")
    g = client.get(B + "/objects/graph", headers=h).json()
    assert g["nodes"], "узлы графа есть"
    r7 = {n["id"]: n.get("risk7d", {}) for n in g["nodes"]}
    assert r7["OBJ1"]["wear"] == pytest.approx(0.45, abs=1e-6)       # максимум по каналам
    assert "wear" not in r7["OBJ2"]                                  # нет прогноза с p7d
    for node in g["nodes"]:
        for v in node.get("risk7d", {}).values():
            assert 0.0 <= v <= 1.0


def test_risk_history_p7d(client):
    h = _h(client, "disp.s")
    r = client.get(B + "/meta/risk-history?task=wear&measure=p7d&days=30", headers=h).json()
    assert r["measure"] == "p7d" and r["rows"]
    assert r["rows"][-1]["max_risk"] == pytest.approx(0.45, abs=1e-3)


def test_objects_risk7d_and_auto_hint(client):
    """Раздел «Объекты» получает недельный риск (risk7d), а UI — параметры автоформирования."""
    h = _h(client, "disp.s")
    tree = client.get(B + "/objects", headers=h).json()
    objs = [o for o in tree["tree"] if o.get("level", 0) >= 2]
    assert objs, "есть объекты уровня 2"
    assert "risk7d" in objs[0] and "risks" in objs[0]
    ob1 = next(o for o in objs if o["object_id"] == "OBJ1")
    assert ob1["risk7d"]["wear"] == pytest.approx(0.45, abs=1e-6)   # максимум по каналам
    # L2-материализация в тесте пуста (bootstrap пересобирает её из parquet), поэтому
    # проверяем только наличие отдельного поля с месячным ориентиром
    assert "risks" in ob1
    ob2 = next((o for o in objs if o["object_id"] == "OBJ2"), None)
    if ob2 is not None:
        assert ob2["risk7d"] == {}                                  # нет недельных прогнозов
    s = client.get(B + "/maintenance/summary", headers=h).json()
    assert "auto" in s and 0 <= s["auto"]["min_risk"] <= 1 and s["auto"]["top_k"] >= 1


def test_ui_static_no_cache(client):
    """UI-ассеты отдаются с no-cache (чтобы после обновления сервиса не было старого JS)."""
    r = client.get("/js/fx.js")
    assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache"
    r2 = client.get(B + "/health")
    assert r2.headers.get("cache-control") != "no-cache"            # API не трогаем


def test_ticket_schedule_dates(client):
    h = _h(client, "disp.s")
    items = client.get(B + "/top-risks?task=wear&k=10", headers=h).json()["items"]
    pred = next(i for i in items if i["ид_канала_данных"] == "CH0")
    # создание с датой выезда
    t = client.post(B + "/maintenance/tickets", headers=h,
                    json={"prediction_id": pred["id"], "assign": True,
                          "scheduled_at": "2026-04-10T09:00:00"}).json()
    assert (t["scheduled_at"] or "").startswith("2026-04-10")
    tid = t["id"]
    # перенос даты (диспетчер меняет дату выезда в карточке заявки)
    upd = client.patch(B + f"/maintenance/tickets/{tid}", headers=h,
                       json={"status": t["status"],
                             "scheduled_at": "2026-04-15T09:00:00"}).json()
    assert (upd["scheduled_at"] or "").startswith("2026-04-15")
    # график обслуживания: сортировка по плановой дате и фильтр по объекту
    ordered = client.get(B + "/maintenance/tickets?order=due&limit=50",
                         headers=h).json()["items"]
    plans = [x["plan_at"] for x in ordered if x.get("plan_at")]
    assert plans == sorted(plans)
    byobj = client.get(B + "/maintenance/tickets?object_id=OBJ1&order=due",
                       headers=h).json()["items"]
    assert byobj and all(x["object_id"] == "OBJ1" for x in byobj)
    assert any(x["id"] == tid for x in byobj)
    assert "overdue" in byobj[0]


def test_decision_preventive_carries_date(client):
    h = _h(client, "disp.s")
    items = client.get(B + "/top-risks?task=wear&k=10", headers=h).json()["items"]
    pred = next(i for i in items if i["ид_канала_данных"] == "CH1")
    d = client.post(B + f"/forecasts/{pred['id']}/decision", headers=h,
                    json={"decision": "preventive", "responsible": "disp.s",
                          "comment": "плановое ТО",
                          "scheduled_at": "2026-05-01T09:00:00"}).json()
    assert d["ok"] is True and d["ticket_id"]
    tl = client.get(B + "/maintenance/tickets?object_id=OBJ1&order=due&limit=200",
                    headers=h).json()["items"]
    got = [x for x in tl if (x.get("scheduled_at") or "").startswith("2026-05-01")]
    assert got, "дата выезда из решения «профилактика» попала в заявку"


def test_replay_restart_keeps_human_data(client):
    """Перезапуск реплея не должен стирать решения диспетчера и «человеческие» заявки.

    Проверяем то же, что делает автоперезапуск круга (`simclock._fresh_start`):
    прогнозы пересчитываются, но решения/заявки/аудит остаются.
    """
    from app.database import SessionLocal
    from app.workers import simclock
    h = _h(client, "disp.s")
    items = client.get(B + "/top-risks?task=wear&k=10", headers=h).json()["items"]
    pred = next(i for i in items if i["ид_канала_данных"] == "CH0")
    d = client.post(B + f"/forecasts/{pred['id']}/decision", headers=h,
                    json={"decision": "preventive", "responsible": "disp.s",
                          "comment": "план ТО перед кругом"}).json()
    tid = d["ticket_id"]
    # необработанные предложения модели (их перезапуск вправе убрать и создать заново)
    client.post(B + "/maintenance/auto-generate", headers=h, json={"tasks": ["wear"]})
    db = SessionLocal()
    try:
        human_before = (db.query(dbm.MaintenanceTask)
                        .filter(dbm.MaintenanceTask.status != "suggested").count())
        n_dec = db.query(dbm.Decision).count()
        simclock._fresh_start(db)
        db.expire_all()
        # 1) заявка диспетчера на месте, ссылка на удалённый прогноз снята
        t = db.get(dbm.MaintenanceTask, tid)
        assert t is not None, "заявка диспетчера сохранилась после перезапуска круга"
        assert t.status == "assigned" and t.prediction_id is None
        assert (db.query(dbm.MaintenanceTask)
                .filter(dbm.MaintenanceTask.status != "suggested").count()) == human_before
        # 2) решения сохранились вместе со своими прогнозами-метками (признаки + метка)
        assert db.query(dbm.Decision).count() == n_dec
        dec = db.query(dbm.Decision).filter(dbm.Decision.prediction_id.isnot(None)).first()
        assert dec is not None
        p = db.get(dbm.Prediction, dec.prediction_id)
        assert p is not None and p.pinned == 1, "прогноз-метка закреплён и не удалён"
        # 3) необработанные предложения автоформирования убраны, обычные прогнозы пересчитаются
        assert (db.query(dbm.MaintenanceTask)
                .filter(dbm.MaintenanceTask.source == "auto",
                        dbm.MaintenanceTask.status == "suggested",
                        dbm.MaintenanceTask.prediction_id.isnot(None)).count()) == 0
        # 4) «закреплённые» строки не влияют на определение текущего бакета
        assert db.query(dbm.Prediction).filter(dbm.Prediction.pinned != 1).count() == 0
    finally:
        db.close()
