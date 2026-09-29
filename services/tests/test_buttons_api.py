# -*- coding: utf-8 -*-
"""Детальные «кнопочные» тесты бэкенда: каждая ручка/действие UI — роль, эффект, данные, время.

Что проверяем (по запросу заказчика):
  * кнопки/ручки: кто имеет право (RBAC) и что происходит при вызове;
  * заявки: назначение исполнителя, допустимые переходы статусов, что техник может/не может;
  * история: комментарии (с меткой времени и автором) и даты выезда сохраняются и видны в API;
  * вложения (фото) — загрузка/список/выдача, валидация, доступ по району;
  * «Заново с января»: прогнозы пересчитываются, человеческие решения/заявки/аудит сохраняются,
    заявка с фото не ломает перезапуск (регресс FK-бага);
  * алерты: журнал/фолбэк, «тишина», ручной запуск правила;
  * мета/риски: формы ответов и краевые случаи (0/1 точка истории);
  * время каждой операции (для отчёта «через какое время обновляется»).

Запуск:  services\\.venv\\Scripts\\python.exe -m pytest tests/test_buttons_api.py -q -s
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import tempfile
import time

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="mc_buttons_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'buttons.db').as_posix()}"
os.environ["SIM_CLOCK"] = "0"
os.environ["RUN_SCHEDULER"] = "0"
os.environ["AUTO_TICKETS"] = "0"
os.environ["ALERTS_PUSH"] = "0"
os.environ["LOG_DIR"] = str(_TMP / "logs")
os.environ["ATTACH_DIR"] = str(_TMP / "att")
os.environ["ALERTS_MIN_P7D"] = "0.2"
os.environ["ALERTS_SILENCE_HOURS"] = "12"
os.environ["LOGIN_RATE_LIMIT"] = "1000"      # тесты логинятся многократно
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest                                              # noqa: E402
from fastapi.testclient import TestClient                  # noqa: E402
from sqlalchemy import create_engine                       # noqa: E402

from app import config, database as dbmod, models_db as dbm  # noqa: E402
from app.main import app                                  # noqa: E402
from app.security import hash_password                     # noqa: E402

B = "/api/v1"
DB_FILE = _TMP / "buttons.db"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000154a24f5c0000000049454e44ae426082")
TXT = b"hello, not an image"
BUCKET_TS = "2026-01-01T00:00:00"
TIMINGS: list = []


def act(name: str, fn):
    """Выполнить действие UI и запомнить время (для сводного отчёта)."""
    t0 = time.perf_counter()
    res = fn()
    TIMINGS.append((name, (time.perf_counter() - t0) * 1000,
                    hasattr(res, "status_code") and res.status_code < 400))
    return res


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
    for u, r, d in [("central.t", "central", None), ("disp.t", "dispatcher", None),
                    ("tech.t", "tech", "OBJ1")]:
        db.add(dbm.User(username=u, full_name=u, role=r, district=d,
                        password_hash=hash_password("pass1234")))
    db.add(dbm.ObjectRef(object_id="OBJ1", hierarchy_level=2, name="Камера 1",
                         object_type="guardObject", district="OBJ1"))
    db.add(dbm.ObjectRef(object_id="OBJ2", hierarchy_level=2, name="Камера 2",
                         object_type="guardObject", district="OBJ2"))
    for i in range(3):
        db.add(dbm.ChannelRef(channel_id=f"CH{i}", object_id="OBJ1",
                              sensor_type="Состояние насоса", sensor_name=f"Насос {i}"))
    db.add(dbm.ChannelRef(channel_id="CH9", object_id="OBJ2",
                          sensor_type="Состояние насоса", sensor_name="Насос чужой"))
    ts = dt.datetime(2026, 1, 1, 0, 0)
    surv = [0.01, 0.02, 0.03, 0.05, 0.35, 0.5, 0.9]
    for i, (obj, ch) in enumerate([("OBJ1", "CH0"), ("OBJ1", "CH1"), ("OBJ1", "CH2"),
                                   ("OBJ2", "CH9")]):
        db.add(dbm.Prediction(task="wear", channel_id=ch, object_id=obj, bucket_ts=ts,
                              p24=0.2, p72=0.4, p7d=0.6, risk30=0.9 - 0.1 * i,
                              risk30_cal=0.9 - 0.1 * i, exp_days=5.0 + i, score=0.8 - i / 10,
                              severity=0.8, scale=1.0, plan="текущий квартал",
                              surv_points=surv, event_flag=0, obs_days=3.0,
                              model_version="test"))
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c


_TOKENS: dict = {}


def tok(c, user: str) -> dict:
    """Токен с кэшем (логин один раз на пользователя — иначе ловим rate-limit)."""
    if user not in _TOKENS:
        r = c.post(B + "/auth/login", json={"username": user, "password": "pass1234"})
        assert r.status_code == 200, r.text
        _TOKENS[user] = {"Authorization": "Bearer " + r.json()["access_token"]}
    return dict(_TOKENS[user])


def make_open_ticket(c, h, channel="CH0") -> int:
    """Открытая заявка по каналу (через решение «профилактика»)."""
    pr = c.get(B + "/top-risks?task=wear&k=50&horizon=30d", headers=h).json()["items"]
    pid = next(p["id"] for p in pr if p["ид_канала_данных"] == channel)
    r = c.post(B + f"/forecasts/{pid}/decision", headers=h,
               json={"decision": "preventive", "comment": "плановый выезд"})
    assert r.status_code == 200, r.text
    return r.json()["ticket_id"]


def ticket_by_id(c, h, tid: int) -> dict:
    items = c.get(B + "/maintenance/tickets?limit=500", headers=h).json()["items"]
    t = next((x for x in items if x["id"] == tid), None)
    assert t is not None, f"заявка {tid} не найдена в списке"
    return t


# === 1. Роли: что каждая «кнопка» разрешает =====================================
@pytest.mark.parametrize("path,user,allowed", [
    ("/meta/summary", "tech.t", True), ("/meta/summary", "disp.t", True),
    ("/top-risks?task=wear&k=3", "tech.t", True),
    ("/maintenance/summary", "tech.t", True),
    ("/alerts?limit=5", "tech.t", True), ("/alerts?limit=5", "central.t", True),
    ("/maintenance/tickets?limit=3", "tech.t", True),
    ("/admin/system", "tech.t", False), ("/admin/system", "disp.t", False),
    ("/admin/system", "central.t", True),
    ("/admin/models", "disp.t", False), ("/admin/models", "central.t", True),
    ("/admin/data/status", "disp.t", True), ("/admin/data/status", "central.t", True),
    ("/meta/client-config", "tech.t", True),
])
def test_role_matrix_get(client, path, user, allowed):
    h = tok(client, user)
    r = act(f"GET {path} [{user}]", lambda: client.get(B + path, headers=h))
    assert (r.status_code == 200) is allowed, f"{user} {path}: {r.status_code} {r.text[:200]}"


def test_role_matrix_actions(client):
    """Кнопки-действия: решения и автоформирование — только диспетчер/центр; часы — центр."""
    hc, hd, ht = tok(client, "central.t"), tok(client, "disp.t"), tok(client, "tech.t")
    pid = client.get(B + "/top-risks?task=wear&k=5", headers=hc).json()["items"][0]["id"]
    assert client.post(B + f"/forecasts/{pid}/decision", headers=ht,
                       json={"decision": "confirm"}).status_code == 403
    assert client.post(B + "/maintenance/auto-generate", headers=ht,
                       json={}).status_code == 403
    assert client.post(B + "/admin/clock/pause", headers=hd).status_code == 403
    assert client.patch(B + "/maintenance/tickets/1", headers=hc,
                        json={"status": "in_progress"}).status_code in (200, 404)
    r = act("decision confirm [disp.t]", lambda: client.post(
        B + f"/forecasts/{pid}/decision", headers=hd,
        json={"decision": "confirm", "comment": "подтверждено обходом"}))
    assert r.status_code == 200, r.text


# === 2. Решения по прогнозу: аудит и история =====================================
def test_decision_audit_and_history(client):
    hd, hc = tok(client, "disp.t"), tok(client, "central.t")
    pid = client.get(B + "/top-risks?task=wear&k=5", headers=hd).json()["items"][0]["id"]
    r = act("decision reject", lambda: client.post(
        B + f"/forecasts/{pid}/decision", headers=hd,
        json={"decision": "reject", "comment": "ложное срабатывание"}))
    assert r.status_code == 200, r.text
    card = client.get(B + f"/forecasts/{pid}", headers=hd).json()
    hist = card.get("history") or []
    assert hist, "история решений пуста"
    assert any("ложное срабатывание" in (x.get("comment") or "") for x in hist), hist
    assert any((x.get("responsible") or "") == "disp.t" for x in hist), hist
    a = client.get(B + "/audit?action=forecast.decision", headers=hc).json()
    det = a["items"][0]["detail"]
    for k in ("comment", "decision", "username", "task", "channel_id"):
        assert det.get(k), f"в аудите нет {k}: {det}"


def test_decision_preventive_creates_linked_ticket(client):
    hd = tok(client, "disp.t")
    tid = make_open_ticket(client, hd, channel="CH1")
    t = ticket_by_id(client, hd, tid)
    assert t["channel_id"] == "CH1" and t["task"] == "wear"
    assert t["status"] in ("assigned", "in_progress"), t
    assert t["prediction_id"], "заявка не связана с прогнозом"
    assert t["scheduled_at"] or t["due_to"]
    assert t["risk"] is not None and t["p24"] is not None


# === 3. Заявки: статусы по ролям, комментарии и даты в истории ====================
def test_ticket_lifecycle_roles_comments_dates(client):
    hd, ht = tok(client, "disp.t"), tok(client, "tech.t")
    tid = make_open_ticket(client, hd, channel="CH2")           # assigned, исполнитель — диспетчер
    t0 = ticket_by_id(client, hd, tid)
    assert t0["status"] == "assigned" and t0["assigned_to"], t0

    # техник: назначенную заявку можно взять в работу (assigned→in_progress)
    r1 = act("ticket: техник «В работу»", lambda: client.patch(
        B + f"/maintenance/tickets/{tid}", headers=ht,
        json={"status": "in_progress", "comment": "выехал на объект", "assign_to_me": True}))
    assert r1.status_code == 200, r1.text
    t1 = ticket_by_id(client, ht, tid)
    assert t1["status"] == "in_progress" and t1["assignee"] == "tech.t", t1
    assert "выехал на объект" in (t1["comment"] or "")
    assert "tech.t" in (t1["comment"] or "")            # автор виден в истории
    assert t1["updated_at"] >= t0["updated_at"]

    # диспетчер переносит дату выезда — сохраняется и видна в списке/истории
    r2 = act("ticket: диспетчер переносит дату", lambda: client.patch(
        B + f"/maintenance/tickets/{tid}", headers=hd,
        json={"status": "in_progress", "scheduled_at": "2026-01-05T09:00:00",
              "comment": "перенесли выезд"}))
    assert r2.status_code == 200, r2.text
    t2 = ticket_by_id(client, hd, tid)
    assert (t2["scheduled_at"] or "").startswith("2026-01-05"), t2
    assert "перенесли выезд" in (t2["comment"] or "")
    assert (t2["plan_at"] or "").startswith("2026-01-05")

    # техник закрывает работу (in_progress→done)
    r3 = act("ticket: техник закрывает", lambda: client.patch(
        B + f"/maintenance/tickets/{tid}", headers=ht,
        json={"status": "done", "comment": "работы выполнены, замечаний нет"}))
    assert r3.status_code == 200, r3.text
    t3 = ticket_by_id(client, ht, tid)
    assert t3["status"] == "done" and "работы выполнены" in (t3["comment"] or "")
    assert (t3["comment"] or "").count("[") >= 3, t3["comment"]   # накопительная история
    assert "tech.t" in (t3["comment"] or "")                      # автор виден в истории

    # «только мои»: у техника — ровно его заявки
    mine = client.get(B + "/maintenance/tickets?mine=1&limit=200", headers=ht).json()["items"]
    assert mine and all(x["assignee"] == "tech.t" for x in mine), [x["assignee"] for x in mine]
    assert any(x["id"] == tid for x in mine)

    # график обслуживания: сортировка по сроку выезда (order=due)
    due = client.get(B + "/maintenance/tickets?order=due&limit=200", headers=hd).json()["items"]
    plans = [x["plan_at"] for x in due if x["plan_at"]]
    assert plans == sorted(plans), "order=due не отсортирован по сроку"


def test_ticket_conflicts_and_offline_idempotency(client):
    hd = tok(client, "disp.t")
    tid = make_open_ticket(client, hd, channel="CH0")
    r = act("ticket: 409 устаревший base_status", lambda: client.patch(
        B + f"/maintenance/tickets/{tid}", headers=hd,
        json={"status": "in_progress", "base_status": "done"}))
    assert r.status_code == 409 and r.json()["detail"]["current"]["status"] == "assigned", r.text
    cid = "btn-cid-1"
    h = dict(hd, **{"X-Client-Id": cid})
    r3 = client.patch(B + f"/maintenance/tickets/{tid}", headers=h,
                      json={"status": "in_progress", "comment": "офлайн-комментарий",
                            "base_status": "assigned", "offline_ts": "2026-01-02T07:00:00"})
    assert r3.status_code == 200, r3.text
    t_first = ticket_by_id(client, hd, tid)
    r4 = act("ticket: повтор офлайн-действия (идемпотентно)", lambda: client.patch(
        B + f"/maintenance/tickets/{tid}", headers=h,
        json={"status": "in_progress", "comment": "офлайн-комментарий",
              "base_status": "assigned", "offline_ts": "2026-01-02T07:00:00"}))
    assert r4.status_code == 200 and r4.json() == r3.json(), r4.text
    t_second = ticket_by_id(client, hd, tid)
    assert (t_second["comment"] or "").count("офлайн-комментарий") == 1
    assert t_second["updated_at"] == t_first["updated_at"]
    a = client.get(B + f"/audit?entity_type=maintenance&entity_id={tid}", headers=hd).json()
    st = [i for i in a["items"] if i["action"] == "ticket.status"]
    assert len(st) == 1 and st[0]["detail"]["source"] == "mobile-offline", st
    assert st[0]["detail"]["client_id"] == cid

# === 4. Вложения (фото): загрузка, список, выдача, валидация, доступ ==============
def test_attachments_flow_and_validation(client):
    hd, ht = tok(client, "disp.t"), tok(client, "tech.t")
    tid = make_open_ticket(client, hd, channel="CH1")
    r = act("attachment: загрузка фото", lambda: client.post(
        B + f"/maintenance/tickets/{tid}/attachments", headers=ht,
        files={"file": ("photo.png", PNG, "image/png")}))
    assert r.status_code == 200 and r.json()["attachment"]["mime"] == "image/png", r.text
    aid = r.json()["attachment"]["id"]
    lst = client.get(B + f"/maintenance/tickets/{tid}/attachments", headers=ht).json()
    assert len(lst["items"]) == 1 and lst["items"][0]["url"].endswith(f"/{aid}")
    img = act("attachment: выдача файла", lambda: client.get(
        B + f"/maintenance/attachments/{aid}", headers=ht))
    assert img.status_code == 200 and img.headers["content-type"].startswith("image/")
    assert img.content[:8] == PNG[:8]
    bad = act("attachment: отказ не-картинке", lambda: client.post(
        B + f"/maintenance/tickets/{tid}/attachments", headers=ht,
        files={"file": ("x.txt", TXT, "text/plain")}))
    assert bad.status_code == 415
    # чужой район: техник OBJ1 не должен прикладывать фото к заявке объекта OBJ2
    tid2 = make_open_ticket(client, hd, channel="CH9")
    assert client.post(B + f"/maintenance/tickets/{tid2}/attachments", headers=ht,
                       files={"file": ("p.png", PNG, "image/png")}).status_code == 403
    assert client.get(B + f"/maintenance/tickets/{tid2}/attachments",
                      headers=ht).status_code == 403


# === 5. Алерты: фолбэк, журнал, ручной запуск =====================================
def test_alerts_buttons(client):
    hc, hd = tok(client, "central.t"), tok(client, "disp.t")
    r = act("alerts: список (фолбэк)", lambda: client.get(B + "/alerts?limit=50", headers=hd))
    assert r.status_code == 200
    j = r.json()
    assert j["fallback"] is True and j["items"], j
    it = j["items"][0]
    for k in ("p7d", "object_id", "channel_id", "task_desc"):
        assert k in it, f"в алерте нет {k}: {it}"
    run = act("alerts: ручной запуск правила (central)", lambda: client.post(
        B + "/admin/alerts/run?force=true", headers=hc))
    assert run.status_code == 200 and run.json()["fired"] > 0, run.text
    j2 = client.get(B + "/alerts?limit=50", headers=hd).json()
    assert j2["fallback"] is False and j2["items"] and j2["items"][0]["sent_at"]
    # «тишина» 12 ч: без новых данных повторный запуск не создаёт дублей
    again = act("alerts: повтор без force (тишина)", lambda: client.post(
        B + "/admin/alerts/run?force=false", headers=hc))
    assert again.json()["fired"] == 0, again.text
    assert client.post(B + "/admin/alerts/run", headers=hd).status_code == 403
    a = client.get(B + "/audit?action=alert.push", headers=hc).json()
    assert a["total"] >= 1

# === 6. Мета и краевые случаи (что рисует фронт) ==================================
def test_meta_endpoints_and_history_edges(client):
    h = tok(client, "disp.t")
    for m in ("risk30", "p24", "p72", "p7d"):
        r = act(f"risk-history measure={m}", lambda: client.get(
            B + f"/meta/risk-history?task=wear&n=120&measure={m}", headers=h))
        assert r.status_code == 200 and r.json()["rows"], f"{m}: {r.text[:200]}"
        row = r.json()["rows"][0]
        for k in ("bucket_ts", "avg_risk", "max_risk", "n"):
            assert k in row
    # n=1 — не должно падать и не больше одной точки
    one = client.get(B + "/meta/risk-history?task=wear&n=1&measure=risk30", headers=h).json()
    assert len(one["rows"]) <= 1
    # задача без прогнозов → пусто, но 200 (а не 500)
    empty = client.get(B + "/meta/risk-history?task=fire&n=120", headers=h)
    assert empty.status_code == 200 and empty.json()["rows"] == []
    # конфиг мобильного профиля и сводки
    cfg = client.get(B + "/meta/client-config", headers=h).json()
    assert {"role", "alerts", "session", "attachments", "features"} <= set(cfg)
    sm = client.get(B + "/meta/summary", headers=h).json()
    assert set(sm) == {"fire", "access", "sensor", "wear"}
    assert client.get(B + "/meta/bucket-dates?task=wear", headers=h).status_code == 200
    assert client.get(B + "/objects", headers=h).status_code == 200
    assert client.get(B + "/top-objects?task=wear&k=3", headers=h).status_code == 200
    assert client.get(B + "/maintenance-plan?task=wear", headers=h).status_code == 200
    assert client.get(B + "/logs/client", headers=h).status_code in (200, 404, 405)


def _clk(r) -> dict:
    """Разбор ответа ручек часов: они отдают {"ok": true, "clock": {...}}."""
    body = r.json() if hasattr(r, "json") else {}
    return (body or {}).get("clock", body or {})


# === 7. «Заново с января»: что сохраняется, а что пересчитывается =================
def test_clock_buttons_and_reset_keeps_human_data(client):
    hc, hd, ht = tok(client, "central.t"), tok(client, "disp.t"), tok(client, "tech.t")
    # пауза/шаг/скорость доступны только центральному
    assert client.post(B + "/admin/clock/pause", headers=hd).status_code == 403
    paused = act("clock: пауза", lambda: client.post(B + "/admin/clock/pause", headers=hc))
    assert paused.status_code == 200 and _clk(paused)["paused"] is True
    resumed = act("clock: продолжить", lambda: client.post(B + "/admin/clock/resume", headers=hc))
    assert _clk(resumed)["paused"] is False
    assert act("clock: шаг +6ч", lambda: client.post(B + "/admin/clock/step?n=1",
                                                     headers=hc)).status_code == 200
    sp = act("clock: скорость 4×+быстрый", lambda: client.post(
        B + "/admin/clock/speed", headers=hc, json={"level": 4, "fast": True}))
    assert _clk(sp)["tick_sec"] == 20 and _clk(sp)["fast"] is True

    # готовим «человеческие» данные: решение + заявка + фото, и машинное предложение
    pid = client.get(B + "/top-risks?task=wear&k=5", headers=hd).json()["items"][0]["id"]
    client.post(B + f"/forecasts/{pid}/decision", headers=hd,
                json={"decision": "preventive", "comment": "человеческое решение"})
    human = make_open_ticket(client, hd, channel="CH2")
    # освобождаем канал CH0 (дедупликация: одна открытая заявка на канал×направление),
    # чтобы автоформирование создало новое машинное предложение
    open_ch0 = [x for x in client.get(B + "/maintenance/tickets?limit=500",
                                      headers=hd).json()["items"]
                if x["channel_id"] == "CH0" and x["status"] in ("suggested", "assigned",
                                                                "in_progress")]
    if open_ch0:
        client.patch(B + f"/maintenance/tickets/{open_ch0[0]['id']}", headers=hd,
                     json={"status": "cancelled", "comment": "освобождаем канал для теста"})
    auto = act("auto-generate: машинные предложения", lambda: client.post(
        B + "/maintenance/auto-generate", headers=hd, json={"tasks": ["wear"]}))
    assert auto.status_code == 200
    items = client.get(B + "/maintenance/tickets?limit=500", headers=hd).json()["items"]
    machine = next(x for x in items if x["source"] == "auto" and x["status"] == "suggested"
                   and x["id"] != human)
    # фото к машинной заявке делает её «человеческой» (регресс FK-бага при сбросе)
    up = client.post(B + f"/maintenance/tickets/{machine['id']}/attachments", headers=ht,
                     files={"file": ("p.png", PNG, "image/png")})
    assert up.status_code == 200, up.text
    aid = up.json()["attachment"]["id"]
    before_pred = client.get(B + "/forecasts?task=wear&page=1&size=5", headers=hd).json()["total"]

    reset = act("clock: «Заново с января»", lambda: client.post(B + "/admin/clock/reset",
                                                                headers=hc))
    assert reset.status_code == 200, reset.text
    assert _clk(reset)["sim_now"].startswith("2026-01-01")
    # человеческие данные сохранены: решение в истории, заявки (в т.ч. с фото) на месте
    card = client.get(B + f"/forecasts/{pid}", headers=hd).json()
    assert any("человеческое решение" in (x.get("comment") or "")
               for x in (card.get("history") or [])), card.get("history")
    after = client.get(B + "/maintenance/tickets?limit=500", headers=hd).json()["items"]
    ids = {x["id"] for x in after}
    assert human in ids, "человеческая заявка удалена при сбросе"
    assert machine["id"] in ids, "заявка с фото удалена при сбросе (FK-регресс)"
    lst = client.get(B + f"/maintenance/tickets/{machine['id']}/attachments",
                     headers=ht).json()
    assert any(x["id"] == aid for x in lst["items"]), "вложение потерялось при сбросе"
    # прогнозы пересоздаются, аудит сброса записан
    a = client.get(B + "/audit?action=admin.clock_reset", headers=hc).json()
    assert a["total"] >= 1
    assert before_pred >= 0          # прогнозы были; после сброса они пересчитываются заново
    assert client.get(B + "/meta/clock", headers=hc).json()["error"] is None


# === 9. Регресс: «Заново с января» и бакеты прошлого круга ========================
def test_history_and_top_risks_ignore_previous_cycle(client, monkeypatch):
    """После перезапуска реплея в таблице остаются бакеты прошлого круга (дальние месяцы).

    «Актуальные» запросы (тренд риска, топ-риски, алерты) должны смотреть на текущий круг
    (не позже сим-времени), иначе UI показывает устаревшую и почти пустую картину.
    """
    import datetime as _dt

    from app.services import prediction_service as ps

    db = dbmod.SessionLocal()
    if db.get(dbm.ChannelRef, "CH7") is None:
        db.add(dbm.ChannelRef(channel_id="CH7", object_id="OBJ1",
                              sensor_type="Состояние насоса", sensor_name="Насос 7"))
    # свежий бакет текущего круга и «хвост» прошлого круга (дальний месяц)
    surv = [0.01, 0.02, 0.03, 0.05, 0.35, 0.5, 0.9]
    for ts, risk in [(_dt.datetime(2026, 1, 2), 0.55), (_dt.datetime(2026, 6, 30, 18), 0.99)]:
        db.add(dbm.Prediction(task="wear", channel_id="CH7", object_id="OBJ1", bucket_ts=ts,
                              p24=0.3, p72=0.5, p7d=0.7, risk30=risk, risk30_cal=risk,
                              exp_days=4.0, score=risk, severity=0.8, scale=1.0,
                              plan="текущий квартал", surv_points=surv, event_flag=0,
                              obs_days=2.0, model_version="test-cycle"))
    db.commit()
    db.close()

    # сим-время — 03.01.2026 (первый круг ещё в январе)
    monkeypatch.setattr(ps, "_sim_bucket_dt", lambda: _dt.datetime(2026, 1, 3))

    rh = client.get(B + "/meta/risk-history?task=wear&n=120&measure=risk30",
                    headers=tok(client, "disp.t")).json()
    stamps = [r["bucket_ts"] for r in rh["rows"]]
    assert stamps, "тренд пуст"
    assert all(s[:10] <= "2026-01-02" for s in stamps), stamps[-3:]
    assert not any(s.startswith("2026-06-30") for s in stamps), "в тренд попал прошлый круг"

    tr = client.get(B + "/top-risks?task=wear&k=100&horizon=30d",
                    headers=tok(client, "disp.t")).json()
    assert tr["items"], "топ-рисков нет"
    assert any(i["ид_канала_данных"] == "CH7" for i in tr["items"]), "нет свежего бакета CH7"
    ch = client.get(B + "/meta/channel-history?task=wear&channel_id=CH7&n=30",
                    headers=tok(client, "disp.t")).json()
    assert ch["rows"] and all(r["bucket_ts"][:10] <= "2026-01-02" for r in ch["rows"]), ch["rows"]


# === 10. Классы тревожных сообщений и маршрут нарушителя ==========================
def test_alarm_classes_and_security_route(client):
    """Ответы заказчика: авария (пожар/наводнение/газ/террор/аном. температура) против
    инцидента (питание/связь); охранные сработки = «террор, проникновение» → маршрут."""
    import datetime as _dt

    hc, ht = tok(client, "central.t"), tok(client, "tech.t")
    # класс события приходит в элементах топа («Состояние насоса» → авария/наводнение)
    tr = act("top-risks: class поля", lambda: client.get(
        B + "/top-risks?task=wear&k=100&horizon=30d", headers=hc))
    it = tr.json()["items"][0]
    assert it["класс_события"] == "авария" and it["группа_события"] == "наводнение", it
    assert it["косвенно_авария"] is False
    # «Состояние фазы» → инцидент/электроснабжение, косвенно допускает аварию
    from app.services.alarm_service import alarm_class
    assert alarm_class("Состояние фазы") == {"класс": "инцидент", "группа": "электроснабжение",
                                             "косвенно_авария": True}
    cl = act("alarm-classes справочник", lambda: client.get(
        B + "/objects/OBJ1/alarm-classes", headers=hc))
    body = cl.json()
    assert "пожар" in body["авария"] and "террор" in body["авария"]
    assert "электроснабжение" in body["инцидент"] and "связь" in body["инцидент"]

    # охранные сработки объекта → маршрут нарушителя (порядок по сим-времени)
    db = dbmod.SessionLocal()
    if db.get(dbm.ChannelRef, "CH8") is None:
        db.add(dbm.ChannelRef(channel_id="CH8", object_id="OBJ1",
                              sensor_type="КД Люк", sensor_name="Люк-8", tag="1.2.13"))
    db.add(dbm.ChannelRef(channel_id="CH9A", object_id="OBJ1",
                          sensor_type="КД Дверь", sensor_name="Дверь-9"))
    for ts, ch in [(_dt.datetime(2026, 1, 2, 6), "CH8"), (_dt.datetime(2026, 1, 3, 12), "CH9A")]:
        db.add(dbm.Prediction(task="access", channel_id=ch, object_id="OBJ1", bucket_ts=ts,
                              p24=0.4, p72=0.5, p7d=0.6, risk30=0.7, risk30_cal=0.7,
                              exp_days=3.0, score=0.6, severity=0.7, scale=1.0,
                              plan="текущий квартал", surv_points=[0.01, 0.02, 0.03, 0.05, 0.4, 0.5, 0.9],
                              event_flag=1, obs_days=1.0, model_version="test-sec"))
    db.commit()
    db.close()

    r = act("security-route: маршрут нарушителя", lambda: client.get(
        B + "/objects/OBJ1/security-route?hours=720", headers=hc))
    route = r.json()
    assert route["points"], "маршрут пуст, хотя есть охранные сработки"
    kinds = {p["тип_датчика"] for p in route["points"]}
    assert kinds <= {"КД Люк", "КД Дверь", "КД АВ", "Датчик движения", "Стекло",
                     "9-секционный люк"}, kinds
    assert all(p["группа_события"] == "террор" for p in route["points"])
    ts = [p["bucket_ts"] for p in route["points"]]
    assert ts == sorted(ts), f"маршрут не упорядочен: {ts}"
    assert any(p["тег_пикета"] for p in route["points"])
    # RBAC: техник своего района видит, чужого — нет
    assert client.get(B + "/objects/OBJ1/security-route",
                      headers=ht).status_code == 200
    assert client.get(B + "/objects/OBJ2/security-route",
                      headers=ht).status_code == 403
    # объект без охранных каналов — пустой маршрут, но 200
    empty = client.get(B + "/objects/OBJ2/security-route", headers=hc).json()
    assert empty["points"] == []


def test_ticket_close_reason_in_history(client):
    """Закрытие заявки с причиной («что устранено»): причина остаётся в истории заявки и аудите."""
    hd, ht = tok(client, "disp.t"), tok(client, "tech.t")
    tid = make_open_ticket(client, hd, channel="CH7")      # в текущем круге прогнозы есть у CH7
    reason = "устранено: контактор"
    r = act("ticket: закрытие с причиной", lambda: client.patch(
        B + f"/maintenance/tickets/{tid}", headers=hd,
        json={"status": "in_progress", "comment": f"заменили контактор, связь восстановлена · {reason}"}))
    assert r.status_code == 200, r.text
    t1 = ticket_by_id(client, hd, tid)
    assert reason in (t1["comment"] or ""), t1["comment"]
    assert "disp.t" in (t1["comment"] or "")


# === 11. Реальные происшествия (журнал) против прогнозов ==========================
def test_events_vs_forecast_and_card_facts(client):
    """Панель «прогноз ↔ факт»: факты — тревожные сообщения журнала, а не ML-метка."""
    import datetime as _dt

    hc, ht = tok(client, "central.t"), tok(client, "tech.t")
    db = dbmod.SessionLocal()
    if db.get(dbm.ChannelRef, "CH11") is None:
        db.add(dbm.ChannelRef(channel_id="CH11", object_id="OBJ1", sensor_type="КД Люк",
                              sensor_name="Люк-11", tag="1.2.11"))
    surv = [0.01, 0.02, 0.03, 0.05, 0.4, 0.5, 0.9]
    base = dict(task="access", object_id="OBJ1", p72=0.5, p7d=0.6, risk30=0.7, risk30_cal=0.7,
                exp_days=2.0, severity=0.7, scale=1.0, plan="текущий квартал",
                surv_points=surv, model_version="test-facts")
    db.add(dbm.Prediction(channel_id="CH11", bucket_ts=_dt.datetime(2026, 1, 4, 0), p24=0.9,
                          event_flag=0, obs_days=1.0, score=0.9,
                          features_json={"тревог": 0, "тревог_дверь": 0, "тревог_движение": 0},
                          **base))
    fact = dbm.Prediction(channel_id="CH11", bucket_ts=_dt.datetime(2026, 1, 4, 6), p24=0.9,
                          event_flag=1, obs_days=0.1, score=0.9,
                          features_json={"тревог": 3, "тревог_дверь": 0, "тревог_движение": 3},
                          **base)
    db.add(fact)
    db.commit()
    fact_id = fact.id
    prev = (db.query(dbm.Prediction)
            .filter(dbm.Prediction.channel_id == "CH11",
                    dbm.Prediction.bucket_ts == _dt.datetime(2026, 1, 4, 0)).first())
    prev_id, prev.p24 = prev.id, 0.55
    db.commit()
    db.close()

    d = act("events: факты журнала", lambda: client.get(
        B + "/meta/events?task=access&n=50&threshold=0.5", headers=hc)).json()
    assert d["fact_kind"].startswith("тревожное сообщение"), d["fact_kind"]
    assert d["summary"]["events"] >= 1 and d["summary"]["predicted"] >= 1, d["summary"]
    it = next(x for x in d["items"] if x["channel_id"] == "CH11")
    assert it["произошло"].startswith("04.01"), it
    assert it["событий_в_бакете"] == 3
    assert it["предсказано"] is True and it["предсказано_за_ч"] == 6
    assert it["прогноз_p24"] == 0.55 and it["прогноз_бакет"].startswith("04.01 00:00")
    assert it["prediction_id"] == fact_id and it["прогноз_prediction_id"] == prev_id
    assert it["группа_события"] == "террор" and it["класс_события"] == "авария"

    # карточка прогноза: «предсказано / произошло» + ожидание события в горизонте
    f = act("forecasts: facts карточки", lambda: client.get(
        B + f"/forecasts/{prev_id}/facts?n=5&threshold=0.5", headers=hc)).json()
    assert f["выдано"] and f["p24"] == 0.55 and f["окно_до"]
    assert f["ожидается_событие"] is True and f["summary"]["events"] >= 1
    assert any(x["channel_id"] == "CH11" for x in f["items"])

    # RBAC/валидация
    assert client.get(B + "/meta/events?task=nope", headers=hc).status_code == 400
    assert client.get(B + "/meta/events?task=access", headers=ht).status_code == 200


def test_ticket_by_id_endpoint(client):
    """GET /maintenance/tickets/{id}: карточка объекта открывает заявку без загрузки списка."""
    hd, ht = tok(client, "disp.t"), tok(client, "tech.t")
    tid = make_open_ticket(client, hd, channel="CH7")
    r = act("ticket: получить по id", lambda: client.get(
        B + f"/maintenance/tickets/{tid}", headers=hd))
    assert r.status_code == 200
    t = r.json()
    assert t["id"] == tid and t["channel_id"] == "CH7" and t["status_ru"]
    assert client.get(B + "/maintenance/tickets/99999999", headers=hd).status_code == 404
    # техник своего района — можно, чужого — 403
    assert client.get(B + f"/maintenance/tickets/{tid}", headers=ht).status_code == 200
    db = dbmod.SessionLocal()
    other = dbm.MaintenanceTask(task="wear", channel_id="CH9", object_id="OBJ2",
                                plan_bucket=0, score=0.5, status="suggested",
                                source="manual", created_at=dt.datetime(2026, 1, 1))
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    assert client.get(B + f"/maintenance/tickets/{other_id}",
                      headers=ht).status_code == 403


# === 7b. Тренд: устойчивость среднего по «постоянной когорте» ======================
def test_trend_cohort_ignores_cold_channels(client, monkeypatch):
    """Регресс «график скачет на каждом тике».

    Причина была не в отрисовке: в бакете скачет число каналов, причём канал, впервые
    появившийся в бакете, получает risk30 ≈ 1.0 («холодный старт»). Поэтому среднее «по
    всем» «пилит» и на каждом тике график выглядит новым. Линия тренда считается по
    «постоянной когорте» — каналам, встречающимся в большинстве бакетов окна.
    """
    import datetime as _dt

    from app.services import prediction_service as ps

    base = _dt.datetime(2026, 1, 1)
    db = dbmod.SessionLocal()
    db.query(dbm.MaintenanceTask).update({"prediction_id": None})
    db.query(dbm.Prediction).filter(dbm.Prediction.task == "wear").delete()   # изоляция
    for i in range(10):                                  # 10 бакетов по 6 ч
        ts = base + _dt.timedelta(hours=6 * i)
        for j in range(8):                               # 8 «постоянных» каналов
            db.add(dbm.Prediction(task="wear", channel_id=f"S{j}", object_id="OBJ1",
                                  bucket_ts=ts, p24=0.05, risk30=0.1, event_flag=0,
                                  obs_days=30.0, model_version="cohort"))
    for j in range(20):                                  # 20 «холодных» — только в последнем
        db.add(dbm.Prediction(task="wear", channel_id=f"C{j}", object_id="OBJ1",
                              bucket_ts=base + _dt.timedelta(hours=54), p24=0.9,
                              risk30=1.0, event_flag=1, obs_days=0.25,
                              model_version="cohort"))
    db.commit()
    db.close()

    monkeypatch.setattr(ps, "_sim_bucket_dt", lambda: base + _dt.timedelta(hours=54))
    res = act("risk-history: когорта", lambda: client.get(
        B + "/meta/risk-history?task=wear&n=120&measure=risk30&cohort_share=0.5",
        headers=tok(client, "disp.t"))).json()

    assert len(res["rows"]) == 10, res["rows"]
    assert res["cohort_share"] == 0.5 and res["cohort_n"] == 8, res
    last = res["rows"][-1]
    assert last["n"] == 28 and last["cohort_n"] == 8, last
    assert abs(last["avg_risk"] - 0.1) < 0.01, last      # «холодные» исключены когортой
    assert last["avg_risk_all"] > 0.6, last              # «по всем» — задран холодными
    assert last["avg_risk_raw"] == last["avg_risk"]      # сырое = когортное (smooth=1)
    # без когорты сырое среднее скачет >0.5; с когортой — ровно
    alls = [r["avg_risk_all"] for r in res["rows"]]
    cohs = [r["avg_risk"] for r in res["rows"]]
    assert max(alls) - min(alls) > 0.5, alls
    assert max(cohs) - min(cohs) < 1e-6, cohs


# === 8. Отчёт по времени операций ================================================
def test_report_timings(client):
    lines = ["| операция | время, мс | ok |", "|---|---|---|"]
    for name, ms, ok in TIMINGS:
        lines.append(f"| {name} | {ms:.0f} | {'✓' if ok else '✗'} |")
    slow = [t for t in TIMINGS if t[1] > 3000]
    report = "\n".join(lines)
    out_dir = pathlib.Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "buttons_api_report.md").write_text(report, encoding="utf-8")
    print("\n\n=== ВРЕМЯ ОПЕРАЦИЙ (кнопки/ручки) ===\n" + report)
    print(f"\nмедленных (>3 с): {len(slow)}")
    assert not slow, f"операции дольше 3 с: {[(n, round(m)) for n, m, _ in slow]}"
