# -*- coding: utf-8 -*-
"""Смоук новых ручек (аудит, логи, заявки, система) по живому серверу.

Запуск: services\\.venv\\Scripts\\python.exe tests\\smoke_new_api.py
"""
import sys
import time

import httpx

# Windows-консоль по умолчанию cp1251 — переводим вывод в utf-8,
# иначе печать символов вроде «×», «→», «≈» падает на encode.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

B = "http://127.0.0.1:8000/api/v1"
c = httpx.Client(timeout=90)
ok = True


def chk(name, cond, extra=""):
    global ok
    print(("  OK   " if cond else "  FAIL ") + name, extra if not cond else "")
    ok = ok and cond


def login(u, p):
    r = c.post(f"{B}/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}, r.headers.get("x-request-id")


hc, rid = login("central.operator", "central123")
hd, _ = login("dispatcher.alpha", "alpha123")
ht, _ = login("tech.alpha", "tech123")
chk("login возвращает X-Request-ID", bool(rid), rid)

# --- аудит: фильтры, действия, статистика ---
r = c.get(f"{B}/audit?action=auth.*&size=20", headers=hc)
chk("GET /audit (auth.*)", r.status_code == 200 and r.json()["total"] >= 3, r.text[:200])
items = r.json()["items"]
chk("аудит содержит action_ru и detail.request_id",
    all("action_ru" in i and "detail" in i for i in items)
    and any(i["detail"].get("request_id") for i in items))
r = c.get(f"{B}/audit?q=central", headers=hc)
chk("GET /audit?q=", r.status_code == 200)
chk("GET /audit/actions", c.get(f"{B}/audit/actions", headers=hc).status_code == 200)
rs = c.get(f"{B}/audit/stats?hours=24", headers=hc)
chk("GET /audit/stats", rs.status_code == 200 and "by_action" in rs.json())
chk("dispatcher видит только свои действия",
    c.get(f"{B}/audit", headers=hd).status_code == 200)
chk("техник к аудиту закрыт", c.get(f"{B}/audit", headers=ht).status_code == 403)

# --- системный лог ---
r = c.get(f"{B}/admin/logs?limit=50", headers=hc)
chk("GET /admin/logs", r.status_code == 200 and r.json()["last_id"] > 0)
data = r.json()
chk("в логе есть http-запросы с request_id",
    any(i["logger"] == "http" and i["request_id"] != "-" for i in data["items"]))
after = data["last_id"]
c.get(f"{B}/meta/tasks", headers=hc)
r2 = c.get(f"{B}/admin/logs?after_id={after}&logger=http", headers=hc).json()
chk("инкрементальный хвост лога", all(i["id"] > after for i in r2["items"]))
chk("лог только для central", c.get(f"{B}/admin/logs", headers=hd).status_code == 403)
rf = c.get(f"{B}/admin/logs/file", headers=hc)
chk("GET /admin/logs/file", rf.status_code == 200 and len(rf.text) > 0)

# --- клиентский лог ---
r = c.post(f"{B}/logs/client", headers=hd,
           json={"level": "error", "message": "smoke: тестовая ошибка UI", "url": "#/smoke"})
chk("POST /logs/client", r.status_code == 200)
chk("ошибка UI попала в аудит",
    c.get(f"{B}/audit?action=client.error", headers=hc).json()["total"] >= 1)

# --- заявки ---
r = c.post(f"{B}/maintenance/auto-generate", json={"tasks": ["wear"]}, headers=hc)
chk("POST /maintenance/auto-generate", r.status_code == 200, r.text[:200])
gen = r.json()
r2 = c.post(f"{B}/maintenance/auto-generate", json={"tasks": ["wear"]}, headers=hc).json()
chk("повторное автоформирование идемпотентно (дублей нет)", r2["created"] == 0, str(r2))
lst = c.get(f"{B}/maintenance/tickets?limit=50", headers=hc).json()
chk("GET /maintenance/tickets", lst["total"] >= gen["created"])
t = lst["items"][0] if lst["items"] else None
if t:
    chk("поля заявки", all(k in t for k in ("status_ru", "priority", "source", "due_to", "risk", "object_name")))
    chk("диспетчер назначает",
        c.patch(f"{B}/maintenance/tickets/{t['id']}", json={"status": "assigned", "comment": "smoke"},
                headers=hc).status_code == 200)
# недопустимый переход проверяем на своей «предложенной» заявке (POST с assign=false)
sug = None
for it in (c.get(f"{B}/top-risks?task=wear&k=10&horizon=30d", headers=hc).json().get("items") or []):
    r = c.post(f"{B}/maintenance/tickets", json={"prediction_id": it["id"], "assign": False}, headers=hc)
    if r.status_code == 200 and r.json().get("status") == "suggested":
        sug = r.json()
        break
chk("POST /maintenance/tickets (предложенная заявка)", sug is not None)
if sug:
    chk("недопустимый переход (предложена -> выполнена) отклонён",
        c.patch(f"{B}/maintenance/tickets/{sug['id']}", json={"status": "done"},
                headers=hc).status_code == 409, "ожидался 409")
    chk("допустимый переход (предложена -> отменена)",
        c.patch(f"{B}/maintenance/tickets/{sug['id']}", json={"status": "cancelled"},
                headers=hc).status_code == 200)
if t:
    chk("смена статуса попала в аудит",
        c.get(f"{B}/audit?action=ticket.status", headers=hc).json()["total"] >= 1)
r = c.get(f"{B}/maintenance/summary", headers=hc)
chk("GET /maintenance/summary", r.status_code == 200 and "by_status" in r.json())
chk("заявки видны технику (свой район)", c.get(f"{B}/maintenance/tickets", headers=ht).status_code == 200)

# --- карточка прогноза: блок ticket + просмотр в аудите ---
fl = c.get(f"{B}/forecasts?task=wear&page=1&size=5", headers=hc).json()
if fl["items"]:
    pid = fl["items"][0]["id"]
    card = c.get(f"{B}/forecasts/{pid}", headers=hc).json()
    chk("карточка содержит блок ticket", "ticket" in card)
    chk("просмотр карточки отражён в аудите",
        c.get(f"{B}/audit?action=forecast.view", headers=hc).json()["total"] >= 1)
    d = c.post(f"{B}/forecasts/{pid}/decision", headers=hc,
               json={"decision": "preventive", "comment": "smoke-решение"})
    chk("решение «профилактика» создаёт/назначает заявку",
        d.status_code == 200 and d.json().get("ticket_id"), d.text[:200])

# --- система ---
s = c.get(f"{B}/admin/system", headers=hc)
chk("GET /admin/system", s.status_code == 200 and s.json()["counts"]["predictions"] > 0)
chk("system: модели ok", all(v == "ok" for v in s.json()["models"].values()))
chk("system закрыт для dispatcher", c.get(f"{B}/admin/system", headers=hd).status_code == 403)

# --- статика SPA ---
for path in ["/", "/js/app.js", "/css/themes.css", "/js/cards.js".replace("cards", "card_forecast")]:
    rr = c.get("http://127.0.0.1:8000" + path)
    chk(f"статика {path}", rr.status_code == 200, str(rr.status_code))

# --- выход ---
chk("POST /auth/logout", c.post(f"{B}/auth/logout", headers=hd).status_code == 200)
chk("выход в аудите", c.get(f"{B}/audit?action=auth.logout", headers=hc).json()["total"] >= 1)

# --- часы/реплей: состояние, управление ---
cl = c.get(f"{B}/meta/clock", headers=hc)
chk("GET /meta/clock: поля цикла и прогресса",
    cl.status_code == 200 and all(k in cl.json() for k in
                                  ("bucket", "panel_max", "progress", "paused", "loop", "start_ts")),
    cl.text[:200])
chk("реплей стартует с 2026-01-01", str(cl.json().get("start_ts", "")).startswith("2026-01-01"))
chk("пауза реплея", c.post(f"{B}/admin/clock/pause", headers=hc).json()["clock"]["paused"] is True)
chk("запрос ручного шага принят", c.post(f"{B}/admin/clock/step?n=1", headers=hc).status_code == 200)
chk("возобновление реплея", c.post(f"{B}/admin/clock/resume", headers=hc).json()["clock"]["paused"] is False)
chk("управление реплеем в аудите",
    c.get(f"{B}/audit?action=admin.clock_*", headers=hc).json()["total"] >= 3)
chk("управление реплеем только для central",
    c.post(f"{B}/admin/clock/pause", headers=hd).status_code == 403)

# --- скорость прокрута и SHAP-факторы «по запросу» ---
chk("GET /admin/clock/speed", c.get(f"{B}/admin/clock/speed", headers=hc).status_code == 200)
sp = c.post(f"{B}/admin/clock/speed", headers=hc, json={"level": 4, "fast": True}).json()["clock"]
chk("POST /admin/clock/speed: уровень 4x и быстрый расчёт",
    sp["tick_sec"] == 20 and sp["speed"] == 4 and sp["fast"] is True, str(sp)[:200])
chk("управление скоростью только для central",
    c.post(f"{B}/admin/clock/speed", headers=hd, json={"level": 1}).status_code == 403)
# быстрый тик: один шаг без SHAP, затем факторы досчитываются по запросу
b_before = c.get(f"{B}/meta/clock", headers=hc).json()["bucket"]
c.post(f"{B}/admin/clock/step?n=1", headers=hc)
bucket_now = b_before
for _ in range(40):
    _st = c.get(f"{B}/meta/clock", headers=hc).json()
    if _st["bucket"] != b_before and not _st["computing"]:
        bucket_now = _st["bucket"]
        break
    time.sleep(1)
chk("быстрый шаг продвинул реплей", bucket_now != b_before,
    f"bucket {b_before} -> {bucket_now}")
top = c.get(f"{B}/top-risks?task=wear&k=1&horizon=30d", headers=hc).json()["items"]
if top:
    pid = top[0]["id"]
    r = c.get(f"{B}/forecasts/{pid}/factors?compute=true", headers=hc)
    j = r.json() if r.status_code == 200 else {}
    chk("факторы досчитываются по запросу в быстром режиме",
        r.status_code == 200 and (j.get("computed") is True or j.get("factors")),
        str(j)[:200])
    again = c.get(f"{B}/forecasts/{pid}/factors", headers=hc).json()
    chk("факторы сохранились в прогнозе (повторный запрос без пересчёта)",
        bool(again.get("factors")), str(again)[:200])
else:
    chk("top-risks для проверки факторов", False, "пустой список")

chk("перезапуск реплея с января",
    c.post(f"{B}/admin/clock/reset", headers=hc).json()["clock"]["bucket"] == cl.json()["bucket_start"])
chk("после сброса период пройден почти с нуля (гонка с фоновым тиком — допуск 5%)",
    c.get(f"{B}/meta/clock", headers=hc).json()["progress"] < 0.05)

# --- горизонты тренда риска (1д/3д/7д/30д) ---
# предыдущий шаг сбросил реплей — ждём, пока сим-часы просчитают хотя бы один бакет
for _ in range(60):
    if c.get(f"{B}/meta/risk-history?task=wear&n=5", headers=hc).json().get("rows"):
        break
    time.sleep(1)
for m, label in (("risk30", "30д"), ("p24", "1д"), ("p72", "3д"), ("p7d", "7д")):
    r = c.get(f"{B}/meta/risk-history?task=wear&n=30&measure={m}", headers=hc)
    j = r.json() if r.status_code == 200 else {}
    ok_row = bool(j.get("rows")) and all(k in j["rows"][0] for k in ("bucket_ts", "avg_risk", "max_risk", "n"))
    chk(f"тренд {label}: measure={m}", r.status_code == 200 and ok_row and j.get("measure") == m,
        str(j)[:160])
r30 = c.get(f"{B}/meta/risk-history?task=wear&n=30&measure=risk30", headers=hc).json()["rows"]
r1 = c.get(f"{B}/meta/risk-history?task=wear&n=30&measure=p24", headers=hc).json()["rows"]
same_bucket = {x["bucket_ts"]: x for x in r30}
diff = [x for x in r1 if x["bucket_ts"] in same_bucket
        and abs((x["avg_risk"] or 0) - (same_bucket[x["bucket_ts"]]["avg_risk"] or 0)) > 1e-6]
chk("тренд: значения 24ч отличаются от 30д (горизонт реально влияет)", bool(diff),
    f"совпало по всем {len(r1)} точкам")
chk("тренд: неизвестная мера отклонена",
    c.get(f"{B}/meta/risk-history?task=wear&measure=zzz", headers=hc).status_code == 422)

print("=== SMOKE NEW API:", "ALL OK" if ok else "FAIL", "===")
sys.exit(0 if ok else 1)
